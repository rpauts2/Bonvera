"""Штамп сборки: /health и обзор админки показывают актуальный коммит.

Без него нельзя отличить свежий деплой от старой закэшированной страницы —
именно эта неопределённость и была проблемой.
"""
import time

from bot.version import build_info
from test_tma_api import client, db, get_json, loop, sign_login_widget  # noqa: F401


def test_build_info_shape():
    info = build_info()
    assert set(info) == {"commit", "built_at"}
    assert isinstance(info["commit"], str) and info["commit"]
    assert info["built_at"] is None or "T" in info["built_at"]


def test_health_reports_build(loop, client):
    resp = loop.run_until_complete(client.get("/health"))
    assert resp.status == 200
    body = loop.run_until_complete(resp.json())
    assert body["build"] == build_info()
    assert body["build"]["commit"]


def test_admin_overview_reports_build(loop, client, monkeypatch, tmp_path):
    from bot.config import cfg as app_cfg

    monkeypatch.setattr(app_cfg, "admins", [919993])
    monkeypatch.setattr("bot.tma_files.PROOF_DIR", tmp_path / "proofs")
    payload = sign_login_widget(
        {"id": 919993, "first_name": "Admin", "auth_date": int(time.time())}
    )
    resp = loop.run_until_complete(client.post("/api/v1/auth/telegram-widget", json=payload))
    assert resp.status == 200, loop.run_until_complete(resp.text())
    token = loop.run_until_complete(resp.json())["data"]["token"]
    status, body = get_json(loop, client, "/api/v1/admin/overview", token)
    assert status == 200
    assert body["data"]["build"]["commit"] == build_info()["commit"]
