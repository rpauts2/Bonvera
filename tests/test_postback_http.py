"""HTTP-тесты обработчика /postback: авторизация, subid и POST-варианты.

Приложение поднимается так же, как в остальных тестах проекта: `make_web(bot)`
на `aiohttp.test_utils.TestClient` поверх временной SQLite из conftest.
Здесь передаётся `make_web(None)` — бот не нужен: ветка успеха зовёт
`notify()`, который глотает исключения, поэтому postback без Telegram-клиента
не падает. Сеть и Postgres не используются.

Проверяется:
  * неверный/отсутствующий secret → 403 {"ok": false, "err": "auth"};
  * битый subid → 200 {"err": "subid"};
  * корректный `bot.logic.subid(aid)` для несуществующей сделки → 200 {"err": "app"};
  * GET, POST form-urlencoded и POST JSON доходят до одной логики;
  * `sub1` работает как алиас `subid`;
  * повторный одинаковый вызов детерминирован и не создаёт вторую сделку.
"""
from uuid import uuid4

import asyncio

import pytest
from aiohttp.test_utils import TestClient, TestServer
from sqlalchemy import func, select

from bot.config import cfg
from bot.db import HOLD, App, Bank, DealEvent, Offer, PbLog, Session, User, init_db
from bot.logic import subid
from bot.web import make_web

SECRET = cfg.pb_secret


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
    """make_web(None): обработчик постбэка обязан работать без Telegram-бота."""

    async def build():
        return TestClient(TestServer(make_web(None)))

    c = loop.run_until_complete(build())
    loop.run_until_complete(c.start_server())
    yield c
    loop.run_until_complete(c.close())


def _get(loop, client, **params):
    return loop.run_until_complete(client.get("/postback", params=params))


def _post_form(loop, client, data):
    return loop.run_until_complete(client.post("/postback", data=data))


def _post_json(loop, client, data):
    return loop.run_until_complete(client.post("/postback", json=data))


def _json(loop, resp):
    return loop.run_until_complete(resp.json())


def _missing_aid(loop):
    """Id, которого заведомо нет в БД (с запасом выше максимума)."""

    async def mx():
        async with Session() as s:
            return (await s.execute(select(func.max(App.id)))).scalar() or 0

    return loop.run_until_complete(mx()) + 1_000_000


def test_wrong_secret_returns_403(loop, client):
    resp = _get(loop, client, secret=SECRET + "x", subid=subid(1), status="approved", payout="100")
    assert resp.status == 403
    assert _json(loop, resp) == {"ok": False, "err": "auth"}


def test_missing_secret_returns_403(loop, client):
    resp = _get(loop, client, subid=subid(1), status="approved")
    assert resp.status == 403
    assert _json(loop, resp) == {"ok": False, "err": "auth"}


@pytest.mark.parametrize("broken", ["broken-subid", "a1-deadbeef", ""])
def test_broken_subid_returns_subid_error(loop, client, broken):
    resp = _get(loop, client, secret=SECRET, subid=broken, status="approved", payout="100")
    assert resp.status == 200
    body = _json(loop, resp)
    assert body["ok"] is False
    assert body["err"] == "subid"


def test_valid_subid_for_missing_deal_returns_app_error(loop, client):
    sid = subid(_missing_aid(loop))
    resp = _get(loop, client, secret=SECRET, subid=sid, status="approved", payout="100")
    assert resp.status == 200
    body = _json(loop, resp)
    assert body["ok"] is False
    assert body["err"] == "app"


def test_get_and_post_variants_reach_same_logic(loop, client):
    sid = subid(_missing_aid(loop))
    payload = {"secret": SECRET, "subid": sid, "status": "approved", "payout": "100"}

    get_body = _json(loop, _get(loop, client, **payload))
    form_body = _json(loop, _post_form(loop, client, payload))
    json_body = _json(loop, _post_json(loop, client, payload))

    expected = {"ok": False, "err": "app"}
    assert get_body == form_body == json_body == expected

    # Битый subid через оба POST-формата тоже уходит в ту же ветку валидации.
    bad = {"secret": SECRET, "subid": "broken-subid", "status": "approved"}
    assert _json(loop, _post_form(loop, client, bad))["err"] == "subid"
    assert _json(loop, _post_json(loop, client, bad))["err"] == "subid"


def test_post_variants_require_secret(loop, client):
    data = {"secret": "wrong", "subid": subid(1), "status": "approved"}
    for resp in (_post_form(loop, client, data), _post_json(loop, client, data)):
        assert resp.status == 403
        assert _json(loop, resp) == {"ok": False, "err": "auth"}


def test_sub1_is_alias_of_subid(loop, client):
    aid = _missing_aid(loop)
    by_sub1 = _get(loop, client, secret=SECRET, sub1=subid(aid), status="approved", payout="100")
    by_subid = _get(loop, client, secret=SECRET, subid=subid(aid), status="approved", payout="100")

    assert by_sub1.status == 200
    # Если бы sub1 не читался, ниже был бы err == "subid".
    assert _json(loop, by_sub1) == _json(loop, by_subid) == {"ok": False, "err": "app"}

    broken = _json(loop, _get(loop, client, secret=SECRET, sub1="broken-subid", status="approved"))
    assert broken["err"] == "subid"


@pytest.fixture(scope="module")
def deal(loop, client):
    """Сделка в статусе new с валидным subid — для ветки успеха и идемпотентности."""
    tag = uuid4().hex[:8]

    async def create():
        async with Session() as s:
            uid = 9_700_000_001
            bank = Bank(slug=f"pb-test-bank-{tag}", name="PB Test Bank")
            s.add(bank)
            await s.flush()
            offer = Offer(bank_id=bank.id, code=f"pb-test-offer-{tag}", name="PB Test Offer", hold=7, pct=10)
            s.add(offer)
            await s.flush()
            s.add(User(id=uid, name="PB tester", balance=0))
            app = App(user_id=uid, offer_id=offer.id, status="new", payout=0,
                      offer_snapshot={"hold_days": 7, "reward": 500}, verification={})
            s.add(app)
            await s.flush()
            app.subid = subid(app.id)
            await s.commit()
            return {"aid": app.id, "uid": uid, "sid": app.subid}

    data = loop.run_until_complete(create())
    yield data

    async def cleanup():
        async with Session() as s:
            for row in (await s.execute(select(App).where(App.user_id == data["uid"]))).scalars().all():
                for ev in (await s.execute(select(DealEvent).where(DealEvent.app_id == row.id))).scalars().all():
                    await s.delete(ev)
                await s.delete(row)
            for log in (await s.execute(select(PbLog).where(PbLog.subid == data["sid"]))).scalars().all():
                await s.delete(log)
            await s.execute(User.__table__.delete().where(User.id == data["uid"]))
            await s.commit()

    loop.run_until_complete(cleanup())


def test_approved_postback_success_path_without_bot(loop, client, deal):
    # sub1 (алиас) + статус approved: сделка уходит в холд, notify(None, ...) не падает.
    resp = _post_form(loop, client, {"secret": SECRET, "sub1": deal["sid"], "status": "approved", "payout": "1000"})
    assert resp.status == 200
    assert _json(loop, resp) == {"ok": True, "app": deal["aid"]}

    async def state():
        async with Session() as s:
            app = await s.get(App, deal["aid"])
            events = (await s.execute(select(func.count()).select_from(DealEvent).where(DealEvent.app_id == app.id))).scalar()
            return app.status, app.payout, app.hold_until, events

    status, payout, hold_until, events = loop.run_until_complete(state())
    assert status == HOLD
    assert payout == 1000
    assert hold_until is not None
    assert events == 1


def test_repeated_postback_is_deterministic_and_keeps_single_deal(loop, client, deal):
    body = {"secret": SECRET, "subid": deal["sid"], "status": "approved", "payout": "1000"}
    first = _post_json(loop, client, body)
    second = _post_json(loop, client, body)
    assert first.status == second.status == 200
    assert _json(loop, first) == _json(loop, second) == {"ok": True, "app": deal["aid"]}

    async def state():
        async with Session() as s:
            apps = (await s.execute(select(App).where(App.user_id == deal["uid"]))).scalars().all()
            events = (await s.execute(
                select(func.count()).select_from(DealEvent).where(DealEvent.app_id == deal["aid"])
            )).scalar()
            return apps, events

    apps, events = loop.run_until_complete(state())
    assert len(apps) == 1  # вторая сделка не создана
    assert apps[0].status == HOLD
    assert events == 1  # повторный постбэк не переобработал сделку
