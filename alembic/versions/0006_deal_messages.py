"""Add per-deal support conversation messages."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0006_deal_messages"
down_revision = "0005_tma_sessions"
branch_labels = None
depends_on = None


def upgrade():
    if "deal_messages" not in set(inspect(op.get_bind()).get_table_names()):
        op.create_table(
            "deal_messages",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("app_id", sa.Integer(), sa.ForeignKey("apps.id"), nullable=False),
            sa.Column("actor_id", sa.BigInteger(), nullable=False),
            sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("created", sa.DateTime(), server_default=sa.func.now()),
        )
        op.create_index("ix_deal_messages_app_id", "deal_messages", ["app_id"])


def downgrade():
    op.drop_index("ix_deal_messages_app_id", table_name="deal_messages")
    op.drop_table("deal_messages")
