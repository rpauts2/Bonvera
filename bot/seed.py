from datetime import datetime
from pathlib import Path
import yaml
from sqlalchemy import select
from bot.db import Session, Bank, Offer, Tier, CatalogState
from bot.evidence import verification, required_proofs

CATEGORY_EMOJI = {"cards":"💳", "bk":"⚽", "mfo":"🏦", "cpl":"📝"}
CATEGORY_RU = {"cards":"Карты", "bk":"Букмекеры", "mfo":"Займы МФО", "cpl":"Заявки МФО"}
CATALOG_VERSION = "user-supplied-93-offer-list-2026-11-13-final"
PROOF_TEMPLATE_VERSION = "evidence-checklist-v2-fio-card-issue-mfo-disbursement-bk-settled-bet"


async def seed(path="catalog.yaml"):
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    rows = data.get("offers", [])
    async with Session() as s:
        state = await s.get(CatalogState, "cashback_catalog_version")
        sync_catalog = state is None or state.value != CATALOG_VERSION
        proof_state = await s.get(CatalogState, "cashback_proof_template_version")
        sync_proofs = proof_state is None or proof_state.value != PROOF_TEMPLATE_VERSION
        known_codes = {row["code"] for row in rows}
        for i, row in enumerate(rows):
            cat = row["category"]
            bank = (await s.execute(select(Bank).where(Bank.slug == row["slug"]))).scalar_one_or_none()
            if bank is None:
                bank = Bank(slug=row["slug"], name=row["name"], emoji=row.get("emoji", CATEGORY_EMOJI[cat]), category=cat, sort=i)
                s.add(bank); await s.flush()
            else:
                bank.name, bank.category = row["name"], cat
                bank.emoji = row.get("emoji", CATEGORY_EMOJI[cat])
                bank.sort = i

            o = (await s.execute(select(Offer).where(Offer.code == row["code"]))).scalar_one_or_none()
            is_new = o is None
            if is_new:
                o = Offer(code=row["code"], bank_id=bank.id, name=row["title"])
                s.add(o); await s.flush()
            else:
                # Keep admin-entered tracking link and enabled flag on reseed.
                o.bank_id = bank.id

            condition = row["condition"]
            if sync_catalog or is_new:
                # Catalogue is a baseline; once this version is synced, admin edits
                # survive restarts. Bump CATALOG_VERSION only for intentional imports.
                o.name = row["title"]
                o.action = condition
                o.condition_text = condition
                o.condition_type = {"cards":"card_issue_purchase", "bk":"bk_registration_deposit_bet", "mfo":"loan_issued", "cpl":"lead_form"}[cat]
                o.hold = row["hold"]
                o.age = row["age_min"]
                o.age_min = row["age_min"]
                o.age_max = row["age_max"]
                o.purchase_min = row.get("minimum", 0)
                o.kind = row.get("kind", "")
                o.image_path = f"assets/offers/{cat}/{row['code']}.jpg"
                o.source_url = row.get("source_url", "")
                o.notes = row.get("note", "")
                o.enabled = True
            elif is_new:
                o.enabled = True
            if sync_proofs or is_new:
                # Refresh the checklist once per template version; later admin edits
                # are preserved across restarts until the template version is bumped.
                o.verification_steps = verification(cat, condition, o.kind)
                o.required_proofs = required_proofs(cat, condition, o.kind)
            o.sort = i
            if is_new:
                o.network_status = "needs_approval" if cat == "bk" else "not_checked"
            o.link_param = o.link_param or "subid"
            if is_new or not o.url:
                o.url = row.get("url", "")
            if is_new:
                o.approval = ""
                s.add(Tier(offer_id=o.id, payout=0, cashback=row["reward"], label="Вознаграждение пользователю по каталогу владельца"))
            else:
                tiers = (await s.execute(select(Tier).where(Tier.offer_id == o.id).order_by(Tier.id))).scalars().all()
                if not tiers:
                    s.add(Tier(offer_id=o.id, payout=0, cashback=row["reward"], label="Вознаграждение пользователю по каталогу владельца"))
                else:
                    if sync_catalog:
                        tiers[0].cashback = row["reward"]
                        # Do not overwrite a network payout manually entered by admin.
                    tiers[0].label = "Вознаграждение пользователю по каталогу владельца"
                    for extra in tiers[1:]:
                        await s.delete(extra)
        # Retain legacy records for existing deal history, but remove them from the public catalog.
        legacy = (await s.execute(select(Offer))).scalars().all()
        for old_offer in legacy:
            # Offers imported outside catalog.yaml (ProCPA) stay live as long as they
            # carry a partner link; only linkless leftovers are hidden.
            if old_offer.code not in known_codes and not old_offer.url:
                old_offer.enabled = False
        if state is None:
            s.add(CatalogState(key="cashback_catalog_version", value=CATALOG_VERSION))
        elif state.value != CATALOG_VERSION:
            state.value = CATALOG_VERSION
        if proof_state is None:
            s.add(CatalogState(key="cashback_proof_template_version", value=PROOF_TEMPLATE_VERSION))
        elif proof_state.value != PROOF_TEMPLATE_VERSION:
            proof_state.value = PROOF_TEMPLATE_VERSION
        await s.commit()
    return len(rows)
