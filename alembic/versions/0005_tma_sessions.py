"""Add Mini App bearer sessions and per-user notification read marker (additive)."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0005_tma_sessions"
down_revision = "0004_offer_audit"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = inspect(bind)
    if "tma_sessions" not in set(insp.get_table_names()):
        op.create_table(
            "tma_sessions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("token_hash", sa.String(64), nullable=False),
            sa.Column("user_id", sa.BigInteger(), nullable=False),
            sa.Column("created", sa.DateTime(), server_default=sa.func.now()),
            sa.Column("expires", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_tma_sessions_token_hash", "tma_sessions", ["token_hash"], unique=True)
        op.create_index("ix_tma_sessions_user_id", "tma_sessions", ["user_id"])
    if "notif_read_at" not in {c["name"] for c in insp.get_columns("users")}:
        op.add_column("users", sa.Column("notif_read_at", sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column("users", "notif_read_at")
    op.drop_index("ix_tma_sessions_user_id", table_name="tma_sessions")
    op.drop_index("ix_tma_sessions_token_hash", table_name="tma_sessions")
    op.drop_table("tma_sessions")