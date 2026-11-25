"""Привязка постбэков: алиасы subid и алерты о «потерянных» конверсиях.

Живые постбэки ProCPA приходят без sub1: сеть кладёт идентификатор в другой
параметр либо конверсия пришла не из приложения. Такая конверсия - деньги,
которые нельзя тихо терять, поэтому обработчик обязан разбудить админов.
"""
import asyncio
from uuid import uuid4

import pytest
from aiohttp.test_utils import TestClient, TestServer
from sqlalchemy import select

from bot.config import cfg
from bot.db import PbLog, Session, init_db
from bot.web import make_web, pick_subid


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
        return TestClient(TestServer(make_web(None)))

    c = loop.run_until_complete(build())
    loop.run_until_complete(c.start_server())
    yield c
    loop.run_until_complete(c.close())


@pytest.fixture
def alerts(monkeypatch):
    box = []

    async def fake_notify(bot, uid, text, **kwargs):
        box.append((uid, text))

    monkeypatch.setattr("bot.web.notify", fake_notify)
    monkeypatch.setattr(cfg, "admins", [555001])
    return box


def _params(**extra):
    """Callback query params with the shared secret taken from config."""
    return {**{"secret": cfg.pb_secret}, **extra}


def _get(loop, client, **params):
    return loop.run_until_complete(client.get("/postback", params=_params(**params)))


def _json(loop, resp):
    return loop.run_until_complete(resp.json())


def test_pick_subid_accepts_aliases():
    assert pick_subid({"sub1": "a1-x"}) == "a1-x"
    assert pick_subid({"subid": "a2-y"}) == "a2-y"
    assert pick_subid({"aff_sub": "a3-z"}) == "a3-z"
    assert pick_subid({"sub1": "", "s1": "a4-w"}) == "a4-w"


def test_pick_subid_ignores_unsubstituted_macro():
    """Если сеть не подставила макрос, приходит литерал в фигурных скобках."""
    assert pick_subid({"sub1": "{sub1}"}) == ""
    assert pick_subid({"sub1": "{sub_id}", "subid": "a5-v"}) == "a5-v"


def test_paid_lead_without_subid_alerts_admins_once(loop, client, alerts):
    lead = f"L{uuid4().hex[:8]}"
    params = dict(status="approved", payout="7980", lead_id=lead, offer_id="535")
    resp = _get(loop, client, **params)
    assert resp.status == 200 and _json(loop, resp)["err"] == "subid"
    assert len(alerts) == 1
    uid, text = alerts[0]
    assert uid == 555001 and lead in text and "7980" in text
    # Повторный колбэк по тому же лиду не должен спамить.
    _get(loop, client, **params)
    assert len(alerts) == 1


def test_rejected_lead_without_subid_stays_silent(loop, client, alerts):
    resp = _get(loop, client, status="rejected", payout="0", lead_id=f"R{uuid4().hex[:8]}")
    assert resp.status == 200 and _json(loop, resp)["err"] == "subid"
    assert alerts == []


def test_lead_is_still_stored_in_postback_log(loop, client, alerts):
    lead = f"S{uuid4().hex[:8]}"
    _get(loop, client, status="approved", payout="1000", lead_id=lead)

    async def find():
        async with Session() as s:
            return (await s.execute(select(PbLog).where(PbLog.raw.contains(lead)))).scalars().all()

    rows = loop.run_until_complete(find())
    assert rows and rows[0].payout == 1000
