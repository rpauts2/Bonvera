"""Test session configuration: isolated sqlite DB and test-only secrets.

Environment is set before any bot module import so bot.config/bot.db bind to
the temporary database instead of a developer bot.db.
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_TMP = tempfile.mkdtemp(prefix="bonvera-tests-")
os.environ["DB_URL"] = f"sqlite+aiosqlite:///{_TMP}/test.db"
os.environ["BOT_TOKEN"] = "123456789:TEST_TOKEN_FOR_UNIT_TESTS_ONLY"
os.environ["HASH_SALT"] = "unit-test-salt-0123456789abcdef0123456789abcdef"
os.environ["PHONE_ENCRYPTION_KEY"] = "unit-test-phone-key-0123456789abcdef0123456789"
os.environ["POSTBACK_SECRET"] = "unit-test-postback-secret-0123456789abcdef"
os.environ["BONVERA_CHANNEL_ID"] = ""
os.environ["BONVERA_CHANNEL_URL"] = ""


def sign_init_data(fields: dict, token: str) -> str:
    """Build a correctly signed initData query string (official HMAC protocol)."""
    import hashlib
    import hmac
    from urllib.parse import urlencode

    data_check_string = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    signature = hmac.new(secret, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode({**fields, "hash": signature})