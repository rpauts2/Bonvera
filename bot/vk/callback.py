"""VK Callback API validation and idempotent event dispatch."""
from __future__ import annotations

import hmac
from datetime import datetime, timedelta
from typing import Awaitable, Callable

from aiohttp import web
from sqlalchemy.exc import IntegrityError

from bot.config import cfg
from bot.db import Session, VkCallbackEvent

MessageHandler = Callable[[dict, str], Awaitable[None]]


async def claim_callback_event(event_id: str, event_type: str) -> bool:
    """Claim an event once; failed or stale processing can be retried."""
    now = datetime.utcnow()
    async with Session() as session:
        row = await session.get(VkCallbackEvent, event_id, with_for_update=True)
        if row is not None:
            if row.status == "processed":
                return False
            if row.status == "processing" and row.received_at and now - row.received_at < timedelta(minutes=5):
                return False
            row.status = "processing"
            row.event_type = event_type
            row.attempt_count += 1
            row.received_at = now
            row.last_error_code = ""
        else:
            session.add(VkCallbackEvent(
                event_id=event_id,
                event_type=event_type,
                status="processing",
                attempt_count=1,
                received_at=now,
            ))
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            return False
    return True


async def finish_callback_event(event_id: str, *, success: bool, error_code: str = "") -> None:
    async with Session() as session:
        row = await session.get(VkCallbackEvent, event_id)
        if row is None:
            return
        row.status = "processed" if success else "failed"
        row.processed_at = datetime.utcnow() if success else None
        row.last_error_code = "" if success else (error_code[:80] or "handler_error")
        await session.commit()


async def _default_message_handler(message: dict, event_id: str) -> None:
    from bot.vk.flow import handle_vk_message
    await handle_vk_message(message, event_id)


async def handle_vk_callback(
    request,
    *,
    message_handler: MessageHandler | None = None,
) -> web.Response:
    if not cfg.vk_enabled:
        return web.Response(text="disabled", status=503)
    try:
        payload = await request.json()
    except Exception:
        return web.Response(text="bad_request", status=400)
    if not isinstance(payload, dict):
        return web.Response(text="bad_request", status=400)

    supplied_secret = payload.get("secret")
    group_id = payload.get("group_id")
    try:
        received_group_id = int(group_id)
    except (TypeError, ValueError):
        received_group_id = 0

    if (
        not isinstance(supplied_secret, str)
        or not cfg.vk_callback_secret
        or not hmac.compare_digest(supplied_secret, cfg.vk_callback_secret)
        or received_group_id != cfg.vk_group_id
    ):
        return web.Response(text="forbidden", status=403)

    event_type = payload.get("type")
    if event_type == "confirmation":
        if not cfg.vk_confirmation:
            return web.Response(text="confirmation_not_configured", status=503)
        return web.Response(text=cfg.vk_confirmation)

    if event_type != "message_new":
        return web.Response(text="ok")

    event_id = payload.get("event_id")
    obj = payload.get("object")
    message = obj.get("message") if isinstance(obj, dict) else None
    if not isinstance(event_id, str) or not event_id or len(event_id) > 64:
        return web.Response(text="bad_event_id", status=400)
    if not isinstance(message, dict):
        return web.Response(text="bad_message", status=400)
    try:
        sender_id = int(message.get("from_id", 0))
    except (TypeError, ValueError):
        sender_id = 0
    if sender_id <= 0:
        # Only one-to-one messages initiated by a VK user enter the lead flow.
        return web.Response(text="ok")

    claimed = await claim_callback_event(event_id, event_type)
    if not claimed:
        return web.Response(text="ok")

    handler = message_handler or _default_message_handler
    try:
        await handler(message, event_id)
    except Exception as exc:
        await finish_callback_event(
            event_id,
            success=False,
            error_code=type(exc).__name__,
        )
        return web.Response(text="temporarily_unavailable", status=500)

    await finish_callback_event(event_id, success=True)
    return web.Response(text="ok")
