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
from sqlalchemy import delete, select

from bot.config import cfg
from bot.db import AdminAuditEvent, App, Bank, BroadcastCampaign, DealEvent, Offer, OfferEvent, PayoutEvent, PayoutReq, Session, Tier, TmaSession, User, WalletEntry, init_db
from bot.tma_auth import create_session, session_user_id, token_hash
from bot.tma_api import api_limiter, auth_limiter, channel_limiter
from bot.web import make_web
from conftest import sign_init_data


class BotStub:
    chat_member_status = "member"
    chat_member_error = False

    async def get_me(self):
        return SimpleNamespace(username="bonvera_test_bot")

    async def send_message(self, chat_id, *args, **kwargs):
        return SimpleNamespace(message_id=777, chat=SimpleNamespace(id=chat_id))

    async def copy_message(self, *args, **kwargs):
        return None

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

def sign_login_widget(payload, token=None):
    import hashlib, hmac
    from bot.config import cfg as app_cfg
    values = {k: str(v) for k, v in payload.items()}
    check = "\n".join(f"{k}={values[k]}" for k in sorted(values))
    secret = hashlib.sha256((token or app_cfg.token).encode()).digest()
    values["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return values

def test_admin_widget_login_only_allows_configured_admin(loop, client, monkeypatch, tmp_path):
    from bot.config import cfg as app_cfg
    from bot.tma_api import _BOT_USERNAME
    monkeypatch.setattr(app_cfg, "admins", [919991])
    monkeypatch.setattr("bot.tma_api._BOT_USERNAME", None)
    monkeypatch.setattr("bot.tma_files.PROOF_DIR", tmp_path / "proofs")
    redirect = loop.run_until_complete(client.get("/admin", allow_redirects=False))
    assert redirect.status == 302 and redirect.headers["Location"] == "/app/admin/login"
    status, body = get_json(loop, client, "/api/v1/admin/login-config")
    assert status == 200 and body["data"]["bot_username"] == "bonvera_test_bot"
    payload = sign_login_widget({"id": 919992, "first_name": "Not Admin", "auth_date": int(time.time())})
    resp = loop.run_until_complete(client.post("/api/v1/auth/telegram-widget", json=payload))
    assert resp.status == 403
    payload = sign_login_widget({"id": 919991, "first_name": "Admin", "auth_date": int(time.time())})
    resp = loop.run_until_complete(client.post("/api/v1/auth/telegram-widget", json=payload))
    assert resp.status == 200, loop.run_until_complete(resp.text())
    result = loop.run_until_complete(resp.json())["data"]
    assert result["token"]
    monkeypatch.setattr(app_cfg, "webapp_url", "https://bonvera.example/app")
    preview = loop.run_until_complete(client.post("/api/v1/admin/broadcasts/preview", json={"text":"Тестовая новость","audience":"accepted"}, headers={"Authorization": f"Bearer {result['token']}"}))
    assert preview.status == 200 and isinstance(loop.run_until_complete(preview.json())["data"]["recipient_count"], int)
    preview_count = loop.run_until_complete(preview.json())["data"]["recipient_count"]
    sent = loop.run_until_complete(client.post("/api/v1/admin/broadcasts/send", json={"text":"Тестовая новость","audience":"accepted","expected_count":preview_count}, headers={"Authorization": f"Bearer {result['token']}"}))
    assert sent.status == 202
    campaign_id = loop.run_until_complete(sent.json())["data"]["id"]
    from bot.tma_api import BROADCAST_TASKS
    task = BROADCAST_TASKS.get(campaign_id)
    if task is not None:
        loop.run_until_complete(task)
    status, broadcasts = get_json(loop, client, "/api/v1/admin/section/broadcasts", result["token"])
    campaign = next(row for row in broadcasts["data"]["items"] if row["id"] == campaign_id)
    assert campaign["status"] == "completed"
    status, overview = get_json(loop, client, "/api/v1/admin/overview", result["token"])
    assert status == 200 and "users_total" in overview["data"]
    status, users = get_json(loop, client, "/api/v1/admin/section/users", result["token"])
    assert status == 200 and users["data"]["section"] == "users"
    assert any(row["id"] == 919991 for row in users["data"]["items"])
    status, finance = get_json(loop, client, "/api/v1/admin/section/finance", result["token"])
    assert status == 200 and "wallet_credits" in finance["data"]["items"]
    for section in ("offers", "applications", "payouts", "broadcasts", "audit"):
        section_status, section_body = get_json(loop, client, f"/api/v1/admin/section/{section}", result["token"])
        assert section_status == 200 and section_body["data"]["section"] == section
    status, denied = get_json(loop, client, "/api/v1/admin/section/users")
    assert status == 401 and denied["err"]["code"] == "unauthorized"

    async def seed_admin_controls():
        async with Session() as session:
            bank = Bank(slug="admin-test-bank", name="Test Bank", category="cards")
            bookmaker = Bank(slug="admin-test-bk", name="Test BK", category="bk")
            session.add_all([bank, bookmaker]); await session.flush()
            offer = Offer(bank_id=bank.id, code="admin-test-card", name="Test card", url="https://partner.example/", enabled=False, required_proofs=["Скриншот выполнения"])
            bk_offer = Offer(bank_id=bookmaker.id, code="admin-test-bk", name="Test bookmaker", url="https://partner.example/bk", enabled=False, network_status="approved", approval="Written approval #test")
            user = await session.get(User, 919991)
            if user is None:
                user = User(id=919991, username="admin_test_user", name="Admin test", balance=1000, accepted=True)
                session.add(user)
                await session.flush()
            target_user = await session.get(User, 919993)
            if target_user is None:
                target_user = User(id=919993, username="ban_test_user", name="Ban test", balance=0, accepted=True)
                session.add(target_user)
                await session.flush()
            payout = PayoutReq(user_id=919991, amount=500, phone="", bank="Test", status="pending")
            payout_reject = PayoutReq(user_id=919991, amount=300, phone="", bank="Test", status="pending")
            session.add_all([offer, bk_offer, payout, payout_reject]); await session.flush()
            tier = Tier(offer_id=offer.id, payout=500, cashback=100)
            now = datetime.utcnow().isoformat()
            confirm_app = App(user_id=919991, offer_id=offer.id, subid="web-admin-confirm", status="proof", verification={"proof_submitted_at":now}, offer_snapshot={"reward":100})
            hold_app = App(user_id=919991, offer_id=offer.id, subid="web-admin-hold", status="proof")
            reject_app = App(user_id=919991, offer_id=offer.id, subid="web-admin-reject", status="proof")
            session.add_all([tier, confirm_app, hold_app, reject_app]); await session.flush()
            from bot.tma_files import store_proof
            storage, _ctype = store_proof(confirm_app.id, "evidence.png", b"test-evidence-bytes")
            confirm_app.proof_files = [{"proof_index":0,"storage":storage,"name":"evidence.png","label":"Скриншот выполнения","uploaded_at":now}]
            await session.commit()
            return offer.id, bk_offer.id, payout.id, payout_reject.id, bank.id, bookmaker.id, confirm_app.id, hold_app.id, reject_app.id
    offer_id, bk_offer_id, payout_id, payout_reject_id, bank_id, bookmaker_id, confirm_app_id, hold_app_id, reject_app_id = loop.run_until_complete(seed_admin_controls())
    status, apps_list = get_json(loop, client, "/api/v1/admin/section/applications", result["token"])
    app_row = next(row for row in apps_list["data"]["items"] if row["id"] == confirm_app_id)
    assert app_row["proof_files"][0]["name"] == "evidence.png"
    proof_resp = loop.run_until_complete(client.get(f"/api/v1/admin/applications/{confirm_app_id}/proof/0", headers={"Authorization": f"Bearer {result['token']}"}))
    assert proof_resp.status == 200 and loop.run_until_complete(proof_resp.read()) == b"test-evidence-bytes"

    resp = loop.run_until_complete(client.put(f"/api/v1/admin/offers/{offer_id}/enabled", json={"enabled": True}, headers={"Authorization": f"Bearer {result['token']}"}))
    assert resp.status == 200 and loop.run_until_complete(resp.json())["data"]["enabled"] is True
    resp = loop.run_until_complete(client.put(f"/api/v1/admin/offers/{offer_id}", json={"name":"Updated card name","url":"https://partner.example/new","hold":14,"age_min":21,"age_max":65,"action":"Открыть счёт","rules":"Только новые клиенты","network_payout":750,"user_reward":125}, headers={"Authorization": f"Bearer {result['token']}"}))
    assert resp.status == 200 and loop.run_until_complete(resp.json())["data"]["name"] == "Updated card name"
    assert loop.run_until_complete(resp.json())["data"]["user_reward"] == 125
    resp = loop.run_until_complete(client.put(f"/api/v1/admin/offers/{offer_id}", json={"age_min":80}, headers={"Authorization": f"Bearer {result['token']}"}))
    assert resp.status == 400 and loop.run_until_complete(resp.json())["err"]["code"] == "bad_age_range"
    resp = loop.run_until_complete(client.put(f"/api/v1/admin/offers/{bk_offer_id}", json={"url":"https://partner.example/bk-new"}, headers={"Authorization": f"Bearer {result['token']}"}))
    assert resp.status == 200 and loop.run_until_complete(resp.json())["data"]["approval_reset"] is True
    assert loop.run_until_complete(resp.json())["data"]["enabled"] is False
    resp = loop.run_until_complete(client.put(f"/api/v1/admin/offers/{bk_offer_id}/enabled", json={"enabled": True}, headers={"Authorization": f"Bearer {result['token']}"}))
    assert resp.status == 409 and loop.run_until_complete(resp.json())["err"]["code"] == "bookmaker_not_approved"
    resp = loop.run_until_complete(client.post(f"/api/v1/admin/payouts/{payout_id}/action", json={"action":"take"}, headers={"Authorization": f"Bearer {result['token']}"}))
    assert resp.status == 200 and loop.run_until_complete(resp.json())["data"]["status"] == "processing"
    resp = loop.run_until_complete(client.post(f"/api/v1/admin/payouts/{payout_id}/action", json={"action":"paid"}, headers={"Authorization": f"Bearer {result['token']}"}))
    assert resp.status == 200 and loop.run_until_complete(resp.json())["data"]["status"] == "paid"
    resp = loop.run_until_complete(client.post(f"/api/v1/admin/payouts/{payout_id}/action", json={"action":"paid"}, headers={"Authorization": f"Bearer {result['token']}"}))
    assert resp.status == 409
    resp = loop.run_until_complete(client.post(f"/api/v1/admin/payouts/{payout_reject_id}/action", json={"action":"reject","reason":"Реквизиты не прошли проверку"}, headers={"Authorization": f"Bearer {result['token']}"}))
    assert resp.status == 200 and loop.run_until_complete(resp.json())["data"]["refunded"] == 300
    resp = loop.run_until_complete(client.post(f"/api/v1/admin/payouts/{payout_reject_id}/action", json={"action":"reject","reason":"Повтор"}, headers={"Authorization": f"Bearer {result['token']}"}))
    assert resp.status == 409

    resp = loop.run_until_complete(client.post(f"/api/v1/admin/applications/{confirm_app_id}/action", json={"action":"confirm"}, headers={"Authorization": f"Bearer {result['token']}"}))
    assert resp.status == 200 and loop.run_until_complete(resp.json())["data"]["status"] == "confirmed"
    resp = loop.run_until_complete(client.post(f"/api/v1/admin/applications/{hold_app_id}/action", json={"action":"hold"}, headers={"Authorization": f"Bearer {result['token']}"}))
    assert resp.status == 200 and loop.run_until_complete(resp.json())["data"]["status"] == "hold"
    resp = loop.run_until_complete(client.post(f"/api/v1/admin/applications/{reject_app_id}/action", json={"action":"reject","reason":"Недостаточно подтверждений"}, headers={"Authorization": f"Bearer {result['token']}"}))
    assert resp.status == 200 and loop.run_until_complete(resp.json())["data"]["status"] == "rejected"
    resp = loop.run_until_complete(client.post("/api/v1/admin/users/919991/action", json={"action":"ban"}, headers={"Authorization": f"Bearer {result['token']}"}))
    assert resp.status == 409 and loop.run_until_complete(resp.json())["err"]["code"] == "admin_protected"
    resp = loop.run_until_complete(client.post("/api/v1/admin/users/919993/action", json={"action":"ban"}, headers={"Authorization": f"Bearer {result['token']}"}))
    assert resp.status == 200 and loop.run_until_complete(resp.json())["data"]["banned"] is True
    resp = loop.run_until_complete(client.post("/api/v1/admin/users/919993/action", json={"action":"unban"}, headers={"Authorization": f"Bearer {result['token']}"}))
    assert resp.status == 200 and loop.run_until_complete(resp.json())["data"]["banned"] is False
    status, audit = get_json(loop, client, "/api/v1/admin/section/audit", result["token"])
    assert status == 200 and any(item["action"] == "payout_rejected_refunded" for item in audit["data"]["items"])
    assert any(item["action"] == "ban" for item in audit["data"]["items"])
    assert any(item["action"] == "offer_updated" for item in audit["data"]["items"])
    assert any(item["action"] == "broadcast_started" for item in audit["data"]["items"])

    async def cleanup_admin_controls():
        async with Session() as session:
            await session.execute(delete(BroadcastCampaign).where(BroadcastCampaign.id == campaign_id))
            await session.execute(delete(AdminAuditEvent).where(AdminAuditEvent.actor_id == 919991))
            await session.execute(delete(User).where(User.id == 919993))
            await session.execute(delete(DealEvent).where(DealEvent.app_id.in_([confirm_app_id, hold_app_id, reject_app_id])))
            await session.execute(delete(WalletEntry).where(WalletEntry.ref == f"app:{confirm_app_id}"))
            await session.execute(delete(App).where(App.id.in_([confirm_app_id, hold_app_id, reject_app_id])))
            await session.execute(delete(Tier).where(Tier.offer_id == offer_id))
            await session.execute(delete(PayoutEvent).where(PayoutEvent.payout_id.in_([payout_id, payout_reject_id])))
            await session.execute(delete(WalletEntry).where(WalletEntry.ref == f"withdraw-refund:{payout_reject_id}"))
            await session.execute(delete(PayoutReq).where(PayoutReq.id.in_([payout_id, payout_reject_id])))
            await session.execute(delete(OfferEvent).where(OfferEvent.offer_id.in_([offer_id, bk_offer_id])))
            await session.execute(delete(Offer).where(Offer.id.in_([offer_id, bk_offer_id])))
            await session.execute(delete(Bank).where(Bank.id.in_([bank_id, bookmaker_id])))
            await session.execute(delete(TmaSession).where(TmaSession.user_id == 919991))
            await session.execute(delete(User).where(User.id == 919991))
            await session.commit()
    loop.run_until_complete(cleanup_admin_controls())
