"""Integration tests for the TMA API against a real (temporary sqlite) database.

Covers: HMAC auth end-to-end, session lifecycle, banned users, identity
isolation, profile/age/SBP validation, dashboard/meta/notifications and
rate limiting. No Telegram network calls: the bot is a local stub.
"""
import asyncio
import json
import time
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from aiohttp.test_utils import TestClient, TestServer
from sqlalchemy import select

from bot.config import cfg
from bot.db import Session, TmaSession, User, init_db
from bot.tma_auth import create_session, session_user_id, token_hash
from bot.tma_api import api_limiter, auth_limiter, channel_limiter
from bot.web import make_web
from conftest import sign_init_data


class BotStub:
    chat_member_status = "member"
    chat_member_error = False

    async def get_me(self):
        return SimpleNamespace(username="bonvera_test_bot")

    async def send_message(self, *args, **kwargs):
        pass

    async def get_chat_member(self, chat_id, user_id):
        if self.chat_member_error:
            raise RuntimeError("telegram unavailable")
        return SimpleNamespace(status=self.chat_member_status)


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
    yield


@pytest.fixture(scope="module")
def client(loop, db):
    async def build():
        return TestClient(TestServer(make_web(BotStub())))

    c = loop.run_until_complete(build())
    loop.run_until_complete(c.start_server())
    yield c
    loop.run_until_complete(c.close())


@pytest.fixture(autouse=True)
def _reset_limiters():
    auth_limiter.hits.clear()
    api_limiter.hits.clear()
    channel_limiter.hits.clear()
    yield
    auth_limiter.hits.clear()
    api_limiter.hits.clear()
    channel_limiter.hits.clear()


def init_data_for(tg_id: int, username: str = "testuser", first_name: str = "Test",
                  auth_date: int | None = None, token: str | None = None) -> str:
    fields = {
        "auth_date": str(auth_date if auth_date is not None else int(time.time())),
        "query_id": "AAHdF6IQAAAAAN0XohDhrOrc",
        "user": json.dumps({"id": tg_id, "first_name": first_name, "username": username}, separators=(",", ":")),
    }
    return sign_init_data(fields, token or cfg.token)


def post_auth(loop, client, tg_id, **kw):
    return loop.run_until_complete(
        client.post("/api/v1/auth/telegram", json={"initData": init_data_for(tg_id, **kw)})
    )


def login(loop, client, tg_id, **kw):
    resp = post_auth(loop, client, tg_id, **kw)
    assert resp.status == 200, loop.run_until_complete(resp.text())
    body = loop.run_until_complete(resp.json())
    assert body["ok"] is True
    return body["data"]["token"], body["data"]["user"]


def get_json(loop, client, path, token=None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    resp = loop.run_until_complete(client.get(path, headers=headers))
    return resp.status, loop.run_until_complete(resp.json())


def put_json(loop, client, path, token, payload):
    resp = loop.run_until_complete(
        client.put(path, json=payload, headers={"Authorization": f"Bearer {token}"})
    )
    return resp.status, loop.run_until_complete(resp.json())


def post_json(loop, client, path, token, payload=None):
    resp = loop.run_until_complete(
        client.post(path, json=payload or {}, headers={"Authorization": f"Bearer {token}"})
    )
    return resp.status, loop.run_until_complete(resp.json())


def test_auth_creates_user_and_me(loop, client):
    token, profile = login(loop, client, 910001, username="alice", first_name="Alice")
    assert token and isinstance(profile["id"], int)
    assert profile["id"] == 910001
    assert profile["username"] == "alice"
    assert profile["accepted"] is False
    assert profile["balance"] == 0
    assert profile["level"] == 1

    status, body = get_json(loop, client, "/api/v1/me", token)
    assert status == 200 and body["data"]["id"] == 910001

    status, body = get_json(loop, client, "/api/v1/me")
    assert status == 401 and body["err"]["code"] == "unauthorized"

    status, body = get_json(loop, client, "/api/v1/me", "garbage-token")
    assert status == 401


def test_logout_revokes_server_session(loop, client):
    token, _ = login(loop, client, 910099)
    status, body = post_json(loop, client, "/api/v1/auth/logout", token)
    assert status == 200 and body["data"]["logged_out"] is True
    status, body = get_json(loop, client, "/api/v1/me", token)
    assert status == 401 and body["err"]["code"] == "unauthorized"


def test_auth_rejects_bad_signature(loop, client):
    signed = init_data_for(910002)
    from urllib.parse import parse_qsl, urlencode
    pairs = dict(parse_qsl(signed))
    pairs["user"] = json.dumps({"id": 999999, "first_name": "Evil"})
    resp = loop.run_until_complete(
        client.post("/api/v1/auth/telegram", json={"initData": urlencode(pairs)})
    )
    assert resp.status == 401
    body = loop.run_until_complete(resp.json())
    assert body["err"]["code"] == "bad_signature"


def test_auth_rejects_expired_init_data(loop, client):
    resp = post_auth(loop, client, 910003, auth_date=int(time.time()) - 7200)
    assert resp.status == 401
    assert loop.run_until_complete(resp.json())["err"]["code"] == "expired"


def test_auth_rejects_foreign_bot_token(loop, client):
    resp = post_auth(loop, client, 910004, token="999999:ANOTHER_BOT_TOKEN")
    assert resp.status == 401
    assert loop.run_until_complete(resp.json())["err"]["code"] == "bad_signature"


def test_auth_requires_init_data(loop, client):
    resp = loop.run_until_complete(client.post("/api/v1/auth/telegram", json={}))
    assert resp.status == 400
    assert loop.run_until_complete(resp.json())["err"]["code"] == "no_init_data"


def test_auth_updates_username_without_duplicate_user(loop, client):
    login(loop, client, 910005, username="old_name")
    token, profile = login(loop, client, 910005, username="new_name")
    assert profile["username"] == "new_name"

    async def count():
        async with Session() as s:
            return (await s.execute(select(User).where(User.id == 910005))).scalars().all()

    rows = loop.run_until_complete(count())
    assert len(rows) == 1 and rows[0].username == "new_name"


def test_accept_and_age_validation(loop, client):
    token, _ = login(loop, client, 910006)
    status, body = post_json(loop, client, "/api/v1/me/accept", token)
    assert status == 200
    assert body["data"]["accepted"] is True and body["data"]["adult"] is True

    status, body = put_json(loop, client, "/api/v1/me/age", token, {"years": 17})
    assert status == 400 and body["err"]["code"] == "bad_age"

    status, _ = put_json(loop, client, "/api/v1/me/age", token, {"years": "25"})
    assert status == 400

    status, body = put_json(loop, client, "/api/v1/me/age", token, {"years": 25})
    assert status == 200 and body["data"]["age_years"] == 25


def test_sbp_validation_and_masking(loop, client):
    token, _ = login(loop, client, 910007)

    status, body = put_json(loop, client, "/api/v1/me/sbp", token, {"bank": "Т-Банк", "phone": "123"})
    assert status == 400 and body["err"]["code"] == "bad_phone"

    status, body = put_json(loop, client, "/api/v1/me/sbp", token, {"bank": "X", "phone": "+79991234567"})
    assert status == 400 and body["err"]["code"] == "bad_bank"

    status, body = put_json(loop, client, "/api/v1/me/sbp", token, {"bank": "Т-Банк", "phone": "+79991234567"})
    assert status == 200
    assert body["data"]["sbp_phone_masked"] == "+7 *** ***-4567"
    assert body["data"]["sbp_bank"] == "Т-Банк"

    status, body = put_json(loop, client, "/api/v1/me/sbp", token, {"bank": "Сбербанк", "phone": None})
    assert status == 200
    assert body["data"]["sbp_bank"] == "Сбербанк"
    assert body["data"]["sbp_phone_masked"] == "+7 *** ***-4567"

    async def check_storage():
        async with Session() as s:
            u = await s.get(User, 910007)
            assert u.sbp_phone and "79991234567" not in u.sbp_phone
            assert u.phone_hash and len(u.phone_hash) == 64

    loop.run_until_complete(check_storage())


def test_dashboard_shape(loop, client):
    token, _ = login(loop, client, 910008)
    status, body = get_json(loop, client, "/api/v1/dashboard", token)
    assert status == 200
    d = body["data"]
    assert d["tasks_total"] == 4
    assert d["tasks_done"] == 0
    assert d["confirmed_orders"] == 0
    assert d["ten_progress"] == 0
    assert d["wallet"]["available"] == 0
    assert d["wallet"]["min_withdraw"] == cfg.min_wd
    assert isinstance(d["popular_offers"], list)
    assert d["unread_notifications"] == 0
    assert d["referral"] == {"invited": 0, "qualified": 0, "earned": 0}


def test_meta(loop, client):
    token, _ = login(loop, client, 910009)
    status, body = get_json(loop, client, "/api/v1/meta", token)
    assert status == 200
    m = body["data"]
    assert "Т-Банк" in m["banks"]
    assert m["min_withdraw"] == cfg.min_wd
    assert m["ref_percent"] == cfg.ref_pct
    assert m["bot_username"] == "bonvera_test_bot"


def test_notifications_and_read(loop, client):
    token, _ = login(loop, client, 910010)
    status, body = get_json(loop, client, "/api/v1/notifications", token)
    assert status == 200 and body["data"] == []

    status, body = post_json(loop, client, "/api/v1/notifications/read", token)
    assert status == 200 and body["data"]["read"] is True

    status, body = get_json(loop, client, "/api/v1/dashboard", token)
    assert body["data"]["unread_notifications"] == 0


def test_banned_user_blocked(loop, client):
    token, _ = login(loop, client, 910011)

    async def ban():
        async with Session() as s:
            u = await s.get(User, 910011)
            u.banned = True
            await s.commit()

    loop.run_until_complete(ban())

    status, body = get_json(loop, client, "/api/v1/me", token)
    assert status == 403 and body["err"]["code"] == "banned"

    resp = post_auth(loop, client, 910011)
    assert resp.status == 403
    assert loop.run_until_complete(resp.json())["err"]["code"] == "banned"


def test_identity_isolation(loop, client):
    token_a, _ = login(loop, client, 910012, username="user_a")
    token_b, _ = login(loop, client, 910013, username="user_b")

    status, body = get_json(loop, client, "/api/v1/me", token_a)
    assert body["data"]["id"] == 910012
    status, body = get_json(loop, client, "/api/v1/me", token_b)
    assert body["data"]["id"] == 910013


def test_auth_rate_limit(loop, client):
    for _ in range(20):
        resp = post_auth(loop, client, 910014)
        assert resp.status == 200
    resp = post_auth(loop, client, 910014)
    assert resp.status == 429
    assert loop.run_until_complete(resp.json())["err"]["code"] == "rate_limited"


def test_expired_session_rejected(loop, client):
    token, _ = login(loop, client, 910015)

    async def expire():
        async with Session() as s:
            row = (
                await s.execute(select(TmaSession).where(TmaSession.token_hash == token_hash(token)))
            ).scalar_one()
            row.expires = datetime.utcnow() - timedelta(hours=1)
            await s.commit()

    loop.run_until_complete(expire())
    status, body = get_json(loop, client, "/api/v1/me", token)
    assert status == 401 and body["err"]["code"] == "unauthorized"


def test_session_helpers(loop, db):
    async def scenario():
        async with Session() as s:
            token, expires = await create_session(s, 910016)
            assert expires > datetime.utcnow()
            assert await session_user_id(s, token) == 910016
            assert await session_user_id(s, "unknown-token") is None
            assert await session_user_id(s, "") is None

    loop.run_until_complete(scenario())


def test_health(loop, client):
    resp = loop.run_until_complete(client.get("/health"))
    payload = loop.run_until_complete(resp.json())
    assert resp.status == 200
    assert payload["ok"] is True
    assert payload["db_live"] is True
    assert payload["db"] in ("ok", "unknown")
    assert "telegram" in payload and "web" in payload
    assert "X-Content-Type-Options" in resp.headers


def test_spa_route_responds(loop, client):
    resp = loop.run_until_complete(client.get("/app"))
    assert resp.status in (200, 503)