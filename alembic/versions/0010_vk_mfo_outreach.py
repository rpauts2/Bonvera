"""Add VK MFO outreach contacts, consent, offers, tracking and campaigns."""
from alembic import op
import sqlalchemy as sa

revision = "0010_vk_mfo_outreach"
down_revision = "0009_admin_audit_events"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "vk_contacts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("vk_user_id", sa.BigInteger(), nullable=False),
        sa.Column("first_name", sa.String(128), nullable=True),
        sa.Column("last_name", sa.String(128), nullable=True),
        sa.Column("phone_encrypted", sa.String(500), nullable=True),
        sa.Column("phone_hash", sa.String(64), nullable=True),
        sa.Column("flow_state", sa.String(40), nullable=False, server_default="awaiting_personal_data_consent"),
        sa.Column("personal_data_consent_at", sa.DateTime(), nullable=True),
        sa.Column("personal_data_consent_version", sa.String(40), nullable=False, server_default=""),
        sa.Column("marketing_consent_at", sa.DateTime(), nullable=True),
        sa.Column("marketing_consent_version", sa.String(40), nullable=False, server_default=""),
        sa.Column("marketing_consent_source", sa.String(120), nullable=False, server_default=""),
        sa.Column("marketing_suppressed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("source_campaign", sa.String(80), nullable=False, server_default=""),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("created", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("vk_user_id", name="uq_vk_contacts_vk_user_id"),
    )
    op.create_index("ix_vk_contacts_vk_user_id", "vk_contacts", ["vk_user_id"])
    op.create_index("ix_vk_contacts_phone_hash", "vk_contacts", ["phone_hash"])

    op.create_table(
        "vk_consent_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("contact_id", sa.Integer(), sa.ForeignKey("vk_contacts.id"), nullable=False),
        sa.Column("consent_type", sa.String(32), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("text_version", sa.String(40), nullable=False, server_default=""),
        sa.Column("source", sa.String(120), nullable=False, server_default=""),
        sa.Column("proof_reference", sa.String(255), nullable=False, server_default=""),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_vk_consent_events_contact_id", "vk_consent_events", ["contact_id"])

    op.create_table(
        "vk_offer_slots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slot_number", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("advertiser_name", sa.String(160), nullable=False, server_default=""),
        sa.Column("title", sa.String(160), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("target_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("tracking_param", sa.String(40), nullable=False, server_default=""),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_by", sa.BigInteger(), nullable=True),
        sa.Column("created", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("slot_number", name="uq_vk_offer_slots_slot_number"),
        sa.CheckConstraint("slot_number BETWEEN 1 AND 5", name="ck_vk_offer_slots_number"),
        sa.CheckConstraint(
            "(slot_number BETWEEN 1 AND 4 AND kind = 'mfo_offer') OR "
            "(slot_number = 5 AND kind = 'storefront')",
            name="ck_vk_offer_slots_kind",
        ),
    )

    op.create_table(
        "vk_campaigns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("admin_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("cta_label", sa.String(80), nullable=False, server_default="Начать"),
        sa.Column("status", sa.String(24), nullable=False, server_default="draft"),
        sa.Column("audience_type", sa.String(32), nullable=False, server_default="opted_in"),
        sa.Column("advertiser_name", sa.String(200), nullable=False, server_default=""),
        sa.Column("advertiser_inn", sa.String(20), nullable=False, server_default=""),
        sa.Column("warning_text", sa.String(240), nullable=False, server_default="Оценивайте свои финансовые возможности и риски."),
        sa.Column("erid", sa.String(120), nullable=False, server_default=""),
        sa.Column("targeting_json", sa.JSON(), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("recipient_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sent_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_vk_campaigns_status", "vk_campaigns", ["status"])

    op.create_table(
        "vk_campaign_recipients",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("campaign_id", sa.Integer(), sa.ForeignKey("vk_campaigns.id"), nullable=False),
        sa.Column("contact_id", sa.Integer(), sa.ForeignKey("vk_contacts.id"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("last_error_code", sa.String(80), nullable=False, server_default=""),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("created", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("idempotency_key", name="uq_vk_campaign_recipients_idempotency_key"),
        sa.UniqueConstraint("campaign_id", "contact_id", name="uq_vk_campaign_recipient"),
    )
    op.create_index("ix_vk_campaign_recipients_campaign_id", "vk_campaign_recipients", ["campaign_id"])
    op.create_index("ix_vk_campaign_recipients_contact_id", "vk_campaign_recipients", ["contact_id"])
    op.create_index("ix_vk_campaign_recipients_status", "vk_campaign_recipients", ["status"])

    op.create_table(
        "vk_clicks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("contact_id", sa.Integer(), sa.ForeignKey("vk_contacts.id"), nullable=True),
        sa.Column("slot_number", sa.Integer(), nullable=False),
        sa.Column("campaign_id", sa.Integer(), sa.ForeignKey("vk_campaigns.id"), nullable=True),
        sa.Column("source", sa.String(80), nullable=False, server_default=""),
        sa.Column("destination_domain", sa.String(255), nullable=False, server_default=""),
        sa.Column("outcome", sa.String(24), nullable=False, server_default="created"),
        sa.Column("created", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("token_hash", name="uq_vk_clicks_token_hash"),
    )
    op.create_index("ix_vk_clicks_token_hash", "vk_clicks", ["token_hash"])
    op.create_index("ix_vk_clicks_contact_id", "vk_clicks", ["contact_id"])
    op.create_index("ix_vk_clicks_campaign_id", "vk_clicks", ["campaign_id"])


def downgrade():
    op.drop_index("ix_vk_clicks_campaign_id", table_name="vk_clicks")
    op.drop_index("ix_vk_clicks_contact_id", table_name="vk_clicks")
    op.drop_index("ix_vk_clicks_token_hash", table_name="vk_clicks")
    op.drop_table("vk_clicks")
    op.drop_index("ix_vk_campaign_recipients_status", table_name="vk_campaign_recipients")
    op.drop_index("ix_vk_campaign_recipients_contact_id", table_name="vk_campaign_recipients")
    op.drop_index("ix_vk_campaign_recipients_campaign_id", table_name="vk_campaign_recipients")
    op.drop_table("vk_campaign_recipients")
    op.drop_index("ix_vk_campaigns_status", table_name="vk_campaigns")
    op.drop_table("vk_campaigns")
    op.drop_table("vk_offer_slots")
    op.drop_index("ix_vk_consent_events_contact_id", table_name="vk_consent_events")
    op.drop_table("vk_consent_events")
    op.drop_index("ix_vk_contacts_phone_hash", table_name="vk_contacts")
    op.drop_index("ix_vk_contacts_vk_user_id", table_name="vk_contacts")
    op.drop_table("vk_contacts")
