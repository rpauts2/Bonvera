import asyncio
from types import SimpleNamespace

from bot.config import cfg
from bot.vk.callback import handle_vk_callback


class FakeRequest:
    def __init__(self, payload):
        self.payload = payload

    async def json(self):
        return self.payload


def base_payload(**overrides):
    payload = {
        "type": "confirmation",
        "group_id": 12345,
        "secret": "vk-callback-secret",
    }
    payload.update(overrides)
    return payload


def test_vk_callback_returns_confirmation_string(monkeypatch):
    monkeypatch.setattr(cfg, "vk_enabled", True)
    monkeypatch.setattr(cfg, "vk_group_id", 12345)
    monkeypatch.setattr(cfg, "vk_callback_secret", "vk-callback-secret")
    monkeypatch.setattr(cfg, "vk_confirmation", "vk-confirm-me")
    response = asyncio.run(handle_vk_callback(FakeRequest(base_payload())))
    assert response.status == 200
    assert response.text == "vk-confirm-me"


def test_vk_callback_rejects_wrong_secret(monkeypatch):
    monkeypatch.setattr(cfg, "vk_enabled", True)
    monkeypatch.setattr(cfg, "vk_group_id", 12345)
    monkeypatch.setattr(cfg, "vk_callback_secret", "vk-callback-secret")
    response = asyncio.run(handle_vk_callback(FakeRequest(base_payload(secret="wrong"))))
    assert response.status == 403


def test_vk_callback_rejects_wrong_group_id(monkeypatch):
    monkeypatch.setattr(cfg, "vk_enabled", True)
    monkeypatch.setattr(cfg, "vk_group_id", 12345)
    monkeypatch.setattr(cfg, "vk_callback_secret", "vk-callback-secret")
    response = asyncio.run(handle_vk_callback(FakeRequest(base_payload(group_id=99999))))
    assert response.status == 403


def test_vk_message_event_dispatches_only_after_callback_validation(monkeypatch):
    from bot.vk import callback

    async def claim(event_id, event_type):
        return True

    async def finish(event_id, *, success, error_code=""):
        return None

    monkeypatch.setattr(callback, "claim_callback_event", claim)
    monkeypatch.setattr(callback, "finish_callback_event", finish)
    monkeypatch.setattr(cfg, "vk_enabled", True)
    monkeypatch.setattr(cfg, "vk_group_id", 12345)
    monkeypatch.setattr(cfg, "vk_callback_secret", "vk-callback-secret")
    calls = []

    async def handler(message, event_id):
        calls.append((message, event_id))

    payload = base_payload(
        type="message_new",
        event_id="event-123",
        object={"message": {"from_id": 777, "text": "Начать"}},
    )
    response = asyncio.run(handle_vk_callback(FakeRequest(payload), message_handler=handler))
    assert response.status == 200
    assert response.text == "ok"
    assert calls == [({"from_id": 777, "text": "Начать"}, "event-123")]


def test_vk_callback_is_disabled_by_default(monkeypatch):
    monkeypatch.setattr(cfg, "vk_enabled", False)
    response = asyncio.run(handle_vk_callback(FakeRequest(base_payload())))
    assert response.status == 503
