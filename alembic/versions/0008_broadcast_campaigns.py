"""Record administrator broadcast campaign summaries."""
from alembic import op
import sqlalchemy as sa

revision = "0008_broadcast_campaigns"
down_revision = "0007_proof_fingerprints"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "broadcast_campaigns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("admin_id", sa.BigInteger(), nullable=False),
        sa.Column("source_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("source_message_id", sa.Integer(), nullable=False),
        sa.Column("audience", sa.String(20), nullable=False),
        sa.Column("recipient_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sent_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_broadcast_campaigns_created", "broadcast_campaigns", ["created"])


def downgrade():
    op.drop_index("ix_broadcast_campaigns_created", table_name="broadcast_campaigns")
    op.drop_table("broadcast_campaigns")
