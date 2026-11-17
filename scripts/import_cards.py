"""Import the ProCPA card inventory: partner links, debit/credit split, payouts.

Idempotent: matches offers by code, creates the missing banks/offers, and never
touches an existing tier that already carries a payout or a cashback.

    docker compose exec -T bot python scripts/import_cards.py
"""
import asyncio
import json
from pathlib import Path

from sqlalchemy import select

from bot.db import Bank, Offer, Session, Tier

DATA = Path(__file__).with_name("procpa_cards.json")
CASHBACK_SHARE = 0.30  # placeholder share of the network payout until the owner sets it


def suggest_cashback(payout: int) -> int:
    return int(round(payout * CASHBACK_SHARE / 10.0) * 10)


async def main() -> None:
    rows = json.loads(DATA.read_text(encoding="utf-8"))
    stats = {"banks_new": 0, "offers_new": 0, "offers_updated": 0, "tiers_new": 0, "tiers_kept": 0}

    async with Session() as s:
        for item in rows:
            bank = (await s.execute(select(Bank).where(Bank.slug == item["slug"]))).scalar_one_or_none()
            if bank is None:
                bank = Bank(slug=item["slug"], name=item["bank"], emoji="💳", category="cards", sort=900)
                s.add(bank)
                await s.flush()
                stats["banks_new"] += 1

            offer = (await s.execute(select(Offer).where(Offer.code == item["code"]))).scalar_one_or_none()
            is_new = offer is None
            if is_new:
                offer = Offer(code=item["code"], bank_id=bank.id, name=item["name"])
                s.add(offer)
                await s.flush()
                stats["offers_new"] += 1
            else:
                stats["offers_updated"] += 1

            offer.bank_id = bank.id
            offer.name = item["name"]
            offer.url = item["url"]
            offer.link_param = item["url"] and "sub1" or offer.link_param
            offer.network_status = "approved"
            offer.enabled = True
            offer.kind = item["kind"]
            if item.get("condition"):
                offer.condition_text = item["condition"]
                if is_new:
                    offer.action = item["condition"]

            payout = int(item.get("payout") or 0)
            tiers = (await s.execute(select(Tier).where(Tier.offer_id == offer.id))).scalars().all()
            if payout > 0 and not any((t.payout or 0) > 0 for t in tiers):
                s.add(Tier(
                    offer_id=offer.id,
                    payout=payout,
                    cashback=suggest_cashback(payout),
                    label="Выплата сети ProCPA; вознаграждение пользователю предварительное",
                ))
                stats["tiers_new"] += 1
            elif tiers:
                stats["tiers_kept"] += 1

        await s.commit()

    print("import done:", json.dumps(stats, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
