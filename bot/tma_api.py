"""Mini App JSON API mounted on the existing aiohttp server (no second backend).

All money/ownership decisions happen server-side; the client only renders.
Bearer sessions come from bot.tma_auth after HMAC-verified initData.
"""
import time
import re
import html
from collections import deque
from datetime import datetime
from io import BytesIO
from pathlib import Path

from aiohttp import web
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from bot import services
from bot.bonuses import CHANNEL_BONUS, grant_bonus
from bot.config import cfg
from bot.db import App, Bank, DealEvent, DealMessage, Offer, PayoutEvent, PayoutReq, Session, TmaSession, User
from bot.logic import notify, phone_decrypt, phone_encrypt, phone_norm, phash
from bot.proofs import proof_progress, proofs_complete
from bot.tma_auth import InitDataError, create_session, session_user_id, token_hash, verify_init_data
from bot.tma_files import (
    IMAGE_EXT, MAX_FILES_PER_UPLOAD, FileError, resolve_proof, safe_ext, store_proof,
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
    from datetime import datetime
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
    async with Session() as s:
        return ok(await services.list_offers(s, request["uid"], q=q, category=category, sort=sort, available_only=available_only))


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
        return ok(await services.app_detail(s, a))


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

def setup_tma(app: web.Application, bot):
    app[BOT_KEY] = bot
    app.middlewares.insert(0, headers_middleware)
    app.middlewares.append(api_middleware)
    r = app.router
    async def root_redirect(_request):
        return web.Response(status=302, headers={"Location": "/app"})
    r.add_get("/", root_redirect)
    r.add_post("/api/v1/auth/telegram", auth_telegram)
    r.add_post("/api/v1/auth/logout", auth_logout)
    r.add_get("/api/v1/me", me)
    r.add_get("/api/v1/admin/overview", admin_overview)
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