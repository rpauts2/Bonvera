"""Shared read/write service layer for the Mini App API.

Reuses the existing financial core (bot.logic) and evidence rules (bot.proofs)
so the bot and the TMA never diverge on money, ownership or offer conditions.
"""
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select

from bot.config import cfg
from bot.db import (
    App, Bank, DealEvent, Offer, PayoutEvent, PayoutReq, RefAcc, Session, Tier,
    User, WalletEntry, NEW, PROOF, HOLD, CONFIRMED, PAID, REJECTED, EXPIRED, RU,
)
from bot.logic import bank_taken, link, phone_decrypt
from bot.proofs import proof_progress, proofs_complete

KIND_RU = {
    "cashback": "Кэшбэк за заказ",
    "referral": "Реферальная комиссия",
    "task_channel": "Бонус за подписку",
    "task_first_order": "Бонус за первый заказ",
    "task_ten_orders": "Бонус за 10 заказов",
    "task_ref_bonus": "Бонус за друга",
    "withdraw_request": "Резерв под вывод",
    "withdraw_cancel": "Возврат отменённого вывода",
    "withdraw_refund": "Возврат отклонённой выплаты",
    "withdraw_release": "Возврат резерва",
    "clawback": "Сторно кэшбэка",
    "referral_clawback": "Сторно реферального начисления",
}

PAYOUT_RU = {
    "pending": "Ожидает проверки",
    "processing": "В обработке",
    "review_required": "Нужна сверка",
    "paid": "Выплачено",
    "rejected": "Отклонено",
    "cancelled": "Отменено",
}

SBP_BANKS = [
    "Т-Банк", "Сбербанк", "ВТБ", "Альфа-Банк", "Газпромбанк", "Райффайзенбанк",
    "Совкомбанк", "Росбанк", "МКБ", "Промсвязьбанк", "Открытие", "Почта Банк",
    "Россельхозбанк", "Ак Барс", "Уралсиб", "Банк Санкт-Петербург", "Зенит", "Синара",
]

BK_FALLBACK_IMAGES = {
    "pari": "bk_green.jpg", "marathon": "bk_blue.jpg", "fonbet": "bk_orange.jpg",
    "melbet": "bk_red.jpg", "baltbet": "bk_gold.jpg", "leon": "bk_purple.jpg",
}


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def mask_phone(stored: str | None) -> str | None:
    if not stored:
        return None
    plain = phone_decrypt(stored)
    return f"+7 *** ***-{plain[-4:]}" if len(plain) >= 4 else None


async def confirmed_orders_count(s: Session, uid: int) -> int:
    return (
        await s.execute(select(func.count(App.id)).where(App.user_id == uid, App.status.in_([CONFIRMED, PAID])))
    ).scalar() or 0


async def user_profile(s: Session, u: User) -> dict:
    confirmed = await confirmed_orders_count(s, u.id)
    return {
        "id": u.id,
        "username": u.username,
        "name": u.name,
        "accepted": bool(u.accepted),
        "adult": bool(u.adult),
        "age_years": u.age_years,
        "balance": int(u.balance or 0),
        "banned": bool(u.banned),
        "sbp_bank": u.sbp_bank or "",
        "sbp_phone_masked": mask_phone(u.sbp_phone),
        "referrer_id": u.referrer_id,
        "created": iso(u.created),
        "confirmed_orders": confirmed,
        "level": 1 + confirmed // 5,
    }


async def wallet_summary(s: Session, uid: int) -> dict:
    u = await s.get(User, uid)
    apps = (await s.execute(select(App).where(App.user_id == uid))).scalars().all()
    reward_of = lambda a: int((a.offer_snapshot or {}).get("reward", 0))
    reserved = (
        await s.execute(
            select(func.coalesce(func.sum(PayoutReq.amount), 0)).where(
                PayoutReq.user_id == uid, PayoutReq.status.in_(["pending", "processing", "review_required"])
            )
        )
    ).scalar()
    paid = (
        await s.execute(
            select(func.coalesce(func.sum(PayoutReq.amount), 0)).where(PayoutReq.user_id == uid, PayoutReq.status == "paid")
        )
    ).scalar()
    refs = (
        await s.execute(select(func.coalesce(func.sum(RefAcc.amount), 0)).where(RefAcc.referrer_id == uid))
    ).scalar()
    return {
        "available": int(u.balance or 0),
        "pending_setup": sum(reward_of(a) for a in apps if a.status == NEW),
        "review": sum(reward_of(a) for a in apps if a.status == PROOF),
        "hold": sum(reward_of(a) for a in apps if a.status == HOLD),
        "reserved": int(reserved),
        "paid_total": int(paid),
        "referral_earned": int(refs),
        "min_withdraw": cfg.min_wd,
    }


def entry_view(e: WalletEntry) -> dict:
    return {
        "id": e.id,
        "amount": int(e.amount),
        "kind": e.kind,
        "kind_ru": KIND_RU.get(e.kind, e.kind),
        # task_ref_bonus refs embed the friend's Telegram ID; never expose it.
        "ref": "" if e.kind == "task_ref_bonus" else e.ref,
        "note": e.note or "",
        "created": iso(e.created),
    }


async def wallet_entries(s: Session, uid: int, limit: int = 200) -> list[dict]:
    rows = (
        await s.execute(select(WalletEntry).where(WalletEntry.user_id == uid).order_by(WalletEntry.id.desc()).limit(limit))
    ).scalars().all()
    return [entry_view(e) for e in rows]


def offer_image_url(o: Offer, bk: Bank) -> str:
    if o.image_path and Path(o.image_path).exists():
        return "/" + o.image_path.replace("\\", "/").lstrip("/")
    default = Path("assets/offers") / bk.category / f"{o.code}.jpg"
    if default.exists():
        return "/" + default.as_posix()
    if bk.category == "bk":
        candidate = Path("assets/offers/bk") / BK_FALLBACK_IMAGES.get(bk.slug, "bk_blue.jpg")
        if candidate.exists():
            return "/" + candidate.as_posix()
    return ""


async def taken_bank_ids(s: Session, uid: int, phone_hash: str | None) -> set[int]:
    rows = (
        await s.execute(
            select(App, Offer.bank_id).join(Offer, Offer.id == App.offer_id).where(App.status.notin_([REJECTED, EXPIRED]))
        )
    ).all()
    return {bank_id for a, bank_id in rows if a.user_id == uid or (phone_hash and a.phone_hash == phone_hash)}


async def slots_left_today(s: Session, offer_ids: list[int]) -> dict[int, int]:
    if not offer_ids:
        return {}
    day_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    rows = (
        await s.execute(
            select(App.offer_id, func.count(App.id)).where(App.offer_id.in_(offer_ids), App.created >= day_start).group_by(App.offer_id)
        )
    ).all()
    return {oid: cnt for oid, cnt in rows}


def offer_availability(o: Offer, bk: Bank, taken: set[int], active_count: int, slots_left: int, uid: int) -> tuple[bool, str | None, bool]:
    already_taken = o.bank_id in taken
    if already_taken:
        return False, "Ты уже оформлял предложение этого банка.", True
    if not o.enabled:
        return False, "Предложение временно отключено администратором.", False
    gate = {"bk": cfg.bk, "mfo": cfg.mfo, "cpl": cfg.cpl}.get(bk.category, True)
    if not gate:
        return False, "Раздел на согласовании и откроется позже.", False
    if bk.category == "bk" and o.network_status != "approved":
        return False, "Букмекерский оффер ждёт согласования партнёрской сети.", False
    if not o.url:
        return False, "Партнёрская ссылка ещё не добавлена. Мы не выдумываем ссылки — оформление откроется после проверки администратором.", False
    if active_count >= cfg.max_active:
        return False, f"Достигнут лимит активных заявок ({cfg.max_active}). Заверши текущие.", False
    if slots_left <= 0:
        return False, "Места на сегодня закончились. Попробуй завтра.", False
    return True, None, False


async def offer_card(s: Session, o: Offer, bk: Bank, uid: int, taken: set[int], active_count: int, slots: dict[int, int]) -> dict:
    reward = (await s.execute(select(func.max(Tier.cashback)).where(Tier.offer_id == o.id))).scalar() or 0
    slots_left = max(0, o.slots - slots.get(o.id, 0))
    available, reason, already_taken = offer_availability(o, bk, taken, active_count, slots_left, uid)
    return {
        "id": o.id,
        "code": o.code,
        "name": o.name,
        "brand": bk.name,
        "brand_slug": bk.slug,
        "emoji": bk.emoji,
        "category": bk.category,
        "reward": int(reward),
        "condition": o.condition_text or o.action,
        "hold_days": o.hold,
        "purchase_min": o.purchase_min,
        "age_min": o.age_min,
        "age_max": o.age_max,
        "image_url": offer_image_url(o, bk),
        "enabled": bool(o.enabled),
        "has_partner_link": bool(o.url),
        "network_status": o.network_status,
        "available": available,
        "unavailable_reason": reason,
        "already_taken": already_taken,
    }


async def list_offers(s: Session, uid: int, q: str = "", category: str = "", sort: str = "reward", available_only: bool = False) -> list[dict]:
    u = await s.get(User, uid)
    stmt = select(Offer, Bank).join(Bank, Bank.id == Offer.bank_id)
    if category in ("cards", "bk", "mfo", "cpl"):
        stmt = stmt.where(Bank.category == category)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(func.lower(Offer.name).like(like) | func.lower(Bank.name).like(like))
    rows = (await s.execute(stmt)).all()
    taken = await taken_bank_ids(s, uid, u.phone_hash if u else None)
    active_count = (
        await s.execute(select(func.count(App.id)).where(App.user_id == uid, App.status.in_([NEW, PROOF, HOLD])))
    ).scalar() or 0
    slots = await slots_left_today(s, [o.id for o, _ in rows])
    cards = [await offer_card(s, o, bk, uid, taken, active_count, slots) for o, bk in rows]
    if available_only:
        cards = [c for c in cards if c["available"]]
    if sort == "hold":
        cards.sort(key=lambda c: (c["hold_days"], -c["reward"]))
    elif sort == "new":
        cards.sort(key=lambda c: -c["id"])
    else:
        cards.sort(key=lambda c: -c["reward"])
    return cards


async def offer_detail(s: Session, o: Offer, uid: int) -> dict | None:
    bk = await s.get(Bank, o.bank_id)
    if not bk:
        return None
    u = await s.get(User, uid)
    taken = await taken_bank_ids(s, uid, u.phone_hash if u else None)
    active_count = (
        await s.execute(select(func.count(App.id)).where(App.user_id == uid, App.status.in_([NEW, PROOF, HOLD])))
    ).scalar() or 0
    slots = await slots_left_today(s, [o.id])
    card = await offer_card(s, o, bk, uid, taken, active_count, slots)
    card.update({
        "action": o.action or "",
        "rules": o.rules or "",
        "notes": o.notes or "",
        "source_url": o.source_url or "",
        "verification_steps": list(o.verification_steps or []),
        "required_proofs": list(o.required_proofs or []),
        "mfo_info": dict(o.mfo_info or {}) if bk.category == "mfo" else None,
        "forbidden": list(o.forbidden or []),
        "allowed": list(o.allowed or []),
        "slots_left_today": max(0, o.slots - slots.get(o.id, 0)),
    })
    return card


async def create_deal(s: Session, uid: int, oid: int) -> tuple[App | None, str | None, str | None]:
    """Same validation chain as the bot's take: callback, shared by the TMA API."""
    u = (await s.execute(select(User).where(User.id == uid).with_for_update())).scalar_one_or_none()
    if not u:
        return None, "no_user", "Пользователь не найден."
    if u.banned:
        return None, "banned", "Доступ ограничен."
    if not u.accepted or not u.adult:
        return None, "not_accepted", "Сначала подтверди возраст 18+ и правила."
    o = await s.get(Offer, oid)
    if not o:
        return None, "no_offer", "Предложение не найдено."
    bk = await s.get(Bank, o.bank_id)
    if not bk or not o.enabled:
        return None, "disabled", "Предложение недоступно."
    gate = {"bk": cfg.bk, "mfo": cfg.mfo, "cpl": cfg.cpl}.get(bk.category, True)
    if not gate:
        return None, "category_closed", "Раздел на согласовании и откроется позже."
    if o.age_min > 18 or o.age_max < 120:
        if u.age_years is None:
            return None, "age_required", f"Для этого предложения доступен возраст {o.age_min}–{o.age_max} лет. Укажи число полных лет."
        if not (o.age_min <= u.age_years <= o.age_max):
            return None, "age_mismatch", f"Этот оффер доступен только в возрасте {o.age_min}–{o.age_max} лет."
    if bk.category == "bk" and o.network_status != "approved":
        return None, "bk_not_approved", "Букмекерский оффер ждёт согласования партнёрской сети."
    if not o.url:
        return None, "no_link", "Партнёрская ссылка ещё не добавлена. Выбери другое предложение."
    if await bank_taken(s, u.id, o.bank_id, u.phone_hash):
        return None, "bank_taken", "Ты уже брал предложение этого банка."
    active = (
        await s.execute(select(func.count(App.id)).where(App.user_id == u.id, App.status.in_([NEW, PROOF, HOLD])))
    ).scalar() or 0
    if active >= cfg.max_active:
        return None, "max_active", f"Максимум {cfg.max_active} активные заявки."
    day_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today = (
        await s.execute(select(func.count(App.id)).where(App.offer_id == oid, App.created >= day_start))
    ).scalar() or 0
    if today >= o.slots:
        return None, "no_slots", "Места на сегодня закончились."
    tier = (await s.execute(select(Tier).where(Tier.offer_id == oid).order_by(Tier.id))).scalars().first()
    reward = int(tier.cashback) if tier else 0
    snapshot = {
        "code": o.code, "name": o.name, "brand": bk.name, "emoji": bk.emoji, "category": bk.category,
        "condition": o.condition_text or o.action, "promo_notes": o.notes or "", "source_url": o.source_url or "",
        "verification_steps": list(o.verification_steps or []), "proofs": list(o.required_proofs or []),
        "reward": reward, "hold_days": o.hold, "age_min": o.age_min, "age_max": o.age_max,
        "url": o.url, "link_param": o.link_param, "created_terms_at": datetime.utcnow().isoformat(),
    }
    a = App(user_id=u.id, offer_id=oid, subid="pending-" + uuid.uuid4().hex,
            phone_hash=u.phone_hash, offer_snapshot=snapshot, cashback=0, payout=0)
    s.add(a)
    await s.commit()
    from bot.logic import subid
    a.subid = subid(a.id)
    s.add(DealEvent(app_id=a.id, actor_id=u.id, event="created", from_status="", to_status=NEW,
                    comment="Пользователь начал оформление через Mini App"))
    await s.commit()
    return a, None, None


def app_view(s_apps: App, o: Offer | None, events: list[DealEvent], bk: Bank | None = None) -> dict:
    a = s_apps
    snap = a.offer_snapshot or {}
    required, received, _missing = proof_progress(a, o)
    ver = a.verification or {}
    submitted_at = ver.get("proof_submitted_at")
    last_received = ver.get("proof_last_received_at")
    already_submitted = bool(submitted_at and (not last_received or last_received <= submitted_at))
    complete, _labels = proofs_complete(a, o, require_submission=False)
    can_upload = a.status in (NEW, PROOF, HOLD)
    personal = None
    if a.status in (NEW, PROOF):
        personal = link(snap.get("url", o.url if o else ""), a.subid, snap.get("link_param", o.link_param if o else "subid")) or None
    proofs = []
    for item in a.proof_files or []:
        if not isinstance(item, dict):
            continue
        proofs.append({
            "index": item.get("proof_index"),
            "label": item.get("label", ""),
            "kind": item.get("kind", "photo"),
            "name": item.get("name") or item.get("label") or "Файл",
            "uploaded_at": item.get("uploaded_at", ""),
            "duplicate_suspected": bool(item.get("duplicate_suspected")),
        })
    return {
        "id": a.id,
        "offer_id": a.offer_id,
        "offer_name": snap.get("name", o.name if o else ""),
        "brand": snap.get("brand", ""),
        "emoji": snap.get("emoji", "🏦"),
        "category": snap.get("category", ""),
        "image_url": offer_image_url(o, bk) if o and bk else "",
        "status": a.status,
        "status_ru": RU.get(a.status, a.status),
        "reward": int(snap.get("reward", 0)),
        "cashback": int(a.cashback or 0),
        "condition": snap.get("condition", ""),
        "created": iso(a.created),
        "hold_until": iso(a.hold_until),
        "booking_until": iso(a.created + timedelta(hours=cfg.booking_h)) if a.status == NEW else None,
        "reason": a.reason or "",
        "personal_link": personal,
        "proofs_required": required,
        "proofs_received": sorted(received),
        "proofs": proofs,
        "events": [
            {"id": e.id, "event": e.event, "from_status": e.from_status, "to_status": e.to_status,
             "comment": e.comment or "", "created": iso(e.created)}
            for e in events
        ],
        "can_upload": can_upload,
        "can_submit": a.status in (PROOF, HOLD) and complete and not already_submitted,
        "submitted": bool(submitted_at),
        "more_info_text": ver.get("more_info_text") if ver.get("more_info_requested_at") else None,
    }


def withdrawal_view(p: PayoutReq, events: list[PayoutEvent]) -> dict:
    return {
        "id": p.id,
        "amount": int(p.amount),
        "bank": p.bank or "",
        "status": p.status,
        "status_ru": PAYOUT_RU.get(p.status, p.status),
        "created": iso(p.created),
        "paid_at": iso(p.paid_at),
        "admin_note": p.admin_note or "",
        "can_cancel": p.status == "pending",
        "events": [
            {"id": e.id, "event": e.event, "from_status": e.from_status, "to_status": e.to_status,
             "comment": e.comment or "", "created": iso(e.created)}
            for e in events
        ],
    }


async def has_task_entry(s: Session, uid: int, ref: str) -> WalletEntry | None:
    return (await s.execute(select(WalletEntry).where(WalletEntry.user_id == uid, WalletEntry.ref == ref))).scalar_one_or_none()


def image_phash(data: bytes) -> str | None:
    """Perceptual hash for image evidence; None for PDFs/HEIC/undecodable files."""
    try:
        from io import BytesIO

        import imagehash
        from PIL import Image

        return str(imagehash.phash(Image.open(BytesIO(data)).convert("RGB")))
    except Exception:
        return None


async def phash_duplicates(s: Session, ph: str) -> tuple[bool, bool, int]:
    """Same anti-duplicate rule as the bot's proof_got: exact copy rejects,
    distance <= 3 flags for manual admin review. Returns (exact, suspected, matches)."""
    import imagehash

    recent = (await s.execute(select(App).order_by(App.id.desc()).limit(500))).scalars().all()
    candidate = imagehash.hex_to_hash(ph)
    suspected = False
    matches = 0
    for old in recent:
        hashes = [x.get("hash") for x in (old.proof_files or []) if isinstance(x, dict) and x.get("hash")]
        if old.proof_hash:
            hashes.append(old.proof_hash)
        for old_hash in set(hashes):
            try:
                distance = candidate - imagehash.hex_to_hash(old_hash)
                if distance == 0:
                    return True, True, matches + 1
                if distance <= 3:
                    suspected = True
                    matches += 1
            except Exception:
                pass
    return False, suspected, matches


async def list_apps(s: Session, uid: int) -> list[dict]:
    apps = (await s.execute(select(App).where(App.user_id == uid).order_by(App.id.desc()))).scalars().all()
    result = []
    for a in apps:
        o = await s.get(Offer, a.offer_id)
        bk = await s.get(Bank, o.bank_id) if o else None
        events = (
            await s.execute(select(DealEvent).where(DealEvent.app_id == a.id).order_by(DealEvent.id.desc()).limit(5))
        ).scalars().all()
        result.append(app_view(a, o, list(reversed(events)), bk))
    return result


async def app_detail(s: Session, a: App) -> dict:
    o = await s.get(Offer, a.offer_id)
    bk = await s.get(Bank, o.bank_id) if o else None
    events = (
        await s.execute(select(DealEvent).where(DealEvent.app_id == a.id).order_by(DealEvent.id))
    ).scalars().all()
    return app_view(a, o, list(events), bk)


async def create_withdrawal(s: Session, uid: int, amount, bank: str | None, phone: str | None) -> tuple[PayoutReq | None, str | None, str | None]:
    """Same reserve mechanics as the bot's wd_amt: row lock, idempotent posting."""
    from bot.logic import phone_decrypt, phone_encrypt, phone_norm, phash

    if not isinstance(amount, int) or isinstance(amount, bool) or amount < cfg.min_wd:
        return None, "bad_amount", f"Минимальная сумма вывода — {cfg.min_wd} ₽."
    u = (await s.execute(select(User).where(User.id == uid).with_for_update())).scalar_one_or_none()
    if u is None:
        return None, "no_user", "Пользователь не найден."
    if u.banned:
        return None, "banned", "Доступ ограничен."
    if amount > int(u.balance or 0):
        return None, "insufficient", f"Недостаточно доступных средств: {u.balance} ₽."
    chosen_bank = (bank or u.sbp_bank or "").strip()
    if not 2 <= len(chosen_bank) <= 80:
        return None, "bad_bank", "Укажи корректный банк СБП (2–80 символов)."
    if phone is not None:
        normalized = phone_norm(str(phone))
        if len(normalized) != 11 or not normalized.isdigit():
            return None, "bad_phone", "Нужен номер телефона из 11 цифр (например, +79991234567)."
        encrypted = phone_encrypt(normalized)
    elif u.sbp_phone:
        encrypted = u.sbp_phone
    else:
        return None, "no_phone", "Сначала укажи телефон СБП в настройках или в форме вывода."
    u.balance -= amount
    p = PayoutReq(user_id=u.id, amount=amount, phone=encrypted, bank=chosen_bank, status="pending")
    s.add(p)
    await s.flush()
    s.add(WalletEntry(user_id=u.id, amount=-amount, kind="withdraw_request", ref=f"withdraw:{p.id}", note="Резерв под запрос на вывод"))
    s.add(PayoutEvent(payout_id=p.id, actor_id=u.id, event="created", from_status="", to_status="pending",
                      comment="Пользователь создал запрос на вывод через Mini App"))
    await s.commit()
    return p, None, None


async def cancel_withdrawal(s: Session, uid: int, pid: int) -> tuple[PayoutReq | None, str | None, str | None]:
    """Same refund mechanics as the bot's wd_cancel: pending only, idempotent ref."""
    u = (await s.execute(select(User).where(User.id == uid).with_for_update())).scalar_one_or_none()
    p = (await s.execute(select(PayoutReq).where(PayoutReq.id == pid).with_for_update())).scalar_one_or_none()
    if not u or not p or p.user_id != uid:
        return None, "not_found", "Запрос на вывод не найден."
    if p.status != "pending":
        return None, "not_pending", "Отменить можно только запрос, который ещё не взят в работу."
    old = p.status
    p.status, p.updated_at = "cancelled", datetime.utcnow()
    ref = f"withdraw-cancel:{p.id}"
    exists = (await s.execute(select(WalletEntry).where(WalletEntry.ref == ref))).scalar_one_or_none()
    if not exists:
        u.balance += p.amount
        s.add(WalletEntry(user_id=u.id, amount=p.amount, kind="withdraw_cancel", ref=ref, note="Возврат пользователю отменённого запроса"))
    s.add(PayoutEvent(payout_id=p.id, actor_id=u.id, event="cancelled", from_status=old, to_status="cancelled",
                      comment="Пользователь отменил запрос до взятия в работу (Mini App)"))
    await s.commit()
    return p, None, None


async def qualified_friends_count(s: Session, uid: int) -> int:
    return (
        await s.execute(
            select(func.count(func.distinct(PayoutReq.user_id)))
            .join(User, User.id == PayoutReq.user_id)
            .where(User.referrer_id == uid, PayoutReq.status == "paid")
        )
    ).scalar() or 0


async def task_states(s: Session, uid: int) -> list[dict]:
    confirmed = await confirmed_orders_count(s, uid)
    qualified = await qualified_friends_count(s, uid)
    channel_done = await has_task_entry(s, uid, f"task:channel:{uid}")
    first_done = await has_task_entry(s, uid, f"task:first_order:{uid}")
    ten_done = await has_task_entry(s, uid, f"task:ten_orders:{uid}")
    ref_bonus = (
        await s.execute(select(WalletEntry).where(WalletEntry.user_id == uid, WalletEntry.kind == "task_ref_bonus").limit(1))
    ).scalar_one_or_none()
    channel_configured = bool(cfg.channel_id and cfg.channel_url)
    return [
        {
            "key": "channel", "title": "Подписка на канал", "description": "Подпишись на официальный канал BONVERA и подтверди подписку.",
            "reward": 20, "done": channel_done is not None, "progress": 1 if channel_done else 0, "target": 1,
            "action": "check_subscription", "channel_url": cfg.channel_url or None,
            "claimable": channel_configured and channel_done is None,
            "hint": None if channel_configured else "Канал пока не настроен администратором — бонус временно недоступен.",
        },
        {
            "key": "referral", "title": "Первый друг с выплатой", "description": "Пригласи друга. Бонус придёт после его первой реальной выплаты.",
            "reward": 100, "done": ref_bonus is not None, "progress": min(qualified, 1), "target": 1,
            "action": "invite", "channel_url": None, "claimable": False,
            "hint": "Регистрация друга и клик по ссылке не считаются — нужна именно выплата.",
        },
        {
            "key": "first_order", "title": "Первый подтверждённый заказ", "description": "Выполни условие любого предложения и получи подтверждение.",
            "reward": 10, "done": first_done is not None, "progress": min(confirmed, 1), "target": 1,
            "action": "order", "channel_url": None, "claimable": False, "hint": None,
        },
        {
            "key": "ten_orders", "title": "10 подтверждённых заказов", "description": "Доведи счётчик подтверждённых заказов до 10.",
            "reward": 500, "done": ten_done is not None, "progress": min(confirmed, 10), "target": 10,
            "action": "orders", "channel_url": None, "claimable": False,
            "hint": "Отклонённые, отменённые и истёкшие заявки не учитываются.",
        },
    ]


async def achievements(s: Session, uid: int) -> list[dict]:
    confirmed_apps = (
        await s.execute(
            select(App).where(App.user_id == uid, App.status.in_([CONFIRMED, PAID])).order_by(App.reviewed_at, App.id)
        )
    ).scalars().all()
    n = len(confirmed_apps)
    first_paid = (
        await s.execute(select(PayoutReq).where(PayoutReq.user_id == uid, PayoutReq.status == "paid").order_by(PayoutReq.paid_at).limit(1))
    ).scalar_one_or_none()
    qualified = await qualified_friends_count(s, uid)
    channel_entry = await has_task_entry(s, uid, f"task:channel:{uid}")
    ref_entry = (
        await s.execute(select(WalletEntry).where(WalletEntry.user_id == uid, WalletEntry.kind == "task_ref_bonus").order_by(WalletEntry.id).limit(1))
    ).scalar_one_or_none()

    def at(i: int) -> str | None:
        return iso(confirmed_apps[i].reviewed_at or confirmed_apps[i].created) if n > i else None

    return [
        {"key": "first_order", "title": "Первый заказ", "description": "Первый подтверждённый заказ", "icon": "star",
         "unlocked": n >= 1, "unlocked_at": at(0)},
        {"key": "ten_orders", "title": "Десятка", "description": "10 подтверждённых заказов", "icon": "chest",
         "unlocked": n >= 10, "unlocked_at": at(9)},
        {"key": "first_payout", "title": "Первая выплата", "description": "Деньги реально переведены по СБП", "icon": "wallet",
         "unlocked": first_paid is not None, "unlocked_at": iso(first_paid.paid_at) if first_paid else None},
        {"key": "friend_bonus", "title": "Наставник", "description": "Друг получил первую выплату", "icon": "friends",
         "unlocked": qualified >= 1, "unlocked_at": iso(ref_entry.created) if ref_entry else None},
        {"key": "channel", "title": "Свой в канале", "description": "Подписка на официальный канал", "icon": "bell",
         "unlocked": channel_entry is not None, "unlocked_at": iso(channel_entry.created) if channel_entry else None},
        {"key": "veteran", "title": "Ветеран", "description": "25 подтверждённых заказов", "icon": "crown",
         "unlocked": n >= 25, "unlocked_at": at(24)},
    ]


async def notifications(s: Session, uid: int, limit: int = 30) -> list[dict]:
    app_ids = (await s.execute(select(App.id).where(App.user_id == uid))).scalars().all()
    items: list[dict] = []
    if app_ids:
        events = (
            await s.execute(select(DealEvent).where(DealEvent.app_id.in_(app_ids)).order_by(DealEvent.id.desc()).limit(limit))
        ).scalars().all()
        for e in events:
            items.append({
                "id": f"deal:{e.id}", "kind": "deal", "title": f"Заявка #{e.app_id}",
                "text": e.comment or e.event, "created": iso(e.created), "app_id": e.app_id,
            })
    payouts = (await s.execute(select(PayoutReq.id).where(PayoutReq.user_id == uid))).scalars().all()
    if payouts:
        pevents = (
            await s.execute(select(PayoutEvent).where(PayoutEvent.payout_id.in_(payouts)).order_by(PayoutEvent.id.desc()).limit(limit))
        ).scalars().all()
        for e in pevents:
            items.append({
                "id": f"payout:{e.id}", "kind": "payout", "title": f"Вывод #{e.payout_id}",
                "text": e.comment or e.event, "created": iso(e.created), "app_id": None,
            })
    bonuses = (
        await s.execute(
            select(WalletEntry).where(WalletEntry.user_id == uid, WalletEntry.kind.like("task_%")).order_by(WalletEntry.id.desc()).limit(limit)
        )
    ).scalars().all()
    for b in bonuses:
        items.append({
            "id": f"bonus:{b.id}", "kind": "bonus", "title": KIND_RU.get(b.kind, "Бонус"),
            "text": f"+{b.amount} ₽ · {b.note}", "created": iso(b.created), "app_id": None,
        })
    items.sort(key=lambda x: x["created"] or "", reverse=True)
    return items[:limit]


async def unread_notifications_count(s: Session, u: User) -> int:
    since = u.notif_read_at or datetime(2000, 1, 1)
    app_ids = (await s.execute(select(App.id).where(App.user_id == u.id))).scalars().all()
    total = 0
    if app_ids:
        total += (
            await s.execute(select(func.count(DealEvent.id)).where(DealEvent.app_id.in_(app_ids), DealEvent.created > since))
        ).scalar() or 0
    payout_ids = (await s.execute(select(PayoutReq.id).where(PayoutReq.user_id == u.id))).scalars().all()
    if payout_ids:
        total += (
            await s.execute(select(func.count(PayoutEvent.id)).where(PayoutEvent.payout_id.in_(payout_ids), PayoutEvent.created > since))
        ).scalar() or 0
    total += (
        await s.execute(
            select(func.count(WalletEntry.id)).where(WalletEntry.user_id == u.id, WalletEntry.kind.like("task_%"), WalletEntry.created > since)
        )
    ).scalar() or 0
    return min(total, 99)


async def dashboard(s: Session, uid: int, bot_username: str | None) -> dict:
    u = await s.get(User, uid)
    summary = await wallet_summary(s, uid)
    confirmed = await confirmed_orders_count(s, uid)
    tasks = await task_states(s, uid)
    invited = (await s.execute(select(func.count(User.id)).where(User.referrer_id == uid))).scalar() or 0
    qualified = await qualified_friends_count(s, uid)
    refs = (
        await s.execute(select(func.coalesce(func.sum(RefAcc.amount), 0)).where(RefAcc.referrer_id == uid))
    ).scalar() or 0
    # Популярные предложения показываем независимо от доступности к оформлению:
    # у 87 из 93 офферов ещё нет проверенной партнёрской ссылки, и из-за
    # available_only главная выглядела поломкой, хотя каталог отдаёт все 93.
    # Честные бейджи («Нет ссылки», «Скоро») остаются на самих карточках.
    offers = await list_offers(s, uid, sort="reward")
    offers.sort(key=lambda c: (0 if c["available"] else 1, -c["reward"]))
    ach = await achievements(s, uid)
    events = await notifications(s, uid, limit=3)
    return {
        "wallet": summary,
        "confirmed_orders": confirmed,
        "ten_progress": min(confirmed, 10),
        "tasks_done": sum(1 for t in tasks if t["done"]),
        "tasks_total": len(tasks),
        "referral": {"invited": invited, "qualified": qualified, "earned": int(refs)},
        "ref_link": f"https://t.me/{bot_username}?start=ref_{uid}" if bot_username else f"/start ref_{uid}",
        "channel_url": cfg.channel_url or None,
        "popular_offers": offers[:4],
        "achievements_preview": ach[:4],
        "recent_events": events,
        "unread_notifications": await unread_notifications_count(s, u),
    }


async def friends_info(s: Session, uid: int, bot_username: str | None) -> dict:
    invited = (await s.execute(select(func.count(User.id)).where(User.referrer_id == uid))).scalar() or 0
    qualified = await qualified_friends_count(s, uid)
    refs = (
        await s.execute(select(func.coalesce(func.sum(RefAcc.amount), 0)).where(RefAcc.referrer_id == uid))
    ).scalar() or 0
    bonus = (
        await s.execute(select(func.coalesce(func.sum(WalletEntry.amount), 0)).where(WalletEntry.user_id == uid, WalletEntry.kind == "task_ref_bonus"))
    ).scalar() or 0
    history = (
        await s.execute(
            select(WalletEntry).where(WalletEntry.user_id == uid, WalletEntry.kind.in_(["referral", "task_ref_bonus"]))
            .order_by(WalletEntry.id.desc()).limit(50)
        )
    ).scalars().all()
    ref_link = f"https://t.me/{bot_username}?start=ref_{uid}" if bot_username else f"/start ref_{uid}"
    share = f"https://t.me/share/url?url={ref_link}&text=Кэшбэк за карты, займы и заявки в BONVERA — приглашаю тебя"
    return {
        "ref_link": ref_link,
        "share_link": share,
        "invited": invited,
        "qualified": qualified,
        "referral_earned": int(refs),
        "bonus_earned": int(bonus),
        "ref_percent": cfg.ref_pct,
        "history": [entry_view(e) for e in history],
    }


async def leaderboard(s: Session, uid: int, lb_type: str, period: str) -> dict:
    """Real results only: confirmed orders / friends with an actual paid payout.
    Banned users are excluded; display is @username or an anonymized label —
    never Telegram IDs, phones or real names."""
    month_start = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if lb_type == "orders":
        stmt = select(App.user_id, func.count(App.id)).where(App.status.in_([CONFIRMED, PAID])).group_by(App.user_id)
        if period == "month":
            stmt = stmt.where(App.reviewed_at >= month_start)
        rows = (await s.execute(stmt)).all()
    else:
        stmt = (
            select(User.referrer_id, func.count(func.distinct(PayoutReq.user_id)))
            .join(User, User.id == PayoutReq.user_id)
            .where(PayoutReq.status == "paid", User.referrer_id.isnot(None))
            .group_by(User.referrer_id)
        )
        if period == "month":
            stmt = stmt.where(PayoutReq.paid_at >= month_start)
        rows = (await s.execute(stmt)).all()
    values = {int(r[0]): int(r[1]) for r in rows if r[0] is not None and r[1] > 0}
    users = (await s.execute(select(User).where(User.id.in_(list(values))))).scalars().all() if values else []
    by_id = {u.id: u for u in users}
    ranked = sorted(
        ((u, v) for u, v in values.items() if u in by_id and not by_id[u].banned),
        key=lambda x: (-x[1], x[0]),
    )
    top = []
    for i, (user_id, value) in enumerate(ranked[:20]):
        u = by_id[user_id]
        top.append({
            "rank": i + 1,
            "display": f"@{u.username}" if u.username else f"Участник {i + 1}",
            "value": value,
            "is_me": user_id == uid,
        })
    me_rank = next((i + 1 for i, (user_id, _) in enumerate(ranked) if user_id == uid), None)
    return {"period": period, "rows": top, "me": {"rank": me_rank, "value": values.get(uid, 0)}}


async def meta_info(s: Session, uid: int, bot_username: str | None) -> dict:
    u = await s.get(User, uid)
    banks = list(SBP_BANKS)
    if u and u.sbp_bank and u.sbp_bank not in banks:
        banks.insert(0, u.sbp_bank)
    return {
        "banks": banks,
        "min_withdraw": cfg.min_wd,
        "ref_percent": cfg.ref_pct,
        "support_url": cfg.support_url or None,
        "channel_url": cfg.channel_url or None,
        "bot_username": bot_username,
    }