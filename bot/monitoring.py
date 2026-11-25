"""Мониторинг живости сервиса.

Задача модуля — не дать «тихо умереть»: если polling упал, база недоступна или
Telegram API не отвечает, администраторы должны узнать об этом без звонка
пользователя. Проверка выполняется раз в `HEALTH_INTERVAL_MIN` минут, алерт
повторяется не чаще одного раза в `HEALTH_ALERT_COOLDOWN_MIN` минут.

`/health` отдаёт последнее известное состояние и дешёвую живую проверку БД —
её использует healthcheck контейнера.
"""
import logging
import time
from datetime import datetime, timezone

from sqlalchemy import text

from bot.config import cfg
from bot.db import Session
from bot.version import build_info

HEALTH: dict = {
    "started_at": None,
    "last_check": None,
    "db": "unknown",
    "telegram": "unknown",
    "web": "ok",
    "last_error": "",
}

_last_alert_at: float = 0.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


async def check_db() -> bool:
    try:
        async with Session() as s:
            await s.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # noqa: BLE001
        HEALTH["db"] = "error"
        HEALTH["last_error"] = f"db: {exc}"[:200]
        return False


async def check_telegram(bot) -> bool:
    if bot is None:
        HEALTH["telegram"] = "unknown"
        return True
    try:
        me = await bot.get_me()
        HEALTH["telegram"] = "ok"
        HEALTH["bot_username"] = getattr(me, "username", "") or ""
        return True
    except Exception as exc:  # noqa: BLE001
        HEALTH["telegram"] = "error"
        HEALTH["last_error"] = f"telegram: {exc}"[:200]
        return False


async def run_healthcheck(bot) -> dict:
    """One health round: database, Telegram API, web layer."""
    HEALTH["last_check"] = _now_iso()
    db_ok = await check_db()
    if db_ok:
        HEALTH["db"] = "ok"
    tg_ok = await check_telegram(bot)
    HEALTH["ok"] = bool(db_ok and tg_ok)
    return HEALTH


async def watchdog(bot) -> bool:
    """Scheduled health round; notifies admins when something is broken."""
    global _last_alert_at
    health = await run_healthcheck(bot)
    if health.get("ok"):
        return True
    now = time.monotonic()
    if now - _last_alert_at < cfg.health_alert_cooldown_min * 60:
        return False
    _last_alert_at = now
    text = (
        "🚨 <b>BONVERA: проблема с живостью сервиса</b>\n"
        f"БД: {health.get('db')} · Telegram: {health.get('telegram')}\n"
        f"Детали: {health.get('last_error') or 'неизвестно'}\n"
        f"Проверка: {health.get('last_check')}"
    )
    for ad in cfg.admins:
        try:
            from bot.logic import notify

            await notify(bot, ad, text)
        except Exception:  # noqa: BLE001 — алерт не должен ронять планировщик
            logging.exception("не удалось отправить алерт админу %s", ad)
    return False


def health_payload() -> dict:
    """Snapshot for /health."""
    payload = {
        "ok": bool(HEALTH.get("db") in ("ok", "unknown") and HEALTH.get("telegram") in ("ok", "unknown")),
        "db": HEALTH.get("db", "unknown"),
        "telegram": HEALTH.get("telegram", "unknown"),
        "web": "ok",
        "last_check": HEALTH.get("last_check"),
        "started_at": HEALTH.get("started_at"),
        "build": build_info(),
    }
    if HEALTH.get("bot_username"):
        payload["bot"] = HEALTH["bot_username"]
    if HEALTH.get("last_error"):
        payload["last_error"] = HEALTH["last_error"]
    return payload
