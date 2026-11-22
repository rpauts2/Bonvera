"""Opaque click tracking for VK outbound MFO and CPA links."""
from __future__ import annotations

import hashlib
import ipaddress
import re
import secrets
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import select

from bot.config import cfg
from bot.db import Session, VkClick, VkOfferSlot


def validate_external_target(url: str) -> str:
    """Allow only safe public HTTPS partner destinations."""
    if not isinstance(url, str) or not url.strip() or len(url) > 2048:
        raise ValueError("Partner URL is empty or too long")
    parsed = urlsplit(url.strip())
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise ValueError("Partner URL must use HTTPS")
    if parsed.username or parsed.password:
        raise ValueError("Partner URL cannot contain credentials")
    if parsed.port not in (None, 443):
        raise ValueError("Partner URL must use the standard HTTPS port")
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith((".localhost", ".local", ".internal")):
        raise ValueError("Partner URL cannot point to a local host")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ValueError("Partner URL cannot point to a private or reserved IP")
    if re.search(r"[\r\n\x00]", url):
        raise ValueError("Partner URL contains invalid characters")
    return url.strip()


async def create_click(
    *,
    contact_id: int | None,
    slot_number: int,
    campaign_id: int | None = None,
    source: str = "",
) -> str:
    """Create an opaque redirect token tied to one configured offer slot."""
    if slot_number not in range(1, 6):
        raise ValueError("VK offer slot must be between 1 and 5")
    if not cfg.vk_public_base_url.startswith("https://"):
        raise RuntimeError("VK_PUBLIC_BASE_URL must be configured before exposing tracked links")
    async with Session() as session:
        slot = await session.get(VkOfferSlot, slot_number, populate_existing=True)
        if slot is None or not slot.enabled or not slot.target_url:
            raise ValueError("VK offer slot is not configured or active")
        target = validate_external_target(slot.target_url)
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        domain = urlsplit(target).hostname or ""
        session.add(VkClick(
            token_hash=token_hash,
            contact_id=contact_id,
            slot_number=slot_number,
            campaign_id=campaign_id,
            source=(source or "")[:80],
            destination_domain=domain[:255],
            outcome="created",
        ))
        await session.commit()
    return f"{cfg.vk_public_base_url.rstrip('/')}/vk/go/{token}"


async def resolve_click(token: str) -> str | None:
    """Resolve an opaque token only through its stored slot; never accepts a target from the request."""
    if not isinstance(token, str) or not token or len(token) > 128:
        return None
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    async with Session() as session:
        click = (await session.execute(
            select(VkClick).where(VkClick.token_hash == token_hash)
        )).scalar_one_or_none()
        if click is None:
            return None
        slot = await session.get(VkOfferSlot, click.slot_number)
        if slot is None or not slot.enabled or not slot.target_url:
            click.outcome = "blocked"
            await session.commit()
            return None
        try:
            target = validate_external_target(slot.target_url)
        except ValueError:
            click.outcome = "blocked"
            await session.commit()
            return None
        if slot.tracking_param:
            param = slot.tracking_param.strip()
            if not re.fullmatch(r"[A-Za-z0-9_]{1,40}", param):
                click.outcome = "blocked"
                await session.commit()
                return None
            parts = urlsplit(target)
            query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if key != param]
            query.append((param, token))
            target = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
        click.outcome = "redirected"
        await session.commit()
        return target
