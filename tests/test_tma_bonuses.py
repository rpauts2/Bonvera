"""Stage F tests: real bonus credits (+20/+100/+10/+500), referral rules,
leaderboards and the tasks/friends/achievements endpoints.

Runs against the same temporary sqlite database and aiohttp test server as
test_tma_api (fixtures imported from there, offers from test_tma_deals).
"""
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from bot import logic
from bot import admin as admin_mod
from bot.bonuses import referral_payout_bonus
from bot.config import cfg
from bot.db import App, PayoutReq, Session, User, WalletEntry, CONFIRMED, PROOF
from bot.logic import phone_encrypt
from test_tma_api import (  # noqa: F401  (fixtures reused per-module)
    BotStub, _reset_limiters, client, db, get_json, login, loop, post_json, put_json,
)
from test_tma_deals import accepted_user, offers, oid, png_bytes, take, upload  # noqa: F401


def confirm_app(loop, aid):
    async def run():
        async with Session() as s:
            a = await s.get(App, aid)
            return await logic.confirm(BotStub(), s, a)

    return loop.run_until_complete(run())


def make_app(loop, uid, offer_id, tag, reviewed_at=None, status=PROOF):
    async def run():
        async with Session() as s:
            a = App(user_id=uid, offer_id=offer_id, subid=f"bonus-{uid}-{tag}",
                    offer_snapshot={"reward": 500}, cashback=0, payout=0, status=status,
                    reviewed_at=reviewed_at)
            s.add(a)
            await s.commit()
            return a.id

    return loop.run_until_complete(run())


def bind_referrer(loop, friend_id, referrer_id):
    async def run():
        async with Session() as s:
            f = await s.get(User, friend_id)
            f.referrer_id = referrer_id
            await s.commit()

    loop.run_until_complete(run())


def make_payout(loop, uid, amount=300, status="processing"):
    async def run():
        async with Session() as s:
            p = PayoutReq(user_id=uid, amount=amount, phone=phone_encrypt("79991234567"), bank="Т-Банк", status=status)
            s.add(p)
            await s.commit()
            return p.id

    return loop.run_until_complete(run())


def mark_paid(loop, pid):
    """Replicates the admin.paid() transaction: mark paid, then the bonus hook."""
    async def run():
        async with Session() as s:
            p = (await s.execute(select(PayoutReq).where(PayoutReq.id == pid).with_for_update())).scalar_one()
            p.status, p.paid_at = "paid", datetime.utcnow()
            result = await referral_payout_bonus(s, p)
            await s.commit()
            return result

    return loop.run_until_complete(run())


def wallet_of(loop, client, token):
    status, body = get_json(loop, client, "/api/v1/wallet", token)
    assert status == 200
    return body["data"]


def test_first_order_bonus_via_api(loop, client, offers):
    token = accepted_user(loop, client, 930001)
    status, body = take(loop, client, token, oid(loop, "tst_card_a"))
    aid = body["data"]["app_id"]
    status, _ = upload(loop, client, token, aid, [("proof.png", png_bytes(41))])
    assert status == 200
    status, _ = post_json(loop, client, f"/api/v1/apps/{aid}/submit", token)
    assert status == 200
    assert confirm_app(loop, aid) is True

    data = wallet_of(loop, client, token)
    assert data["summary"]["available"] == 510  # 500 cashback + 10 bonus
    bonuses = [e for e in data["entries"] if e["kind"] == "task_first_order"]
    assert len(bonuses) == 1 and bonuses[0]["amount"] == 10
    assert bonuses[0]["ref"] == "task:first_order:930001"

    # Repeat confirmation is a no-op: no second credit.
    assert confirm_app(loop, aid) is False
    data = wallet_of(loop, client, token)
    assert data["summary"]["available"] == 510
    assert sum(1 for e in data["entries"] if e["kind"] == "task_first_order") == 1


def test_ten_orders_bonus_no_double(loop, client, offers):
    token, _ = login(loop, client, 930002)
    offer_id = oid(loop, "tst_card_a")
    for i in range(10):
        aid = make_app(loop, 930002, offer_id, f"ten-{i}")
        assert confirm_app(loop, aid) is True

    data = wallet_of(loop, client, token)
    assert data["summary"]["available"] == 5510  # 10*500 + 10 + 500
    kinds = [e["kind"] for e in data["entries"]]
    assert kinds.count("task_first_order") == 1
    assert kinds.count("task_ten_orders") == 1

    aid = make_app(loop, 930002, offer_id, "ten-10")
    assert confirm_app(loop, aid) is True
    data = wallet_of(loop, client, token)
    assert data["summary"]["available"] == 6010
    assert sum(1 for e in data["entries"] if e["kind"] == "task_ten_orders") == 1


def test_referral_bonus_first_paid_only(loop, client, offers):
    ref_token, _ = login(loop, client, 930003)
    login(loop, client, 930004)
    bind_referrer(loop, 930004, 930003)

    pid1 = make_payout(loop, 930004)
    result = mark_paid(loop, pid1)
    assert result == (930003, 100)
    data = wallet_of(loop, client, ref_token)
    assert data["summary"]["available"] == 100
    bonuses = [e for e in data["entries"] if e["kind"] == "task_ref_bonus"]
    assert len(bonuses) == 1 and bonuses[0]["amount"] == 100
    assert bonuses[0]["ref"] == ""  # friend ID never exposed
    assert "930004" not in bonuses[0]["note"]

    # A second paid payout of the same friend does not qualify.
    pid2 = make_payout(loop, 930004)
    assert mark_paid(loop, pid2) is None
    # Replaying the first payout's hook is idempotent.
    assert mark_paid(loop, pid1) is None
    data = wallet_of(loop, client, ref_token)
    assert data["summary"]["available"] == 100
    assert sum(1 for e in data["entries"] if e["kind"] == "task_ref_bonus") == 1


def test_referral_task_remains_repeatable_for_each_qualified_friend(loop, client, offers):
    ref_token, _ = login(loop, client, 930040)
    for friend_id in (930041, 930042):
        login(loop, client, friend_id)
        bind_referrer(loop, friend_id, 930040)
        assert mark_paid(loop, make_payout(loop, friend_id)) == (930040, 100)

    status, body = get_json(loop, client, "/api/v1/tasks", ref_token)
    assert status == 200
    task = next(t for t in body["data"] if t["key"] == "referral")
    assert task["done"] is False, "реферальная награда остаётся повторяемой после первого друга"
    assert task["progress"] == 2 and task["target"] == 0
    assert "2 × 100 ₽" in task["hint"]
    assert "каждого следующего друга" in task["hint"]

    status, body = get_json(loop, client, "/api/v1/friends", ref_token)
    assert status == 200
    assert body["data"]["qualified"] == 2
    assert body["data"]["bonus_earned"] == 200


def test_referral_bonus_guards(loop, client, offers):
    # No referrer.
    login(loop, client, 930005)
    assert mark_paid(loop, make_payout(loop, 930005)) is None

    # Self-referral is ignored.
    login(loop, client, 930006)
    bind_referrer(loop, 930006, 930006)
    assert mark_paid(loop, make_payout(loop, 930006)) is None

    # Banned referrer gets nothing.
    login(loop, client, 930007)
    login(loop, client, 930008)
    bind_referrer(loop, 930008, 930007)

    async def ban():
        async with Session() as s:
            u = await s.get(User, 930007)
            u.banned = True
            await s.commit()

    loop.run_until_complete(ban())
    assert mark_paid(loop, make_payout(loop, 930008)) is None


def test_admin_paid_hook_end_to_end(loop, client, offers, monkeypatch):
    ref_token, _ = login(loop, client, 930010)
    login(loop, client, 930011)
    bind_referrer(loop, 930011, 930010)
    pid = make_payout(loop, 930011)
    monkeypatch.setattr(cfg, "admins", [999001])

    async def noop(*a, **k):
        pass

    fake_c = SimpleNamespace(
        data=f"adm:paid:{pid}",
        from_user=SimpleNamespace(id=999001),
        message=SimpleNamespace(edit_text=noop),
        answer=noop,
    )
    loop.run_until_complete(admin_mod.paid(fake_c, BotStub()))

    async def check():
        async with Session() as s:
            p = await s.get(PayoutReq, pid)
            assert p.status == "paid" and p.paid_at is not None

    loop.run_until_complete(check())
    data = wallet_of(loop, client, ref_token)
    assert data["summary"]["available"] == 100
    assert any(e["kind"] == "task_ref_bonus" for e in data["entries"])


def test_channel_bonus_once(loop, client, offers, monkeypatch):
    token, _ = login(loop, client, 930012)
    status, body = post_json(loop, client, "/api/v1/tasks/channel/check", token)
    assert status == 409 and body["err"]["code"] == "channel_not_configured"

    monkeypatch.setattr(cfg, "channel_id", "-1001234567890")
    monkeypatch.setattr(cfg, "channel_url", "https://t.me/bonvera_test")
    status, body = post_json(loop, client, "/api/v1/tasks/channel/check", token)
    assert status == 200
    task = body["data"]
    assert task["key"] == "channel" and task["done"] is True and task["reward"] == 20

    data = wallet_of(loop, client, token)
    assert data["summary"]["available"] == 20
    assert any(e["kind"] == "task_channel" and e["amount"] == 20 for e in data["entries"])

    # Repeat checks never credit twice.
    for _ in range(3):
        status, body = post_json(loop, client, "/api/v1/tasks/channel/check", token)
        assert status == 200 and body["data"]["done"] is True
    data = wallet_of(loop, client, token)
    assert data["summary"]["available"] == 20
    assert sum(1 for e in data["entries"] if e["kind"] == "task_channel") == 1


def test_channel_not_subscribed(loop, client, offers, monkeypatch):
    token, _ = login(loop, client, 930013)
    monkeypatch.setattr(cfg, "channel_id", "-1001234567890")
    monkeypatch.setattr(cfg, "channel_url", "https://t.me/bonvera_test")
    monkeypatch.setattr(BotStub, "chat_member_status", "left")
    status, body = post_json(loop, client, "/api/v1/tasks/channel/check", token)
    assert status == 400 and body["err"]["code"] == "not_subscribed"
    assert wallet_of(loop, client, token)["summary"]["available"] == 0


def test_channel_telegram_error(loop, client, offers, monkeypatch):
    token, _ = login(loop, client, 930014)
    monkeypatch.setattr(cfg, "channel_id", "-1001234567890")
    monkeypatch.setattr(cfg, "channel_url", "https://t.me/bonvera_test")
    monkeypatch.setattr(BotStub, "chat_member_error", True)
    status, body = post_json(loop, client, "/api/v1/tasks/channel/check", token)
    assert status == 502 and body["err"]["code"] == "channel_unavailable"
    assert wallet_of(loop, client, token)["summary"]["available"] == 0


def test_leaderboard_orders_anonymized(loop, client, offers):
    top_token, _ = login(loop, client, 930020, username="top_user")
    me_token, _ = login(loop, client, 930021, username=None)
    login(loop, client, 930022, username="banned_whale")
    offer_id = oid(loop, "tst_card_a")
    now = datetime.utcnow()
    last_month = now.replace(day=1) - timedelta(days=1)
    for i in range(2):
        make_app(loop, 930020, offer_id, f"lb-{i}", reviewed_at=now, status=CONFIRMED)
    make_app(loop, 930020, offer_id, "lb-old", reviewed_at=last_month, status=CONFIRMED)
    make_app(loop, 930021, offer_id, "lb-me", reviewed_at=now, status=CONFIRMED)
    for i in range(5):
        make_app(loop, 930022, offer_id, f"lb-ban-{i}", reviewed_at=now, status=CONFIRMED)

    async def ban():
        async with Session() as s:
            u = await s.get(User, 930022)
            u.banned = True
            await s.commit()

    loop.run_until_complete(ban())

    status, body = get_json(loop, client, "/api/v1/leaderboard?type=orders&period=all", me_token)
    assert status == 200
    data = body["data"]
    rows = data["rows"]
    displays = [r["display"] for r in rows]
    # The leaderboard is global: users from other tests are present too.
    assert "@top_user" in displays
    assert next(r for r in rows if r["display"] == "@top_user")["value"] == 3
    me_row = next(r for r in rows if r["is_me"])
    assert me_row["value"] == 1 and me_row["display"].startswith("Участник ")
    assert data["me"]["value"] == 1 and data["me"]["rank"] is not None
    assert "@banned_whale" not in displays  # banned users never appear
    import re
    for r in rows:
        # Only @username or an anonymized label — never IDs, phones or names.
        assert re.fullmatch(r"@[A-Za-z0-9_]+|Участник \d+", r["display"]), r["display"]
        assert "930020" not in r["display"] and "930021" not in r["display"]

    status, body = get_json(loop, client, "/api/v1/leaderboard?type=orders&period=month", me_token)
    data = body["data"]
    assert next(r for r in data["rows"] if r["display"] == "@top_user")["value"] == 2  # last month excluded
    assert data["me"]["value"] == 1

    status, body = get_json(loop, client, "/api/v1/leaderboard?type=bad&period=all", me_token)
    assert status == 400
    status, body = get_json(loop, client, "/api/v1/leaderboard?type=orders&period=year", me_token)
    assert status == 400


def test_leaderboard_friends(loop, client, offers):
    ref_token, _ = login(loop, client, 930027, username="mentor")
    login(loop, client, 930028)
    bind_referrer(loop, 930028, 930027)
    pid = make_payout(loop, 930028)
    mark_paid(loop, pid)

    status, body = get_json(loop, client, "/api/v1/leaderboard?type=friends&period=all", ref_token)
    assert status == 200
    data = body["data"]
    assert data["me"]["value"] == 1 and data["me"]["rank"] is not None
    mentor = next(r for r in data["rows"] if r["display"] == "@mentor")
    assert mentor["value"] == 1 and mentor["is_me"] is True


def test_tasks_friends_achievements_endpoints(loop, client, offers):
    token, _ = login(loop, client, 930029)
    status, body = get_json(loop, client, "/api/v1/tasks", token)
    assert status == 200
    tasks = {t["key"]: t for t in body["data"]}
    assert set(tasks) == {"channel", "referral", "first_order", "ten_orders"}
    assert tasks["channel"]["claimable"] is False  # channel unconfigured
    assert tasks["channel"]["hint"]
    assert tasks["ten_orders"]["target"] == 10 and tasks["ten_orders"]["reward"] == 500

    status, body = get_json(loop, client, "/api/v1/friends", token)
    assert status == 200
    friends = body["data"]
    assert friends["ref_link"] == "https://t.me/bonvera_test_bot?start=ref_930029"
    assert friends["ref_percent"] == cfg.ref_pct
    assert friends["invited"] == 0 and friends["qualified"] == 0

    status, body = get_json(loop, client, "/api/v1/achievements", token)
    assert status == 200
    keys = {a["key"] for a in body["data"]}
    assert keys == {"first_order", "ten_orders", "first_payout", "friend_bonus", "channel", "veteran"}
    assert all(a["unlocked"] is False for a in body["data"])


def test_referral_commission_separate_from_bonus(loop, client, offers):
    ref_token, _ = login(loop, client, 930025)
    token = accepted_user(loop, client, 930026)
    bind_referrer(loop, 930026, 930025)
    status, body = take(loop, client, token, oid(loop, "tst_card_a"))
    aid = body["data"]["app_id"]
    status, _ = upload(loop, client, token, aid, [("proof.png", png_bytes(42))])
    assert status == 200
    status, _ = post_json(loop, client, f"/api/v1/apps/{aid}/submit", token)
    assert status == 200
    assert confirm_app(loop, aid) is True

    # REF_PERCENT commission is a separate "referral" entry, not the +100 bonus.
    data = wallet_of(loop, client, ref_token)
    commissions = [e for e in data["entries"] if e["kind"] == "referral"]
    assert len(commissions) == 1
    assert commissions[0]["amount"] == int(500 * cfg.ref_pct / 100)
    assert commissions[0]["ref"] == f"ref:{aid}"
    assert not any(e["kind"] == "task_ref_bonus" for e in data["entries"])

    # The +100 bonus arrives only after the friend's first actual payout.
    status, body = post_json(loop, client, "/api/v1/withdrawals", token,
                             {"amount": 300, "bank": "Т-Банк", "phone": "+79991234567"})
    assert status == 201
    mark_paid(loop, body["data"]["id"])
    data = wallet_of(loop, client, ref_token)
    kinds = [e["kind"] for e in data["entries"]]
    assert kinds.count("referral") == 1 and kinds.count("task_ref_bonus") == 1
    assert data["summary"]["available"] == int(500 * cfg.ref_pct / 100) + 100