"""Stage H hardening tests: the remaining §21 gaps — repeat postbacks,
admin rights enforcement and concurrent requests (no double credits).

Runs against the same temporary sqlite database and aiohttp test server as
the other TMA modules (fixtures imported from test_tma_api).
"""
import asyncio
import io
import random
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from bot import admin as admin_mod
from bot import logic
from bot.config import cfg
from bot.db import (
    App, DealEvent, PayoutEvent, PayoutReq, Session, WalletEntry,
    CONFIRMED, HOLD, PROOF, REJECTED,
)
from bot.logic import subid
from test_tma_api import (  # noqa: F401  (fixtures reused per-module)
    BotStub, _reset_limiters, client, db, get_json, login, loop, post_json,
)
from test_tma_deals import accepted_user, offers, oid, take, upload  # noqa: F401
from test_tma_bonuses import confirm_app, make_payout, wallet_of


def hard_png(seed: int) -> bytes:
    """Full-frame noise: perceptual hashes stay far apart, so the global
    anti-duplicate check never mistakes one test proof for another."""
    from PIL import Image

    rng = random.Random(seed)
    img = Image.frombytes("RGB", (64, 64), bytes(rng.getrandbits(8) for _ in range(64 * 64 * 3)))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def submitted_app(loop, client, uid, seed):
    token = accepted_user(loop, client, uid)
    status, body = take(loop, client, token, oid(loop, "tst_card_a"))
    assert status == 201, body
    aid = body["data"]["app_id"]
    status, _ = upload(loop, client, token, aid, [("proof.png", hard_png(seed))])
    assert status == 200
    status, _ = post_json(loop, client, f"/api/v1/apps/{aid}/submit", token)
    assert status == 200
    return token, aid


def postback(loop, client, aid, status, payout=1000, secret=None):
    sec = cfg.pb_secret if secret is None else secret
    url = f"/postback?secret={sec}&subid={subid(aid)}&status={status}&payout={payout}"
    resp = loop.run_until_complete(client.get(url))
    return resp.status, loop.run_until_complete(resp.json())


def app_row(loop, aid):
    async def q():
        async with Session() as s:
            return await s.get(App, aid)

    return loop.run_until_complete(q())


def event_count(loop, aid, event):
    async def q():
        async with Session() as s:
            rows = (await s.execute(
                select(DealEvent).where(DealEvent.app_id == aid, DealEvent.event == event)
            )).scalars().all()
            return len(rows)

    return loop.run_until_complete(q())


def test_postback_approved_hold_and_repeat(loop, client, offers):
    token, aid = submitted_app(loop, client, 940001, 61)

    status, body = postback(loop, client, aid, "approved", payout=1000)
    assert status == 200 and body["ok"] is True
    a = app_row(loop, aid)
    assert a.status == HOLD and a.payout == 1000
    assert a.hold_until is not None
    assert (a.verification or {}).get("network_approved") is True
    hold_until = a.hold_until
    assert event_count(loop, aid, "network_approved_hold") == 1
    # Hold never credits the wallet: money arrives only after admin confirmation.
    assert wallet_of(loop, client, token)["summary"]["available"] == 0

    # Repeating the same approved postback changes nothing.
    status, body = postback(loop, client, aid, "approved", payout=1000)
    assert status == 200 and body["ok"] is True
    a = app_row(loop, aid)
    assert a.status == HOLD and a.payout == 1000 and a.hold_until == hold_until
    assert event_count(loop, aid, "network_approved_hold") == 1

    # A later postback with a different payout cannot overwrite the recorded one.
    status, _ = postback(loop, client, aid, "approved", payout=2000)
    assert status == 200
    assert app_row(loop, aid).payout == 1000


def test_postback_auth_and_validation(loop, client, offers):
    _, aid = submitted_app(loop, client, 940002, 62)

    status, body = postback(loop, client, aid, "approved", secret="wrong-secret")
    assert status == 403 and body["err"] == "auth"

    status, body = postback(loop, client, aid, "approved", payout=-5)
    assert status == 400 and body["err"] == "payout"

    resp = loop.run_until_complete(
        client.get(f"/postback?secret={cfg.pb_secret}&subid=garbage&status=approved")
    )
    assert resp.status == 200
    assert loop.run_until_complete(resp.json()) == {"ok": False, "err": "subid"}

    # Correctly signed subid of a nonexistent deal.
    resp = loop.run_until_complete(
        client.get(f"/postback?secret={cfg.pb_secret}&subid={subid(999999)}&status=approved")
    )
    assert resp.status == 200
    assert loop.run_until_complete(resp.json()) == {"ok": False, "err": "app"}

    # The deal itself was never touched by the rejected requests.
    assert app_row(loop, aid).status == PROOF


def test_postback_rejected_clawback_once(loop, client, offers):
    token, aid = submitted_app(loop, client, 940003, 63)
    assert confirm_app(loop, aid) is True
    assert wallet_of(loop, client, token)["summary"]["available"] == 510

    status, body = postback(loop, client, aid, "rejected", payout=0)
    assert status == 200 and body["ok"] is True
    a = app_row(loop, aid)
    assert a.status == REJECTED and a.reason

    data = wallet_of(loop, client, token)
    assert data["summary"]["available"] == 10  # 510 - 500 clawback, +10 bonus stays
    clawbacks = [e for e in data["entries"] if e["kind"] == "clawback"]
    assert len(clawbacks) == 1
    assert clawbacks[0]["amount"] == -500
    assert clawbacks[0]["ref"] == f"clawback:app:{aid}"

    # Repeating the rejection never claws back twice.
    status, _ = postback(loop, client, aid, "rejected", payout=0)
    assert status == 200
    data = wallet_of(loop, client, token)
    assert data["summary"]["available"] == 10
    assert sum(1 for e in data["entries"] if e["kind"] == "clawback") == 1
    assert app_row(loop, aid).status == REJECTED


def test_postback_hold_idempotent_then_approved(loop, client, offers):
    _, aid = submitted_app(loop, client, 940004, 64)

    status, _ = postback(loop, client, aid, "hold", payout=0)
    assert status == 200
    a = app_row(loop, aid)
    assert a.status == HOLD and a.hold_until is not None
    assert (a.verification or {}).get("network_approved") is False
    hold_until = a.hold_until
    assert event_count(loop, aid, "network_hold") == 1

    # Repeated pending postbacks do not extend the control deadline.
    status, _ = postback(loop, client, aid, "pending", payout=0)
    assert status == 200
    a = app_row(loop, aid)
    assert a.hold_until == hold_until
    assert event_count(loop, aid, "network_hold") == 1

    # Approval after hold flips the flag and records the payout once.
    status, _ = postback(loop, client, aid, "approved", payout=700)
    assert status == 200
    a = app_row(loop, aid)
    assert a.status == HOLD and a.payout == 700
    assert (a.verification or {}).get("network_approved") is True


def test_admin_rights_paid_and_confirm(loop, client, offers, monkeypatch):
    monkeypatch.setattr(cfg, "admins", [999001])
    login(loop, client, 940005)
    pid = make_payout(loop, 940005, status="processing")

    async def noop(*a, **k):
        pass

    def callback(uid, data):
        return SimpleNamespace(
            data=data,
            from_user=SimpleNamespace(id=uid),
            message=SimpleNamespace(photo=None, edit_text=noop, edit_caption=noop),
            answer=noop,
        )

    # A non-admin callback is a silent no-op: the payout stays untouched.
    loop.run_until_complete(admin_mod.paid(callback(12345, f"adm:paid:{pid}"), BotStub()))

    async def check_processing():
        async with Session() as s:
            p = await s.get(PayoutReq, pid)
            assert p.status == "processing" and p.paid_at is None
            events = (await s.execute(select(PayoutEvent).where(PayoutEvent.payout_id == pid))).scalars().all()
            assert events == []

    loop.run_until_complete(check_processing())

    # The configured admin can mark the same payout paid.
    loop.run_until_complete(admin_mod.paid(callback(999001, f"adm:paid:{pid}"), BotStub()))

    async def check_paid():
        async with Session() as s:
            p = await s.get(PayoutReq, pid)
            assert p.status == "paid" and p.paid_at is not None

    loop.run_until_complete(check_paid())

    # Manual deal confirmation is admin-only too.
    token, aid = submitted_app(loop, client, 940006, 65)
    loop.run_until_complete(admin_mod.manual_confirm(callback(12345, f"adm:confirm:{aid}"), BotStub()))
    assert app_row(loop, aid).status == PROOF
    assert wallet_of(loop, client, token)["summary"]["available"] == 0

    loop.run_until_complete(admin_mod.manual_confirm(callback(999001, f"adm:confirm:{aid}"), BotStub()))
    assert app_row(loop, aid).status == CONFIRMED
    assert wallet_of(loop, client, token)["summary"]["available"] == 510


def test_concurrent_channel_checks_single_credit(loop, client, offers, monkeypatch):
    monkeypatch.setattr(cfg, "channel_id", "-1001234567890")
    monkeypatch.setattr(cfg, "channel_url", "https://t.me/bonvera_test")
    token, _ = login(loop, client, 940007)

    async def check():
        resp = await client.post(
            "/api/v1/tasks/channel/check", json={}, headers={"Authorization": f"Bearer {token}"}
        )
        return resp.status, await resp.json()

    results = loop.run_until_complete(asyncio.gather(*[check() for _ in range(5)]))
    assert all(status == 200 for status, _ in results)
    assert all(body["data"]["done"] is True for _, body in results)

    data = wallet_of(loop, client, token)
    assert data["summary"]["available"] == 20
    assert sum(1 for e in data["entries"] if e["kind"] == "task_channel") == 1


def test_concurrent_confirm_single_credit(loop, client, offers):
    token, aid = submitted_app(loop, client, 940008, 66)

    async def one():
        async with Session() as s:
            a = await s.get(App, aid)
            return await logic.confirm(BotStub(), s, a)

    results = loop.run_until_complete(asyncio.gather(*[one() for _ in range(5)]))
    assert results.count(True) == 1 and results.count(False) == 4

    data = wallet_of(loop, client, token)
    assert data["summary"]["available"] == 510
    kinds = [e["kind"] for e in data["entries"]]
    assert kinds.count("cashback") == 1
    assert kinds.count("task_first_order") == 1
    assert event_count(loop, aid, "confirmed") == 1