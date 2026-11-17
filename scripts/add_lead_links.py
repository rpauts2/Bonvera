"""Attach ProCPA partner links to existing lead offers and create the missing two.

Only touches the offers listed here: sets the partner link, tracking param and
network status, keeps names, rates and banks untouched.
"""
import asyncio
import sys

from sqlalchemy import select

from bot.db import Bank, Offer, Session

LINKS = {
    "narodnyy_zaym": "https://bit-do.ru/541-1000326-rvRip5jjUXP",
    "s_dengi": "https://bit-do.ru/500-1000326-gkBTDgaacAJ",
    "zarubas": "https://bit-do.ru/516-1000326-NO3sbavvT5n",
    "23_zayma": "https://bit-do.ru/600-1000326-gD3sDgaacAJ",
}

NEW = [
    {
        "code": "mama_cash",
        "bank": "Мама Кеш",
        "name": "Мама Кеш — Займы",
        "url": "https://bit-do.ru/542-1000326-MpoFzKkkhQ0",
        "condition": "Оформлена заявка на заём",
    },
    {
        "code": "dobrozaim",
        "bank": "Доброзайм",
        "name": "Доброзайм — Займ под авто",
        "url": "https://bit-do.ru/1652-1000326-Lp2s9XKKskZ",
        "condition": "Заявка на займ под залог автомобиля",
    },
]


async def main() -> None:
    dry = "--dry" in sys.argv
    updated, missing, created = [], [], []
    async with Session() as s:
        for code, url in LINKS.items():
            offer = (await s.execute(select(Offer).where(Offer.code == code))).scalar_one_or_none()
            if offer is None:
                missing.append(code)
                continue
            offer.url = url
            offer.link_param = "sub1"
            offer.network_status = "approved"
            offer.enabled = True
            updated.append(code)

        for item in NEW:
            exists = (await s.execute(select(Offer).where(Offer.code == item["code"]))).scalar_one_or_none()
            if exists:
                exists.url = item["url"]
                exists.link_param = "sub1"
                exists.network_status = "approved"
                exists.enabled = True
                updated.append(item["code"])
                continue
            bank = (await s.execute(select(Bank).where(Bank.slug == item["code"]))).scalar_one_or_none()
            if bank is None:
                bank = Bank(slug=item["code"], name=item["bank"], emoji="📝", category="cpl", sort=950)
                s.add(bank)
                await s.flush()
            offer = Offer(code=item["code"], bank_id=bank.id, name=item["name"])
            s.add(offer)
            await s.flush()
            offer.url = item["url"]
            offer.link_param = "sub1"
            offer.network_status = "approved"
            offer.enabled = True
            offer.kind = "заявка"
            offer.condition_text = item["condition"]
            offer.action = item["condition"]
            created.append(item["code"])

        if dry:
            await s.rollback()
        else:
            await s.commit()

    print(f"{'DRY ' if dry else ''}updated={updated} created={created} missing={missing}")


if __name__ == "__main__":
    asyncio.run(main())
