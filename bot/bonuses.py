"""Idempotent task bonuses shared by the bot and the Mini App API.

Every credit is a real WalletEntry with a unique ref (DB backstop against
races). Callers own the transaction: grant_bonus only stages the posting,
the caller commits. No money is ever credited from the client side.
"""
from sqlalchemy import func, select

from bot.db import App, PayoutReq, Session, User, WalletEntry, CONFIRMED, PAID

CHANNEL_BONUS = 20
FIRST_ORDER_BONUS = 10
TEN_ORDERS_BONUS = 500
REF_PAYOUT_BONUS = 100


async def grant_bonus(s: Session, uid: int, amount: int, kind: str, ref: str, note: str) -> WalletEntry | None:
    """Stage one bonus credit. Returns None when already granted or user ineligible.

    The unique WalletEntry.ref constraint is the final guard: if two concurrent
    callers pass the exists-check, only one commit succeeds (IntegrityError).
    """
    exists = (await s.execute(select(WalletEntry).where(WalletEntry.ref == ref))).scalar_one_or_none()
    if exists is not None:
        return None
    u = (await s.execute(select(User).where(User.id == uid).with_for_update())).scalar_one_or_none()
    if u is None or u.banned:
        return None
    u.balance += int(amount)
    e = WalletEntry(user_id=uid, amount=int(amount), kind=kind, ref=ref, note=note)
    s.add(e)
    return e


async def order_bonuses(s: Session, uid: int) -> list[tuple[int, str]]:
    """+10 on the first confirmed order, +500 on the tenth. Called inside
    logic.confirm() before its commit, so the count includes the new deal.
    Rejected/cancelled/expired deals never count. Returns granted (amount, kind).
    """
    count = (
        await s.execute(select(func.count(App.id)).where(App.user_id == uid, App.status.in_([CONFIRMED, PAID])))
    ).scalar() or 0
    granted: list[tuple[int, str]] = []
    if count >= 1:
        e = await grant_bonus(s, uid, FIRST_ORDER_BONUS, "task_first_order", f"task:first_order:{uid}",
                              "Бонус за первый подтверждённый заказ")
        if e is not None:
            granted.append((FIRST_ORDER_BONUS, "task_first_order"))
    if count >= 10:
        e = await grant_bonus(s, uid, TEN_ORDERS_BONUS, "task_ten_orders", f"task:ten_orders:{uid}",
                              "Бонус за 10 подтверждённых заказов")
        if e is not None:
            granted.append((TEN_ORDERS_BONUS, "task_ten_orders"))
    return granted


async def referral_payout_bonus(s: Session, payout: PayoutReq) -> tuple[int, int] | None:
    """+100 to the referrer, only after the invited friend's FIRST payout that
    an admin actually marked paid. Registration, link clicks, offer starts and
    confirmations alone never qualify. Called inside admin.paid() before commit.
    Returns (referrer_id, amount) for the notification, or None.
    """
    # Serialize concurrent paid() calls for the same friend so the first-paid
    # check and the unique-ref credit cannot race.
    friend = (await s.execute(select(User).where(User.id == payout.user_id).with_for_update())).scalar_one_or_none()
    if friend is None or not friend.referrer_id or friend.referrer_id == friend.id:
        return None
    paid_count = (
        await s.execute(select(func.count(PayoutReq.id)).where(PayoutReq.user_id == friend.id, PayoutReq.status == "paid"))
    ).scalar() or 0
    if paid_count != 1:
        return None
    referrer = await s.get(User, friend.referrer_id)
    if referrer is None or referrer.banned:
        return None
    # The note deliberately carries no friend identifier (privacy).
    e = await grant_bonus(s, referrer.id, REF_PAYOUT_BONUS, "task_ref_bonus", f"task:ref_bonus:{friend.id}",
                          "Бонус за друга: его первая выплата")
    if e is None:
        return None
    return referrer.id, REF_PAYOUT_BONUS