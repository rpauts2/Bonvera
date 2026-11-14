import os
from dataclasses import dataclass, field
from dotenv import load_dotenv
load_dotenv()
_b = lambda k, d="true": os.getenv(k, d).lower() == "true"

@dataclass
class Cfg:
    token: str = os.getenv("BOT_TOKEN", "")
    admins: list = field(default_factory=lambda: [int(x) for x in os.getenv("ADMINS", "").split(",") if x.strip()])
    db: str = os.getenv("DB_URL", "sqlite+aiosqlite:///bot.db")
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    salt: str = os.getenv("HASH_SALT", "salt")
    phone_key: str = os.getenv("PHONE_ENCRYPTION_KEY", os.getenv("HASH_SALT", "development-only-change-me"))
    pb_secret: str = os.getenv("POSTBACK_SECRET", "secret")
    port: int = int(os.getenv("WEB_PORT", 8080))
    bk: bool = _b("BK_ENABLED", "true"); mfo: bool = _b("MFO_ENABLED", "true"); cpl: bool = _b("CPL_ENABLED", "true")
    ref_pct: int = int(os.getenv("REF_PERCENT", 7))
    booking_h: int = int(os.getenv("BOOKING_HOURS", 48))
    min_wd: int = int(os.getenv("MIN_WITHDRAW", 300))
    max_active: int = int(os.getenv("MAX_ACTIVE", 3))
    webapp_url: str = os.getenv("WEBAPP_URL", "")
    channel_id: str = os.getenv("BONVERA_CHANNEL_ID", "")
    channel_url: str = os.getenv("BONVERA_CHANNEL_URL", "")
    support_url: str = os.getenv("BONVERA_SUPPORT_URL", "")
    tma_session_hours: int = int(os.getenv("TMA_SESSION_HOURS", "24"))

cfg = Cfg()


def validate_runtime_config():
    """Fail fast rather than start a bot with insecure or missing production secrets."""
    errors = []
    if not cfg.token or cfg.token.upper().startswith(("PASTE_", "CHANGE_ME", "GENERATE", "REPLACE")):
        errors.append("BOT_TOKEN не заполнен реальным токеном BotFather")
    if not cfg.admins:
        errors.append("ADMINS пуст: укажи Telegram ID администраторов через запятую")
    for env_name in ("HASH_SALT", "PHONE_ENCRYPTION_KEY", "POSTBACK_SECRET"):
        value = os.getenv(env_name, "")
        if len(value) < 32 or value.upper().startswith(("CHANGE_ME", "REPLACE", "LONG_RANDOM", "GENERATE", "PASTE")):
            errors.append(f"{env_name} должен быть индивидуальным случайным секретом длиной минимум 32 символа")
    if cfg.db.startswith("postgresql"):
        pg = os.getenv("POSTGRES_PASSWORD", "")
        if len(pg) < 24 or pg.upper().startswith(("CHANGE_ME", "REPLACE", "GENERATE", "PASTE")):
            errors.append("POSTGRES_PASSWORD должен быть задан (не менее 24 символов)")
    if errors:
        raise RuntimeError("Конфигурация не готова к запуску:\n- " + "\n- ".join(errors))
