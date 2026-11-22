"""Persist VK Callback API event receipts for idempotent processing."""
from alembic import op
import sqlalchemy as sa

revision = "0011_vk_callback_events"
down_revision = "0010_vk_mfo_outreach"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "vk_callback_events",
        sa.Column("event_id", sa.String(64), primary_key=True),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="received"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("received_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("processed_at", sa.DateTime(), nullable=True),
        sa.Column("last_error_code", sa.String(80), nullable=False, server_default=""),
    )
    op.create_index("ix_vk_callback_events_status", "vk_callback_events", ["status"])


def downgrade():
    op.drop_index("ix_vk_callback_events_status", table_name="vk_callback_events")
    op.drop_table("vk_callback_events")
