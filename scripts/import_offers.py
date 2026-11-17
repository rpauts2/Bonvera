"""Import additional offers into an existing category (default: cpl / lead forms).

Additive by design: existing offers are matched by `code` and only their url,
rate, condition and availability are refreshed. Nothing is deleted, no schema
changes, no migrations.

Input JSON (list):
    [{"code": "lead_x", "bank": "Название", "name": "Отображаемое имя",
      "url": "https://...", "rate": 270, "condition": "Заполнена анкета",
      "category": "cpl", "kind": "заявка", "slug": "lead_x"}]

Run:
    docker compose exec -T -e PYTHONPATH=/app bot python scripts/import_offers.py scripts/leads.json --dry
"""
import asyncio
import json
import sys
from pathlib import Path

from sqlalchemy import select

from bot.db import Bank, Offer, Session, Tier

LABEL = "Ставка ProCPA"


async def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry" in sys.argv
    data_path = Path(args[0] if args else "scripts/leads.json")
    rows = json.loads(data_path.read_text(encoding="utf-8"))

    stats = {"banks_new": 0, "offers_new": 0, "offers_updated": 0, "tiers_set": 0}
    async with Session() as s:
        for item in rows:
            category = item.get("category", "cpl")
            kind = item.get("kind", "заявка")
            slug = item.get("slug") or item["code"]

            bank = (await s.execute(select(Bank).where(Bank.slug == slug))).scalar_one_or_none()
            if bank is None:
                bank = Bank(slug=slug, name=item["bank"], emoji=item.get("emoji", "📝"),
                            category=category, sort=item.get("sort", 900))
                s.add(bank)
                await s.flush()
                stats["banks_new"] += 1

            offer = (await s.execute(select(Offer).where(Offer.code == item["code"]))).scalar_one_or_none()
            if offer is None:
                offer = Offer(code=item["code"], bank_id=bank.id, name=item["name"])
                s.add(offer)
                await s.flush()
                stats["offers_new"] += 1
            else:
                stats["offers_updated"] += 1

            offer.bank_id = bank.id
            offer.name = item["name"]
            offer.url = item.get("url", "")
            offer.link_param = "sub1"
            offer.network_status = "approved"
            offer.enabled = True
            offer.kind = kind
            if item.get("condition"):
                offer.condition_text = item["condition"]
                offer.action = item["condition"]

            rate = int(item.get("rate") or 0)
            tiers = (await s.execute(select(Tier).where(Tier.offer_id == offer.id))).scalars().all()
            if rate > 0:
                if tiers:
                    tiers[0].payout = rate
                    tiers[0].cashback = rate
                    tiers[0].label = LABEL
                    for extra in tiers[1:]:
                        await s.delete(extra)
                else:
                    s.add(Tier(offer_id=offer.id, payout=rate, cashback=rate, label=LABEL))
                stats["tiers_set"] += 1

            print(f"{'DRY ' if dry else ''}{category:5} {item['code']:22} rate={rate:6} {item['name']}")

        if dry:
            await s.rollback()
        else:
            await s.commit()

    print("import done:", json.dumps(stats, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
