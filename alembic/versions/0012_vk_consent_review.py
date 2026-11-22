"""Add manual evidence review state to imported VK marketing consents."""
from alembic import op
import sqlalchemy as sa

revision = "0012_vk_consent_review"
down_revision = "0011_vk_callback_events"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "vk_contacts",
        sa.Column("consent_review_status", sa.String(24), nullable=False, server_default="pending_review"),
    )
    op.add_column(
        "vk_contacts",
        sa.Column("consent_reviewed_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "vk_contacts",
        sa.Column("consent_reviewed_by", sa.BigInteger(), nullable=True),
    )
    op.create_index(
        "ix_vk_contacts_consent_review_status",
        "vk_contacts",
        ["consent_review_status"],
    )


def downgrade():
    op.drop_index("ix_vk_contacts_consent_review_status", table_name="vk_contacts")
    op.drop_column("vk_contacts", "consent_reviewed_by")
    op.drop_column("vk_contacts", "consent_reviewed_at")
    op.drop_column("vk_contacts", "consent_review_status")
