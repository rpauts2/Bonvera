"""Approve bookmaker offers after the network confirmed them.

Sets network_status="approved" so the catalog stops hiding them behind the
"ждёт согласования" gate. Run with --dry first, then --apply.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from bot.db import AdminAuditEvent, Bank, Offer, Session


async def main() -> None:
    apply = "--apply" in sys.argv
    changed = []
    async with Session() as s:
        rows = (
            await s.execute(
                select(Offer).join(Bank, Bank.id == Offer.bank_id).where(Bank.category == "bk")
            )
        ).scalars().all()
        for offer in rows:
            if offer.network_status == "approved" and offer.enabled:
                continue
            before = offer.network_status
            offer.network_status = "approved"
            offer.enabled = True
            s.add(
                AdminAuditEvent(
                    actor_id=0,
                    action="offer_bk_approved",
                    target_type="offer",
                    target_id=str(offer.id),
                    details=f"{offer.code}: {before} -> approved",
                )
            )
            changed.append(offer.code)
        if apply:
            await s.commit()
        else:
            await s.rollback()

    print(f"{'APPLIED' if apply else 'DRY'} bk_total={len(rows)} changed={len(changed)}")
    print("codes:", ",".join(changed) if changed else "-")


if __name__ == "__main__":
    asyncio.run(main())
