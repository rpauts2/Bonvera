"""Apply the owner's payout policy: the user gets 70% of the network payout.

Two sources of truth, in this order:
  1. the explicit "up to N RUB" list from ProCPA (cashback values, already 70%),
  2. payout / 0.7 for offers whose network payout is known but that are missing
     from that list (for example "Bez % PLYUS" with a 5000 RUB payout).

Offers that appear in neither are left untouched.
"""
import asyncio
import json
import re
from pathlib import Path

from sqlalchemy import select

from bot.db import Bank, Offer, Session, Tier

SHARE = 0.70
LABEL = "Вознаграждение пользователю: 70% выплаты сети"

# category -> brand -> cashback the user receives
CASHBACK = {
    "cards_debit": {
        "УБРиР": 1820, "ВТБ": 1400, "ОТП Банк": 1330, "БСПБ": 1330, "ПСБ": 1540,
        "Совкомбанк": 1470, "Ак Барс": 1120, "Рокетбанк": 1080, "Ренессанс": 980,
        "МТС Деньги": 950, "Т-Банк": 910, "Альфа-Банк": 870, "ОЗОН Банк": 630, "МКБ": 630,
    },
    "cards_credit": {
        "Яндекс": 3640, "Уралсиб": 3430, "Совкомбанк": 3360, "Займер": 3190,
        "Кредит Европа": 3190, "Альфа-Банк": 3050, "СБЕР": 2940, "Сбербанк": 2870,
        "ОТП Банк": 2870, "Т-Банк": 2800, "Русский Стандарт": 2380, "АТБ": 2310,
        "ВТБ": 2170, "Ренессанс": 2130, "МТС Деньги": 1820, "АК Барс": 1330, "ОЗОН Банк": 1060,
    },
    "bk": {
        "PARI": 3640, "Марафон Бет": 2800, "Fonbet": 2590, "Мелбет": 2590,
        "Балтбет": 2590, "Леон": 1680,
    },
    "mfo": {
        "Cashiro": 2030, "Bunny Money": 2030, "Целевые Финансы": 2030, "Свои люди": 1960,
        "Хурма Кредит": 1820, "МИР Денег": 1750, "Деньги сразу": 1730, "Fin5": 1470,
        "Мигом Займ": 1330, "ЗаймиРУБ": 1330, "Credit 365": 1260, "ДеньгиОк": 1190,
        "Эквазайм": 1060, "Займикс": 980, "Алистар": 740, "FinMi": 740,
    },
    "cpl": {
        "Народный Займ": 270, "Твой займ": 270, "С-Деньги": 260, "Зарубас": 210,
        "Credeo": 160, "7 Займов": 120, "23 Займа": 80, "РосЗайм": 60, "Вишня": 60,
        "Zaimsrazu": 60, "РублиON": 50, "Telezaim": 40, "Рябина": 40, "Щедрая казна": 40,
        "Т-Заём": 40, "КликЗайм": 40, "Dayvdolg": 20, "ZolBank": 20, "Буратино": 20,
    },
}


def norm(value: str) -> str:
    value = value.lower().replace("ё", "е")
    return re.sub(r"[^a-zа-я0-9]+", "", value)


def lookup(bank_name: str, category: str, kind: str):
    """Return the cashback for a brand, tolerating name variants."""
    group = f"cards_{kind}" if category == "cards" else category
    table = CASHBACK.get(group)
    if not table:
        return None
    target = norm(bank_name)
    exact = {norm(k): v for k, v in table.items()}
    if target in exact:
        return exact[target]
    # "Кредит Европа Банк" -> "Кредит Европа", "Яндекс Банк" -> "Яндекс"
    for brand, value in table.items():
        b = norm(brand)
        if target.startswith(b) or b.startswith(target):
            return value
    return None


def payout_from_cashback(cashback: int) -> int:
    return int(round(cashback / SHARE / 10.0) * 10)


async def main() -> None:
    dry = "--dry" in __import__("sys").argv
    stats = {"list": 0, "policy": 0, "kept": 0}
    async with Session() as s:
        rows = (await s.execute(select(Offer, Bank).join(Bank, Bank.id == Offer.bank_id))).all()
        for offer, bank in rows:
            tiers = (await s.execute(select(Tier).where(Tier.offer_id == offer.id).order_by(Tier.id))).scalars().all()
            cashback = lookup(bank.name, bank.category, offer.kind or "")
            if cashback is not None:
                payout = payout_from_cashback(cashback)
                stats["list"] += 1
                if dry:
                    print(f"LIST   {bank.category:6} {bank.name:24} cb={cashback:6} payout={payout}")
            else:
                known_payout = max([t.payout or 0 for t in tiers] or [0])
                if known_payout <= 0:
                    stats["kept"] += 1
                    if dry:
                        print(f"KEEP   {bank.category:6} {bank.name:24} (no data)")
                    continue
                payout = known_payout
                cashback = int(round(payout * SHARE / 10.0) * 10)
                stats["policy"] += 1
                if dry:
                    print(f"POLICY {bank.category:6} {bank.name:24} cb={cashback:6} payout={payout}")

            if not tiers:
                s.add(Tier(offer_id=offer.id, payout=payout, cashback=cashback, label=LABEL))
                continue
            tiers[0].payout = max(tiers[0].payout or 0, payout)
            tiers[0].cashback = cashback
            tiers[0].label = LABEL
            for extra in tiers[1:]:
                await s.delete(extra)
        if dry:
            await s.rollback()
        else:
            await s.commit()
    print("rewards applied:", json.dumps(stats, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
