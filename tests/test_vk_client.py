import asyncio

from bot.vk.client import VKAPIError, VKClient


def test_vk_client_uses_configured_version_and_group_token():
    captured = {}

    async def requester(url, data, timeout):
        captured.update(url=url, data=dict(data), timeout=timeout)
        return {"response": {"is_allowed": 1}}

    client = VKClient(
        group_id=555001,
        group_token="vk-test-token",
        api_version="5.199",
        timeout=7,
        requester=requester,
    )
    assert asyncio.run(client.is_messages_allowed(987654321)) is True
    assert captured["url"] == "https://api.vk.com/method/messages.isMessagesFromGroupAllowed"
    assert captured["data"]["access_token"] == "vk-test-token"
    assert captured["data"]["v"] == "5.199"
    assert captured["data"]["group_id"] == 555001
    assert captured["data"]["user_id"] == 987654321
    assert captured["timeout"] == 7


def test_vk_permission_check_returns_false_when_permission_is_denied():
    async def requester(url, data, timeout):
        return {"response": {"is_allowed": 0}}

    client = VKClient(group_token="token", requester=requester)
    assert asyncio.run(client.is_messages_allowed(123)) is False


@pytest.mark.asyncio
async def test_vk_send_uses_stable_random_id_and_serialized_keyboard():
    import json

    captured = {}

    async def requester(url, data, timeout):
        captured.update(data=dict(data))
        return {"response": {"message_id": 4321}}

    client = VKClient(group_token="token", requester=requester)
    keyboard = {"one_time": False, "buttons": []}
    response = asyncio.run(client.send_message(
        user_id=123,
        text="Проверка",
        keyboard=keyboard,
        random_id=991122,
    ))
    assert response["message_id"] == 4321
    assert captured["data"]["random_id"] == 991122
    assert json.loads(captured["data"]["keyboard"]) == keyboard
    assert captured["data"]["peer_id"] == 123


@pytest.mark.asyncio
async def test_vk_api_error_does_not_leak_access_token():
    async def requester(url, data, timeout):
        return {
            "error": {
                "error_code": 5,
                "error_msg": "User authorization failed",
            }
        }

    client = VKClient(group_token="secret-token", requester=requester)
    try:
        asyncio.run(client.send_message(123, "hello", random_id=1))
    except VKAPIError as exc:
        assert exc.code == 5
        assert "secret-token" not in str(exc)
        assert exc.retryable is False
    else:
        raise AssertionError("VK API errors must be raised")
