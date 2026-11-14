"""Add administrator audit history for offer/catalog changes."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0004_offer_audit"
down_revision = "0003_age_withdrawal_audit"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if "offer_events" not in set(inspect(bind).get_table_names()):
        op.create_table(
            "offer_events",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("offer_id", sa.Integer(), sa.ForeignKey("offers.id"), nullable=False),
            sa.Column("actor_id", sa.BigInteger(), nullable=True),
            sa.Column("event", sa.String(40), nullable=False),
            sa.Column("details", sa.Text(), nullable=False, server_default=""),
            sa.Column("created", sa.DateTime(), server_default=sa.func.now()),
        )
        op.create_index("ix_offer_events_offer_id", "offer_events", ["offer_id"])


def downgrade():
    op.drop_index("ix_offer_events_offer_id", table_name="offer_events")
    op.drop_table("offer_events")
