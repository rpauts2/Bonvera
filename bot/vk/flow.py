"""VK lead funnel: consent, phone capture and five tracked offer buttons."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime

from sqlalchemy import select

from bot.config import cfg
from bot.db import Session, VkContact, VkConsentEvent, VkOfferSlot
from bot.logic import phone_encrypt, phash
from bot.vk.client import VKClient
from bot.vk.attribution import parse_campaign_ref
from bot.vk.tracking import create_click

PERSONAL_DATA_CONSENT_VERSION = "vk-personal-data-2026-11-22-v1"
MARKETING_CONSENT_VERSION = "vk-marketing-2026-11-22-v1"

START_WORDS = {"начать", "start", "/start", "подбор", "подобрать"}
STOP_WORDS = {"стоп", "отписаться", "не присылать рекламу", "stop", "/stop"}


def normalize_vk_phone(value: str) -> str | None:
    """Return normalized Russian mobile phone digits (7XXXXXXXXXX), else None."""
    if not isinstance(value, str):
        return None
    digits = re.sub(r"\D", "", value)
    if len(digits) == 10:
        digits = "7" + digits
    elif len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    elif len(digits) == 11 and digits.startswith("7"):
        pass
    else:
        return None
    if not re.fullmatch(r"7\d{10}", digits):
        return None
    return digits


def payload_action(message: dict) -> str:
    raw = message.get("payload")
    if isinstance(raw, dict):
        return str(raw.get("action", ""))
    if isinstance(raw, str):
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            return ""
        if isinstance(payload, dict):
            return str(payload.get("action", ""))
    return ""


def _keyboard(rows: list[list[dict]]) -> dict:
    return {"one_time": False, "inline": False, "buttons": rows}


def _text_button(label: str, action: str, color: str = "primary") -> dict:
    return {
        "action": {
            "type": "text",
            "label": label,
            "payload": json.dumps({"action": action}, ensure_ascii=False),
        },
        "color": color,
    }


def _personal_consent_keyboard() -> dict:
    return _keyboard([[
        _text_button("Согласен на обработку данных", "personal_data_consent", "positive")
    ], [
        _text_button("Не согласен", "personal_data_decline", "negative")
    ]])


def _marketing_choice_keyboard() -> dict:
    return _keyboard([[
        _text_button("Да, получать предложения", "marketing_opt_in", "positive")
    ], [
        _text_button("Нет, только текущий запрос", "marketing_opt_out", "secondary")
    ]])


def _stable_random_id(event_id: str, action: str) -> int:
    digest = hashlib.sha256(f"{event_id}:{action}".encode("utf-8")).digest()
    # VK random_id is an integer; keeping the sign bit clear makes it portable.
    return int.from_bytes(digest[:4], "big") & 0x7FFFFFFF or 1


async def _send(
    client: VKClient,
    user_id: int,
    text: str,
    event_id: str,
    action: str,
    keyboard: dict | None = None,
) -> None:
    await client.send_message(
        user_id=user_id,
        text=text,
        keyboard=keyboard,
        random_id=_stable_random_id(event_id, action),
    )


async def _ask_personal_data_consent(client: VKClient, user_id: int, event_id: str) -> None:
    operator = cfg.vk_operator_name.strip()
    text = (
        "Здравствуйте! Это Bonvera. Здесь можно посмотреть предложения микрофинансовых организаций "
        "и перейти на сайты выбранных компаний. Bonvera не выдаёт займы и не принимает решение об одобрении.\n\n"
        f"Чтобы сохранить ваш номер и продолжить, нужно отдельное согласие на обработку персональных данных "
        f"оператором: {operator}. Цель — обработка вашего запроса и предоставление выбранных предложений.\n"
        f"Политика обработки данных: {cfg.vk_privacy_url}\n\n"
        "Согласие на рекламу будет запрошено отдельно и необязательно."
    )
    await _send(client, user_id, text, event_id, "personal-consent", _personal_consent_keyboard())


async def _ask_marketing_choice(client: VKClient, user_id: int, event_id: str) -> None:
    await _send(
        client,
        user_id,
        "Хотите отдельно получать от Bonvera рекламные сообщения о новых предложениях МФО? "
        "Это необязательно и не влияет на доступ к текущим ссылкам.",
        event_id,
        "marketing-choice",
        _marketing_choice_keyboard(),
    )


async def _ask_phone(client: VKClient, user_id: int, event_id: str) -> None:
    await _send(
        client,
        user_id,
        "Теперь отправьте номер телефона в формате +7 900 123-45-67. "
        "Он будет храниться в Bonvera в зашифрованном виде и не будет добавляться к партнёрским ссылкам.",
        event_id,
        "phone-request",
    )


async def _show_offer_menu(client: VKClient, contact: VkContact, event_id: str) -> None:
    async with Session() as session:
        slots = (await session.execute(
            select(VkOfferSlot).where(
                VkOfferSlot.enabled == True,
                VkOfferSlot.target_url != "",
            ).order_by(VkOfferSlot.slot_number)
        )).scalars().all()
        contact_id = contact.id
        source = contact.source_campaign or "vk_organic"
        campaign_id = None
        if source.startswith("campaign:"):
            try:
                campaign_id = int(source.split(":", 1)[1])
            except ValueError:
                campaign_id = None

    buttons = []
    for slot in slots:
        try:
            tracked_url = await create_click(
                contact_id=contact_id,
                slot_number=slot.slot_number,
                campaign_id=campaign_id,
                source=source,
            )
        except (ValueError, RuntimeError):
            continue
        label = (slot.title or slot.advertiser_name or (
            "Все предложения Bonvera" if slot.slot_number == 5 else f"МФО №{slot.slot_number}"
        )).strip()[:40]
        buttons.append([{
            "action": {
                "type": "open_link",
                "link": tracked_url,
                "label": label,
            },
            "color": "primary",
        }])

    if not buttons:
        await _send(
            client,
            contact.vk_user_id,
            "Предложения временно настраиваются. Вернитесь немного позже.",
            event_id,
            "offers-unavailable",
        )
        return

    await _send(
        client,
        contact.vk_user_id,
        "Готово. Выберите одно из предложений МФО или откройте общую витрину Bonvera. "
        "Условия и решение по заявке определяет выбранный кредитор.",
        event_id,
        "offer-menu",
        _keyboard(buttons),
    )


async def _record_consent(
    session,
    contact: VkContact,
    *,
    consent_type: str,
    action: str,
    version: str,
    event_id: str,
) -> None:
    session.add(VkConsentEvent(
        contact_id=contact.id,
        consent_type=consent_type,
        action=action,
        text_version=version,
        source="vk_community_bot",
        proof_reference=event_id[:255],
        metadata_json={"event_id": event_id},
    ))


async def handle_vk_message(message: dict, event_id: str) -> None:
    """Process one user-initiated VK community message."""
    try:
        user_id = int(message.get("from_id", 0))
    except (TypeError, ValueError):
        return
    if user_id <= 0:
        return
    text = str(message.get("text", "") or "").strip()
    lowered = text.casefold()
    action = payload_action(message)
    campaign_ref_id = parse_campaign_ref(message.get("ref"))
    client = VKClient()

    async with Session() as session:
        contact = (await session.execute(
            select(VkContact).where(VkContact.vk_user_id == user_id).with_for_update()
        )).scalar_one_or_none()
        if contact is None:
            contact = VkContact(
                vk_user_id=user_id,
                first_name=str(message.get("first_name") or "")[:128] or None,
                last_name=str(message.get("last_name") or "")[:128] or None,
                flow_state="awaiting_personal_data_consent",
                source_campaign=("campaign:" + str(campaign_ref_id)) if campaign_ref_id else "vk_organic",
            )
            session.add(contact)
            await session.commit()
            contact_id = contact.id
            await _ask_personal_data_consent(client, user_id, event_id)
            return
        contact.last_seen_at = datetime.utcnow()
        if campaign_ref_id is not None:
            contact.source_campaign = "campaign:" + str(campaign_ref_id)
        if lowered in STOP_WORDS or action == "marketing_stop":
            if contact.marketing_consent_at is not None:
                await _record_consent(
                    session,
                    contact,
                    consent_type="marketing",
                    action="withdrawn",
                    version=contact.marketing_consent_version or MARKETING_CONSENT_VERSION,
                    event_id=event_id,
                )
            contact.marketing_consent_at = None
            contact.marketing_suppressed = True
            contact.marketing_consent_source = "user_withdrawal"
            contact.consent_review_status = "not_opted_in"
            contact.consent_reviewed_at = None
            contact.consent_reviewed_by = None
            await session.commit()
            await _send(
                client,
                user_id,
                "Рекламные сообщения отключены. По текущему запросу вы по-прежнему можете открыть меню предложений.",
                event_id,
                "marketing-stop",
            )
            return

        if contact.flow_state == "awaiting_personal_data_consent":
            if action == "personal_data_decline":
                await _send(
                    client,
                    user_id,
                    "Без согласия на обработку номера мы не будем его запрашивать. Диалог можно закрыть.",
                    event_id,
                    "personal-consent-declined",
                )
                return
            if action != "personal_data_consent":
                await _ask_personal_data_consent(client, user_id, event_id)
                return
            contact.personal_data_consent_at = datetime.utcnow()
            contact.personal_data_consent_version = PERSONAL_DATA_CONSENT_VERSION
            contact.flow_state = "awaiting_marketing_choice"
            await _record_consent(
                session,
                contact,
                consent_type="personal_data",
                action="granted",
                version=PERSONAL_DATA_CONSENT_VERSION,
                event_id=event_id,
            )
            await session.commit()
            await _ask_marketing_choice(client, user_id, event_id)
            return

        if contact.flow_state == "awaiting_marketing_choice":
            if action not in {"marketing_opt_in", "marketing_opt_out"}:
                await _ask_marketing_choice(client, user_id, event_id)
                return
            if action == "marketing_opt_in":
                contact.marketing_consent_at = datetime.utcnow()
                contact.marketing_consent_version = MARKETING_CONSENT_VERSION
                contact.marketing_consent_source = "vk_community_bot"
                contact.marketing_suppressed = False
                contact.consent_review_status = "verified"
                contact.consent_reviewed_at = datetime.utcnow()
                contact.consent_reviewed_by = None
                await _record_consent(
                    session,
                    contact,
                    consent_type="marketing",
                    action="granted",
                    version=MARKETING_CONSENT_VERSION,
                    event_id=event_id,
                )
            else:
                contact.marketing_consent_at = None
                contact.marketing_consent_version = MARKETING_CONSENT_VERSION
                contact.marketing_consent_source = "user_declined"
                contact.marketing_suppressed = True
                contact.consent_review_status = "not_opted_in"
                contact.consent_reviewed_at = None
                contact.consent_reviewed_by = None
                await _record_consent(
                    session,
                    contact,
                    consent_type="marketing",
                    action="declined",
                    version=MARKETING_CONSENT_VERSION,
                    event_id=event_id,
                )
            contact.flow_state = "awaiting_phone"
            await session.commit()
            await _ask_phone(client, user_id, event_id)
            return

        if contact.flow_state == "awaiting_phone":
            phone = normalize_vk_phone(text)
            if phone is None:
                await _send(
                    client,
                    user_id,
                    "Не удалось распознать номер. Введите российский номер из 10 цифр или в формате +7.",
                    event_id,
                    "phone-invalid",
                )
                return
            contact.phone_encrypted = phone_encrypt(phone)
            contact.phone_hash = phash(phone)
            contact.flow_state = "menu"
            await session.commit()
            await _show_offer_menu(client, contact, event_id)
            return

        await session.commit()
        await _show_offer_menu(client, contact, event_id)
