"""Guardrails for public-facing MFO advertising copy."""
from __future__ import annotations

import re

REQUIRED_WARNING = "Оценивайте свои финансовые возможности и риски."
APPROVAL_CLAIM = re.compile(
    r"(вам\s+)?(предварительно\s+)?одобрен[а-яё]*|"
    r"одобряем\s+всем|100\s*%\s+одобр|гарантированн[а-яё]*\s+одобр",
    re.IGNORECASE,
)


def validate_campaign_copy(
    text: str,
    *,
    advertiser_name: str,
    warning_text: str,
) -> dict:
    errors: list[str] = []
    if not isinstance(text, str) or not text.strip():
        errors.append("empty_text")
    elif len(text) > 3500:
        errors.append("text_too_long")
    if not isinstance(advertiser_name, str) or not advertiser_name.strip():
        errors.append("advertiser")
    if not isinstance(warning_text, str) or REQUIRED_WARNING.casefold() not in warning_text.casefold():
        errors.append("warning")
    combined = f"{text or ''}\n{warning_text or ''}"
    if APPROVAL_CLAIM.search(combined):
        errors.append("approval_claim")
    return {"ok": not errors, "errors": errors}
