"""Mini App JSON API mounted on the existing aiohttp server (no second backend).

All money/ownership decisions happen server-side; the client only renders.
Bearer sessions come from bot.tma_auth after HMAC-verified initData.
"""
import time
import asyncio
import logging
import re
import html
from collections import deque
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path

from aiohttp import web
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from bot import services
from bot.bonuses import CHANNEL_BONUS, grant_bonus
from bot.config import cfg
from bot.db import AdminAuditEvent, App, Bank, BroadcastCampaign, DealEvent, DealMessage, Offer, OfferEvent, PayoutEvent, PayoutReq, PbLog, Session, TmaSession, Tier, User, WalletEntry
from bot.logic import notify, phone_decrypt, phone_encrypt, phone_norm, phash
from bot.proofs import proof_progress, proofs_complete
from bot.tma_auth import InitDataError, create_session, session_user_id, token_hash, verify_init_data, verify_telegram_login
from bot.tma_files import (
    ALLOWED_EXT, IMAGE_EXT, MAX_FILES_PER_UPLOAD, FileError, resolve_proof, safe_ext, store_proof,
)

ROOT = Path(__file__).resolve().parent.parent


def _apply_response_headers(request, response):
    """Apply security and cache policy to every response, including errors."""
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")

    # Caddy terminates TLS in production. Trust the forwarded scheme only as
    # a signal for HSTS; the application itself remains behind that proxy.
    forwarded_proto = request.headers.get("X-Forwarded-Proto", "").split(",", 1)[0].strip().lower()
    if request.scheme == "https" or forwarded_proto == "https":
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )

    # Never weaken explicit policies (notably private evidence files).
    if "Cache-Control" not in response.headers:
        path = request.path
        if path.startswith("/api/v1/"):
            cache = "private, no-store"
        elif path.startswith("/app/assets/") and re.search(r"-[A-Za-z0-9_-]{6,}\.", path):
            cache = "public, max-age=31536000, immutable"
        elif path == "/app" or path.startswith("/app/"):
            cache = "no-cache"
        elif path.startswith("/assets/offers/"):
            cache = "public, max-age=86400"
        else:
            cache = None
        if cache:
            response.headers["Cache-Control"] = cache
    return response


@web.middleware
async def headers_middleware(request, handler):
    """Outer middleware so early auth/rate-limit responses get headers too."""
    response = await handler(request)
    return _apply_response_headers(request, response)


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
channel_limiter = RateLimiter(10)
BROADCAST_TASKS: dict[int, asyncio.Task] = {}

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
    if request.path in ("/api/v1/auth/telegram", "/api/v1/auth/telegram-widget"):
        if not auth_limiter.allow(request.remote or "unknown"):
            return err("rate_limited", "Слишком много попыток входа. Подожди минуту.", 429)
        return await handler(request)
    if request.path == "/api/v1/admin/login-config":
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
    request["session_token"] = token
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


async def admin_login_config(request):
    username = await bot_username(request)
    if not username:
        return err("bot_unavailable", "Не удалось определить имя Telegram-бота.", 503)
    return ok({"bot_username": username})


async def auth_telegram_widget(request):
    try:
        body = await request.json()
    except Exception:
        return err("bad_json", "Некорректный запрос.")
    try:
        tg_user = verify_telegram_login(body, cfg.token)
    except InitDataError as e:
        return err(e.code, str(e), 401)
    uid = tg_user["id"]
    if uid not in cfg.admins:
        return err("forbidden", "Этот Telegram-аккаунт не входит в список администраторов.", 403)
    async with Session() as s:
        u = await s.get(User, uid)
        if u is None:
            u = User(id=uid, username=tg_user.get("username"), name=tg_user.get("first_name") or "Администратор")
            s.add(u)
            await s.flush()
        elif u.banned:
            return err("banned", "Доступ ограничен.", 403)
        else:
            if tg_user.get("username"):
                u.username = tg_user["username"]
            if tg_user.get("first_name"):
                u.name = tg_user["first_name"]
        token, expires = await create_session(s, uid)
        profile = await services.user_profile(s, u)
    return ok({"token": token, "expires_at": expires.isoformat(), "user": profile})


async def auth_logout(request):
    """Revoke the current opaque bearer session server-side."""
    async with Session() as s:
        await s.execute(delete(TmaSession).where(
            TmaSession.token_hash == token_hash(request["session_token"]),
            TmaSession.user_id == request["uid"],
        ))
        await s.commit()
    return ok({"logged_out": True})


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
    from datetime import datetime, timedelta
    async with Session() as s:
        u = await s.get(User, request["uid"])
        u.notif_read_at = datetime.utcnow()
        await s.commit()
    return ok({"read": True})


async def offers_list(request):
    q = request.query.get("q", "")[:80]
    category = request.query.get("category", "")
    sort = request.query.get("sort", "reward")
    available_only = request.query.get("available") == "1"
    card_type = request.query.get("card_type", "")
    async with Session() as s:
        return ok(await services.list_offers(s, request["uid"], q=q, category=category, sort=sort, available_only=available_only, card_type=card_type))


async def offer_detail(request):
    try:
        oid = int(request.match_info["id"])
    except ValueError:
        return err("not_found", "Предложение не найдено.", 404)
    async with Session() as s:
        o = await s.get(Offer, oid)
        if o is None:
            return err("not_found", "Предложение не найдено.", 404)
        detail = await services.offer_detail(s, o, request["uid"])
    if detail is None:
        return err("not_found", "Предложение не найдено.", 404)
    return ok(detail)


TAKE_ERROR_STATUS = {
    "banned": 403, "not_accepted": 403, "no_offer": 404, "no_user": 404,
    "bank_taken": 409, "max_active": 409, "no_slots": 409, "disabled": 409,
    "category_closed": 409, "bk_not_approved": 409, "no_link": 409,
}


async def offer_take(request):
    try:
        oid = int(request.match_info["id"])
    except ValueError:
        return err("not_found", "Предложение не найдено.", 404)
    async with Session() as s:
        a, code, msg = await services.create_deal(s, request["uid"], oid)
        if a is None:
            return err(code, msg, TAKE_ERROR_STATUS.get(code, 400))
        offer_name = (a.offer_snapshot or {}).get("name") or f"Оффер #{a.offer_id}"
        reward = int(a.cashback or 0)
    bot = request.app.get(BOT_KEY)
    if bot is not None:
        for admin_id in cfg.admins:
            try:
                await bot.send_message(admin_id, f"🆕 <b>Новая заявка #{a.id}</b>\n{offer_name}\n" 
                                               f"Пользователь: <code>{a.user_id}</code> · {reward} ₽")
            except Exception:
                continue
    return ok({"app_id": a.id}, status=201)


async def apps_list(request):
    async with Session() as s:
        return ok(await services.list_apps(s, request["uid"]))


async def _owned_app(s: Session, uid: int, aid: int) -> App | None:
    a = await s.get(App, aid)
    return a if a and a.user_id == uid else None


async def app_detail(request):
    try:
        aid = int(request.match_info["id"])
    except ValueError:
        return err("not_found", "Сделка не найдена.", 404)
    async with Session() as s:
        a = await _owned_app(s, request["uid"], aid)
        if a is None:
            return err("not_found", "Сделка не найдена.", 404)
        return ok(await services.app_detail(s, a))


async def app_proofs_upload(request):
    try:
        aid = int(request.match_info["id"])
    except ValueError:
        return err("not_found", "Сделка не найдена.", 404)
    uid = request["uid"]
    try:
        reader = await request.multipart()
    except Exception:
        return err("bad_form", "Ожидается multipart-форма с полем files.")
    files: list[tuple[str, bytes]] = []
    async for part in reader:
        if part.name != "files":
            continue
        data = await part.read(decode=False)
        files.append((part.filename or "file", data))
        if len(files) > MAX_FILES_PER_UPLOAD:
            return err("too_many", f"Максимум {MAX_FILES_PER_UPLOAD} файлов за одну отправку.", 400)
    if not files:
        return err("no_files", "Выбери хотя бы один файл.")

    import imagehash

    async with Session() as s:
        a = (await s.execute(select(App).where(App.id == aid).with_for_update())).scalar_one_or_none()
        if a is None or a.user_id != uid:
            return err("not_found", "Сделка не найдена.", 404)
        if a.status not in ("new", "proof", "hold"):
            return err("closed", "Для этой сделки загрузка подтверждений закрыта.", 409)
        o = await s.get(Offer, a.offer_id)
        required, _received, missing = proof_progress(a, o)

        prepared = []
        for filename, data in files:
            try:
                ext = safe_ext(filename)
            except FileError as e:
                return err(e.code, str(e), 400)
            if not data:
                return err("empty_file", f"Файл «{filename}» пуст.", 400)
            if len(data) > 10 * 1024 * 1024:
                return err("too_large", f"Файл «{filename}» больше 10 МБ.", 400)
            ph = services.image_phash(data) if ext in IMAGE_EXT else None
            prepared.append((filename, data, ext, ph))

        next_missing = list(missing)
        batch_hashes: list[str] = []
        planned = []
        for filename, data, ext, ph in prepared:
            suspected, matches = False, 0
            if ph:
                exact, suspected, matches = await services.phash_duplicates(s, ph, a.offer_id)
                candidate = imagehash.hex_to_hash(ph)
                for prev in batch_hashes:
                    try:
                        distance = candidate - imagehash.hex_to_hash(prev)
                        if distance == 0:
                            exact = True
                        elif distance <= 3:
                            suspected = True
                            matches += 1
                    except Exception:
                        pass
                if exact:
                    return err("duplicate_proof",
                               "Это точная копия скриншота, который уже приложен к другой сделке или ранее к этой. "
                               "Нужен оригинальный файл подтверждения именно для текущего пункта.", 409)
                batch_hashes.append(ph)
            current_index = next_missing.pop(0) if next_missing else None
            label = required[current_index] if current_index is not None else "Дополнительное подтверждение"
            planned.append((filename, data, ext, ph, current_index, label, suspected, matches))

        # Reserve exact fingerprints before writing files. The database unique
        # constraint closes the race when two Telegram accounts upload the same
        # document for this offer at nearly the same time.
        for _filename, _data, _ext, ph, _idx, _label, _suspected, _matches in planned:
            if ph:
                services.add_proof_fingerprint(s, offer_id=a.offer_id, app_id=a.id, user_id=uid, ph=ph)
        try:
            await s.flush()
        except IntegrityError:
            await s.rollback()
            return err("duplicate_proof", "Этот документ уже загружали на данный оффер с другого аккаунта. Нужен оригинальный документ именно для вашей заявки.", 409)

        items = []
        for filename, data, ext, ph, current_index, label, suspected, matches in planned:
            try:
                storage, _ctype = store_proof(aid, filename, data)
            except FileError as e:
                return err(e.code, str(e), 400)
            items.append({
                "file_id": None, "storage": storage, "source": "tma",
                "kind": "photo" if ext in IMAGE_EXT else "document",
                "name": filename, "hash": ph, "proof_index": current_index, "label": label,
                "duplicate_suspected": suspected, "duplicate_matches": matches,
                "uploaded_at": datetime.utcnow().isoformat(),
            })

        old_status = a.status
        a.proof_files = list(a.proof_files or []) + items
        if items[-1]["hash"]:
            a.proof_hash = items[-1]["hash"]
        if a.status == "new":
            a.status = "proof"
        ver = dict(a.verification or {})
        ver.pop("proof_submitted_at", None)
        ver["proof_last_received_at"] = items[-1]["uploaded_at"]
        a.verification = ver
        labels = ", ".join(x["label"] for x in items)
        s.add(DealEvent(app_id=a.id, actor_id=uid, event="proof_uploaded", from_status=old_status, to_status=a.status,
                        comment=f"Загружено через Mini App: {labels}"))
        await s.commit()

        # One less step for the user: a complete package goes straight to review.
        complete_now, _missing_now = proofs_complete(a, o, require_submission=False)
        if complete_now:
            ver2 = dict(a.verification or {})
            if not ver2.get("proof_submitted_at"):
                ver2["proof_submitted_at"] = datetime.utcnow().isoformat()
                ver2.pop("more_info_requested_at", None)
                ver2.pop("more_info_text", None)
                a.verification = ver2
                s.add(DealEvent(app_id=a.id, actor_id=uid, event="proof_submitted", from_status=a.status,
                                to_status=a.status, comment="Комплект собран и автоматически отправлен на проверку"))
                await s.commit()
                await _notify_admins_new_proof(request, a, o, items)
        return ok(await services.app_detail(s, a))


async def _notify_admins_new_proof(request, app_row, offer, items):
    """Send the uploaded evidence itself to every admin chat."""
    from aiogram.types import FSInputFile
    from bot.tma_files import resolve_proof
    bot = request.app.get(BOT_KEY)
    if bot is None:
        return
    name = (app_row.offer_snapshot or {}).get("name") or (offer.name if offer else "")
    caption = (f"📥 <b>Новые доказательства</b>\nСделка #{app_row.id} · {name}\n"
               f"Пользователь: ID {app_row.user_id}\nОткрой админ-меню → «📥 Скрины».")
    for admin_id in cfg.admins:
        try:
            await bot.send_message(admin_id, caption)
        except Exception:
            continue
        for item in items[:3]:
            try:
                if not isinstance(item, dict) or not item.get("storage"):
                    continue
                path = resolve_proof(item["storage"])
                if item.get("kind") == "document":
                    await bot.send_document(admin_id, FSInputFile(path))
                else:
                    await bot.send_photo(admin_id, FSInputFile(path))
            except Exception:
                continue


async def app_proof_file(request):
    try:
        aid = int(request.match_info["id"])
        idx = int(request.match_info["idx"])
    except ValueError:
        return err("not_found", "Файл не найден.", 404)
    async with Session() as s:
        a = await _owned_app(s, request["uid"], aid)
        if a is None:
            return err("not_found", "Сделка не найдена.", 404)
        items = [x for x in (a.proof_files or []) if isinstance(x, dict)]
        if not 0 <= idx < len(items):
            return err("not_found", "Файл не найден.", 404)
        item = items[idx]
    headers = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}
    storage = item.get("storage")
    if storage:
        try:
            path = resolve_proof(storage)
        except FileError:
            return err("not_found", "Файл не найден.", 404)
        return web.FileResponse(path, headers={**headers, "Content-Disposition": "inline"})
    fid = item.get("file_id")
    if fid:
        bot = request.app[BOT_KEY]
        try:
            f = await bot.get_file(fid)
            buf = BytesIO()
            await bot.download_file(f.file_path, destination=buf)
        except Exception:
            return err("telegram_unavailable", "Файл из Telegram временно недоступен. Открой сделку в боте.", 502)
        ctype = "application/pdf" if str(item.get("name", "")).lower().endswith(".pdf") else "image/jpeg"
        return web.Response(body=buf.getvalue(), content_type=ctype, headers=headers)
    return err("not_found", "Файл не найден.", 404)


async def app_submit(request):
    try:
        aid = int(request.match_info["id"])
    except ValueError:
        return err("not_found", "Сделка не найдена.", 404)
    uid = request["uid"]
    async with Session() as s:
        a = (await s.execute(select(App).where(App.id == aid).with_for_update())).scalar_one_or_none()
        if a is None or a.user_id != uid:
            return err("not_found", "Сделка не найдена.", 404)
        if a.status not in ("proof", "hold"):
            return err("closed", "Сделка не найдена или пока не содержит подтверждений.", 409)
        o = await s.get(Offer, a.offer_id)
        complete, missing_labels = proofs_complete(a, o, require_submission=False)
        if not complete:
            return err("incomplete", "Не хватает подтверждений: " + "; ".join(missing_labels[:2]), 400)
        ver = dict(a.verification or {})
        submitted_at = ver.get("proof_submitted_at")
        last_received = ver.get("proof_last_received_at")
        if submitted_at and (not last_received or last_received <= submitted_at):
            return err("already_submitted", "Этот комплект уже отправлен на проверку. Дождись решения администратора.", 409)
        old = a.status
        ver["proof_submitted_at"] = datetime.utcnow().isoformat()
        ver.pop("more_info_requested_at", None)
        ver.pop("more_info_text", None)
        a.verification = ver
        s.add(DealEvent(app_id=a.id, actor_id=uid, event="proof_submitted", from_status=old, to_status=a.status,
                        comment="Пользователь отправил полный комплект на проверку через Mini App"))
        o_name = (a.offer_snapshot or {}).get("name", o.name if o else "")
        file_count = len(a.proof_files or [])
        await s.commit()
        bot = request.app[BOT_KEY]
        for ad in cfg.admins:
            await notify(bot, ad, f"📥 <b>Комплект доказательств отправлен (Mini App)</b>\nСделка #{aid} · {o_name}\n"
                                  f"Пользователь: ID {uid}\nФайлов: {file_count}\nОткрой /admin → сделка #{aid}.")
        return ok(await services.app_detail(s, a))



async def deal_messages_list(request):
    try:
        aid = int(request.match_info["id"])
    except ValueError:
        return err("not_found", "Сделка не найдена.", 404)
    async with Session() as s:
        deal = await s.get(App, aid)
        if deal is None or deal.user_id != request["uid"]:
            return err("not_found", "Сделка не найдена.", 404)
        rows = (await s.execute(
            select(DealMessage).where(DealMessage.app_id == aid).order_by(DealMessage.id.asc()).limit(200)
        )).scalars().all()
        return ok([{
            "id": row.id, "is_admin": row.is_admin, "body": row.body,
            "created": row.created.isoformat() if row.created else None,
        } for row in rows])


async def deal_message_create(request):
    try:
        aid = int(request.match_info["id"])
    except ValueError:
        return err("not_found", "Сделка не найдена.", 404)
    try:
        body = await request.json()
    except Exception:
        return err("bad_json", "Некорректный запрос.")
    text = body.get("body") if isinstance(body, dict) else None
    if not isinstance(text, str):
        return err("bad_message", "Напиши сообщение.")
    text = text.strip()
    if not text or len(text) > 2000:
        return err("bad_message", "Сообщение должно содержать от 1 до 2000 символов.")
    async with Session() as s:
        deal = await s.get(App, aid)
        if deal is None or deal.user_id != request["uid"]:
            return err("not_found", "Сделка не найдена.", 404)
        row = DealMessage(app_id=aid, actor_id=request["uid"], is_admin=False, body=text)
        s.add(row)
        s.add(DealEvent(app_id=aid, actor_id=request["uid"], event="support_message",
                        from_status=deal.status, to_status=deal.status,
                        comment="Пользователь написал в поддержку по сделке"))
        await s.commit()
        await s.refresh(row)
        offer = await s.get(Offer, deal.offer_id)
        offer_name = offer.name if offer else f"сделка #{aid}"
    bot = request.app[BOT_KEY]
    for admin_id in cfg.admins:
        await notify(bot, admin_id, f"💬 <b>Сообщение по сделке #{aid}</b> · {offer_name}\n"
                                    f"Пользователь: {request['uid']}\n"
                                    f"<blockquote>{html.escape(text[:1500])}</blockquote>\n"
                                    f"Ответ: <code>/dealreply {aid} текст</code>")
    return ok({"id": row.id, "is_admin": False, "body": row.body,
               "created": row.created.isoformat() if row.created else None}, status=201)


async def wallet(request):
    async with Session() as s:
        return ok({
            "summary": await services.wallet_summary(s, request["uid"]),
            "entries": await services.wallet_entries(s, request["uid"]),
        })


async def wallet_entries(request):
    async with Session() as s:
        return ok(await services.wallet_entries(s, request["uid"]))


async def withdrawals_list(request):
    uid = request["uid"]
    async with Session() as s:
        u = await s.get(User, uid)
        rows = (await s.execute(select(PayoutReq).where(PayoutReq.user_id == uid).order_by(PayoutReq.id.desc()))).scalars().all()
        requests = []
        for p in rows:
            events = (await s.execute(select(PayoutEvent).where(PayoutEvent.payout_id == p.id).order_by(PayoutEvent.id))).scalars().all()
            requests.append(services.withdrawal_view(p, list(events)))
        banks = list(services.SBP_BANKS)
        if u and u.sbp_bank and u.sbp_bank not in banks:
            banks.insert(0, u.sbp_bank)
        return ok({"requests": requests, "banks": banks, "min_withdraw": cfg.min_wd, "available": int(u.balance or 0) if u else 0})


WITHDRAW_ERROR_STATUS = {"banned": 403, "not_found": 404, "insufficient": 409, "not_pending": 409}


async def withdrawals_create(request):
    try:
        body = await request.json()
    except Exception:
        return err("bad_json", "Некорректный запрос.")
    if not isinstance(body, dict):
        return err("bad_json", "Некорректный запрос.")
    amount = body.get("amount")
    if isinstance(amount, float) and amount.is_integer():
        amount = int(amount)
    bank = body.get("bank")
    phone = body.get("phone")
    if bank is not None and not isinstance(bank, str):
        return err("bad_bank", "Укажи корректный банк СБП.")
    if phone is not None and not isinstance(phone, str):
        return err("bad_phone", "Укажи корректный телефон СБП.")
    uid = request["uid"]
    async with Session() as s:
        p, code, msg, created = await services.create_withdrawal(s, uid, amount, bank, phone)
        if p is None:
            return err(code, msg, WITHDRAW_ERROR_STATUS.get(code, 400))
        events = (await s.execute(select(PayoutEvent).where(PayoutEvent.payout_id == p.id).order_by(PayoutEvent.id))).scalars().all()
        view = services.withdrawal_view(p, list(events))
        bot = request.app[BOT_KEY]
        if created:
            for ad in cfg.admins:
                await notify(bot, ad, f"💸 <b>Новый запрос на вывод #{p.id} (Mini App)</b>\nСумма: {p.amount} ₽\nБанк: {p.bank}\n"
                                      f"Телефон СБП: {phone_decrypt(p.phone)}\nПользователь: {uid}")
    return ok(view, status=201 if created else 200)


async def withdrawals_cancel(request):
    try:
        pid = int(request.match_info["id"])
    except ValueError:
        return err("not_found", "Запрос на вывод не найден.", 404)
    uid = request["uid"]
    async with Session() as s:
        p, code, msg = await services.cancel_withdrawal(s, uid, pid)
        if p is None:
            return err(code, msg, WITHDRAW_ERROR_STATUS.get(code, 400))
        events = (await s.execute(select(PayoutEvent).where(PayoutEvent.payout_id == p.id).order_by(PayoutEvent.id))).scalars().all()
        view = services.withdrawal_view(p, list(events))
        bot = request.app[BOT_KEY]
        for ad in cfg.admins:
            await notify(bot, ad, f"Запрос на вывод #{p.id} отменён пользователем (Mini App); {p.amount} ₽ возвращены на баланс.")
    return ok(view)


async def tasks_list(request):
    async with Session() as s:
        return ok(await services.task_states(s, request["uid"]))


async def _channel_task(s: Session, uid: int) -> dict:
    tasks = await services.task_states(s, uid)
    return next(t for t in tasks if t["key"] == "channel")


async def tasks_channel_check(request):
    uid = request["uid"]
    if not (cfg.channel_id and cfg.channel_url):
        return err("channel_not_configured", "Канал пока не настроен администратором — бонус временно недоступен.", 409)
    if not channel_limiter.allow(f"u{uid}"):
        return err("rate_limited", "Слишком много проверок. Подожди немного.", 429)
    async with Session() as s:
        if await services.has_task_entry(s, uid, f"task:channel:{uid}"):
            return ok(await _channel_task(s, uid))
        chat_id = int(cfg.channel_id) if cfg.channel_id.lstrip("-").isdigit() else cfg.channel_id
        try:
            member = await request.app[BOT_KEY].get_chat_member(chat_id, uid)
        except Exception:
            return err("channel_unavailable", "Не удалось проверить подписку. Попробуй позже.", 502)
        if getattr(member, "status", None) not in ("member", "administrator", "creator"):
            return err("not_subscribed", "Подписка не найдена. Подпишись на канал и проверь ещё раз.", 400)
        try:
            await grant_bonus(s, uid, CHANNEL_BONUS, "task_channel", f"task:channel:{uid}", "Бонус за подписку на канал")
            await s.commit()
        except IntegrityError:
            # A concurrent check already credited the same unique ref.
            await s.rollback()
        return ok(await _channel_task(s, uid))


async def friends(request):
    async with Session() as s:
        return ok(await services.friends_info(s, request["uid"], await bot_username(request)))


async def achievements_list(request):
    async with Session() as s:
        return ok(await services.achievements(s, request["uid"]))


async def leaderboard(request):
    lb_type = request.query.get("type", "orders")
    period = request.query.get("period", "month")
    if lb_type not in ("orders", "friends"):
        return err("bad_type", "Неизвестный тип рейтинга.")
    if period not in ("month", "all"):
        return err("bad_period", "Неизвестный период рейтинга.")
    async with Session() as s:
        return ok(await services.leaderboard(s, request["uid"], lb_type, period))


async def spa_index(request):
    dist = ROOT / "webapp" / "dist"
    index = dist / "index.html"
    if not index.exists():
        return web.json_response(
            {"ok": False, "err": {"code": "no_frontend", "message": "Frontend не собран. Выполни npm run build в webapp/."}},
            status=503,
        )
    return web.FileResponse(index)



async def admin_overview(request):
    """Read-only operational dashboard; all access is checked server-side."""
    if request["uid"] not in cfg.admins:
        return err("forbidden", "Нет доступа к панели администратора.", 403)
    from sqlalchemy import func
    async with Session() as s:
        users_total = int((await s.execute(select(func.count(User.id)))).scalar() or 0)
        users_active = int((await s.execute(select(func.count(User.id)).where(User.banned == False))).scalar() or 0)
        offers_total = int((await s.execute(select(func.count(Offer.id)))).scalar() or 0)
        offers_enabled = int((await s.execute(select(func.count(Offer.id)).where(Offer.enabled == True))).scalar() or 0)
        apps_by_status = dict((await s.execute(select(App.status, func.count(App.id)).group_by(App.status))).all())
        pending_payouts = int((await s.execute(select(func.count(PayoutReq.id)).where(PayoutReq.status.in_(["pending", "processing", "review_required"])))).scalar() or 0)
        pending_sum = int((await s.execute(select(func.coalesce(func.sum(PayoutReq.amount), 0)).where(PayoutReq.status.in_(["pending", "processing", "review_required"])))).scalar() or 0)
        recent_apps = (await s.execute(select(App).order_by(App.created.desc()).limit(8))).scalars().all()
        recent_payouts = (await s.execute(select(PayoutReq).order_by(PayoutReq.created.desc()).limit(6))).scalars().all()
        app_rows = [{"id": a.id, "user_id": a.user_id, "offer": (a.offer_snapshot or {}).get("name", f"Оффер #{a.offer_id}"), "status": a.status, "reward": a.cashback, "created": a.created.isoformat() if a.created else None} for a in recent_apps]
        payout_rows = [{"id": p.id, "user_id": p.user_id, "amount": p.amount, "status": p.status, "created": p.created.isoformat() if p.created else None} for p in recent_payouts]
    return ok({"users_total": users_total, "users_active": users_active, "offers_total": offers_total, "offers_enabled": offers_enabled, "apps_by_status": apps_by_status, "pending_payouts": pending_payouts, "pending_payouts_sum": pending_sum, "recent_apps": app_rows, "recent_payouts": payout_rows})


async def admin_section(request):
    """Read-only datasets for the standalone admin workspace."""
    if request["uid"] not in cfg.admins:
        return err("forbidden", "Нет доступа к панели администратора.", 403)
    from sqlalchemy import func, or_
    section = request.match_info["section"]
    query = (request.query.get("q", "") or "").strip()[:80]
    async with Session() as s:
        if section == "users":
            stmt = select(User).order_by(User.created.desc()).limit(100)
            if query:
                filters = [User.username.ilike(f"%{query}%"), User.name.ilike(f"%{query}%")]
                if query.isdigit():
                    filters.append(User.id == int(query))
                stmt = select(User).where(or_(*filters)).order_by(User.created.desc()).limit(100)
            rows = (await s.execute(stmt)).scalars().all()
            data = [{"id": u.id, "name": u.name or "", "username": u.username or "", "balance": u.balance, "banned": u.banned, "created": u.created.isoformat() if u.created else None, "referrer_id": u.referrer_id} for u in rows]
        elif section == "offers":
            rows = (await s.execute(select(Offer, Bank).join(Bank, Offer.bank_id == Bank.id).order_by(Offer.sort, Offer.id.desc()).limit(200))).all()
            offer_ids = [o.id for o, _b in rows]
            tier_rows = (await s.execute(select(Tier).where(Tier.offer_id.in_(offer_ids)).order_by(Tier.id))).scalars().all() if offer_ids else []
            tier_by_offer = {}
            for tier in tier_rows:
                tier_by_offer.setdefault(tier.offer_id, tier)
            data = [{"id": o.id, "name": o.name, "code": o.code, "bank": b.name, "category": b.category, "enabled": o.enabled, "network_status": o.network_status, "url": o.url, "approval": o.approval, "hold": o.hold, "age_min": o.age_min, "age_max": o.age_max, "network_payout": tier_by_offer[o.id].payout if o.id in tier_by_offer else 0, "user_reward": tier_by_offer[o.id].cashback if o.id in tier_by_offer else 0} for o, b in rows]
        elif section == "applications":
            rows = (await s.execute(select(App).order_by(App.created.desc()).limit(200))).scalars().all()
            data = [{"id": a.id, "user_id": a.user_id, "offer": (a.offer_snapshot or {}).get("name", f"Оффер #{a.offer_id}"), "status": a.status, "payout": a.payout, "cashback": a.cashback, "created": a.created.isoformat() if a.created else None, "reason": a.reason, "proof_files": [{"index": i, "name": str(item.get("name") or item.get("label") or f"Доказательство {i+1}"), "label": str(item.get("label") or ""), "uploaded_at": item.get("uploaded_at")} for i, item in enumerate(a.proof_files or []) if isinstance(item, dict)]} for a in rows]
        elif section == "payouts":
            rows = (await s.execute(select(PayoutReq).order_by(PayoutReq.created.desc()).limit(200))).scalars().all()
            data = [{"id": p.id, "user_id": p.user_id, "amount": p.amount, "bank": p.bank, "status": p.status, "admin_note": p.admin_note, "created": p.created.isoformat() if p.created else None, "paid_at": p.paid_at.isoformat() if p.paid_at else None} for p in rows]
        elif section == "broadcasts":
            rows = (await s.execute(select(BroadcastCampaign).order_by(BroadcastCampaign.created.desc()).limit(100))).scalars().all()
            data = [{"id": c.id, "admin_id": c.admin_id, "audience": c.audience, "recipient_count": c.recipient_count, "sent_count": c.sent_count, "failed_count": c.failed_count, "status": "sending" if c.id in BROADCAST_TASKS else ("completed" if c.sent_count + c.failed_count >= c.recipient_count else "interrupted"), "created": c.created.isoformat() if c.created else None} for c in rows]
        elif section == "audit":
            rows = (await s.execute(select(AdminAuditEvent).order_by(AdminAuditEvent.created.desc(), AdminAuditEvent.id.desc()).limit(300))).scalars().all()
            data = [{"id": e.id, "actor_id": e.actor_id, "action": e.action, "target_type": e.target_type, "target_id": e.target_id, "details": e.details, "created": e.created.isoformat() if e.created else None} for e in rows]
        elif section == "postbacks":
            rows = (await s.execute(select(PbLog).order_by(PbLog.id.desc()).limit(200))).scalars().all()
            data = [{"id": p.id, "subid": p.subid, "status": p.status, "payout": p.payout, "raw": p.raw} for p in rows]
        elif section == "finance":
            credits = int((await s.execute(select(func.coalesce(func.sum(WalletEntry.amount), 0)).where(WalletEntry.amount > 0))).scalar() or 0)
            debits = int((await s.execute(select(func.coalesce(func.sum(-WalletEntry.amount), 0)).where(WalletEntry.amount < 0))).scalar() or 0)
            paid = int((await s.execute(select(func.coalesce(func.sum(PayoutReq.amount), 0)).where(PayoutReq.status == "paid"))).scalar() or 0)
            network = int((await s.execute(select(func.coalesce(func.sum(PbLog.payout), 0)))).scalar() or 0)
            data = {"wallet_credits": credits, "wallet_debits": debits, "paid_to_users": paid, "network_postback_total": network, "note": "Postback — учётная сумма сети, не подтверждение фактического поступления денег."}
        else:
            return err("not_found", "Раздел не найден.", 404)
    return ok({"section": section, "items": data})


async def _admin_audit(session, actor_id: int, action: str, target_type: str, target_id, details: str = ""):
    session.add(AdminAuditEvent(actor_id=actor_id, action=action[:50], target_type=target_type[:30], target_id=str(target_id)[:80], details=details[:2000]))


async def admin_user_action(request):
    if request["uid"] not in cfg.admins:
        return err("forbidden", "Нет доступа.", 403)
    try:
        uid = int(request.match_info["id"])
        body = await request.json()
    except Exception:
        return err("bad_request", "Некорректный запрос.")
    action = body.get("action") if isinstance(body, dict) else None
    if action not in {"ban", "unban"}:
        return err("bad_action", "Допустимые действия: ban, unban.")
    if action == "ban" and uid in cfg.admins:
        return err("admin_protected", "Нельзя заблокировать аккаунт администратора.", 409)
    async with Session() as s:
        user = (await s.execute(select(User).where(User.id == uid).with_for_update())).scalar_one_or_none()
        if user is None:
            return err("not_found", "Пользователь не найден.", 404)
        banned = action == "ban"
        if user.banned == banned:
            return ok({"id": uid, "banned": banned, "unchanged": True})
        user.banned = banned
        await _admin_audit(s, request["uid"], action, "user", uid, "Изменён статус доступа пользователя через веб-админку")
        await s.commit()
    return ok({"id": uid, "banned": banned})


async def admin_proof_file(request):
    if request["uid"] not in cfg.admins:
        return err("forbidden", "Нет доступа.", 403)
    try:
        aid, idx = int(request.match_info["id"]), int(request.match_info["idx"])
    except (TypeError, ValueError):
        return err("not_found", "Файл не найден.", 404)
    async with Session() as s:
        app = await s.get(App, aid)
        if app is None:
            return err("not_found", "Заявка не найдена.", 404)
        items = [x for x in (app.proof_files or []) if isinstance(x, dict)]
        if not 0 <= idx < len(items):
            return err("not_found", "Файл не найден.", 404)
        item = items[idx]
    headers = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff", "Content-Disposition": "inline"}
    storage = item.get("storage")
    if storage:
        try:
            path = resolve_proof(storage)
        except FileError:
            return err("not_found", "Файл не найден.", 404)
        return web.FileResponse(path, headers=headers)
    fid = item.get("file_id")
    if fid:
        try:
            file = await request.app[BOT_KEY].get_file(fid)
            buf = BytesIO()
            await request.app[BOT_KEY].download_file(file.file_path, destination=buf)
        except Exception:
            return err("telegram_unavailable", "Файл из Telegram временно недоступен.", 502)
        name = str(item.get("name") or "").lower()
        ctype = ALLOWED_EXT.get(Path(name).suffix, "application/octet-stream")
        return web.Response(body=buf.getvalue(), content_type=ctype, headers=headers)
    return err("not_found", "Файл не найден.", 404)


async def admin_app_action(request):
    if request["uid"] not in cfg.admins:
        return err("forbidden", "Нет доступа.", 403)
    try:
        body = await request.json()
    except Exception:
        return err("bad_json", "Некорректный запрос.")
    action = body.get("action") if isinstance(body, dict) else None
    if action not in {"confirm", "hold", "reject"}:
        return err("bad_action", "Допустимые действия: confirm, hold, reject.")
    try:
        app_id = int(request.match_info["id"])
    except (TypeError, ValueError):
        return err("bad_id", "Некорректный ID заявки.")
    bot = request.app[BOT_KEY]
    async with Session() as s:
        deal = (await s.execute(select(App).where(App.id == app_id).with_for_update())).scalar_one_or_none()
        if deal is None:
            return err("not_found", "Заявка не найдена.", 404)
        old = deal.status
        if action == "confirm":
            if old not in ("proof", "hold"):
                return err("invalid_status", "Подтвердить можно только заявку с отправленными доказательствами или на холде.", 409)
            offer = await s.get(Offer, deal.offer_id)
            complete, missing = proofs_complete(deal, offer)
            if not complete:
                return err("proofs_incomplete", "Не хватает доказательств: " + "; ".join(missing[:4]), 409)
            if not (await s.execute(select(Tier.id).where(Tier.offer_id == deal.offer_id))).first():
                return err("reward_not_configured", "У оффера не настроено вознаграждение.", 409)
            from bot.logic import confirm
            try:
                done = await confirm(bot, s, deal, None, actor_id=request["uid"], comment="Подтверждено через веб-админку")
            except ValueError as exc:
                return err("reward_not_configured", str(exc), 409)
            if not done:
                return err("already_processed", "Заявка уже обработана другим действием.", 409)
            await _admin_audit(s, request["uid"], "application_confirmed", "application", deal.id, "Награда начислена через веб-админку")
            await s.commit()
            return ok({"id": app_id, "status": "confirmed"})
        if action == "hold":
            if old not in ("proof", "hold"):
                return err("invalid_status", "В холд можно перевести только заявку на проверке.", 409)
            verification = dict(deal.verification or {})
            if old == "hold" and deal.hold_until:
                if not verification.get("proof_submitted_at"):
                    return err("already_on_hold", "Заявка уже находится в холде; срок не изменён.", 409)
                verification["proof_reviewed_at"] = verification["proof_submitted_at"]
                deal.verification = verification
                comment = "Повторные доказательства проверены; исходный срок холда сохранён"
            else:
                offer = await s.get(Offer, deal.offer_id)
                days = int((deal.offer_snapshot or {}).get("hold_days", offer.hold))
                deal.status = "hold"
                deal.hold_until = datetime.utcnow() + timedelta(days=days)
                deal.reviewed_by, deal.reviewed_at = request["uid"], datetime.utcnow()
                verification.setdefault("network_approved", False)
                if verification.get("proof_submitted_at"):
                    verification["proof_reviewed_at"] = verification["proof_submitted_at"]
                deal.verification = verification
                comment = f"Ручной холд {days} дней через веб-админку; ожидается решение сети"
            s.add(DealEvent(app_id=deal.id, actor_id=request["uid"], event="hold_set", from_status=old, to_status=deal.status, comment=comment))
            await _admin_audit(s, request["uid"], "application_hold", "application", deal.id, comment)
            await s.commit()
            await notify(bot, deal.user_id, f"⏳ Заявка #{deal.id} переведена в холд до {deal.hold_until:%d.%m.%Y}. Ожидаем проверку партнёрской сети.")
            return ok({"id": app_id, "status": "hold"})
        reason = body.get("reason", "") if isinstance(body, dict) else ""
        reason = reason.strip() if isinstance(reason, str) else ""
        if not reason or len(reason) > 1500:
            return err("bad_reason", "Для отказа укажи причину длиной до 1500 символов.")
        if old in ("confirmed", "paid", "rejected", "expired"):
            return err("invalid_status", "Заявка уже закрыта; повторное изменение запрещено.", 409)
        deal.status, deal.reason = "rejected", reason
        deal.reviewed_by, deal.reviewed_at = request["uid"], datetime.utcnow()
        s.add(DealEvent(app_id=deal.id, actor_id=request["uid"], event="rejected", from_status=old, to_status="rejected", comment=reason))
        await _admin_audit(s, request["uid"], "application_rejected", "application", deal.id, reason)
        user_id = deal.user_id
        await s.commit()
    await notify(bot, user_id, f"❌ Заявка #{app_id} отклонена.\nПричина: {reason}\nЕсть вопросы? Открой сделку и напиши в поддержку.")
    return ok({"id": app_id, "status": "rejected"})


async def admin_broadcast_preview(request):
    if request["uid"] not in cfg.admins:
        return err("forbidden", "Нет доступа.", 403)
    try:
        body = await request.json()
    except Exception:
        return err("bad_json", "Некорректный запрос.")
    audience = body.get("audience", "all") if isinstance(body, dict) else "all"
    message = body.get("text", "") if isinstance(body, dict) else ""
    if audience not in {"all", "accepted"}:
        return err("bad_audience", "Неизвестный сегмент аудитории.")
    if not isinstance(message, str) or not message.strip() or len(message) > 4096:
        return err("bad_message", "Текст должен содержать от 1 до 4096 символов.")
    if not cfg.webapp_url:
        return err("webapp_not_configured", "WEBAPP_URL не настроен: нельзя добавить кнопку перехода в Bonvera.", 409)
    from sqlalchemy import func
    conditions = [User.banned == False]
    if audience == "accepted":
        conditions.append(User.accepted == True)
    async with Session() as s:
        count = int((await s.execute(select(func.count(User.id)).where(*conditions))).scalar() or 0)
    return ok({"recipient_count": count, "audience": audience, "text_length": len(message.strip())})


async def _run_admin_broadcast(campaign_id: int, bot, recipient_ids: list[int], source_chat_id: int, source_message_id: int, keyboard):
    sent = failed = 0
    try:
        for index, uid in enumerate(recipient_ids, start=1):
            try:
                await bot.copy_message(chat_id=uid, from_chat_id=source_chat_id, message_id=source_message_id, reply_markup=keyboard)
                sent += 1
            except Exception:
                failed += 1
            if index % 10 == 0 or index == len(recipient_ids):
                async with Session() as s:
                    campaign = await s.get(BroadcastCampaign, campaign_id)
                    if campaign:
                        campaign.sent_count = sent
                        campaign.failed_count = failed
                        await s.commit()
            await asyncio.sleep(0.05)
        if not recipient_ids:
            async with Session() as s:
                campaign = await s.get(BroadcastCampaign, campaign_id)
                if campaign:
                    campaign.sent_count = 0
                    campaign.failed_count = 0
                    await s.commit()
    except Exception:
        logging.exception("web admin broadcast worker failed: campaign=%s", campaign_id)
    finally:
        BROADCAST_TASKS.pop(campaign_id, None)


async def admin_broadcast_send(request):
    if request["uid"] not in cfg.admins:
        return err("forbidden", "Нет доступа.", 403)
    try:
        body = await request.json()
    except Exception:
        return err("bad_json", "Некорректный запрос.")
    audience = body.get("audience", "all") if isinstance(body, dict) else "all"
    message = body.get("text", "") if isinstance(body, dict) else ""
    if audience not in {"all", "accepted"}:
        return err("bad_audience", "Неизвестный сегмент аудитории.")
    if not isinstance(message, str) or not message.strip() or len(message) > 4096:
        return err("bad_message", "Текст должен содержать от 1 до 4096 символов.")
    if not cfg.webapp_url:
        return err("webapp_not_configured", "WEBAPP_URL не настроен: нельзя добавить кнопку перехода в Bonvera.", 409)
    from bot.admin import broadcast_audience_query, broadcast_keyboard
    bot = request.app[BOT_KEY]
    keyboard = broadcast_keyboard()
    async with Session() as s:
        recipient_ids = (await s.execute(broadcast_audience_query(audience))).scalars().all()
        expected_count = body.get("expected_count")
        if not isinstance(expected_count, int) or expected_count != len(recipient_ids):
            return err("audience_changed", "Размер аудитории изменился после предпросмотра. Пересчитай аудиторию перед отправкой.", 409)
        source = await bot.send_message(chat_id=request["uid"], text=message.strip(), reply_markup=keyboard)
        campaign = BroadcastCampaign(admin_id=request["uid"], source_chat_id=request["uid"], source_message_id=source.message_id, audience=audience, recipient_count=len(recipient_ids))
        s.add(campaign)
        await s.flush()
        campaign_id = campaign.id
        await _admin_audit(s, request["uid"], "broadcast_started", "broadcast", campaign_id, f"Аудитория: {audience}; получателей: {len(recipient_ids)}; длина текста: {len(message.strip())}")
        await s.commit()
    task = asyncio.create_task(_run_admin_broadcast(campaign_id, bot, recipient_ids, request["uid"], source.message_id, keyboard))
    BROADCAST_TASKS[campaign_id] = task
    return ok({"id": campaign_id, "recipient_count": len(recipient_ids), "status": "sending"}, 202)


async def admin_offer_enabled(request):
    if request["uid"] not in cfg.admins:
        return err("forbidden", "Нет доступа.", 403)
    try:
        body = await request.json()
    except Exception:
        return err("bad_json", "Некорректный запрос.")
    enabled = body.get("enabled") if isinstance(body, dict) else None
    if not isinstance(enabled, bool):
        return err("bad_enabled", "Ожидается логическое значение enabled.")
    try:
        offer_id = int(request.match_info["id"])
    except (TypeError, ValueError):
        return err("bad_id", "Некорректный ID оффера.")
    async with Session() as s:
        offer = (await s.execute(select(Offer).where(Offer.id == offer_id).with_for_update())).scalar_one_or_none()
        if offer is None:
            return err("not_found", "Оффер не найден.", 404)
        bank = await s.get(Bank, offer.bank_id)
        if enabled:
            if not offer.url or not offer.url.startswith(("https://", "http://")):
                return err("missing_partner_url", "Нельзя включить оффер без рабочей партнёрской ссылки.", 409)
            if bank and bank.category == "bk" and (offer.network_status != "approved" or not offer.approval.strip()):
                return err("bookmaker_not_approved", "Букмекерский оффер нельзя включить без зафиксированного согласования партнёра.", 409)
        if offer.enabled == enabled:
            return ok({"id": offer.id, "enabled": offer.enabled, "unchanged": True})
        offer.enabled = enabled
        s.add(OfferEvent(offer_id=offer.id, actor_id=request["uid"], event="enabled" if enabled else "disabled", details="Изменено через веб-админку"))
        await _admin_audit(s, request["uid"], "offer_enabled" if enabled else "offer_disabled", "offer", offer.id, offer.name)
        await s.commit()
        return ok({"id": offer.id, "enabled": offer.enabled})


async def admin_offer_create(request):
    """Create an offer with a partner link and a rate straight from the panel."""
    if request["uid"] not in cfg.admins:
        return err("forbidden", "Нет доступа.", 403)
    try:
        body = await request.json()
    except Exception:
        return err("bad_request", "Некорректный запрос.")
    if not isinstance(body, dict):
        return err("bad_json", "Некорректный запрос.")

    name = str(body.get("name") or "").strip()
    bank_name = str(body.get("bank") or "").strip()
    category = str(body.get("category") or "cpl").strip()
    url = str(body.get("url") or "").strip()
    condition = str(body.get("condition") or "").strip()
    kind = str(body.get("kind") or "").strip()
    raw_code = str(body.get("code") or "").strip().lower()

    if not name or len(name) > 160:
        return err("bad_field", "Название оффера обязательно, до 160 символов.")
    if not bank_name or len(bank_name) > 80:
        return err("bad_field", "Название партнёра обязательно, до 80 символов.")
    if category not in ("cards", "bk", "mfo", "cpl"):
        return err("bad_field", "Неизвестная категория.")
    if url and not url.startswith(("https://", "http://")):
        return err("bad_url", "Партнёрская ссылка должна начинаться с http:// или https://.")
    try:
        rate = int(body.get("rate") or 0)
        hold = int(body.get("hold") or 30)
    except (TypeError, ValueError):
        return err("bad_field", "Ставка и холд должны быть целыми числами.")
    if not 0 <= rate <= 100000000:
        return err("bad_field", "Ставка вне диапазона.")
    if not 0 <= hold <= 365:
        return err("bad_field", "Холд вне диапазона.")

    code = raw_code or "".join(ch if (ch.isalnum() or ch in "-_") else "-" for ch in name.lower()).strip("-")[:40]
    if not code or len(code) > 60 or not all(ch.isalnum() or ch in "-_" for ch in code) or not code.isascii():
        return err("bad_field", "Код оффера: латиница, цифры, дефис и подчёркивание (до 60 символов).")
    if category == "cards" and kind not in ("debit", "credit"):
        kind = "credit" if "кредит" in name.lower() else "debit"

    async with Session() as s:
        if (await s.execute(select(Offer).where(Offer.code == code))).scalar_one_or_none():
            return err("duplicate_code", f"Оффер с кодом {code} уже существует.", 409)
        bank = (await s.execute(select(Bank).where(Bank.slug == code))).scalar_one_or_none()
        if bank is None:
            emoji = {"cards": "\U0001F4B3", "bk": "\u26bd", "mfo": "\U0001F3E6", "cpl": "\U0001F4DD"}[category]
            bank = Bank(slug=code, name=bank_name, emoji=emoji, category=category, sort=900)
            s.add(bank)
            await s.flush()

        offer = Offer(code=code, bank_id=bank.id, name=name)
        s.add(offer)
        await s.flush()
        offer.url = url
        offer.link_param = "sub1"
        offer.network_status = "approved"
        offer.enabled = True
        offer.hold = hold
        offer.kind = kind
        if condition:
            offer.condition_text = condition
            offer.action = condition
        s.add(Tier(offer_id=offer.id, payout=rate, cashback=rate, label="Ставка ProCPA"))
        s.add(AdminAuditEvent(actor_id=request["uid"], action="offer_created", target_type="offer",
                              target_id=str(offer.id), details=f"{name} / {code} / {category} / {rate}"))
        await s.commit()
        return ok({"id": offer.id, "code": code}, status=201)


async def admin_offer_update(request):
    if request["uid"] not in cfg.admins:
        return err("forbidden", "Нет доступа.", 403)
    try:
        offer_id = int(request.match_info["id"])
        body = await request.json()
    except Exception:
        return err("bad_request", "Некорректный запрос.")
    if not isinstance(body, dict):
        return err("bad_json", "Некорректный запрос.")
    allowed = {"name": (160, True), "url": (2000, False), "action": (10000, False), "rules": (10000, False), "condition_text": (3000, False)}
    values = {}
    for key, (limit, required) in allowed.items():
        if key in body:
            value = body[key]
            if not isinstance(value, str) or len(value.strip()) > limit or (required and not value.strip()):
                return err("bad_field", f"Поле {key}: некорректное значение.")
            values[key] = value.strip()
    if "url" in values and values["url"] and not values["url"].startswith(("https://", "http://")):
        return err("bad_url", "Партнёрская ссылка должна начинаться с http:// или https://.")
    for key, low, high in (("hold", 0, 365), ("age_min", 18, 120), ("age_max", 18, 120), ("network_payout", 0, 100000000), ("user_reward", 1, 100000000)):
        if key in body:
            value = body[key]
            if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
                return err("bad_field", f"Поле {key}: значение вне допустимого диапазона.")
            values[key] = value
    if not values:
        return err("empty_update", "Нет полей для изменения.")
    async with Session() as s:
        offer = (await s.execute(select(Offer).where(Offer.id == offer_id).with_for_update())).scalar_one_or_none()
        if offer is None:
            return err("not_found", "Оффер не найден.", 404)
        bank = await s.get(Bank, offer.bank_id)
        next_age_min = values.get("age_min", offer.age_min)
        next_age_max = values.get("age_max", offer.age_max)
        if next_age_min > next_age_max:
            return err("bad_age_range", "Минимальный возраст не может быть выше максимального.")
        next_url = values.get("url", offer.url)
        if offer.enabled and (not next_url or not next_url.startswith(("https://", "http://"))):
            return err("missing_partner_url", "Нельзя оставить активный оффер без партнёрской ссылки.", 409)
        if bank and bank.category == "bk" and offer.enabled and (offer.network_status != "approved" or not offer.approval.strip()):
            return err("bookmaker_not_approved", "Сначала зафиксируй согласование партнёра.", 409)
        current_tier = (await s.execute(select(Tier).where(Tier.offer_id == offer.id).order_by(Tier.id))).scalars().first()
        before = {
            "name": offer.name, "condition": offer.condition_text or offer.action,
            "network_payout": current_tier.payout if current_tier else 0, "user_reward": current_tier.cashback if current_tier else 0, "hold_days": offer.hold,
            "minimum": offer.purchase_min, "age_min": offer.age_min, "age_max": offer.age_max,
            "tracking_param": offer.link_param, "partner_url": offer.url, "source_url": offer.source_url,
        }
        after = dict(before)
        after.update({"name": values.get("name", offer.name), "condition": values.get("condition_text", values.get("action", offer.condition_text or offer.action)), "network_payout": values.get("network_payout", before["network_payout"]), "user_reward": values.get("user_reward", before["user_reward"]), "hold_days": values.get("hold", offer.hold), "age_min": next_age_min, "age_max": next_age_max, "partner_url": next_url, "source_url": values.get("source_url", offer.source_url)})
        from bot.offer_rules import bk_approval_must_be_reset
        reset_approval = bk_approval_must_be_reset(bank.category if bank else "", before, after)
        for key, value in values.items():
            if key in {"network_payout", "user_reward"}:
                continue
            setattr(offer, key, value)
        if "network_payout" in values or "user_reward" in values:
            if current_tier is None:
                current_tier = Tier(offer_id=offer.id, payout=after["network_payout"], cashback=after["user_reward"])
                s.add(current_tier)
            else:
                current_tier.payout = after["network_payout"]
                current_tier.cashback = after["user_reward"]
        if reset_approval:
            offer.network_status = "needs_approval"
            offer.approval = "Старое согласование сброшено после изменения существенных условий. Требуется повторное письменное подтверждение."
            offer.terms_checked_at = None
            offer.enabled = False
            s.add(OfferEvent(offer_id=offer.id, actor_id=request["uid"], event="approval_reset", details="Существенные условия изменены; оффер отключён до нового письменного согласования"))
        summary = ", ".join(sorted(values.keys()))
        s.add(OfferEvent(offer_id=offer.id, actor_id=request["uid"], event="updated", details=f"Поля: {summary}"))
        await _admin_audit(s, request["uid"], "offer_updated", "offer", offer.id, f"Изменены поля: {summary}" + ("; согласование сброшено, оффер отключён" if reset_approval else ""))
        await s.commit()
        return ok({"id": offer.id, "name": offer.name, "url": offer.url, "action": offer.action, "rules": offer.rules, "hold": offer.hold, "age_min": offer.age_min, "age_max": offer.age_max, "network_payout": after["network_payout"], "user_reward": after["user_reward"], "condition_text": offer.condition_text, "enabled": offer.enabled, "network_status": offer.network_status, "approval_reset": reset_approval})


async def admin_payout_action(request):
    if request["uid"] not in cfg.admins:
        return err("forbidden", "Нет доступа.", 403)
    try:
        body = await request.json()
    except Exception:
        return err("bad_json", "Некорректный запрос.")
    action = body.get("action") if isinstance(body, dict) else None
    if action not in {"take", "paid", "reject"}:
        return err("bad_action", "Допустимые действия: take, paid, reject.")
    try:
        payout_id = int(request.match_info["id"])
    except (TypeError, ValueError):
        return err("bad_id", "Некорректный ID выплаты.")
    referral = None
    async with Session() as s:
        payout = (await s.execute(select(PayoutReq).where(PayoutReq.id == payout_id).with_for_update())).scalar_one_or_none()
        if payout is None:
            return err("not_found", "Запрос на вывод не найден.", 404)
        old = payout.status
        if action == "take":
            if old != "pending":
                return err("invalid_status", "Запрос уже взят в работу или закрыт.", 409)
            payout.status = "processing"
            payout.processed_by = request["uid"]
            payout.updated_at = datetime.utcnow()
            s.add(PayoutEvent(payout_id=payout.id, actor_id=request["uid"], event="taken", from_status=old, to_status="processing", comment="Администратор взял запрос в работу через веб-панель"))
            await _admin_audit(s, request["uid"], "payout_taken", "payout", payout.id, f"Сумма: {payout.amount} ₽")
            await s.commit()
            await notify(request.app[BOT_KEY], payout.user_id, f"🔄 Запрос на вывод #{payout.id} взят в обработку. Сумма {payout.amount} ₽ зарезервирована.")
            return ok({"id": payout.id, "status": payout.status})
        if action == "reject":
            reason = body.get("reason", "") if isinstance(body, dict) else ""
            reason = reason.strip() if isinstance(reason, str) else ""
            if not reason or len(reason) > 1500:
                return err("bad_reason", "Для отказа укажи причину длиной до 1500 символов.")
            if old not in ("pending", "processing", "review_required"):
                return err("invalid_status", "Этот запрос уже закрыт; повторный возврат запрещён.", 409)
            user = (await s.execute(select(User).where(User.id == payout.user_id).with_for_update())).scalar_one_or_none()
            if user is None:
                return err("user_not_found", "Пользователь не найден.", 409)
            payout.status, payout.admin_note, payout.updated_at, payout.processed_by = "rejected", reason, datetime.utcnow(), request["uid"]
            refund_ref = f"withdraw-refund:{payout.id}"
            exists = (await s.execute(select(WalletEntry).where(WalletEntry.ref == refund_ref))).scalar_one_or_none()
            if not exists:
                user.balance += payout.amount
                s.add(WalletEntry(user_id=user.id, amount=payout.amount, kind="withdraw_refund", ref=refund_ref, note="Возврат отклонённой выплаты"))
            s.add(PayoutEvent(payout_id=payout.id, actor_id=request["uid"], event="rejected", from_status=old, to_status="rejected", comment=reason))
            await _admin_audit(s, request["uid"], "payout_rejected_refunded", "payout", payout.id, f"{payout.amount} ₽ возвращены на баланс. Причина: {reason}")
            user_id, amount = payout.user_id, payout.amount
            await s.commit()
            await notify(request.app[BOT_KEY], user_id, f"❌ Запрос на вывод #{payout_id} отклонён.\nПричина: {reason}\n{amount} ₽ возвращены на доступный баланс.")
            return ok({"id": payout_id, "status": "rejected", "refunded": amount})
        if old not in ("processing", "review_required"):
            return err("invalid_status", "Сначала возьми запрос в работу. Уже закрытый запрос нельзя отметить выплаченным.", 409)
        payout.status = "paid"
        payout.paid_at = datetime.utcnow()
        payout.updated_at = datetime.utcnow()
        payout.processed_by = request["uid"]
        comment = "Фактический банковский перевод подтверждён администратором через веб-панель"
        s.add(PayoutEvent(payout_id=payout.id, actor_id=request["uid"], event="paid", from_status=old, to_status="paid", comment=comment))
        await _admin_audit(s, request["uid"], "payout_marked_paid", "payout", payout.id, f"Фактический перевод подтверждён: {payout.amount} ₽")
        from bot.bonuses import referral_payout_bonus
        referral = await referral_payout_bonus(s, payout)
        user_id, amount = payout.user_id, payout.amount
        await s.commit()
    await notify(request.app[BOT_KEY], user_id, f"💸 <b>Перевод {amount} ₽ выполнен</b> по заявке на вывод #{payout_id}.")
    if referral:
        referrer_id, bonus_amount = referral
        await notify(request.app[BOT_KEY], referrer_id, f"🎁 <b>+{bonus_amount} ₽ за друга!</b> Твой друг получил первую выплату — бонус зачислен в кошелёк.")
    return ok({"id": payout_id, "status": "paid"})


def setup_tma(app: web.Application, bot):
    app[BOT_KEY] = bot
    app.middlewares.insert(0, headers_middleware)
    app.middlewares.append(api_middleware)
    r = app.router
    async def root_redirect(_request):
        return web.Response(status=302, headers={"Location": "/app"})
    async def admin_root_redirect(_request):
        return web.Response(status=302, headers={"Location": "/app/admin/login"})
    r.add_get("/", root_redirect)
    r.add_get("/admin", admin_root_redirect)
    r.add_post("/api/v1/auth/telegram", auth_telegram)
    r.add_get("/api/v1/admin/login-config", admin_login_config)
    r.add_post("/api/v1/auth/telegram-widget", auth_telegram_widget)
    r.add_post("/api/v1/auth/logout", auth_logout)
    r.add_get("/api/v1/me", me)
    r.add_get("/api/v1/admin/overview", admin_overview)
    r.add_get("/api/v1/admin/section/{section}", admin_section)
    r.add_post("/api/v1/admin/applications/{id}/action", admin_app_action)
    r.add_get("/api/v1/admin/applications/{id}/proof/{idx}", admin_proof_file)
    r.add_post("/api/v1/admin/users/{id}/action", admin_user_action)
    r.add_post("/api/v1/admin/broadcasts/preview", admin_broadcast_preview)
    r.add_post("/api/v1/admin/broadcasts/send", admin_broadcast_send)
    r.add_put("/api/v1/admin/offers/{id}/enabled", admin_offer_enabled)
    r.add_put("/api/v1/admin/offers/{id}", admin_offer_update)
    r.add_post("/api/v1/admin/offers", admin_offer_create)
    r.add_post("/api/v1/admin/payouts/{id}/action", admin_payout_action)
    r.add_post("/api/v1/me/accept", me_accept)
    r.add_put("/api/v1/me/age", me_age)
    r.add_put("/api/v1/me/sbp", me_sbp)
    r.add_get("/api/v1/dashboard", dashboard)
    r.add_get("/api/v1/meta", meta)
    r.add_get("/api/v1/notifications", notifications)
    r.add_post("/api/v1/notifications/read", notifications_read)
    r.add_get("/api/v1/offers", offers_list)
    r.add_get("/api/v1/offers/{id}", offer_detail)
    r.add_post("/api/v1/offers/{id}/take", offer_take)
    r.add_get("/api/v1/apps", apps_list)
    r.add_get("/api/v1/apps/{id}", app_detail)
    r.add_post("/api/v1/apps/{id}/proofs", app_proofs_upload)
    r.add_get("/api/v1/apps/{id}/proofs/{idx}/file", app_proof_file)
    r.add_post("/api/v1/apps/{id}/submit", app_submit)
    r.add_get("/api/v1/apps/{id}/messages", deal_messages_list)
    r.add_post("/api/v1/apps/{id}/messages", deal_message_create)
    r.add_get("/api/v1/wallet", wallet)
    r.add_get("/api/v1/wallet/entries", wallet_entries)
    r.add_get("/api/v1/withdrawals", withdrawals_list)
    r.add_post("/api/v1/withdrawals", withdrawals_create)
    r.add_post("/api/v1/withdrawals/{id}/cancel", withdrawals_cancel)
    r.add_get("/api/v1/tasks", tasks_list)
    r.add_post("/api/v1/tasks/channel/check", tasks_channel_check)
    r.add_get("/api/v1/friends", friends)
    r.add_get("/api/v1/achievements", achievements_list)
    r.add_get("/api/v1/leaderboard", leaderboard)

    assets = ROOT / "assets"
    if assets.exists():
        r.add_static("/assets", assets, show_index=False)
    dist = ROOT / "webapp" / "dist"
    if (dist / "assets").exists():
        r.add_static("/app/assets", dist / "assets", show_index=False)
    r.add_get("/app", spa_index)
    r.add_get("/app/{tail:.*}", spa_index)