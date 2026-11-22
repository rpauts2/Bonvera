from datetime import datetime
import asyncio
from pathlib import Path
from sqlalchemy import BigInteger, String, Integer, Boolean, DateTime, ForeignKey, Text, JSON, func, select, inspect, UniqueConstraint, CheckConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from bot.config import cfg

engine = create_async_engine(cfg.db, echo=False)
Session = async_sessionmaker(engine, expire_on_commit=False)

class Base(DeclarativeBase): pass

NEW, PROOF, HOLD, CONFIRMED, PAID, REJECTED, EXPIRED = "new","proof","hold","confirmed","paid","rejected","expired"
RU = {NEW:"🕐 Оформляешь", PROOF:"📤 На проверке", HOLD:"⏳ Холд", CONFIRMED:"✅ Подтверждено",
      PAID:"💸 Выплачено", REJECTED:"❌ Отклонено", EXPIRED:"⌛️ Истекло"}
CAT_RU = {"cards":"💳 Карты", "bk":"⚽ Ставки", "mfo":"🏦 Займы", "cpl":"📝 Заявки"}

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str | None] = mapped_column(String(64))
    name: Mapped[str | None] = mapped_column(String(128))
    phone_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    referrer_id: Mapped[int | None] = mapped_column(BigInteger)
    adult: Mapped[bool] = mapped_column(Boolean, default=False)
    age21: Mapped[bool] = mapped_column(Boolean, default=False)
    age_years: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sbp_bank: Mapped[str] = mapped_column(String(80), default="")
    sbp_phone: Mapped[str] = mapped_column(String(200), default="")  # Fernet encrypted
    accepted: Mapped[bool] = mapped_column(Boolean, default=False)
    balance: Mapped[int] = mapped_column(Integer, default=0)
    banned: Mapped[bool] = mapped_column(Boolean, default=False)
    created: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    notif_read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

class Bank(Base):
    __tablename__ = "banks"
    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    emoji: Mapped[str] = mapped_column(String(8), default="🏦")
    category: Mapped[str] = mapped_column(String(10), default="cards", index=True)
    sort: Mapped[int] = mapped_column(Integer, default=100)

class Offer(Base):
    __tablename__ = "offers"
    id: Mapped[int] = mapped_column(primary_key=True)
    bank_id: Mapped[int] = mapped_column(ForeignKey("banks.id"))
    code: Mapped[str] = mapped_column(String(60), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    url: Mapped[str] = mapped_column(Text, default="")
    action: Mapped[str] = mapped_column(Text, default="")
    rules: Mapped[str] = mapped_column(Text, default="")
    purchase_min: Mapped[int] = mapped_column(Integer, default=0)
    hold: Mapped[int] = mapped_column(Integer, default=30)
    age: Mapped[int] = mapped_column(Integer, default=18)  # legacy minimum age
    age_min: Mapped[int] = mapped_column(Integer, default=18)
    age_max: Mapped[int] = mapped_column(Integer, default=120)
    pct: Mapped[int] = mapped_column(Integer, default=35)
    kind: Mapped[str] = mapped_column(String(20), default="")      # cpl: заявка | карта
    allowed: Mapped[list] = mapped_column(JSON, default=list)
    forbidden: Mapped[list] = mapped_column(JSON, default=list)
    mfo_info: Mapped[dict] = mapped_column(JSON, default=dict)     # psk, rate, term, registry
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    approval: Mapped[str] = mapped_column(String(200), default="")
    slots: Mapped[int] = mapped_column(Integer, default=50)
    sort: Mapped[int] = mapped_column(Integer, default=100)
    image_path: Mapped[str] = mapped_column(String(255), default="")
    condition_type: Mapped[str] = mapped_column(String(30), default="custom")
    condition_text: Mapped[str] = mapped_column(Text, default="")
    verification_steps: Mapped[list] = mapped_column(JSON, default=list)
    required_proofs: Mapped[list] = mapped_column(JSON, default=list)
    network_status: Mapped[str] = mapped_column(String(30), default="needs_approval")
    source_url: Mapped[str] = mapped_column(Text, default="")
    terms_checked_at: Mapped[datetime | None] = mapped_column(DateTime)
    link_param: Mapped[str] = mapped_column(String(40), default="subid")
    notes: Mapped[str] = mapped_column(Text, default="")

class Tier(Base):
    __tablename__ = "tiers"
    id: Mapped[int] = mapped_column(primary_key=True)
    offer_id: Mapped[int] = mapped_column(ForeignKey("offers.id"), index=True)
    payout: Mapped[int] = mapped_column(Integer)
    cashback: Mapped[int] = mapped_column(Integer)
    label: Mapped[str] = mapped_column(String(200), default="")

class App(Base):
    __tablename__ = "apps"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    offer_id: Mapped[int] = mapped_column(ForeignKey("offers.id"))
    tier_id: Mapped[int | None] = mapped_column(Integer)
    subid: Mapped[str] = mapped_column(String(40), unique=True, index=True, default="")
    status: Mapped[str] = mapped_column(String(12), default=NEW, index=True)
    phone_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    proof: Mapped[str | None] = mapped_column(Text)
    proof_hash: Mapped[str | None] = mapped_column(String(32), index=True)
    hold_until: Mapped[datetime | None] = mapped_column(DateTime)
    payout: Mapped[int] = mapped_column(Integer, default=0)
    cashback: Mapped[int] = mapped_column(Integer, default=0)
    reason: Mapped[str] = mapped_column(Text, default="")
    offer_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    reminder_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    hold_alerted_at: Mapped[datetime | None] = mapped_column(DateTime)
    proof_files: Mapped[list] = mapped_column(JSON, default=list)
    verification: Mapped[dict] = mapped_column(JSON, default=dict)
    reviewed_by: Mapped[int | None] = mapped_column(BigInteger)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

class PayoutReq(Base):
    __tablename__ = "payouts"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    amount: Mapped[int] = mapped_column(Integer)
    phone: Mapped[str] = mapped_column(String(200))   # Fernet encrypted
    bank: Mapped[str] = mapped_column(String(80), default="")
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    paid_at: Mapped[datetime | None] = mapped_column(DateTime)
    admin_note: Mapped[str] = mapped_column(Text, default="")
    processed_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

class RefAcc(Base):
    __tablename__ = "refs"
    id: Mapped[int] = mapped_column(primary_key=True)
    referrer_id: Mapped[int] = mapped_column(BigInteger, index=True)
    referee_id: Mapped[int] = mapped_column(BigInteger)
    app_id: Mapped[int] = mapped_column(Integer)
    amount: Mapped[int] = mapped_column(Integer)

class PbLog(Base):
    __tablename__ = "postbacks"
    id: Mapped[int] = mapped_column(primary_key=True)
    subid: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(20))
    payout: Mapped[int] = mapped_column(Integer, default=0)
    raw: Mapped[str] = mapped_column(Text, default="")
    created: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

async def init_db():
    """Apply the Alembic chain before normal application queries start.

    Existing installations from pre-Alembic releases are detected and stamped at
    the stable base revision before upgrading. The old create_all/ALTER TABLE
    compatibility path is intentionally removed to keep one schema authority.
    """
    from alembic import command
    from alembic.config import Config

    root = Path(__file__).resolve().parent.parent
    alembic_cfg = Config(str(root / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(root / "alembic"))
    alembic_cfg.set_main_option("sqlalchemy.url", cfg.db.replace("%", "%%"))

    async with engine.connect() as conn:
        tables = await conn.run_sync(lambda sync_conn: set(inspect(sync_conn).get_table_names()))
    has_version = "alembic_version" in tables
    has_legacy_core = {"users", "banks", "offers"}.issubset(tables)

    def upgrade_schema():
        if not has_version and has_legacy_core:
            # Prior releases created base tables without recording migration history.
            # Stamp only the immutable initial schema, then apply additive revisions.
            command.stamp(alembic_cfg, "0001_initial")
        command.upgrade(alembic_cfg, "head")

    await asyncio.to_thread(upgrade_schema)

    # Encrypt legacy plaintext phone values once, using the configured stable key.
    from bot.logic import phone_decrypt, phone_encrypt, phone_norm
    async with Session() as s:
        rows = (await s.execute(select(PayoutReq))).scalars().all()
        users = (await s.execute(select(User).where(User.sbp_phone != ""))).scalars().all()
        changed = False
        for row in rows:
            if not row.phone:
                continue
            decoded = phone_decrypt(row.phone)
            if decoded == row.phone:
                legacy = phone_norm(row.phone)
                if len(legacy) != 11 or not legacy.isdigit():
                    raise RuntimeError("Не удалось расшифровать телефон выплаты. Проверь PHONE_ENCRYPTION_KEY; не меняй ключ после запуска.")
                row.phone = phone_encrypt(legacy); changed = True
        for user in users:
            if not user.sbp_phone:
                continue
            decoded = phone_decrypt(user.sbp_phone)
            if decoded == user.sbp_phone:
                legacy = phone_norm(user.sbp_phone)
                if len(legacy) != 11 or not legacy.isdigit():
                    raise RuntimeError("Не удалось расшифровать телефон СБП. Проверь PHONE_ENCRYPTION_KEY; не меняй ключ после запуска.")
                user.sbp_phone = phone_encrypt(legacy); changed = True
        if changed:
            await s.commit()


class WalletEntry(Base):
    __tablename__ = "wallet_entries"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    amount: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(30))
    ref: Mapped[str] = mapped_column(String(100), unique=True)
    note: Mapped[str] = mapped_column(Text, default="")
    created: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

class CatalogState(Base):
    __tablename__ = "catalog_state"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(String(200), default="")


class BroadcastCampaign(Base):
    __tablename__ = "broadcast_campaigns"
    id: Mapped[int] = mapped_column(primary_key=True)
    admin_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_message_id: Mapped[int] = mapped_column(Integer, nullable=False)
    audience: Mapped[str] = mapped_column(String(20), nullable=False)
    recipient_count: Mapped[int] = mapped_column(Integer, default=0)
    sent_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    created: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class DealEvent(Base):
    __tablename__ = "deal_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    app_id: Mapped[int] = mapped_column(ForeignKey("apps.id"), index=True)
    actor_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    event: Mapped[str] = mapped_column(String(40))
    from_status: Mapped[str] = mapped_column(String(20), default="")
    to_status: Mapped[str] = mapped_column(String(20), default="")
    comment: Mapped[str] = mapped_column(Text, default="")
    created: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

class PayoutEvent(Base):
    __tablename__ = "payout_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    payout_id: Mapped[int] = mapped_column(ForeignKey("payouts.id"), index=True)
    actor_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    event: Mapped[str] = mapped_column(String(40))
    from_status: Mapped[str] = mapped_column(String(20), default="")
    to_status: Mapped[str] = mapped_column(String(20), default="")
    comment: Mapped[str] = mapped_column(Text, default="")
    created: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class OfferEvent(Base):
    __tablename__ = "offer_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    offer_id: Mapped[int] = mapped_column(ForeignKey("offers.id"), index=True)
    actor_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    event: Mapped[str] = mapped_column(String(40))
    details: Mapped[str] = mapped_column(Text, default="")
    created: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AdminAuditEvent(Base):
    __tablename__ = "admin_audit_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    target_type: Mapped[str] = mapped_column(String(30), nullable=False)
    target_id: Mapped[str] = mapped_column(String(80), nullable=False)
    details: Mapped[str] = mapped_column(Text, default="")
    created: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class TmaSession(Base):
    __tablename__ = "tma_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    created: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    expires: Mapped[datetime] = mapped_column(DateTime)


class DealMessage(Base):
    __tablename__ = "deal_messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    app_id: Mapped[int] = mapped_column(ForeignKey("apps.id"), index=True)
    actor_id: Mapped[int] = mapped_column(BigInteger)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    body: Mapped[str] = mapped_column(Text)
    created: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ProofFingerprint(Base):
    __tablename__ = "proof_fingerprints"
    id: Mapped[int] = mapped_column(primary_key=True)
    offer_id: Mapped[int] = mapped_column(ForeignKey("offers.id"), nullable=False, index=True)
    app_id: Mapped[int] = mapped_column(ForeignKey("apps.id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    phash: Mapped[str] = mapped_column(String(32), nullable=False)
    created: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    __table_args__ = (
        UniqueConstraint("offer_id", "phash", name="uq_proof_fingerprint_offer_phash"),
    )



# VK acquisition channel. These identities are intentionally separate from Telegram User IDs.
class VkContact(Base):
    __tablename__ = "vk_contacts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vk_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    first_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    phone_encrypted: Mapped[str | None] = mapped_column(String(500), nullable=True)
    phone_hash: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    flow_state: Mapped[str] = mapped_column(String(40), default="awaiting_personal_data_consent")
    personal_data_consent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    personal_data_consent_version: Mapped[str] = mapped_column(String(40), default="")
    marketing_consent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    marketing_consent_version: Mapped[str] = mapped_column(String(40), default="")
    marketing_consent_source: Mapped[str] = mapped_column(String(120), default="")
    marketing_suppressed: Mapped[bool] = mapped_column(Boolean, default=False)
    source_campaign: Mapped[str] = mapped_column(String(80), default="")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    created: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class VkConsentEvent(Base):
    __tablename__ = "vk_consent_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("vk_contacts.id"), index=True)
    consent_type: Mapped[str] = mapped_column(String(32), nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    text_version: Mapped[str] = mapped_column(String(40), default="")
    source: Mapped[str] = mapped_column(String(120), default="")
    proof_reference: Mapped[str] = mapped_column(String(255), default="")
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class VkOfferSlot(Base):
    __tablename__ = "vk_offer_slots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slot_number: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    advertiser_name: Mapped[str] = mapped_column(String(160), default="")
    title: Mapped[str] = mapped_column(String(160), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    target_url: Mapped[str] = mapped_column(Text, default="")
    tracking_param: Mapped[str] = mapped_column(String(40), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    __table_args__ = (
        CheckConstraint("slot_number BETWEEN 1 AND 5", name="ck_vk_offer_slots_number"),
        CheckConstraint(
            "(slot_number BETWEEN 1 AND 4 AND kind = 'mfo_offer') OR "
            "(slot_number = 5 AND kind = 'storefront')",
            name="ck_vk_offer_slots_kind",
        ),
    )


class VkCampaign(Base):
    __tablename__ = "vk_campaigns"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    admin_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    cta_label: Mapped[str] = mapped_column(String(80), default="Начать")
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    audience_type: Mapped[str] = mapped_column(String(32), default="opted_in")
    advertiser_name: Mapped[str] = mapped_column(String(200), default="")
    advertiser_inn: Mapped[str] = mapped_column(String(20), default="")
    warning_text: Mapped[str] = mapped_column(String(240), default="Оценивайте свои финансовые возможности и риски.")
    erid: Mapped[str] = mapped_column(String(120), default="")
    targeting_json: Mapped[dict] = mapped_column(JSON, default=dict)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    recipient_count: Mapped[int] = mapped_column(Integer, default=0)
    sent_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    created: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class VkCampaignRecipient(Base):
    __tablename__ = "vk_campaign_recipients"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("vk_campaigns.id"), index=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("vk_contacts.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)
    last_error_code: Mapped[str] = mapped_column(String(80), default="")
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    __table_args__ = (
        UniqueConstraint("campaign_id", "contact_id", name="uq_vk_campaign_recipient"),
    )


class VkClick(Base):
    __tablename__ = "vk_clicks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("vk_contacts.id"), index=True, nullable=True)
    slot_number: Mapped[int] = mapped_column(Integer, nullable=False)
    campaign_id: Mapped[int | None] = mapped_column(ForeignKey("vk_campaigns.id"), index=True, nullable=True)
    source: Mapped[str] = mapped_column(String(80), default="")
    destination_domain: Mapped[str] = mapped_column(String(255), default="")
    outcome: Mapped[str] = mapped_column(String(24), default="created")
    created: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
