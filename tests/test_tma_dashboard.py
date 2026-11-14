"""Contract tests for the home screen (GET /api/v1/dashboard).

Regression guard for the design review finding: the dashboard filtered the
catalog with `available_only=True`, so 87 of 93 offers (all without a verified
partner link yet) disappeared from the main screen and it looked broken while
`/api/v1/offers` returned the full catalog.

The main screen now shows popular offers regardless of availability — the honest
badge ("Нет ссылки", "Скоро") lives on the card itself. These tests pin that
contract together with the new payload fields (ref_link, channel_url,
recent_events) that the redesigned Home page renders.
"""
import pytest
from sqlalchemy import select

from bot import services
from bot.config import cfg
from bot.db import Bank, Offer, Session, Tier
from test_tma_api import (  # noqa: F401  (fixtures reused per-module)
    BotStub, _reset_limiters, client, db, get_json, login, loop, post_json, put_json,
)


@pytest.fixture(scope="module")
def dashboard_offers(loop, db):  # noqa: F811
    """Two offers: one with a partner link, one without."""

    async def seed():
        async with Session() as s:
            if (await s.execute(select(Offer).where(Offer.code == "dsh_ok"))).scalar_one_or_none():
                return
            bank = Bank(slug="dshbank", name="Dashboard Bank", category="cards")
            s.add(bank)
            await s.flush()
            with_link = Offer(
                bank_id=bank.id, code="dsh_ok", name="Оффер со ссылкой", enabled=True,
                url="https://partner.example/dsh_ok", slots=50,
            )
            without_link = Offer(
                bank_id=bank.id, code="dsh_nolink", name="Оффер без ссылки", enabled=True,
                url="", slots=50,
            )
            s.add_all([with_link, without_link])
            await s.flush()
            s.add(Tier(offer_id=with_link.id, payout=1000, cashback=700))
            s.add(Tier(offer_id=without_link.id, payout=1000, cashback=900))
            await s.commit()

    loop.run_until_complete(seed())
    yield


def test_dashboard_does_not_filter_offers_by_availability(loop, client, dashboard_offers, monkeypatch):
    """The catalog must not be narrowed to `available_only` for the home screen."""
    calls: dict = {}
    original = services.list_offers

    async def spy(s, uid, **kwargs):
        calls.update(kwargs)
        return await original(s, uid, **kwargs)

    monkeypatch.setattr(services, "list_offers", spy)

    token, _ = login(loop, client, 930001)
    status, body = get_json(loop, client, "/api/v1/dashboard", token)

    assert status == 200
    assert calls.get("available_only") is not True, "главная фильтрует каталог по доступности"
    assert body["data"]["popular_offers"], "популярные предложения не должны быть пустыми"


def test_dashboard_shows_offers_without_a_partner_link(loop, client, monkeypatch):
    """An offer without a link still appears — with an honest reason, not hidden."""
    async def fake_list_offers(s, uid, **kwargs):
        return [
            {
                "id": 1, "code": "dsh_nolink", "name": "Оффер без ссылки", "brand": "B",
                "brand_slug": "b", "emoji": "💳", "category": "cards", "reward": 900,
                "condition": "c", "hold_days": 14, "purchase_min": 0, "age_min": 18,
                "age_max": 65, "image_url": "/x.jpg", "enabled": True,
                "has_partner_link": False, "network_status": "approved", "available": False,
                "unavailable_reason": "Партнёрская ссылка ещё не добавлена.",
            },
            {
                "id": 2, "code": "dsh_ok", "name": "Оффер со ссылкой", "brand": "B",
                "brand_slug": "b", "emoji": "💳", "category": "cards", "reward": 500,
                "condition": "c", "hold_days": 14, "purchase_min": 0, "age_min": 18,
                "age_max": 65, "image_url": "/x.jpg", "enabled": True,
                "has_partner_link": True, "network_status": "approved", "available": True,
                "unavailable_reason": None,
            },
        ]

    monkeypatch.setattr(services, "list_offers", fake_list_offers)

    token, _ = login(loop, client, 930002)
    status, body = get_json(loop, client, "/api/v1/dashboard", token)

    assert status == 200
    popular = body["data"]["popular_offers"]
    codes = [o["code"] for o in popular]
    assert "dsh_nolink" in codes, "оффер без ссылки обязан быть виден на главной"
    # доступные идут первыми, недоступные — следом
    assert codes.index("dsh_ok") < codes.index("dsh_nolink")
    nolink = next(o for o in popular if o["code"] == "dsh_nolink")
    assert nolink["available"] is False
    assert nolink["unavailable_reason"], "у недоступного оффера должна быть честная причина"


def test_dashboard_carries_the_new_home_payload(loop, client, dashboard_offers):
    token, _ = login(loop, client, 930003)
    status, body = get_json(loop, client, "/api/v1/dashboard", token)

    assert status == 200
    d = body["data"]
    assert d["ref_link"], "главной нужна персональная реферальная ссылка"
    assert d["ref_link"].startswith("https://t.me/bonvera_test_bot?start=ref_")
    assert "channel_url" in d, "главной нужен канал (может быть None)"
    assert d["channel_url"] is None  # BONVERA_CHANNEL_URL пуст в тестовом окружении
    assert isinstance(d["recent_events"], list)
    for event in d["recent_events"]:
        assert {"id", "kind", "title", "text", "created"} <= set(event)


def test_dashboard_reports_the_configured_channel(loop, client, dashboard_offers, monkeypatch):
    monkeypatch.setattr(cfg, "channel_url", "https://t.me/bonvera_channel")

    token, _ = login(loop, client, 930004)
    status, body = get_json(loop, client, "/api/v1/dashboard", token)

    assert status == 200
    assert body["data"]["channel_url"] == "https://t.me/bonvera_channel"


def test_friends_share_link_mentions_the_service(loop, client):
    token, _ = login(loop, client, 930005)
    status, body = get_json(loop, client, "/api/v1/friends", token)

    assert status == 200
    share = body["data"]["share_link"]
    assert "BONVERA" in share, "текст шеринга должен называть сервис"
    assert "t.me/bonvera_test_bot?start=ref_" in share
