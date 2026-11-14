"""Stable initial schema, before offer-proof and payout workflow extensions."""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("username", sa.String(64), nullable=True),
        sa.Column("name", sa.String(128), nullable=True),
        sa.Column("phone_hash", sa.String(64), nullable=True),
        sa.Column("referrer_id", sa.BigInteger(), nullable=True),
        sa.Column("adult", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("accepted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("balance", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("banned", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_users_phone_hash", "users", ["phone_hash"])
    op.create_table(
        "banks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.String(40), nullable=False, unique=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("emoji", sa.String(8), nullable=False, server_default="🏦"),
        sa.Column("category", sa.String(10), nullable=False, server_default="cards"),
        sa.Column("sort", sa.Integer(), nullable=False, server_default="100"),
    )
    op.create_index("ix_banks_category", "banks", ["category"])
    op.create_table(
        "offers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("bank_id", sa.Integer(), sa.ForeignKey("banks.id"), nullable=False),
        sa.Column("code", sa.String(60), nullable=False, unique=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("url", sa.Text(), nullable=False, server_default=""),
        sa.Column("action", sa.Text(), nullable=False, server_default=""),
        sa.Column("rules", sa.Text(), nullable=False, server_default=""),
        sa.Column("purchase_min", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("hold", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("age", sa.Integer(), nullable=False, server_default="18"),
        sa.Column("pct", sa.Integer(), nullable=False, server_default="35"),
        sa.Column("kind", sa.String(20), nullable=False, server_default=""),
        sa.Column("allowed", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("forbidden", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("mfo_info", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("approval", sa.String(200), nullable=False, server_default=""),
        sa.Column("slots", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("sort", sa.Integer(), nullable=False, server_default="100"),
    )
    op.create_index("ix_offers_bank_id", "offers", ["bank_id"])
    op.create_index("ix_offers_enabled", "offers", ["enabled"])
    op.create_table(
        "tiers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("offer_id", sa.Integer(), sa.ForeignKey("offers.id"), nullable=False),
        sa.Column("payout", sa.Integer(), nullable=False),
        sa.Column("cashback", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(200), nullable=False, server_default=""),
    )
    op.create_index("ix_tiers_offer_id", "tiers", ["offer_id"])
    op.create_table(
        "apps",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("offer_id", sa.Integer(), sa.ForeignKey("offers.id"), nullable=False),
        sa.Column("tier_id", sa.Integer(), nullable=True),
        sa.Column("subid", sa.String(40), nullable=False, unique=True, server_default=""),
        sa.Column("status", sa.String(12), nullable=False, server_default="new"),
        sa.Column("phone_hash", sa.String(64), nullable=True),
        sa.Column("proof", sa.Text(), nullable=True),
        sa.Column("hold_until", sa.DateTime(), nullable=True),
        sa.Column("payout", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cashback", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("created", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_apps_user_id", "apps", ["user_id"])
    op.create_index("ix_apps_subid", "apps", ["subid"])
    op.create_index("ix_apps_status", "apps", ["status"])
    op.create_index("ix_apps_phone_hash", "apps", ["phone_hash"])
    op.create_table(
        "payouts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("phone", sa.String(20), nullable=False),
        sa.Column("status", sa.String(10), nullable=False, server_default="pending"),
        sa.Column("created", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_payouts_user_id", "payouts", ["user_id"])
    op.create_table(
        "refs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("referrer_id", sa.BigInteger(), nullable=False),
        sa.Column("referee_id", sa.BigInteger(), nullable=False),
        sa.Column("app_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
    )
    op.create_index("ix_refs_referrer_id", "refs", ["referrer_id"])
    op.create_table(
        "postbacks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("subid", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("payout", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("raw", sa.Text(), nullable=False, server_default=""),
        sa.Column("created", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_postbacks_subid", "postbacks", ["subid"])


def downgrade():
    op.drop_table("postbacks")
    op.drop_index("ix_refs_referrer_id", table_name="refs")
    op.drop_table("refs")
    op.drop_index("ix_payouts_user_id", table_name="payouts")
    op.drop_table("payouts")
    op.drop_index("ix_apps_phone_hash", table_name="apps")
    op.drop_index("ix_apps_status", table_name="apps")
    op.drop_index("ix_apps_subid", table_name="apps")
    op.drop_index("ix_apps_user_id", table_name="apps")
    op.drop_table("apps")
    op.drop_index("ix_tiers_offer_id", table_name="tiers")
    op.drop_table("tiers")
    op.drop_index("ix_offers_enabled", table_name="offers")
    op.drop_index("ix_offers_bank_id", table_name="offers")
    op.drop_table("offers")
    op.drop_index("ix_banks_category", table_name="banks")
    op.drop_table("banks")
    op.drop_index("ix_users_phone_hash", table_name="users")
    op.drop_table("users")
