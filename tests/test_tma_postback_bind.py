"""Ручная привязка постбэка к заявке из админ-панели.

Реальные конверсии ProCPA приходят с пустым sub1, поэтому заявку выбирает
администратор: `POST /api/v1/admin/postbacks/{id}/bind`. Проверяется успешная
привязка (холд, выплата сети, subid, событие сделки, аудит, уведомление
пользователю), повторная привязка, rejected-постбэк, несуществующая заявка,
привязка к уже подтверждённой заявке и отказ не-админу.
"""
import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from aiohttp.test_utils import TestClient, TestServer
from sqlalchemy import select

from bot.config import cfg
from bot.db import AdminAuditEvent, App, Bank, DealEvent, Offer, PbLog, Session, User, init_db
from bot.logic import subid
from bot.tma_api import api_limiter, auth_limiter
from bot.tma_auth import create_session
from bot.web import make_web

ADMIN_ID = 920001
OWNER_ID = 920100


class BotStub:
    """Локальная заглушка Telegram: фиксирует уведомления пользователям."""

    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text))
        return SimpleNamespace(message_id=1, chat=SimpleNamespace(id=chat_id))

    async def get_me(self):
        return SimpleNamespace(username="bonvera_test_bot")


BOT = BotStub()


@pytest.fixture(scope="module")
def loop():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    asyncio.set_event_loop(None)
    loop.close()


@pytest.fixture(scope="module")
def db(loop):
    loop.run_until_complete(init_db())


@pytest.fixture(scope="module")
def client(loop, db):
    async def build():
        return TestClient(TestServer(make_web(BOT)))

    c = loop.run_until_complete(build())
    loop.run_until_complete(c.start_server())
    yield c
    loop.run_until_complete(c.close())


@pytest.fixture(autouse=True)
def _reset_limiters():
    auth_limiter.hits.clear()
    api_limiter.hits.clear()
    yield
    auth_limiter.hits.clear()
    api_limiter.hits.clear()


def make_token(loop, uid: int) -> str:
    async def build():
        async with Session() as s:
            token, _expires = await create_session(s, uid)
        return token

    return loop.run_until_complete(build())


def bind(loop, client, token, pb_id, payload):
    async def call():
        resp = await client.post(
            f"/api/v1/admin/postbacks/{pb_id}/bind",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )
        return resp.status, await resp.json()

    return loop.run_until_complete(call())


def section(loop, client, token):
    async def call():
        resp = await client.get(
            "/api/v1/admin/section/postbacks",
            headers={"Authorization": f"Bearer {token}"},
        )
        return resp.status, await resp.json()

    return loop.run_until_complete(call())


def seed(
    loop,
    *,
    status="proof",
    payout=0,
    hold_days=14,
    pb_status="approved",
    pb_payout=1500,
    pb_subid="",
    lead_id="LEAD-1",
    hold_until=None,
):
    """Заводит заявку и постбэк без subid — как это делает ProCPA."""

    async def run():
        suffix = uuid4().hex[:8]
        async with Session() as s:
            for uid in (ADMIN_ID, OWNER_ID):
                if await s.get(User, uid) is None:
                    s.add(User(id=uid, username=f"bind_{uid}", name=f"Bind {uid}", balance=0, accepted=True))
            await s.flush()
            bank = Bank(slug=f"pb-bind-{suffix}", name="Bind bank", category="cpl")
            s.add(bank)
            await s.flush()
            offer = Offer(bank_id=bank.id, code=f"pb-bind-{suffix}", name="Bind offer", url="https://partner.example/x")
            s.add(offer)
            await s.flush()
            deal = App(
                user_id=OWNER_ID,
                offer_id=offer.id,
                subid=f"bind-deal-{suffix}",
                status=status,
                payout=payout,
                cashback=700,
                hold_until=hold_until,
                offer_snapshot={"hold_days": hold_days, "reward": 700, "name": "Bind offer"},
                verification={},
            )
            s.add(deal)
            await s.flush()
            postback = PbLog(
                subid=pb_subid,
                status=pb_status,
                payout=pb_payout,
                raw=str({"subid": pb_subid, "status": pb_status, "payout": pb_payout, "lead_id": lead_id}),
            )
            s.add(postback)
            await s.commit()
            return {"app_id": deal.id, "pb_id": postback.id, "deal_subid": deal.subid}

    return loop.run_until_complete(run())


def load(loop, model, pk):
    async def run():
        async with Session() as s:
            return await s.get(model, pk)

    return loop.run_until_complete(run())


def load_events(loop, app_id):
    async def run():
        async with Session() as s:
            return list((await s.execute(select(DealEvent).where(DealEvent.app_id == app_id).order_by(DealEvent.id))).scalars().all())

    return loop.run_until_complete(run())


def load_audit(loop, target_id):
    async def run():
        async with Session() as s:
            return list((await s.execute(select(AdminAuditEvent).where(AdminAuditEvent.target_id == target_id).order_by(AdminAuditEvent.id))).scalars().all())

    return loop.run_until_complete(run())


def test_bind_approved_postback_puts_deal_on_hold(loop, client, monkeypatch):
    monkeypatch.setattr(cfg, "admins", [ADMIN_ID])
    seeded = seed(loop)
    token = make_token(loop, ADMIN_ID)

    status, rows = section(loop, client, token)
    assert status == 200
    row = next(item for item in rows["data"]["items"] if item["id"] == seeded["pb_id"])
    assert row["can_bind"] is True and row["bound_app_id"] is None

    started = datetime.utcnow()
    status, body = bind(loop, client, token, seeded["pb_id"], {"app_id": seeded["app_id"]})
    assert status == 200, body
    assert body["data"]["app_id"] == seeded["app_id"]
    assert body["data"]["status"] == "hold"
    assert body["data"]["subid"] == subid(seeded["app_id"])

    deal = load(loop, App, seeded["app_id"])
    assert deal.status == "hold"
    assert deal.payout == 1500
    assert deal.subid == seeded["deal_subid"]
    assert deal.hold_until is not None
    assert started + timedelta(days=13) <= deal.hold_until <= started + timedelta(days=15)
    assert (deal.verification or {}).get("network_approved") is True

    postback = load(loop, PbLog, seeded["pb_id"])
    assert postback.subid == subid(seeded["app_id"])

    events = load_events(loop, seeded["app_id"])
    approved = [e for e in events if e.event == "network_approved_manual"]
    assert len(approved) == 1
    assert f"#{seeded['pb_id']}" in approved[0].comment
    assert approved[0].from_status == "proof" and approved[0].to_status == "hold"

    audit = load_audit(loop, str(seeded["pb_id"]))
    assert len(audit) == 1
    assert audit[0].action == "postback_bound" and audit[0].target_type == "postback"
    assert audit[0].actor_id == ADMIN_ID
    assert f"app_id={seeded['app_id']}" in audit[0].details
    assert "lead_id=LEAD-1" in audit[0].details

    assert any(uid == OWNER_ID and f"#{seeded['app_id']}" in text for uid, text in BOT.sent)

    status, rows = section(loop, client, token)
    row = next(item for item in rows["data"]["items"] if item["id"] == seeded["pb_id"])
    assert row["can_bind"] is False and row["bound_app_id"] == seeded["app_id"]


def test_bind_twice_returns_409(loop, client, monkeypatch):
    monkeypatch.setattr(cfg, "admins", [ADMIN_ID])
    first = seed(loop)
    second = seed(loop)
    token = make_token(loop, ADMIN_ID)
    assert bind(loop, client, token, first["pb_id"], {"app_id": first["app_id"]})[0] == 200

    status, body = bind(loop, client, token, first["pb_id"], {"app_id": second["app_id"]})
    assert status == 409
    assert body["err"]["code"] == "already_bound"
    assert load(loop, App, second["app_id"]).status == "proof"


def test_bind_rejected_postback_returns_409(loop, client, monkeypatch):
    monkeypatch.setattr(cfg, "admins", [ADMIN_ID])
    seeded = seed(loop, pb_status="rejected")
    token = make_token(loop, ADMIN_ID)

    status, body = bind(loop, client, token, seeded["pb_id"], {"app_id": seeded["app_id"]})
    assert status == 409
    assert body["err"]["code"] == "status_not_bindable"
    assert "подтверждённые конверсии" in body["err"]["message"]
    assert load(loop, PbLog, seeded["pb_id"]).subid == ""
    assert load(loop, App, seeded["app_id"]).status == "proof"


def test_bind_requires_admin(loop, client, monkeypatch):
    monkeypatch.setattr(cfg, "admins", [ADMIN_ID])
    seeded = seed(loop)
    token = make_token(loop, OWNER_ID)

    status, body = bind(loop, client, token, seeded["pb_id"], {"app_id": seeded["app_id"]})
    assert status == 403
    assert body["err"]["code"] == "forbidden"
    assert load(loop, PbLog, seeded["pb_id"]).subid == ""
    assert load(loop, App, seeded["app_id"]).status == "proof"


def test_bind_unknown_deal_returns_404(loop, client, monkeypatch):
    monkeypatch.setattr(cfg, "admins", [ADMIN_ID])
    seeded = seed(loop)
    token = make_token(loop, ADMIN_ID)

    status, body = bind(loop, client, token, seeded["pb_id"], {"app_id": 999_999_999})
    assert status == 404
    assert body["err"]["code"] == "app_not_found"

    status, body = bind(loop, client, token, 999_999_999, {"app_id": seeded["app_id"]})
    assert status == 404
    assert body["err"]["code"] == "postback_not_found"


def test_bind_confirmed_deal_only_fills_payout(loop, client, monkeypatch):
    monkeypatch.setattr(cfg, "admins", [ADMIN_ID])
    seeded = seed(loop, status="confirmed", payout=0)
    token = make_token(loop, ADMIN_ID)

    status, body = bind(loop, client, token, seeded["pb_id"], {"app_id": seeded["app_id"]})
    assert status == 200, body
    assert body["data"]["status"] == "confirmed"

    deal = load(loop, App, seeded["app_id"])
    assert deal.status == "confirmed"
    assert deal.payout == 1500
    assert deal.hold_until is None
    events = [e.event for e in load_events(loop, seeded["app_id"])]
    assert "network_approved_manual" not in events
    assert "network_payout_received" in events
