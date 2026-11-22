"""Opt-in VK audience import, campaign drafts and durable dispatcher."""
from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select

from bot.config import cfg
from bot.db import (
    Session,
    VkCampaign,
    VkCampaignRecipient,
    VkConsentEvent,
    VkContact,
)
from bot.vk.client import VKAPIError, VKClient
from bot.vk.copy_policy import validate_campaign_copy, validate_campaign_launch

CONSENT_COLUMNS = {
    "vk_user_id",
    "personal_data_consent_at",
    "personal_data_consent_source",
    "personal_data_consent_version",
    "personal_data_consent_proof",
    "marketing_consent_at",
    "marketing_consent_source",
    "marketing_consent_version",
    "marketing_consent_proof",
}

def _parse_datetime(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def preview_contact_import(csv_text: str) -> dict[str, Any]:
    """Validate a user-provided VK ID list without writing contacts."""
    if not isinstance(csv_text, str) or not csv_text.strip():
        return {"total": 0, "valid_count": 0, "duplicate_count": 0, "rows": [], "errors": [{"line": 0, "reason": "empty_file"}]}
    if len(csv_text.encode("utf-8")) > 5 * 1024 * 1024:
        return {"total": 0, "valid_count": 0, "duplicate_count": 0, "rows": [], "errors": [{"line": 0, "reason": "file_too_large"}]}
    reader = csv.DictReader(io.StringIO(csv_text))
    headers = {str(h or "").strip().lower() for h in (reader.fieldnames or [])}
    missing = sorted(CONSENT_COLUMNS - headers)
    if missing:
        return {
            "total": 0,
            "valid_count": 0,
            "duplicate_count": 0,
            "rows": [],
            "errors": [{"line": 1, "reason": "missing_columns:" + ",".join(missing)}],
        }

    rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    seen: set[int] = set()
    duplicate_count = 0
    for line, raw in enumerate(reader, start=2):
        if line > 5001:
            errors.append({"line": line, "reason": "row_limit_exceeded"})
            break
        values = {str(k or "").strip().lower(): str(v or "").strip() for k, v in raw.items()}
        try:
            vk_user_id = int(values.get("vk_user_id", ""))
        except (TypeError, ValueError):
            errors.append({"line": line, "reason": "invalid_vk_user_id"})
            continue
        personal_at = _parse_datetime(values.get("personal_data_consent_at", ""))
        personal_source = values.get("personal_data_consent_source", "")
        personal_version = values.get("personal_data_consent_version", "")
        personal_proof = values.get("personal_data_consent_proof", "")
        marketing_at = _parse_datetime(values.get("marketing_consent_at", ""))
        marketing_source = values.get("marketing_consent_source", "")
        marketing_version = values.get("marketing_consent_version", "")
        marketing_proof = values.get("marketing_consent_proof", "")
        if vk_user_id <= 0:
            errors.append({"line": line, "reason": "invalid_vk_user_id"})
            continue
        if personal_at is None or personal_at > datetime.utcnow() + timedelta(minutes=5):
            errors.append({"line": line, "reason": "invalid_personal_data_consent_at"})
            continue
        if marketing_at is None or marketing_at > datetime.utcnow() + timedelta(minutes=5):
            errors.append({"line": line, "reason": "invalid_marketing_consent_at"})
            continue
        required = [
            ("personal_data_consent_source", personal_source, 120),
            ("personal_data_consent_version", personal_version, 40),
            ("personal_data_consent_proof", personal_proof, 255),
            ("marketing_consent_source", marketing_source, 120),
            ("marketing_consent_version", marketing_version, 40),
            ("marketing_consent_proof", marketing_proof, 255),
        ]
        invalid = next((name for name, value, max_len in required if not value or len(value) > max_len), None)
        if invalid:
            errors.append({"line": line, "reason": "missing_or_invalid_" + invalid})
            continue
        if vk_user_id in seen:
            duplicate_count += 1
            continue
        seen.add(vk_user_id)
        rows.append({
            "vk_user_id": vk_user_id,
            "personal_data_consent_at": personal_at,
            "personal_data_consent_source": personal_source,
            "personal_data_consent_version": personal_version,
            "personal_data_consent_proof": personal_proof,
            "marketing_consent_at": marketing_at,
            "marketing_consent_source": marketing_source,
            "marketing_consent_version": marketing_version,
            "marketing_consent_proof": marketing_proof,
            "line": line,
        })

    return {
        "total": len(rows) + duplicate_count + len(errors),
        "valid_count": len(rows),
        "duplicate_count": duplicate_count,
        "rows": rows,
        "errors": errors,
    }


def is_marketing_eligible(contact: VkContact) -> bool:
    return bool(
        contact.personal_data_consent_at is not None
        and contact.marketing_consent_at is not None
        and not contact.marketing_suppressed
    )


async def commit_contact_import(csv_text: str, admin_id: int) -> dict[str, int]:
    preview = preview_contact_import(csv_text)
    if preview["errors"]:
        raise ValueError("CSV contains invalid rows; fix all errors before importing")
    created = updated = suppressed = 0
    async with Session() as session:
        for item in preview["rows"]:
            contact = (await session.execute(
                select(VkContact).where(VkContact.vk_user_id == item["vk_user_id"]).with_for_update()
            )).scalar_one_or_none()
            # An explicit prior opt-out is never silently overridden by re-importing an old list.
            if contact is not None and contact.marketing_suppressed:
                suppressed += 1
                continue
            if contact is None:
                contact = VkContact(
                    vk_user_id=item["vk_user_id"],
                    flow_state="awaiting_personal_data_consent",
                    source_campaign="admin_contact_import",
                    marketing_suppressed=False,
                )
                session.add(contact)
                await session.flush()
                created += 1
            else:
                updated += 1
            contact.personal_data_consent_at = item["personal_data_consent_at"]
            contact.personal_data_consent_version = item["personal_data_consent_version"]
            contact.marketing_consent_at = item["marketing_consent_at"]
            contact.marketing_consent_version = item["marketing_consent_version"]
            contact.marketing_consent_source = item["marketing_consent_source"]
            contact.marketing_suppressed = False
            session.add(VkConsentEvent(
                contact_id=contact.id,
                consent_type="personal_data",
                action="granted",
                text_version=item["personal_data_consent_version"],
                source=item["personal_data_consent_source"],
                proof_reference=item["personal_data_consent_proof"],
                metadata_json={"imported_by_admin": int(admin_id), "csv_line": item["line"]},
                occurred_at=item["personal_data_consent_at"],
            ))
            session.add(VkConsentEvent(
                contact_id=contact.id,
                consent_type="marketing",
                action="granted",
                text_version=item["marketing_consent_version"],
                source=item["marketing_consent_source"],
                proof_reference=item["marketing_consent_proof"],
                metadata_json={"imported_by_admin": int(admin_id), "csv_line": item["line"]},
                occurred_at=item["marketing_consent_at"],
            ))
        await session.commit()
    return {"created": created, "updated": updated, "suppressed": suppressed}


async def create_campaign_draft(admin_id: int, payload: dict) -> int:
    text = str(payload.get("text") or "")
    advertiser = str(payload.get("advertiser_name") or "").strip()
    warning = str(payload.get("warning_text") or "Оценивайте свои финансовые возможности и риски.")
    validation = validate_campaign_copy(text, advertiser_name=advertiser, warning_text=warning)
    if not validation["ok"]:
        raise ValueError(",".join(validation["errors"]))
    async with Session() as session:
        campaign = VkCampaign(
            admin_id=int(admin_id),
            name=str(payload.get("name") or "VK campaign")[:160],
            text=text.strip(),
            cta_label=str(payload.get("cta_label") or "Посмотреть предложения")[:80],
            status="draft",
            audience_type="opted_in",
            advertiser_name=advertiser[:200],
            advertiser_inn=str(payload.get("advertiser_inn") or "")[:20],
            warning_text=warning[:240],
            erid=str(payload.get("erid") or "")[:120],
            targeting_json=payload.get("targeting_json") if isinstance(payload.get("targeting_json"), dict) else {},
        )
        session.add(campaign)
        await session.commit()
        return campaign.id


async def preview_campaign(campaign_id: int) -> dict[str, int]:
    async with Session() as session:
        campaign = await session.get(VkCampaign, campaign_id)
        if campaign is None:
            raise LookupError("Campaign not found")
        total = int((await session.execute(select(func.count(VkContact.id)))).scalar() or 0)
        eligible = int((await session.execute(
            select(func.count(VkContact.id)).where(
                VkContact.personal_data_consent_at.is_not(None),
                VkContact.marketing_consent_at.is_not(None),
                VkContact.marketing_suppressed == False,
            )
        )).scalar() or 0)
        return {
            "total_contacts": total,
            "eligible_by_consent": eligible,
            "excluded_by_consent": max(0, total - eligible),
            "campaign_id": campaign_id,
        }


async def start_campaign(campaign_id: int, admin_id: int) -> int:
    """Queue eligible contacts after an explicit administrator send action."""
    if not cfg.vk_enabled:
        raise ValueError("VK channel is disabled; configure VK credentials before sending")
    async with Session() as session:
        campaign = (await session.execute(
            select(VkCampaign).where(VkCampaign.id == campaign_id).with_for_update()
        )).scalar_one_or_none()
        if campaign is None:
            raise LookupError("Campaign not found")
        if campaign.admin_id != int(admin_id):
            raise PermissionError("Campaign belongs to another administrator")
        if campaign.status not in {"draft", "paused"}:
            raise ValueError("Campaign cannot be started from current state")
        from bot.db import VkOfferSlot
        slots = (await session.execute(
            select(VkOfferSlot).where(
                VkOfferSlot.enabled == True,
                VkOfferSlot.target_url != "",
            )
        )).scalars().all()
        validation = validate_campaign_launch(
            campaign.text,
            advertiser_name=campaign.advertiser_name,
            advertiser_inn=campaign.advertiser_inn,
            erid=campaign.erid,
            warning_text=campaign.warning_text,
            configured_slots=len({slot.slot_number for slot in slots}),
        )
        if not validation["ok"]:
            raise ValueError(",".join(validation["errors"]))
        contacts = (await session.execute(
            select(VkContact).where(
                VkContact.personal_data_consent_at.is_not(None),
                VkContact.marketing_consent_at.is_not(None),
                VkContact.marketing_suppressed == False,
            )
        )).scalars().all()
        queued = 0
        for contact in contacts:
            key = f"vk-campaign:{campaign.id}:contact:{contact.id}"
            existing = (await session.execute(
                select(VkCampaignRecipient).where(
                    VkCampaignRecipient.campaign_id == campaign.id,
                    VkCampaignRecipient.contact_id == contact.id,
                )
            )).scalar_one_or_none()
            if existing is None:
                session.add(VkCampaignRecipient(
                    campaign_id=campaign.id,
                    contact_id=contact.id,
                    status="pending",
                    idempotency_key=key,
                ))
                queued += 1
        campaign.status = "running"
        campaign.recipient_count = len(contacts)
        campaign.started_at = datetime.utcnow()
        await session.commit()
        return queued


def _campaign_random_id(campaign_id: int, vk_user_id: int) -> int:
    digest = hashlib.sha256(f"vk-campaign:{campaign_id}:{vk_user_id}".encode()).digest()
    return int.from_bytes(digest[:4], "big") & 0x7FFFFFFF or 1


async def _update_recipient(recipient_id: int, status: str, *, error_code: str = "", next_attempt_at=None):
    async with Session() as session:
        recipient = await session.get(VkCampaignRecipient, recipient_id)
        if recipient is None:
            return None
        campaign = await session.get(VkCampaign, recipient.campaign_id)
        recipient.status = status
        recipient.last_error_code = error_code[:80]
        recipient.next_attempt_at = next_attempt_at
        if status == "sent":
            recipient.sent_at = datetime.utcnow()
            if campaign:
                campaign.sent_count += 1
        elif status.startswith("skipped_"):
            if campaign:
                campaign.skipped_count += 1
        elif status.startswith("failed_"):
            if campaign:
                campaign.failed_count += 1
        await session.commit()
        return campaign.id if campaign else None


async def dispatch_campaign_batch(batch_size: int = 10) -> dict[str, int]:
    """Send a small durable batch; permissions and consent are rechecked per recipient."""
    if not cfg.vk_enabled:
        return {"processed": 0, "sent": 0, "skipped": 0, "failed": 0}
    batch_size = max(1, min(int(batch_size), 50))
    now = datetime.utcnow()
    processed = sent = skipped = failed = 0
    async with Session() as session:
        jobs = (await session.execute(
            select(VkCampaignRecipient)
            .join(VkCampaign, VkCampaign.id == VkCampaignRecipient.campaign_id)
            .where(
                VkCampaign.status == "running",
                (
                    (VkCampaignRecipient.status == "pending")
                    | (
                        (VkCampaignRecipient.status == "sending")
                        & (VkCampaignRecipient.next_attempt_at <= now)
                    )
                    | (
                        (VkCampaignRecipient.status == "failed_retryable")
                        & (VkCampaignRecipient.next_attempt_at <= now)
                    )
                ),
            )
            .order_by(VkCampaignRecipient.id)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )).scalars().all()
        job_ids = [job.id for job in jobs]
        for job in jobs:
            job.status = "sending"
            job.attempt_count += 1
            job.next_attempt_at = now + timedelta(minutes=5)
        await session.commit()

    client = VKClient()
    for recipient_id in job_ids:
        processed += 1
        async with Session() as session:
            recipient = await session.get(VkCampaignRecipient, recipient_id)
            if recipient is None:
                continue
            campaign = await session.get(VkCampaign, recipient.campaign_id)
            contact = await session.get(VkContact, recipient.contact_id)
            if campaign is None or contact is None or campaign.status != "running":
                continue
            campaign_data = {
                "id": campaign.id,
                "text": campaign.text,
                "advertiser_name": campaign.advertiser_name,
                "advertiser_inn": campaign.advertiser_inn,
                "erid": campaign.erid,
                "warning_text": campaign.warning_text,
                "cta_label": campaign.cta_label,
            }
            user_id = contact.vk_user_id
            eligible = is_marketing_eligible(contact)
            attempts = recipient.attempt_count
        if not eligible:
            await _update_recipient(recipient_id, "skipped_suppressed", error_code="consent_missing_or_withdrawn")
            skipped += 1
            continue
        try:
            allowed = await client.is_messages_allowed(user_id)
            if not allowed:
                await _update_recipient(recipient_id, "skipped_no_vk_permission", error_code="vk_permission_denied")
                skipped += 1
                continue
            message = (
                f"{campaign_data['text'].strip()}\n\n"
                f"{campaign_data['warning_text'].strip()}\n"
                f"Реклама. Рекламодатель: {campaign_data['advertiser_name'].strip()}, "
                f"ИНН: {campaign_data['advertiser_inn']}. erid: {campaign_data['erid']}"
            )
            keyboard = {
                "one_time": False,
                "inline": False,
                "buttons": [[{
                    "action": {
                        "type": "text",
                        "label": campaign_data["cta_label"][:40],
                        "payload": json.dumps({"action": "show_menu"}, ensure_ascii=False),
                    },
                    "color": "primary",
                }]],
            }
            await client.send_message(
                user_id=user_id,
                text=message,
                keyboard=keyboard,
                random_id=_campaign_random_id(campaign_data["id"], user_id),
            )
            await _update_recipient(recipient_id, "sent")
            sent += 1
        except VKAPIError as exc:
            if exc.retryable and attempts < 5:
                retry_at = datetime.utcnow() + timedelta(minutes=min(60, 2 ** attempts))
                await _update_recipient(recipient_id, "failed_retryable", error_code=f"vk_{exc.code or 'temporary'}", next_attempt_at=retry_at)
            else:
                await _update_recipient(recipient_id, "failed_permanent", error_code=f"vk_{exc.code or 'permanent'}")
            failed += 1
        except Exception:
            await _update_recipient(recipient_id, "failed_permanent", error_code="unexpected_error")
            failed += 1

    async with Session() as session:
        running = (await session.execute(select(VkCampaign).where(VkCampaign.status == "running"))).scalars().all()
        for campaign in running:
            remaining = int((await session.execute(
                select(func.count(VkCampaignRecipient.id)).where(
                    VkCampaignRecipient.campaign_id == campaign.id,
                    VkCampaignRecipient.status.in_(["pending", "sending", "failed_retryable"]),
                )
            )).scalar() or 0)
            if remaining == 0:
                campaign.status = "completed"
                campaign.completed_at = datetime.utcnow()
        await session.commit()
    return {"processed": processed, "sent": sent, "skipped": skipped, "failed": failed}


async def resume_campaign(campaign_id: int, admin_id: int) -> int:
    """Resume a paused campaign through the same strict launch checks."""
    return await start_campaign(campaign_id, admin_id)
