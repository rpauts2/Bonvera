from pathlib import Path
from alembic.config import Config
from alembic.script import ScriptDirectory

from sqlalchemy import UniqueConstraint

from bot.db import Base

ROOT = Path(__file__).resolve().parents[1]


def test_vk_outreach_tables_are_registered_in_shared_metadata():
    expected = {
        "vk_contacts",
        "vk_consent_events",
        "vk_offer_slots",
        "vk_clicks",
        "vk_campaigns",
        "vk_campaign_recipients",
        "vk_callback_events",
    }
    assert expected <= set(Base.metadata.tables)


def test_vk_offer_slots_have_a_unique_slot_number():
    table = Base.metadata.tables["vk_offer_slots"]
    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert ("slot_number",) in unique_columns


def test_vk_campaign_recipient_is_unique_per_campaign_and_contact():
    table = Base.metadata.tables["vk_campaign_recipients"]
    unique_pairs = {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
    }
    assert ("campaign_id", "contact_id") in unique_pairs


def test_vk_outreach_migration_is_current_alembic_head():
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    script = ScriptDirectory.from_config(config)
    assert script.get_current_head() == "0011_vk_callback_events"

def test_vk_contact_has_manual_import_consent_review_fields():
    table = Base.metadata.tables["vk_contacts"]
    assert "consent_review_status" in table.columns
    assert "consent_reviewed_at" in table.columns
    assert "consent_reviewed_by" in table.columns
