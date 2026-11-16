"""Persist offer-scoped perceptual fingerprints for evidence deduplication."""
from alembic import op
import sqlalchemy as sa
import json

revision = "0007_proof_fingerprints"
down_revision = "0006_deal_messages"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "proof_fingerprints",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("offer_id", sa.Integer(), sa.ForeignKey("offers.id"), nullable=False),
        sa.Column("app_id", sa.Integer(), sa.ForeignKey("apps.id"), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("phash", sa.String(32), nullable=False),
        sa.Column("created", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("offer_id", "phash", name="uq_proof_fingerprint_offer_phash"),
    )
    op.create_index("ix_proof_fingerprints_offer_id", "proof_fingerprints", ["offer_id"])
    op.create_index("ix_proof_fingerprints_app_id", "proof_fingerprints", ["app_id"])
    op.create_index("ix_proof_fingerprints_user_id", "proof_fingerprints", ["user_id"])

    # Backfill all retained historical hashes so old submissions remain protected.
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, offer_id, user_id, proof_hash, proof_files FROM apps")).mappings()
    seen = set()
    for row in rows:
        hashes = set()
        if row["proof_hash"]:
            hashes.add(str(row["proof_hash"]))
        files = row["proof_files"]
        if isinstance(files, str):
            try:
                files = json.loads(files)
            except Exception:
                files = []
        if isinstance(files, list):
            hashes.update(str(item["hash"]) for item in files if isinstance(item, dict) and item.get("hash"))
        for ph in hashes:
            key = (row["offer_id"], ph)
            if key in seen:
                continue
            bind.execute(sa.text(
                "INSERT INTO proof_fingerprints (offer_id, app_id, user_id, phash) "
                "VALUES (:offer_id, :app_id, :user_id, :phash)"
            ), {"offer_id": row["offer_id"], "app_id": row["id"], "user_id": row["user_id"], "phash": ph})
            seen.add(key)


def downgrade():
    op.drop_index("ix_proof_fingerprints_user_id", table_name="proof_fingerprints")
    op.drop_index("ix_proof_fingerprints_app_id", table_name="proof_fingerprints")
    op.drop_index("ix_proof_fingerprints_offer_id", table_name="proof_fingerprints")
    op.drop_table("proof_fingerprints")
