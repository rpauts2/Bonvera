"""Fill missing ProCPA partner links from a reviewed mapping file.

Only offers that currently have no link are touched: existing links, names,
rates and banks stay as they are. Run with --dry first, then --apply.
"""
import asyncio
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from bot.db import AdminAuditEvent, Offer, Session

MAP = Path(__file__).with_name("procpa_links_2026_11.json")


async def main() -> None:
    apply = "--apply" in sys.argv
    data = json.loads(MAP.read_text(encoding="utf-8"))

    bad_urls = [c for c, v in data.items() if urlparse(v["url"]).hostname != "bit-do.ru"]
    if bad_urls:
        raise SystemExit(f"refusing to write non-ProCPA urls: {bad_urls}")

    updated, skipped, missing = [], [], []
    async with Session() as s:
        for code, item in data.items():
            offer = (await s.execute(select(Offer).where(Offer.code == code))).scalar_one_or_none()
            if offer is None:
                missing.append(code)
                continue
            if (offer.url or "").strip():
                skipped.append(code)
                continue
            offer.url = item["url"]
            offer.link_param = "sub1"
            offer.network_status = "approved"
            offer.enabled = True
            s.add(
                AdminAuditEvent(
                    actor_id=0,
                    action="offer_link_filled",
                    target_type="offer",
                    target_id=str(offer.id),
                    details=f"ProCPA {item['proff_id']} · {code}",
                )
            )
            updated.append(code)

        if apply:
            await s.commit()
        else:
            await s.rollback()

    print(f"{'APPLIED' if apply else 'DRY'} updated={len(updated)} skipped={len(skipped)} missing={len(missing)}")
    print("updated:", ",".join(updated) if updated else "-")
    if skipped:
        print("skipped (already have a link):", ",".join(skipped))
    if missing:
        print("missing in db:", ",".join(missing))


if __name__ == "__main__":
    asyncio.run(main())
