from sqlalchemy.dialects import sqlite

from bot import admin
from bot.config import cfg
from bot.db import User


def test_broadcast_keyboard_opens_configured_mini_app(monkeypatch):
    monkeypatch.setattr(cfg, "webapp_url", "https://bonvera.example/app")
    keyboard = admin.broadcast_keyboard()
    assert keyboard is not None
    button = keyboard.inline_keyboard[0][0]
    assert button.text == "📱 Перейти в Bonvera"
    assert button.web_app.url == "https://bonvera.example/app"


def test_broadcast_keyboard_is_not_created_without_mini_app_url(monkeypatch):
    monkeypatch.setattr(cfg, "webapp_url", "")
    assert admin.broadcast_keyboard() is None


def test_broadcast_audience_query_targets_only_non_banned_users():
    all_users = str(admin.broadcast_audience_query("all").compile(
        dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True}
    ))
    accepted = str(admin.broadcast_audience_query("accepted").compile(
        dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True}
    ))
    assert "users.banned = 0" in all_users
    assert "users.accepted = 1" not in all_users
    assert "users.banned = 0" in accepted
    assert "users.accepted = 1" in accepted
