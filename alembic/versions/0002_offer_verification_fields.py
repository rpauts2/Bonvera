"""Add editable offer rules and verification workflow fields."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
revision = "0002_offer_verification"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

def upgrade():
    bind = op.get_bind(); insp = inspect(bind)
    existing = {c["name"] for c in insp.get_columns("offers")}
    fields = {
      "image_path": sa.Column("image_path", sa.String(255), nullable=False, server_default=""),
      "condition_type": sa.Column("condition_type", sa.String(30), nullable=False, server_default="custom"),
      "condition_text": sa.Column("condition_text", sa.Text(), nullable=False, server_default=""),
      "verification_steps": sa.Column("verification_steps", sa.JSON(), nullable=False, server_default="[]"),
      "required_proofs": sa.Column("required_proofs", sa.JSON(), nullable=False, server_default="[]"),
      "network_status": sa.Column("network_status", sa.String(30), nullable=False, server_default="needs_approval"),
      "source_url": sa.Column("source_url", sa.Text(), nullable=False, server_default=""),
      "terms_checked_at": sa.Column("terms_checked_at", sa.DateTime(), nullable=True),
      "link_param": sa.Column("link_param", sa.String(40), nullable=False, server_default="subid"),
      "notes": sa.Column("notes", sa.Text(), nullable=False, server_default=""),
    }
    for name, col in fields.items():
        if name not in existing: op.add_column("offers", col)
    user_cols = {c["name"] for c in inspect(bind).get_columns("users")}
    if "age21" not in user_cols: op.add_column("users", sa.Column("age21", sa.Boolean(), nullable=False, server_default=sa.false()))
    app_cols = {c["name"] for c in inspect(bind).get_columns("apps")}
    app_fields = {
      "proof_hash": sa.Column("proof_hash", sa.String(32), nullable=True),
      "proof_files": sa.Column("proof_files", sa.JSON(), nullable=False, server_default="[]"),
      "verification": sa.Column("verification", sa.JSON(), nullable=False, server_default="{}"),
      "reviewed_by": sa.Column("reviewed_by", sa.BigInteger(), nullable=True),
      "reviewed_at": sa.Column("reviewed_at", sa.DateTime(), nullable=True),
    }
    for name, col in app_fields.items():
        if name not in app_cols: op.add_column("apps", col)
    payout_cols = {c["name"] for c in inspect(bind).get_columns("payouts")}
    for name, col in {
      "paid_at": sa.Column("paid_at", sa.DateTime(), nullable=True),
      "admin_note": sa.Column("admin_note", sa.Text(), nullable=False, server_default=""),
    }.items():
        if name not in payout_cols: op.add_column("payouts", col)
    # Encrypted Fernet phone values are longer than the legacy 20-character plaintext column.
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("payouts") as batch:
            batch.alter_column("phone", existing_type=sa.String(20), type_=sa.String(200), existing_nullable=False)
    else:
        op.alter_column("payouts", "phone", existing_type=sa.String(20), type_=sa.String(200), existing_nullable=False)
    # Owner explicitly requested that the whole pre-existing catalogue starts enabled.
    if "offers" in inspect(bind).get_table_names():
        op.execute("UPDATE offers SET enabled = TRUE")
    if "wallet_entries" not in inspect(bind).get_table_names():
        op.create_table("wallet_entries",
          sa.Column("id", sa.Integer(), primary_key=True),
          sa.Column("user_id", sa.BigInteger(), nullable=False, index=True),
          sa.Column("amount", sa.Integer(), nullable=False),
          sa.Column("kind", sa.String(30), nullable=False),
          sa.Column("ref", sa.String(100), nullable=False, unique=True),
          sa.Column("note", sa.Text(), nullable=False, server_default=""),
          sa.Column("created", sa.DateTime(), server_default=sa.func.now()))

def downgrade():
    op.drop_table("wallet_entries")
    op.drop_column("users", "age21")
    for name in ("paid_at", "admin_note"): op.drop_column("payouts", name)
    for name in ("proof_hash", "proof_files", "verification", "reviewed_by", "reviewed_at"): op.drop_column("apps", name)
    for name in ("image_path", "condition_type", "condition_text", "verification_steps", "required_proofs", "network_status", "source_url", "terms_checked_at", "link_param", "notes"):
        op.drop_column("offers", name)
