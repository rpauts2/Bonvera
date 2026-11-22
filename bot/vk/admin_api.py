"""Admin-only VK acquisition, offer-slot and campaign endpoints."""
from __future__ import annotations

from datetime import datetime
from urllib.parse import urlsplit
import re

from aiohttp import web
from sqlalchemy import func, select

from bot.config import cfg
from bot.db import AdminAuditEvent, Session, VkCampaign, VkCampaignRecipient, VkClick, VkConsentEvent, VkContact, VkOfferSlot
from bot.vk.outreach import (
    commit_contact_import,
    create_campaign_draft,
    preview_campaign,
    preview_contact_import,
    start_campaign,
)
from bot.vk.tracking import validate_external_target


def _ok(data, status: int = 200):
    return web.json_response({"ok": True, "data": data}, status=status)


def _err(code: str, message: str, status: int = 400):
    return web.json_response({"ok": False, "err": {"code": code, "message": message}}, status=status)


def _admin(request) -> bool:
    return request.get("uid") in cfg.admins


def mask_phone(value: str | None) -> str:
    if not value:
        return ""
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    if len(digits) < 4:
        return "••••"
    return f"+7 *** ***-{digits[-4:-2]}-{digits[-2:]}"


def validate_slots_payload(slots) -> tuple[list[dict], list[str]]:
    if not isinstance(slots, list) or len(slots) != 5:
        return [], ["exactly_five_slots_required"]
    normalized: list[dict] = []
    errors: list[str] = []
    seen: set[int] = set()
    for row in slots:
        if not isinstance(row, dict):
            errors.append("invalid_slot")
            continue
        try:
            number = int(row.get("slot_number", 0))
        except (TypeError, ValueError):
            errors.append("invalid_slot_number")
            continue
        if number < 1 or number > 5 or number in seen:
            errors.append("invalid_or_duplicate_slot_number")
            continue
        seen.add(number)
        expected_kind = "storefront" if number == 5 else "mfo_offer"
        if row.get("kind") != expected_kind:
            errors.append(f"slot_{number}_wrong_kind")
            continue
        url = str(row.get("target_url") or "").strip()
        enabled = bool(row.get("enabled", False))
        advertiser = str(row.get("advertiser_name") or "").strip()[:160]
        title = str(row.get("title") or "").strip()[:160]
        description = str(row.get("description") or "").strip()[:1000]
        tracking_param = str(row.get("tracking_param") or "").strip()
        if url:
            try:
                url = validate_external_target(url)
            except ValueError:
                errors.append(f"slot_{number}_invalid_https_url")
                continue
        if enabled and not url:
            errors.append(f"slot_{number}_url_required")
            continue
        if enabled and not advertiser:
            errors.append(f"slot_{number}_advertiser_required")
            continue
        if tracking_param and not re.fullmatch(r"[A-Za-z0-9_]{1,40}", tracking_param):
            errors.append(f"slot_{number}_invalid_tracking_param")
            continue
        normalized.append({
            "slot_number": number,
            "kind": expected_kind,
            "advertiser_name": advertiser,
            "title": title or ("Все предложения Bonvera" if number == 5 else f"МФО №{number}"),
            "description": description,
            "target_url": url,
            "tracking_param": tracking_param,
            "enabled": enabled and bool(url),
        })
    if seen != {1, 2, 3, 4, 5}:
        errors.append("slot_numbers_must_be_1_to_5")
    if errors:
        return [], errors
    return sorted(normalized, key=lambda item: item["slot_number"]), []


async def _audit(session, admin_id: int, action: str, target_type: str, target_id, details: str = ""):
    session.add(AdminAuditEvent(
        actor_id=int(admin_id),
        action=action[:50],
        target_type=target_type[:30],
        target_id=str(target_id)[:80],
        details=details[:2000],
    ))


async def vk_admin_overview(request):
    if not _admin(request):
        return _err("forbidden", "Нет доступа к VK Marketing.", 403)
    async with Session() as session:
        contacts = int((await session.execute(select(func.count(VkContact.id)))).scalar() or 0)
        marketing_opt_in = int((await session.execute(
            select(func.count(VkContact.id)).where(
                VkContact.marketing_consent_at.is_not(None),
                VkContact.marketing_suppressed == False,
            )
        )).scalar() or 0)
        suppressed = int((await session.execute(
            select(func.count(VkContact.id)).where(VkContact.marketing_suppressed == True)
        )).scalar() or 0)
        campaigns = int((await session.execute(select(func.count(VkCampaign.id)))).scalar() or 0)
        clicks = int((await session.execute(select(func.count(VkClick.id)))).scalar() or 0)
        slots = (await session.execute(select(VkOfferSlot).order_by(VkOfferSlot.slot_number))).scalars().all()
        latest = (await session.execute(select(VkCampaign).order_by(VkCampaign.created.desc()).limit(10))).scalars().all()
    return _ok({
        "vk_enabled": cfg.vk_enabled,
        "contacts_total": contacts,
        "marketing_opt_in": marketing_opt_in,
        "suppressed": suppressed,
        "campaigns_total": campaigns,
        "clicks_total": clicks,
        "configured_slots": sum(1 for slot in slots if slot.enabled and slot.target_url),
        "slots_total": 5,
        "community_url": cfg.vk_community_url,
        "campaigns": [{
            "id": item.id,
            "name": item.name,
            "status": item.status,
            "recipient_count": item.recipient_count,
            "sent_count": item.sent_count,
            "skipped_count": item.skipped_count,
            "failed_count": item.failed_count,
            "created": item.created.isoformat() if item.created else None,
        } for item in latest],
    })


async def vk_admin_slots_get(request):
    if not _admin(request):
        return _err("forbidden", "Нет доступа.", 403)
    async with Session() as session:
        saved = {
            slot.slot_number: slot
            for slot in (await session.execute(select(VkOfferSlot))).scalars().all()
        }
    data = []
    for number in range(1, 6):
        slot = saved.get(number)
        data.append({
            "slot_number": number,
            "kind": "storefront" if number == 5 else "mfo_offer",
            "advertiser_name": slot.advertiser_name if slot else "",
            "title": slot.title if slot else ("Все предложения Bonvera" if number == 5 else f"МФО №{number}"),
            "description": slot.description if slot else "",
            "target_url": slot.target_url if slot else "",
            "tracking_param": slot.tracking_param if slot else "",
            "enabled": bool(slot.enabled and slot.target_url) if slot else False,
        })
    return _ok({"slots": data, "storefront_required": True})


async def vk_admin_slots_put(request):
    if not _admin(request):
        return _err("forbidden", "Нет доступа.", 403)
    try:
        body = await request.json()
    except Exception:
        return _err("bad_json", "Некорректный JSON.")
    slots, errors = validate_slots_payload(body.get("slots") if isinstance(body, dict) else None)
    if errors:
        return _err("invalid_slots", "Исправь настройки ссылок: " + ", ".join(errors), 422)
    async with Session() as session:
        for data in slots:
            slot = (await session.execute(
                select(VkOfferSlot).where(VkOfferSlot.slot_number == data["slot_number"]).with_for_update()
            )).scalar_one_or_none()
            if slot is None:
                slot = VkOfferSlot(slot_number=data["slot_number"], kind=data["kind"])
                session.add(slot)
            for key, value in data.items():
                if key != "slot_number":
                    setattr(slot, key, value)
            slot.updated_by = request["uid"]
            slot.updated_at = datetime.utcnow()
        await _audit(session, request["uid"], "vk_slots_updated", "vk_offer_slots", "1-5", "Администратор обновил пять ссылок VK-воронки")
        await session.commit()
    return _ok({"saved": 5})


async def vk_admin_contacts(request):
    if not _admin(request):
        return _err("forbidden", "Нет доступа.", 403)
    q = (request.query.get("q") or "").strip()[:40]
    try:
        limit = min(100, max(1, int(request.query.get("limit", "50") or 50)))
    except (TypeError, ValueError):
        limit = 50
    async with Session() as session:
        stmt = select(VkContact).order_by(VkContact.created.desc()).limit(limit)
        if q.isdigit():
            stmt = select(VkContact).where(VkContact.vk_user_id == int(q)).limit(limit)
        rows = (await session.execute(stmt)).scalars().all()
        total = int((await session.execute(select(func.count(VkContact.id)))).scalar() or 0)
    return _ok({
        "items": [{
            "vk_user_id": row.vk_user_id,
            "first_name": row.first_name or "",
            "last_name": row.last_name or "",
            "phone": mask_phone(row.phone_encrypted) if row.phone_encrypted else "",
            "has_phone": bool(row.phone_encrypted),
            "personal_data_consent_at": row.personal_data_consent_at.isoformat() if row.personal_data_consent_at else None,
            "marketing_consent_at": row.marketing_consent_at.isoformat() if row.marketing_consent_at else None,
            "marketing_consent_source": row.marketing_consent_source,
            "marketing_suppressed": row.marketing_suppressed,
            "source_campaign": row.source_campaign,
            "created": row.created.isoformat() if row.created else None,
        } for row in rows],
        "total": total,
    })


async def vk_admin_import_preview(request):
    if not _admin(request):
        return _err("forbidden", "Нет доступа.", 403)
    try:
        body = await request.json()
    except Exception:
        return _err("bad_json", "Некорректный JSON.")
    csv_text = body.get("csv_text") if isinstance(body, dict) else None
    preview = preview_contact_import(csv_text or "")
    for row in preview["rows"]:
        row["consent_at"] = row["consent_at"].isoformat()
    return _ok(preview)


async def vk_admin_import_commit(request):
    if not _admin(request):
        return _err("forbidden", "Нет доступа.", 403)
    try:
        body = await request.json()
        csv_text = body.get("csv_text") if isinstance(body, dict) else None
        result = await commit_contact_import(csv_text or "", request["uid"])
    except ValueError as exc:
        return _err("invalid_import", str(exc), 422)
    except Exception:
        return _err("import_failed", "Не удалось импортировать список. Проверь CSV и повтори попытку.", 500)
    async with Session() as session:
        await _audit(session, request["uid"], "vk_contacts_imported", "vk_contacts", "batch", f"Создано: {result['created']}; обновлено: {result['updated']}; подавлено: {result['suppressed']}")
        await session.commit()
    return _ok(result)


async def vk_admin_campaigns_get(request):
    if not _admin(request):
        return _err("forbidden", "Нет доступа.", 403)
    async with Session() as session:
        rows = (await session.execute(select(VkCampaign).order_by(VkCampaign.created.desc()).limit(100))).scalars().all()
    return _ok({"items": [{
        "id": row.id,
        "name": row.name,
        "status": row.status,
        "advertiser_name": row.advertiser_name,
        "recipient_count": row.recipient_count,
        "sent_count": row.sent_count,
        "skipped_count": row.skipped_count,
        "failed_count": row.failed_count,
        "erid": row.erid,
        "created": row.created.isoformat() if row.created else None,
    } for row in rows]})


async def vk_admin_campaign_create(request):
    if not _admin(request):
        return _err("forbidden", "Нет доступа.", 403)
    try:
        payload = await request.json()
        campaign_id = await create_campaign_draft(request["uid"], payload)
    except ValueError as exc:
        return _err("invalid_campaign", str(exc), 422)
    except Exception:
        return _err("campaign_create_failed", "Не удалось создать кампанию.", 500)
    async with Session() as session:
        await _audit(session, request["uid"], "vk_campaign_created", "vk_campaign", campaign_id, "Создан черновик VK-кампании")
        await session.commit()
    return _ok({"id": campaign_id, "status": "draft"}, 201)


async def vk_admin_campaign_preview(request):
    if not _admin(request):
        return _err("forbidden", "Нет доступа.", 403)
    try:
        campaign_id = int(request.match_info["id"])
        data = await preview_campaign(campaign_id)
    except (TypeError, ValueError):
        return _err("bad_campaign_id", "Некорректный ID кампании.")
    except LookupError:
        return _err("not_found", "Кампания не найдена.", 404)
    return _ok(data)


async def vk_admin_campaign_resume(request):
    if not _admin(request):
        return _err("forbidden", "Нет доступа.", 403)
    try:
        campaign_id = int(request.match_info["id"])
        body = await request.json()
        if not isinstance(body, dict) or body.get("confirm") is not True:
            return _err("confirmation_required", "Для возобновления нужно явное подтверждение.", 409)
        from bot.vk.outreach import resume_campaign
        queued = await resume_campaign(campaign_id, request["uid"])
    except (TypeError, ValueError) as exc:
        return _err("invalid_campaign", str(exc), 422)
    except LookupError:
        return _err("not_found", "Кампания не найдена.", 404)
    except PermissionError:
        return _err("forbidden", "Нет доступа к этой кампании.", 403)
    async with Session() as session:
        await _audit(session, request["uid"], "vk_campaign_resumed", "vk_campaign", campaign_id, f"Повторно поставлено в очередь: {queued}")
        await session.commit()
    return _ok({"id": campaign_id, "queued": queued, "status": "running"})


async def vk_admin_campaign_send(request):
    if not _admin(request):
        return _err("forbidden", "Нет доступа.", 403)
    try:
        body = await request.json()
        if not isinstance(body, dict) or body.get("confirm") is not True:
            return _err("confirmation_required", "Для запуска нужно явное подтверждение.", 409)
        campaign_id = int(request.match_info["id"])
        queued = await start_campaign(campaign_id, request["uid"])
    except (TypeError, ValueError) as exc:
        return _err("invalid_campaign", str(exc), 422)
    except LookupError:
        return _err("not_found", "Кампания не найдена.", 404)
    except PermissionError:
        return _err("forbidden", "Нет доступа к этой кампании.", 403)
    async with Session() as session:
        await _audit(session, request["uid"], "vk_campaign_started", "vk_campaign", campaign_id, f"В очередь поставлено: {queued}")
        await session.commit()
    return _ok({"id": campaign_id, "queued": queued, "status": "running"})


async def vk_admin_campaign_pause(request):
    if not _admin(request):
        return _err("forbidden", "Нет доступа.", 403)
    try:
        campaign_id = int(request.match_info["id"])
    except (TypeError, ValueError):
        return _err("bad_campaign_id", "Некорректный ID.")
    async with Session() as session:
        campaign = await session.get(VkCampaign, campaign_id)
        if campaign is None:
            return _err("not_found", "Кампания не найдена.", 404)
        if campaign.status not in {"running", "queued"}:
            return _err("invalid_state", "Кампанию нельзя приостановить в текущем статусе.", 409)
        campaign.status = "paused"
        await _audit(session, request["uid"], "vk_campaign_paused", "vk_campaign", campaign_id)
        await session.commit()
    return _ok({"id": campaign_id, "status": "paused"})


def setup_vk_admin_api(app: web.Application) -> None:
    r = app.router
    r.add_get("/api/v1/admin/vk/overview", vk_admin_overview)
    r.add_get("/api/v1/admin/vk/slots", vk_admin_slots_get)
    r.add_put("/api/v1/admin/vk/slots", vk_admin_slots_put)
    r.add_get("/api/v1/admin/vk/contacts", vk_admin_contacts)
    r.add_post("/api/v1/admin/vk/contacts/import/preview", vk_admin_import_preview)
    r.add_post("/api/v1/admin/vk/contacts/import/commit", vk_admin_import_commit)
    r.add_get("/api/v1/admin/vk/campaigns", vk_admin_campaigns_get)
    r.add_post("/api/v1/admin/vk/campaigns", vk_admin_campaign_create)
    r.add_post("/api/v1/admin/vk/campaigns/{id}/preview", vk_admin_campaign_preview)
    r.add_post("/api/v1/admin/vk/campaigns/{id}/send", vk_admin_campaign_send)
    r.add_post("/api/v1/admin/vk/campaigns/{id}/pause", vk_admin_campaign_pause)
    r.add_post("/api/v1/admin/vk/campaigns/{id}/resume", vk_admin_campaign_resume)
