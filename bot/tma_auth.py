"""Server-side Telegram Mini App initData verification and opaque bearer sessions.

Implements the official HMAC-SHA256 protocol for bot-token validation:
secret = HMAC_SHA256("WebAppData", bot_token), then HMAC over the sorted
decoded field list excluding only `hash`. The client-supplied user id is
never trusted without this check.
"""
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl

from sqlalchemy import delete, select

from bot.config import cfg
from bot.db import Session, TmaSession

MAX_AUTH_AGE_SECONDS = 3600
FUTURE_SKEW_SECONDS = 60


class InitDataError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def verify_init_data(init_data: str, bot_token: str, now: datetime | None = None) -> dict:
    if not init_data or not bot_token:
        raise InitDataError("empty", "Пустые данные авторизации.")
    pairs = parse_qsl(init_data, keep_blank_values=True)
    keys = [k for k, _ in pairs]
    if len(keys) != len(set(keys)):
        raise InitDataError("duplicate_field", "Дублирующиеся поля initData отклонены.")
    fields = dict(pairs)
    received_hash = fields.pop("hash", "")
    if not received_hash:
        raise InitDataError("no_hash", "В initData отсутствует подпись hash.")
    data_check_string = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    computed = hmac.new(secret, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(computed, received_hash):
        raise InitDataError("bad_signature", "Подпись initData не прошла проверку.")
    try:
        auth_date = int(fields.get("auth_date", "0"))
    except ValueError:
        raise InitDataError("bad_auth_date", "Некорректный auth_date.")
    now_ts = (now or datetime.now(timezone.utc)).timestamp()
    if auth_date <= 0:
        raise InitDataError("bad_auth_date", "Некорректный auth_date.")
    if auth_date > now_ts + FUTURE_SKEW_SECONDS:
        raise InitDataError("future_auth_date", "auth_date из будущего отклонён.")
    if now_ts - auth_date > MAX_AUTH_AGE_SECONDS:
        raise InitDataError("expired", "Данные авторизации устарели. Открой приложение заново.")
    try:
        user = json.loads(fields.get("user", "{}"))
    except (ValueError, TypeError):
        raise InitDataError("bad_user", "Некорректные данные пользователя.")
    if not isinstance(user, dict) or not isinstance(user.get("id"), int):
        raise InitDataError("bad_user", "В initData нет корректного Telegram ID.")
    return {"user": user, "auth_date": auth_date, "fields": fields}


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def create_session(s: Session, user_id: int) -> tuple[str, datetime]:
    token = secrets.token_urlsafe(32)
    expires = datetime.utcnow() + timedelta(hours=cfg.tma_session_hours)
    s.add(TmaSession(token_hash=token_hash(token), user_id=user_id, expires=expires))
    await s.execute(delete(TmaSession).where(TmaSession.expires < datetime.utcnow()))
    await s.commit()
    return token, expires


async def session_user_id(s: Session, token: str) -> int | None:
    if not token:
        return None
    row = (
        await s.execute(
            select(TmaSession).where(
                TmaSession.token_hash == token_hash(token),
                TmaSession.expires > datetime.utcnow(),
            )
        )
    ).scalar_one_or_none()
    return row.user_id if row else None