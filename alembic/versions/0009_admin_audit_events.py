"""Add durable audit trail for web administrator actions."""
from alembic import op
import sqlalchemy as sa

revision = "0009_admin_audit_events"
down_revision = "0008_broadcast_campaigns"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "admin_audit_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("actor_id", sa.BigInteger(), nullable=False),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("target_type", sa.String(30), nullable=False),
        sa.Column("target_id", sa.String(80), nullable=False),
        sa.Column("details", sa.Text(), nullable=False, server_default=""),
        sa.Column("created", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_admin_audit_events_actor_id", "admin_audit_events", ["actor_id"])
    op.create_index("ix_admin_audit_events_created", "admin_audit_events", ["created"])


def downgrade():
    op.drop_index("ix_admin_audit_events_created", table_name="admin_audit_events")
    op.drop_index("ix_admin_audit_events_actor_id", table_name="admin_audit_events")
    op.drop_table("admin_audit_events")
