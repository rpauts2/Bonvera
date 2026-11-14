"""Integration tests for stages D+E: catalog, deals, evidence, wallet, withdrawals.

Runs against the same temporary sqlite database and aiohttp test server as
test_tma_api (fixtures imported from there). Offers are seeded directly.
"""
import io

import pytest
from aiohttp import FormData
from sqlalchemy import select

from bot import logic
from bot.db import App, Bank, Offer, Session, Tier
from test_tma_api import (  # noqa: F401  (fixtures reused per-module)
    BotStub, _reset_limiters, client, db, get_json, login, loop, post_json, put_json,
)


def png_bytes(seed: int) -> bytes:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (64, 64), "white")
    d = ImageDraw.Draw(img)
    for i in range(8):
        x = (seed * 7 + i * 13) % 56
        y = (seed * 3 + i * 17) % 56
        d.rectangle([x, y, x + 8, y + 8], fill=(seed * 30 % 255, i * 25, 128))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture(scope="module")
def offers(loop, db):  # noqa: F811
    async def seed():
        async with Session() as s:
            if (await s.execute(select(Offer).where(Offer.code == "tst_card_a"))).scalar_one_or_none():
                return
            specs = [
                ("tsta", "cards"), ("tstnl", "cards"), ("tstbkp", "bk"), ("tstbko", "bk"),
                ("tstage", "cards"), ("tstslot", "cards"), ("tstmfo", "mfo"), ("tsttwo", "cards"),
            ]
            bank_ids = {}
            for slug, cat in specs:
                b = Bank(slug=slug, name=slug.upper(), category=cat)
                s.add(b)
                await s.flush()
                bank_ids[slug] = b.id

            def mk(code, bank, **kw):
                defaults = dict(bank_id=bank_ids[bank], code=code, name=code, enabled=True,
                                url=f"https://partner.example/{code}", slots=5,
                                required_proofs=["Скриншот активации"], hold=30)
                defaults.update(kw)
                o = Offer(**defaults)
                s.add(o)
                return o

            created = [
                mk("tst_card_a", "tsta", slots=50),
                mk("tst_card_b", "tsta"),
                mk("tst_nolink", "tstnl", url=""),
                mk("tst_bk_pending", "tstbkp", network_status="needs_approval"),
                mk("tst_bk_ok", "tstbko", network_status="approved"),
                mk("tst_aged", "tstage", age_min=21, age_max=75),
                mk("tst_slot1", "tstslot", slots=1),
                mk("tst_mfo", "tstmfo", mfo_info={"psk": "292%", "rate": "0.8%", "term": "30 дней", "registry": "ЦБ РФ"}),
                mk("tst_two", "tsttwo", required_proofs=["Первый скрин", "Второй скрин"]),
            ]
            await s.flush()
            for o in created:
                s.add(Tier(offer_id=o.id, payout=1000, cashback=500))
            await s.commit()

    loop.run_until_complete(seed())
    yield


def oid(loop, code: str) -> int:
    async def q():
        async with Session() as s:
            return (await s.execute(select(Offer.id).where(Offer.code == code))).scalar_one()

    return loop.run_until_complete(q())


def accepted_user(loop, client, tg_id):
    token, _ = login(loop, client, tg_id)
    status, _ = post_json(loop, client, "/api/v1/me/accept", token)
    assert status == 200
    return token


def take(loop, client, token, offer_id):
    return post_json(loop, client, f"/api/v1/offers/{offer_id}/take", token)


def upload(loop, client, token, aid, payloads):
    form = FormData()
    for name, data in payloads:
        form.add_field("files", data, filename=name, content_type="image/png")
    resp = loop.run_until_complete(
        client.post(f"/api/v1/apps/{aid}/proofs", data=form, headers={"Authorization": f"Bearer {token}"})
    )
    return resp.status, loop.run_until_complete(resp.json())


def test_offers_list_and_filters(loop, client, offers):
    token = accepted_user(loop, client, 920001)
    status, body = get_json(loop, client, "/api/v1/offers", token)
    assert status == 200
    codes = {c["code"] for c in body["data"]}
    assert {"tst_card_a", "tst_nolink", "tst_bk_pending", "tst_mfo"} <= codes

    status, body = get_json(loop, client, "/api/v1/offers?category=bk", token)
    assert {c["code"] for c in body["data"]} == {"tst_bk_pending", "tst_bk_ok"}

    status, body = get_json(loop, client, "/api/v1/offers?q=tst_mfo", token)
    assert [c["code"] for c in body["data"]] == ["tst_mfo"]

    status, body = get_json(loop, client, "/api/v1/offers?available=1", token)
    avail = {c["code"] for c in body["data"]}
    assert "tst_nolink" not in avail and "tst_bk_pending" not in avail
    assert "tst_card_a" in avail

    nolink = next(c for c in get_json(loop, client, "/api/v1/offers", token)[1]["data"] if c["code"] == "tst_nolink")
    assert nolink["available"] is False
    assert "ссылка" in nolink["unavailable_reason"].lower()


def test_offer_detail_mfo_info(loop, client, offers):
    token = accepted_user(loop, client, 920002)
    status, body = get_json(loop, client, f"/api/v1/offers/{oid(loop, 'tst_mfo')}", token)
    assert status == 200
    d = body["data"]
    assert d["mfo_info"]["psk"] == "292%"
    assert d["required_proofs"] == ["Скриншот активации"]
    assert d["category"] == "mfo"

    status, _ = get_json(loop, client, "/api/v1/offers/999999", token)
    assert status == 404


def test_take_requires_accept(loop, client, offers):
    token, _ = login(loop, client, 920003)
    status, body = take(loop, client, token, oid(loop, "tst_card_a"))
    assert status == 403 and body["err"]["code"] == "not_accepted"


def test_take_full_flow(loop, client, offers):
    token = accepted_user(loop, client, 920004)
    status, body = take(loop, client, token, oid(loop, "tst_card_a"))
    assert status == 201
    aid = body["data"]["app_id"]

    status, body = get_json(loop, client, "/api/v1/apps", token)
    assert status == 200 and len(body["data"]) == 1
    app = body["data"][0]
    assert app["id"] == aid and app["status"] == "new"
    assert app["personal_link"] and "subid=" in app["personal_link"]
    assert app["image_url"] == ""  # no seeded image asset for test offers

    status, body = get_json(loop, client, f"/api/v1/apps/{aid}", token)
    assert body["data"]["proofs_required"] == ["Скриншот активации"]
    assert body["data"]["can_upload"] is True


def test_take_no_link_blocked(loop, client, offers):
    token = accepted_user(loop, client, 920005)
    status, body = take(loop, client, token, oid(loop, "tst_nolink"))
    assert status == 409 and body["err"]["code"] == "no_link"


def test_take_bk_approval_gate(loop, client, offers):
    token = accepted_user(loop, client, 920006)
    status, body = take(loop, client, token, oid(loop, "tst_bk_pending"))
    assert status == 409 and body["err"]["code"] == "bk_not_approved"
    status, _ = take(loop, client, token, oid(loop, "tst_bk_ok"))
    assert status == 201


def test_take_age_gate(loop, client, offers):
    token = accepted_user(loop, client, 920007)
    aged = oid(loop, "tst_aged")
    status, body = take(loop, client, token, aged)
    assert status == 400 and body["err"]["code"] == "age_required"

    status, _ = put_json(loop, client, "/api/v1/me/age", token, {"years": 25})
    assert status == 200
    status, _ = take(loop, client, token, aged)
    assert status == 201

    other = accepted_user(loop, client, 920008)
    status, _ = put_json(loop, client, "/api/v1/me/age", other, {"years": 80})
    assert status == 200
    status, body = take(loop, client, other, aged)
    assert status == 400 and body["err"]["code"] == "age_mismatch"


def test_take_bank_taken(loop, client, offers):
    token = accepted_user(loop, client, 920009)
    status, _ = take(loop, client, token, oid(loop, "tst_card_a"))
    assert status == 201
    status, body = take(loop, client, token, oid(loop, "tst_card_b"))
    assert status == 409 and body["err"]["code"] == "bank_taken"


def test_take_max_active(loop, client, offers):
    token = accepted_user(loop, client, 920010)
    status, _ = put_json(loop, client, "/api/v1/me/age", token, {"years": 25})
    assert status == 200
    for code in ("tst_card_a", "tst_bk_ok", "tst_mfo"):
        status, _ = take(loop, client, token, oid(loop, code))
        assert status == 201
    status, body = take(loop, client, token, oid(loop, "tst_aged"))
    assert status == 409 and body["err"]["code"] == "max_active"


def test_take_daily_slots(loop, client, offers):
    slot_offer = oid(loop, "tst_slot1")
    t1 = accepted_user(loop, client, 920011)
    status, _ = take(loop, client, t1, slot_offer)
    assert status == 201
    t2 = accepted_user(loop, client, 920012)
    status, body = take(loop, client, t2, slot_offer)
    assert status == 409 and body["err"]["code"] == "no_slots"


def test_apps_ownership_isolation(loop, client, offers):
    ta = accepted_user(loop, client, 920013)
    tb = accepted_user(loop, client, 920014)
    status, body = take(loop, client, ta, oid(loop, "tst_card_a"))
    aid = body["data"]["app_id"]

    status, _ = get_json(loop, client, f"/api/v1/apps/{aid}", tb)
    assert status == 404
    status, body = get_json(loop, client, "/api/v1/apps", tb)
    assert body["data"] == []


def test_proof_upload_dedup_and_stream(loop, client, offers):
    token = accepted_user(loop, client, 920015)
    status, body = take(loop, client, token, oid(loop, "tst_card_a"))
    aid = body["data"]["app_id"]

    first = png_bytes(1)
    status, body = upload(loop, client, token, aid, [("proof.png", first)])
    assert status == 200, body
    app = body["data"]
    assert app["status"] == "proof"
    assert app["proofs_received"] == [0]
    assert app["proofs"][0]["label"] == "Скриншот активации"

    resp = loop.run_until_complete(
        client.get(f"/api/v1/apps/{aid}/proofs/0/file", headers={"Authorization": f"Bearer {token}"})
    )
    assert resp.status == 200
    assert loop.run_until_complete(resp.read()) == first
    assert resp.headers["Cache-Control"] == "private, no-store"

    status, body = upload(loop, client, token, aid, [("copy.png", first)])
    assert status == 409 and body["err"]["code"] == "duplicate_proof"

    status, body = upload(loop, client, token, aid, [("extra.png", png_bytes(2))])
    assert status == 200
    assert body["data"]["proofs"][1]["index"] is None

    status, body = upload(loop, client, token, aid, [("evil.exe", b"MZ\x90\x00")])
    assert status == 400 and body["err"]["code"] == "bad_type"

    other = accepted_user(loop, client, 920016)
    status, _ = upload(loop, client, other, aid, [("x.png", png_bytes(3))])
    assert status == 404
    resp = loop.run_until_complete(
        client.get(f"/api/v1/apps/{aid}/proofs/0/file", headers={"Authorization": f"Bearer {other}"})
    )
    assert resp.status == 404


def test_proof_submit_and_repeat(loop, client, offers):
    token = accepted_user(loop, client, 920017)
    status, body = take(loop, client, token, oid(loop, "tst_card_a"))
    aid = body["data"]["app_id"]

    status, body = post_json(loop, client, f"/api/v1/apps/{aid}/submit", token)
    assert status == 409  # status new, nothing uploaded

    status, _ = upload(loop, client, token, aid, [("proof.png", png_bytes(4))])
    assert status == 200
    status, body = post_json(loop, client, f"/api/v1/apps/{aid}/submit", token)
    assert status == 200
    assert body["data"]["submitted"] is True
    assert body["data"]["can_submit"] is False

    status, body = post_json(loop, client, f"/api/v1/apps/{aid}/submit", token)
    assert status == 409 and body["err"]["code"] == "already_submitted"


def test_submit_incomplete_checklist(loop, client, offers):
    token = accepted_user(loop, client, 920018)
    status, body = take(loop, client, token, oid(loop, "tst_two"))
    aid = body["data"]["app_id"]
    status, _ = upload(loop, client, token, aid, [("one.png", png_bytes(5))])
    assert status == 200
    status, body = post_json(loop, client, f"/api/v1/apps/{aid}/submit", token)
    assert status == 400 and body["err"]["code"] == "incomplete"
    assert "Второй скрин" in body["err"]["message"]


def test_wallet_withdrawal_cancel_cycle(loop, client, offers):
    token = accepted_user(loop, client, 920019)
    status, body = take(loop, client, token, oid(loop, "tst_card_a"))
    aid = body["data"]["app_id"]
    status, _ = upload(loop, client, token, aid, [("proof.png", png_bytes(6))])
    assert status == 200
    status, _ = post_json(loop, client, f"/api/v1/apps/{aid}/submit", token)
    assert status == 200

    async def confirm():
        async with Session() as s:
            a = await s.get(App, aid)
            await logic.confirm(BotStub(), s, a)

    loop.run_until_complete(confirm())

    status, body = get_json(loop, client, "/api/v1/wallet", token)
    assert status == 200
    assert body["data"]["summary"]["available"] == 500
    kinds = [e["kind"] for e in body["data"]["entries"]]
    assert "cashback" in kinds

    status, body = post_json(loop, client, "/api/v1/withdrawals", token, {"amount": 100, "bank": "Т-Банк", "phone": "+79991234567"})
    assert status == 400 and body["err"]["code"] == "bad_amount"

    status, body = post_json(loop, client, "/api/v1/withdrawals", token, {"amount": 500, "bank": "Т-Банк", "phone": "+79991234567"})
    assert status == 201
    pid = body["data"]["id"]
    assert body["data"]["status"] == "pending" and body["data"]["can_cancel"] is True

    status, body = get_json(loop, client, "/api/v1/wallet", token)
    assert body["data"]["summary"]["available"] == 0
    assert body["data"]["summary"]["reserved"] == 500

    status, body = get_json(loop, client, "/api/v1/withdrawals", token)
    assert body["data"]["requests"][0]["id"] == pid
    assert body["data"]["available"] == 0

    status, body = post_json(loop, client, f"/api/v1/withdrawals/{pid}/cancel", token)
    assert status == 200 and body["data"]["status"] == "cancelled"

    status, body = get_json(loop, client, "/api/v1/wallet", token)
    assert body["data"]["summary"]["available"] == 500
    assert body["data"]["summary"]["reserved"] == 0
    kinds = [e["kind"] for e in body["data"]["entries"]]
    assert kinds.count("withdraw_request") == 1
    assert kinds.count("withdraw_cancel") == 1

    status, body = post_json(loop, client, f"/api/v1/withdrawals/{pid}/cancel", token)
    assert status == 409 and body["err"]["code"] == "not_pending"


def test_withdrawal_requires_phone(loop, client, offers):
    token = accepted_user(loop, client, 920020)
    status, body = take(loop, client, token, oid(loop, "tst_card_a"))
    aid = body["data"]["app_id"]
    status, _ = upload(loop, client, token, aid, [("proof.png", png_bytes(7))])
    assert status == 200
    status, _ = post_json(loop, client, f"/api/v1/apps/{aid}/submit", token)
    assert status == 200

    async def confirm():
        async with Session() as s:
            a = await s.get(App, aid)
            await logic.confirm(BotStub(), s, a)

    loop.run_until_complete(confirm())

    status, body = post_json(loop, client, "/api/v1/withdrawals", token, {"amount": 300, "bank": "Т-Банк", "phone": None})
    assert status == 400 and body["err"]["code"] == "no_phone"

    status, body = post_json(loop, client, "/api/v1/withdrawals", token, {"amount": 300, "bank": "Т-Банк", "phone": "123"})
    assert status == 400 and body["err"]["code"] == "bad_phone"

    other = accepted_user(loop, client, 920021)
    status, _ = post_json(loop, client, f"/api/v1/withdrawals/999999/cancel", other)
    assert status == 404