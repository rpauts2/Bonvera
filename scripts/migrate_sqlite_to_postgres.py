"""Copy legacy SQLite bot data into an already migrated PostgreSQL database.

Usage:
  python scripts/migrate_sqlite_to_postgres.py \
    'sqlite+aiosqlite:///bot.db' \
    'postgresql+asyncpg://cashback:URL_ENCODED_PASSWORD@localhost:5432/cashback'

The destination must be empty. Only columns present in both schemas are copied,
so legacy SQLite data can be imported before/after the new schema migration.
"""
import asyncio
import sys
from sqlalchemy import MetaData, select, text
from sqlalchemy.ext.asyncio import create_async_engine

ORDER = ["users", "banks", "offers", "tiers", "apps", "payouts", "refs", "postbacks", "wallet_entries", "catalog_state", "deal_events", "payout_events"]

async def main(source_url: str, target_url: str):
    src = create_async_engine(source_url)
    dst = create_async_engine(target_url)
    try:
        src_meta, dst_meta = MetaData(), MetaData()
        async with src.connect() as c: await c.run_sync(lambda sync: src_meta.reflect(sync))
        async with dst.connect() as c: await c.run_sync(lambda sync: dst_meta.reflect(sync))
        async with dst.begin() as c:
            counts = {}
            for name in ORDER:
                if name in dst_meta.tables:
                    counts[name] = (await c.execute(text(f'SELECT COUNT(*) FROM "{name}"'))).scalar_one()
            if any(counts.values()):
                raise RuntimeError(f"Destination is not empty: {counts}. Refusing to duplicate financial data.")
        for name in ORDER:
            if name not in src_meta.tables or name not in dst_meta.tables: continue
            st, dt = src_meta.tables[name], dst_meta.tables[name]
            columns = [col.name for col in dt.columns if col.name in st.columns]
            if not columns: continue
            copied = 0
            async with src.connect() as sc, dst.begin() as dc:
                result = await sc.execute(select(st))
                while batch := result.mappings().fetchmany(500):
                    payload = [{k: row[k] for k in columns} for row in batch]
                    await dc.execute(dt.insert(), payload); copied += len(payload)
            print(f"{name}: {copied} records")
        async with dst.begin() as c:
            for name in ORDER:
                if name not in dst_meta.tables or "id" not in dst_meta.tables[name].columns or name == "users": continue
                await c.execute(text(f"""SELECT setval(pg_get_serial_sequence('"{name}"','id'),
                    COALESCE((SELECT MAX(id) FROM "{name}"), 1),
                    EXISTS(SELECT 1 FROM "{name}"))"""))
        print("Import completed. Verify row counts and balances before switching production traffic.")
    finally:
        await src.dispose(); await dst.dispose()

if __name__ == "__main__":
    if len(sys.argv) != 3: raise SystemExit(__doc__)
    asyncio.run(main(sys.argv[1], sys.argv[2]))
