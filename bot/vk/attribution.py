"""Signed VK deep links for campaign-level source attribution."""
from __future__ import annotations

import hashlib
import hmac
import re
from urllib.parse import urlencode, urlsplit, urlunsplit

from bot.config import cfg


def _community_base() -> str:
    raw = (cfg.vk_community_url or "").strip()
    if not raw:
        raise ValueError("VK_COMMUNITY_URL is not configured")
    parsed = urlsplit(raw)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("VK community URL must use HTTPS")
    host = parsed.hostname.lower()
    if host == "vk.me":
        if not re.fullmatch(r"/[A-Za-z0-9_.-]{2,64}/?", parsed.path):
            raise ValueError("VK community URL must be https://vk.me/{community}")
        return "https://vk.me" + parsed.path.rstrip("/")
    if host in {"vk.com", "www.vk.com"} and re.fullmatch(r"/write-[1-9][0-9]{2,15}", parsed.path):
        return "https://vk.com" + parsed.path
    raise ValueError("Use https://vk.me/{community} or https://vk.com/write-{group_id}")


def make_campaign_ref(campaign_id: int) -> str:
    if campaign_id <= 0:
        raise ValueError("Campaign ID must be positive")
    message = f"vk-entry:{campaign_id}".encode("utf-8")
    signature = hmac.new(cfg.salt.encode("utf-8"), message, hashlib.sha256).hexdigest()[:16]
    return f"c{campaign_id}_{signature}"


def parse_campaign_ref(value: str | None) -> int | None:
    if not isinstance(value, str) or len(value) > 64:
        return None
    match = re.fullmatch(r"c([1-9][0-9]{0,9})_([a-f0-9]{16})", value)
    if not match:
        return None
    campaign_id = int(match.group(1))
    expected = make_campaign_ref(campaign_id)
    return campaign_id if hmac.compare_digest(expected, value) else None


def build_campaign_entry_link(campaign_id: int) -> str:
    base = _community_base()
    params = urlencode({
        "ref": make_campaign_ref(campaign_id),
        "ref_source": "bonvera",
    })
    parts = urlsplit(base)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, params, ""))
