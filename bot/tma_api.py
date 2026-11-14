"""Mini App JSON API mounted on the existing aiohttp server (no second backend).

All money/ownership decisions happen server-side; the client only renders.
Bearer sessions come from bot.tma_auth after HMAC-verified initData.
"""
import time
from collections import deque
from pathlib import Path

from aiohttp import web

from bot import services
from bot.config import cfg
from bot.db import Session, User
from bot.logic import phone_encrypt, phone_norm, phash
from bot.tma_auth import InitDataError, create_session, session_user_id, verify_init_data

ROOT = Path(__file__).resolve().parent.parent


def ok(data, status: int = 200):
    return web.json_response({"ok": True, "data": data}, status=status)


def err(code: str, message: str, status: int = 400):
    return web.json_response({"ok": False, "err": {"code": code, "message": message}}, status=status)


class RateLimiter:
    """Per-process sliding window. Adequate for the single-instance deployment."""

    def __init__(self, limit: int, window: float = 60.0):
        self.limit = limit
        self.window = window
        self.hits: dict[str, deque] = {}

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        q = self.hits.setdefault(key, deque())
        while q and q[0] <= now - self.window:
            q.popleft()
        if len(q) >= self.limit:
            return False
        q.append(now)
        if len(self.hits) > 10000:
            self.hits = {k: v for k, v in self.hits.items() if v and v[-1] > now - self.window}
        return True


auth_limiter = RateLimiter(20)
api_limiter = RateLimiter(240)

BOT_KEY = web.AppKey("bot")
_BOT_USERNAME: str | None = None


async def bot_username(request) -> str | None:
    global _BOT_USERNAME
    if _BOT_USERNAME:
        return _BOT_USERNAME
    try:
        me = await request.app[BOT_KEY].get_me()
        _BOT_USERNAME = me.username
        return _BOT_USERNAME
    except Exception:
        return None


@web.middleware
async def api_middleware(request, handler):
    if not request.path.startswith("/api/v1"):
        return await handler(request)
    if request.path == "/api/v1/auth/telegram":
        if not auth_limiter.allow(request.remote or "unknown"):
            return err("rate_limited", "Слишком много попыток входа. Подожди минуту.", 429)
        return await handler(request)
    auth = request.headers.get("Authorization", "")
    token = auth[7:] if auth.startswith("Bearer ") else ""
    async with Session() as s:
        uid = await session_user_id(s, token)
        if uid is not None:
            u = await s.get(User, uid)
            if u is None or u.banned:
                return err("banned", "Доступ ограничен.", 403)
    if uid is None:
        return err("unauthorized", "Сессия истекла. Открой приложение заново через бота.", 401)
    if not api_limiter.allow(f"u{uid}"):
        return err("rate_limited", "Слишком много запросов. Подожди немного.", 429)
    request["uid"] = uid
    return await handler(request)


async def auth_telegram(request):
    try:
        body = await request.json()
    except Exception:
        return err("bad_json", "Некорректный запрос.")
    init_data = body.get("initData") if isinstance(body, dict) else None
    if not isinstance(init_data, str) or not init_data:
        return err("no_init_data", "Открой приложение через Telegram-бота.")
    try:
        verified = verify_init_data(init_data, cfg.token)
    except InitDataError as e:
        return err(e.code, str(e), 401)
    tg_user = verified["user"]
    uid = tg_user["id"]
    async with Session() as s:
        u = await s.get(User, uid)
        if u is None:
            u = User(id=uid, username=tg_user.get("username"), name=tg_user.get("first_name"))
            s.add(u)
            await s.commit()
        else:
            if u.banned:
                return err("banned", "Доступ ограничен.", 403)
            changed = False
            if tg_user.get("username") and u.username != tg_user["username"]:
                u.username = tg_user["username"]; changed = True
            if tg_user.get("first_name") and u.name != tg_user["first_name"]:
                u.name = tg_user["first_name"]; changed = True
            if changed:
                await s.commit()
        token, expires = await create_session(s, uid)
        profile = await services.user_profile(s, u)
    return ok({"token": token, "expires_at": expires.isoformat(), "user": profile})


async def me(request):
    async with Session() as s:
        u = await s.get(User, request["uid"])
        return ok(await services.user_profile(s, u))


async def me_accept(request):
    async with Session() as s:
        u = await s.get(User, request["uid"])
        u.accepted = u.adult = True
        await s.commit()
        return ok(await services.user_profile(s, u))


async def me_age(request):
    try:
        body = await request.json()
    except Exception:
        return err("bad_json", "Некорректный запрос.")
    years = body.get("years") if isinstance(body, dict) else None
    if not isinstance(years, int) or not 18 <= years <= 120:
        return err("bad_age", "Укажи число полных лет от 18 до 120.")
    async with Session() as s:
        u = await s.get(User, request["uid"])
        u.age_years = years
        await s.commit()
        return ok(await services.user_profile(s, u))


async def me_sbp(request):
    try:
        body = await request.json()
    except Exception:
        return err("bad_json", "Некорректный запрос.")
    if not isinstance(body, dict):
        return err("bad_json", "Некорректный запрос.")
    bank = (body.get("bank") or "").strip()
    phone = body.get("phone")
    if not 2 <= len(bank) <= 80:
        return err("bad_bank", "Укажи корректное название банка (2–80 символов).")
    async with Session() as s:
        u = await s.get(User, request["uid"])
        u.sbp_bank = bank
        if phone is not None:
            normalized = phone_norm(str(phone))
            if len(normalized) != 11 or not normalized.isdigit():
                return err("bad_phone", "Нужен номер телефона из 11 цифр (например, +79991234567).")
            u.sbp_phone = phone_encrypt(normalized)
            u.phone_hash = phash(normalized)
        elif not u.sbp_phone:
            return err("no_phone", "Сначала укажи телефон, привязанный к СБП.")
        await s.commit()
        return ok(await services.user_profile(s, u))


async def dashboard(request):
    async with Session() as s:
        return ok(await services.dashboard(s, request["uid"], await bot_username(request)))


async def meta(request):
    async with Session() as s:
        return ok(await services.meta_info(s, request["uid"], await bot_username(request)))


async def notifications(request):
    async with Session() as s:
        return ok(await services.notifications(s, request["uid"]))


async def notifications_read(request):
    from datetime import datetime
    async with Session() as s:
        u = await s.get(User, request["uid"])
        u.notif_read_at = datetime.utcnow()
        await s.commit()
    return ok({"read": True})


async def spa_index(request):
    dist = ROOT / "webapp" / "dist"
    index = dist / "index.html"
    if not index.exists():
        return web.json_response(
            {"ok": False, "err": {"code": "no_frontend", "message": "Frontend не собран. Выполни npm run build в webapp/."}},
            status=503,
        )
    return web.FileResponse(index)


def setup_tma(app: web.Application, bot):
    app[BOT_KEY] = bot
    app.middlewares.append(api_middleware)
    r = app.router
    r.add_post("/api/v1/auth/telegram", auth_telegram)
    r.add_get("/api/v1/me", me)
    r.add_post("/api/v1/me/accept", me_accept)
    r.add_put("/api/v1/me/age", me_age)
    r.add_put("/api/v1/me/sbp", me_sbp)
    r.add_get("/api/v1/dashboard", dashboard)
    r.add_get("/api/v1/meta", meta)
    r.add_get("/api/v1/notifications", notifications)
    r.add_post("/api/v1/notifications/read", notifications_read)

    assets = ROOT / "assets"
    if assets.exists():
        r.add_static("/assets", assets, show_index=False)
    dist = ROOT / "webapp" / "dist"
    if (dist / "assets").exists():
        r.add_static("/app/assets", dist / "assets", show_index=False)
    r.add_get("/app", spa_index)
    r.add_get("/app/{tail:.*}", spa_index)