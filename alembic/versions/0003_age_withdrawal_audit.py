"""Add age ranges, saved SBP settings, frozen offer snapshots and audit trails."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0003_age_withdrawal_audit"
down_revision = "0002_offer_verification"
branch_labels = None
depends_on = None

def upgrade():
    bind = op.get_bind(); insp = inspect(bind)
    def add(table, columns):
        existing = {c["name"] for c in inspect(bind).get_columns(table)}
        for name, col in columns.items():
            if name not in existing: op.add_column(table, col)
    add("users", {
        "age_years": sa.Column("age_years", sa.Integer(), nullable=True),
        "sbp_bank": sa.Column("sbp_bank", sa.String(80), nullable=False, server_default=""),
        "sbp_phone": sa.Column("sbp_phone", sa.String(200), nullable=False, server_default=""),
    })
    add("offers", {
        "age_min": sa.Column("age_min", sa.Integer(), nullable=False, server_default="18"),
        "age_max": sa.Column("age_max", sa.Integer(), nullable=False, server_default="120"),
    })
    add("apps", {
        "offer_snapshot": sa.Column("offer_snapshot", sa.JSON(), nullable=True),
        "reminder_sent": sa.Column("reminder_sent", sa.Boolean(), nullable=False, server_default=sa.false()),
        "hold_alerted_at": sa.Column("hold_alerted_at", sa.DateTime(), nullable=True),
    })
    add("payouts", {
        "bank": sa.Column("bank", sa.String(80), nullable=False, server_default=""),
        "processed_by": sa.Column("processed_by", sa.BigInteger(), nullable=True),
        "updated_at": sa.Column("updated_at", sa.DateTime(), nullable=True),
    })
    if bind.dialect.name == "postgresql":
        op.alter_column("payouts", "status", type_=sa.String(20), existing_type=sa.String(10), existing_nullable=False)
    tables = set(inspect(bind).get_table_names())
    if "catalog_state" not in tables:
        op.create_table("catalog_state",
            sa.Column("key", sa.String(80), primary_key=True),
            sa.Column("value", sa.String(200), nullable=False, server_default=""))
    if "deal_events" not in tables:
        op.create_table("deal_events",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("app_id", sa.Integer(), sa.ForeignKey("apps.id"), nullable=False, index=True),
            sa.Column("actor_id", sa.BigInteger(), nullable=True),
            sa.Column("event", sa.String(40), nullable=False),
            sa.Column("from_status", sa.String(20), nullable=False, server_default=""),
            sa.Column("to_status", sa.String(20), nullable=False, server_default=""),
            sa.Column("comment", sa.Text(), nullable=False, server_default=""),
            sa.Column("created", sa.DateTime(), server_default=sa.func.now()))
    if "payout_events" not in tables:
        op.create_table("payout_events",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("payout_id", sa.Integer(), sa.ForeignKey("payouts.id"), nullable=False, index=True),
            sa.Column("actor_id", sa.BigInteger(), nullable=True),
            sa.Column("event", sa.String(40), nullable=False),
            sa.Column("from_status", sa.String(20), nullable=False, server_default=""),
            sa.Column("to_status", sa.String(20), nullable=False, server_default=""),
            sa.Column("comment", sa.Text(), nullable=False, server_default=""),
            sa.Column("created", sa.DateTime(), server_default=sa.func.now()))

def downgrade():
    op.drop_table("payout_events"); op.drop_table("deal_events"); op.drop_table("catalog_state")
    for col in ("bank", "processed_by", "updated_at"): op.drop_column("payouts", col)
    for col in ("offer_snapshot", "reminder_sent", "hold_alerted_at"): op.drop_column("apps", col)
    for col in ("age_min", "age_max"): op.drop_column("offers", col)
    for col in ("age_years", "sbp_bank", "sbp_phone"): op.drop_column("users", col)
