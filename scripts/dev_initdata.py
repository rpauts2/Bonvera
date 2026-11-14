"""Generate a signed Telegram initData for LOCAL Mini App development.

Usage:
    python scripts/dev_initdata.py <telegram_id> [username]

Reads BOT_TOKEN from the environment or .env. Prints an initData string to
paste into the dev login screen (the ErrorScreen input shown when the app is
opened outside Telegram). The signature uses the official HMAC algorithm, so
the local backend accepts it exactly like a real Telegram launch.

Development only: never paste production tokens into chats or logs.
"""
import hashlib
import hmac
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]


def load_token() -> str:
    import os

    token = os.getenv("BOT_TOKEN", "")
    if not token:
        env = ROOT / ".env"
        if env.exists():
            for line in env.read_text(encoding="utf-8").splitlines():
                if line.startswith("BOT_TOKEN="):
                    token = line.split("=", 1)[1].strip()
                    break
    if not token or token.upper().startswith(("PASTE_", "CHANGE_ME")):
        sys.exit("BOT_TOKEN не задан: укажи его в .env или окружении.")
    return token


def sign_init_data(fields: dict, token: str) -> str:
    data_check_string = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    signature = hmac.new(secret, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode({**fields, "hash": signature})


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    tg_id = int(sys.argv[1])
    username = sys.argv[2] if len(sys.argv) > 2 else "dev_user"
    fields = {
        "auth_date": str(int(time.time())),
        "query_id": "AAHdF6IQAAAAAN0XohDhrOrc",
        "user": json.dumps({"id": tg_id, "first_name": "Dev", "username": username}, separators=(",", ":")),
    }
    print(sign_init_data(fields, load_token()))


if __name__ == "__main__":
    main()