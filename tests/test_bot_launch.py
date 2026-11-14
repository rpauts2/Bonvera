"""Stage G: Mini App launch path. The /start button must be an INLINE web_app
button (Telegram signs initData for it); a reply-keyboard web_app button would
open the app with empty initData and break server-side auth.
"""
import pytest
from aiogram.types import InlineKeyboardMarkup

from bot.config import cfg
from bot.user import send_webapp_button
from test_tma_api import loop  # noqa: F401


class FakeMessage:
    def __init__(self):
        self.answers = []

    async def answer(self, text, **kw):
        self.answers.append((text, kw))


def test_webapp_button_is_inline_and_signed_path(loop, monkeypatch):
    monkeypatch.setattr(cfg, "webapp_url", "https://bonvera.example.com/app")
    m = FakeMessage()
    loop.run_until_complete(send_webapp_button(m))
    assert len(m.answers) == 1
    kb = m.answers[0][1]["reply_markup"]
    assert isinstance(kb, InlineKeyboardMarkup)  # inline, NOT reply keyboard
    button = kb.inline_keyboard[0][0]
    assert button.web_app is not None
    assert button.web_app.url == "https://bonvera.example.com/app"
    assert button.url is None and button.callback_data is None


def test_webapp_button_hidden_when_unconfigured(loop, monkeypatch):
    monkeypatch.setattr(cfg, "webapp_url", "")
    m = FakeMessage()
    loop.run_until_complete(send_webapp_button(m))
    assert m.answers == []