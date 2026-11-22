"""Small, credential-safe VK Community API client."""
from __future__ import annotations

import asyncio
import json
from typing import Any, Awaitable, Callable

import aiohttp

from bot.config import cfg


class VKAPIError(RuntimeError):
    """Sanitized VK/network failure; never includes request credentials."""

    RETRYABLE_CODES = {6, 9, 10, 29}

    def __init__(self, code: int | None, message: str, *, retryable: bool = False):
        self.code = code
        self.retryable = retryable
        suffix = f" (VK error {code})" if code is not None else ""
        super().__init__(f"{message}{suffix}")


Requester = Callable[[str, dict[str, Any], int], Awaitable[dict[str, Any]]]


async def _aiohttp_request(
    url: str,
    data: dict[str, Any],
    timeout: int,
) -> dict[str, Any]:
    client_timeout = aiohttp.ClientTimeout(total=timeout)
    try:
        async with aiohttp.ClientSession(timeout=client_timeout) as session:
            async with session.post(url, data=data) as response:
                payload = await response.json(content_type=None)
                if not isinstance(payload, dict):
                    raise VKAPIError(None, "VK returned an invalid response")
                if response.status >= 500:
                    raise VKAPIError(None, "VK service is temporarily unavailable", retryable=True)
                return payload
    except VKAPIError:
        raise
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
        raise VKAPIError(None, "VK API request failed", retryable=True) from None


class VKClient:
    """VK methods used by Bonvera's community bot and outreach worker."""

    API_BASE = "https://api.vk.com/method/"

    def __init__(
        self,
        *,
        group_id: int | None = None,
        group_token: str | None = None,
        api_version: str | None = None,
        timeout: int | None = None,
        requester: Requester | None = None,
    ):
        self.group_id = int(cfg.vk_group_id if group_id is None else group_id)
        self.group_token = cfg.vk_group_token if group_token is None else group_token
        self.api_version = api_version or cfg.vk_api_version
        self.timeout = int(cfg.vk_api_timeout_s if timeout is None else timeout)
        self.requester = requester or _aiohttp_request

        if self.timeout < 1 or self.timeout > 60:
            raise ValueError("VK API timeout must be between 1 and 60 seconds")
        if not self.api_version.strip():
            raise ValueError("VK API version cannot be empty")

    async def call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        if not method or "/" in method or method.startswith("."):
            raise ValueError("Invalid VK API method")
        if not self.group_token:
            raise VKAPIError(None, "VK community token is not configured")
        payload = dict(params or {})
        payload["access_token"] = self.group_token
        payload["v"] = self.api_version
        response = await self.requester(
            f"{self.API_BASE}{method}",
            payload,
            self.timeout,
        )
        if not isinstance(response, dict):
            raise VKAPIError(None, "VK returned an invalid response")
        error = response.get("error")
        if isinstance(error, dict):
            try:
                code = int(error.get("error_code"))
            except (TypeError, ValueError):
                code = None
            raise VKAPIError(
                code,
                "VK API rejected the request",
                retryable=code in self.RETRYABLE_CODES,
            )
        if "response" not in response:
            raise VKAPIError(None, "VK response did not contain a result")
        return response["response"]

    async def is_messages_allowed(self, user_id: int) -> bool:
        if user_id <= 0:
            return False
        if self.group_id <= 0:
            raise VKAPIError(None, "VK community ID is not configured")
        result = await self.call(
            "messages.isMessagesFromGroupAllowed",
            {"group_id": self.group_id, "user_id": int(user_id)},
        )
        if not isinstance(result, dict):
            return False
        try:
            return int(result.get("is_allowed", 0)) == 1
        except (TypeError, ValueError):
            return False

    async def send_message(
        self,
        user_id: int,
        text: str,
        keyboard: dict[str, Any] | None = None,
        random_id: int = 0,
    ) -> dict[str, Any]:
        if user_id <= 0:
            raise ValueError("VK user ID must be positive")
        if not isinstance(text, str) or not text.strip() or len(text) > 4096:
            raise ValueError("VK message text must contain 1..4096 characters")
        if random_id < 0:
            raise ValueError("VK random_id cannot be negative")
        params: dict[str, Any] = {
            "peer_id": int(user_id),
            "message": text.strip(),
            "random_id": int(random_id),
        }
        if keyboard is not None:
            params["keyboard"] = json.dumps(
                keyboard,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        result = await self.call("messages.send", params)
        if isinstance(result, int):
            return {"message_id": result}
        if isinstance(result, dict):
            return result
        raise VKAPIError(None, "VK send message returned an invalid result")
