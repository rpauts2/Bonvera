"""Заголовки безопасности и кэширования, редирект корня на /app.

headers_middleware обязан покрывать все ответы: SPA, статику, ранние ошибки
API (401/429) и редирект. HSTS ставится только за HTTPS-прокси (Caddy).
X-Frame-Options/CSP frame-ancestors не ставятся — Telegram Web открывает
Mini App в iframe.
"""
from types import SimpleNamespace

from aiohttp import web

from bot.tma_api import _apply_response_headers
from test_tma_api import BotStub, _reset_limiters, client, db, loop  # noqa: F401


def _get(loop, client, path, headers=None, allow_redirects=True):
    return loop.run_until_complete(
        client.get(path, headers=headers or {}, allow_redirects=allow_redirects)
    )


def test_root_redirects_to_app(loop, client):
    resp = _get(loop, client, "/", allow_redirects=False)
    assert resp.status == 302
    assert resp.headers["Location"] == "/app"
    assert resp.headers["X-Content-Type-Options"] == "nosniff"


def test_spa_index_no_cache_and_security_headers(loop, client):
    resp = _get(loop, client, "/app")
    # dist может быть не собран в тестовой среде → 503, но заголовки обязаны быть
    assert resp.status in (200, 503)
    assert resp.headers["Cache-Control"] == "no-cache"
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"


def test_offer_image_is_cacheable(loop, client):
    resp = _get(loop, client, "/assets/offers/bk/pari.jpg")
    assert resp.status == 200
    assert resp.headers["Cache-Control"] == "public, max-age=86400"
    assert resp.headers["X-Content-Type-Options"] == "nosniff"


def test_unauthorized_api_response_is_no_store(loop, client):
    resp = _get(loop, client, "/api/v1/meta")
    assert resp.status == 401
    assert resp.headers["Cache-Control"] == "private, no-store"
    assert resp.headers["X-Content-Type-Options"] == "nosniff"


def test_hsts_only_behind_https_proxy(loop, client):
    plain = _get(loop, client, "/app")
    assert "Strict-Transport-Security" not in plain.headers
    secure = _get(loop, client, "/app", headers={"X-Forwarded-Proto": "https"})
    assert secure.headers["Strict-Transport-Security"] == "max-age=31536000; includeSubDomains"


def test_hashed_assets_are_immutable():
    # unit: ветка /app/assets не зависит от наличия собранного dist в тестовой среде
    req = SimpleNamespace(path="/app/assets/index-ABC123.js", headers={}, scheme="http")
    resp = web.Response(body=b"console.log(1)")
    _apply_response_headers(req, resp)
    assert resp.headers["Cache-Control"] == "public, max-age=31536000, immutable"
    assert resp.headers["X-Content-Type-Options"] == "nosniff"


def test_existing_cache_control_is_not_overridden():
    req = SimpleNamespace(path="/api/v1/apps/1/proofs/0/file", headers={}, scheme="http")
    resp = web.Response(body=b"x")
    resp.headers["Cache-Control"] = "private, no-store"
    _apply_response_headers(req, resp)
    assert resp.headers["Cache-Control"] == "private, no-store"