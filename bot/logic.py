import hashlib, hmac, re, base64
from cryptography.fernet import Fernet
from datetime import datetime
from sqlalchemy import select, func
from bot.config import cfg
from bot.db import *
from bot.proofs import proof_requirements, proof_progress, proofs_complete
from bot.finance_rules import clawback_withdrawal_action

def phone_norm(p):
    d = re.sub(r"\D", "", p or "")
    return "7" + d[1:] if len(d) == 11 and d[0] in "78" else d

def phash(p): return hashlib.sha256((phone_norm(p) + cfg.salt).encode()).hexdigest()

def _fernet():
    key = base64.urlsafe_b64encode(hashlib.sha256(cfg.phone_key.encode()).digest())
    return Fernet(key)

def phone_encrypt(p): return _fernet().encrypt(phone_norm(p).encode()).decode()
def phone_decrypt(p):
    try: return _fernet().decrypt(p.encode()).decode()
    except Exception: return p  # compatibility with legacy plaintext rows; migrate and rotate key before production

def subid(aid):
    sig = hmac.new(cfg.salt.encode(), str(aid).encode(), hashlib.sha256).hexdigest()[:8]
    return f"a{aid}-{sig}"

def parse_subid(s):
    try: aid = int(s.split("-")[0][1:])
    except Exception: return None
    return aid if hmac.compare_digest(subid(aid), s) else None

def cb_amount(payout, pct): return int(round(payout * pct / 100 / 10.0) * 10)

def link(url, sid, param="subid"):
    if not url: return ""
    from urllib.parse import quote
    return url + ("&" if "?" in url else "?") + f"{quote(param)}={quote(sid)}"

def mfo_ready(o):
    i = o.mfo_info or {}
    return all(i.get(k) for k in ("psk", "rate", "term", "registry"))



async def clawback_credit(s, user_id, amount, wallet_ref, kind, note, actor_id=None):
    """Reverse a credited amount and freeze/release unsettled withdrawals safely.

    pending requests are cancelled and refunded to the available balance. A request
    already in processing is frozen as review_required: an operator must verify
    whether a bank transfer was actually sent before marking it paid or refunding it.
    """
    if amount <= 0:
        return None, []
    user = (await s.execute(select(User).where(User.id == user_id).with_for_update())).scalar_one_or_none()
    if user is None:
        return None, []
    exists = (await s.execute(select(WalletEntry).where(WalletEntry.ref == wallet_ref))).scalar_one_or_none()
    if exists:
        return user, []
    user.balance -= int(amount)
    s.add(WalletEntry(user_id=user.id, amount=-int(amount), kind=kind, ref=wallet_ref, note=note))
    notices = []
    payouts = (await s.execute(
        select(PayoutReq).where(PayoutReq.user_id == user_id, PayoutReq.status.in_(["pending", "processing"])).order_by(PayoutReq.id).with_for_update()
    )).scalars().all()
    for payout in payouts:
        old = payout.status
        action = clawback_withdrawal_action(old)
        if action == "cancel_and_release":
            payout.status = "cancelled"
            payout.admin_note = (payout.admin_note + " | " if payout.admin_note else "") + "Автоматически отменён: отзыв партнёрского лида изменил доступный баланс."
            payout.updated_at = datetime.utcnow()
            release_ref = f"withdraw-clawback-release:{payout.id}"
            released = (await s.execute(select(WalletEntry).where(WalletEntry.ref == release_ref))).scalar_one_or_none()
            if not released:
                user.balance += payout.amount
                s.add(WalletEntry(user_id=user.id, amount=payout.amount, kind="withdraw_release", ref=release_ref,
                                  note="Возврат резерва после отзыва лида"))
            s.add(PayoutEvent(payout_id=payout.id, actor_id=actor_id, event="clawback_cancelled", from_status=old, to_status="cancelled",
                              comment="Запрос автоматически отменён из-за отзыва лида; резерв возвращён пользователю"))
            notices.append((user.id, f"Запрос на вывод #{payout.id} отменён из-за отзыва партнёрского лида; {payout.amount} ₽ возвращены на доступный баланс."))
        elif action == "freeze_for_manual_review":
            payout.status = "review_required"
            payout.admin_note = (payout.admin_note + " | " if payout.admin_note else "") + "ТРЕБУЕТСЯ СВЕРКА: партнёр отозвал лид после начала обработки выплаты. Проверь банковский перевод вручную."
            payout.updated_at = datetime.utcnow()
            s.add(PayoutEvent(payout_id=payout.id, actor_id=actor_id, event="review_required", from_status=old, to_status="review_required",
                              comment="Clawback во время обработки. Не переводить повторно; проверить факт отправки денег в банке."))
            notices.append((user.id, f"Запрос на вывод #{payout.id} приостановлен для сверки из-за отзыва лида. Не создавай повторный запрос на эту сумму; поддержка проверит перевод."))
    return user, notices

async def hold_sum(s, uid):
    ids = (await s.execute(select(App.offer_id).where(App.user_id == uid, App.status.in_([PROOF, HOLD])))).scalars().all()
    t = 0
    for oid in ids:
        t += (await s.execute(select(func.max(Tier.cashback)).where(Tier.offer_id == oid))).scalar() or 0
    return t

async def bank_taken(s, uid, bank_id, ph):
    rows = (await s.execute(select(App).join(Offer, Offer.id == App.offer_id).where(
        Offer.bank_id == bank_id, App.status.notin_([REJECTED, EXPIRED])))).scalars().all()
    return any(a.user_id == uid or (ph and a.phone_hash == ph) for a in rows)

async def notify(bot, uid, text, **kw):
    try: await bot.send_message(uid, text, **kw)
    except Exception: pass

async def log_deal_event(s, app_id, actor_id, event, old_status="", new_status="", comment=""):
    s.add(DealEvent(app_id=app_id, actor_id=actor_id, event=event,
                    from_status=old_status or "", to_status=new_status or "", comment=comment or ""))

async def confirm(bot, s, a, network_payout=None, actor_id=None, comment=""):
    # Serialize concurrent postbacks/admin clicks for one deal (PostgreSQL row lock).
    a = (await s.execute(select(App).where(App.id == a.id).with_for_update())).scalar_one_or_none()
    if a is None: return False
    # One immutable cashback credit per deal. Network payout is tracked separately from
    # the user's reward: the catalog's Tier.cashback is the amount payable to the user.
    if a.status in (CONFIRMED, PAID, REJECTED, EXPIRED):
        return False
    old_status = a.status
    o = await s.get(Offer, a.offer_id)
    tier = (await s.execute(select(Tier).where(Tier.offer_id == o.id).order_by(Tier.id))).scalars().first()
    if tier is None or int(tier.cashback or 0) <= 0:
        raise ValueError(f"Offer {o.code} has no positive user reward configured")
    cashback = int((a.offer_snapshot or {}).get("reward") or tier.cashback)
    if network_payout is not None:
        a.payout = max(0, int(network_payout))
    a.tier_id, a.cashback, a.status = tier.id, cashback, CONFIRMED
    a.reviewed_by, a.reviewed_at = actor_id, datetime.utcnow()
    u = (await s.execute(select(User).where(User.id == a.user_id).with_for_update())).scalar_one()
    exists = (await s.execute(select(WalletEntry).where(WalletEntry.ref == f"app:{a.id}"))).scalar_one_or_none()
    if not exists:
        # If a previous clawback left a negative wallet, this credit first offsets it.
        u.balance += cashback
        s.add(WalletEntry(user_id=u.id, amount=cashback, kind="cashback", ref=f"app:{a.id}", note="Подтверждение оффера"))
    await log_deal_event(s, a.id, actor_id, "confirmed", old_status, CONFIRMED, comment or "Вознаграждение начислено на доступный баланс")
    referral_notice = None

    if u.referrer_id and u.referrer_id != u.id:
        ref = (await s.execute(select(User).where(User.id == u.referrer_id).with_for_update())).scalar_one_or_none()
        if ref and not ref.banned:
            ref_entry = (await s.execute(select(WalletEntry).where(WalletEntry.ref == f"ref:{a.id}"))).scalar_one_or_none()
            if not ref_entry:
                amount = int(cashback * cfg.ref_pct / 100)
                if amount:
                    ref.balance += amount
                    s.add(WalletEntry(user_id=ref.id, amount=amount, kind="referral", ref=f"ref:{a.id}", note="Реферальное начисление"))
                    s.add(RefAcc(referrer_id=ref.id, referee_id=u.id, app_id=a.id, amount=amount))
                    referral_notice = (ref.id, f"👥 По заявке друга начислено {amount} ₽. Баланс: {ref.balance} ₽")
    await s.commit()
    if referral_notice:
        await notify(bot, *referral_notice)
    await notify(bot, u.id, f"✅ <b>Заявка #{a.id} подтверждена!</b>\nНачислено: <b>{cashback} ₽</b>\nДеньги доступны в кошельке: {u.balance} ₽")
    return True
