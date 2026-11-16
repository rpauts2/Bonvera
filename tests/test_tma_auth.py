"""Unit tests for the official initData HMAC verification (no DB, no network)."""
import json
import time
from urllib.parse import parse_qsl, urlencode

import pytest

from bot.config import cfg
from bot.tma_auth import InitDataError, verify_init_data, verify_telegram_login
from conftest import sign_init_data

TOKEN = cfg.token


def fields(tg_id: int = 777001, auth_date: int | None = None, **extra) -> dict:
    base = {
        "auth_date": str(auth_date if auth_date is not None else int(time.time())),
        "query_id": "AAHdF6IQAAAAAN0XohDhrOrc",
        "user": json.dumps({"id": tg_id, "first_name": "Test", "username": "testuser"}, separators=(",", ":")),
    }
    base.update(extra)
    return base


def test_valid_signature_passes():
    result = verify_init_data(sign_init_data(fields(), TOKEN), TOKEN)
    assert result["user"]["id"] == 777001
    assert result["auth_date"] > 0
    assert "hash" not in result["fields"]


def test_tampered_field_rejected():
    signed = sign_init_data(fields(), TOKEN)
    pairs = dict(parse_qsl(signed))
    pairs["user"] = json.dumps({"id": 999999, "first_name": "Evil"})
    with pytest.raises(InitDataError) as e:
        verify_init_data(urlencode(pairs), TOKEN)
    assert e.value.code == "bad_signature"


def test_foreign_bot_token_rejected():
    signed = sign_init_data(fields(), "999999:ANOTHER_BOT_TOKEN")
    with pytest.raises(InitDataError) as e:
        verify_init_data(signed, TOKEN)
    assert e.value.code == "bad_signature"


def test_expired_auth_date_rejected():
    old = int(time.time()) - 7200
    with pytest.raises(InitDataError) as e:
        verify_init_data(sign_init_data(fields(auth_date=old), TOKEN), TOKEN)
    assert e.value.code == "expired"


def test_future_auth_date_rejected():
    future = int(time.time()) + 3600
    with pytest.raises(InitDataError) as e:
        verify_init_data(sign_init_data(fields(auth_date=future), TOKEN), TOKEN)
    assert e.value.code == "future_auth_date"


def test_small_future_skew_allowed():
    slightly_future = int(time.time()) + 30
    result = verify_init_data(sign_init_data(fields(auth_date=slightly_future), TOKEN), TOKEN)
    assert result["user"]["id"] == 777001


def test_duplicate_fields_rejected():
    signed = sign_init_data(fields(), TOKEN)
    with pytest.raises(InitDataError) as e:
        verify_init_data(signed + "&auth_date=1", TOKEN)
    assert e.value.code == "duplicate_field"


def test_missing_hash_rejected():
    unsigned = urlencode(fields())
    with pytest.raises(InitDataError) as e:
        verify_init_data(unsigned, TOKEN)
    assert e.value.code == "no_hash"


def test_missing_user_rejected():
    f = fields()
    del f["user"]
    with pytest.raises(InitDataError) as e:
        verify_init_data(sign_init_data(f, TOKEN), TOKEN)
    assert e.value.code == "bad_user"


def test_non_integer_user_id_rejected():
    f = fields()
    f["user"] = json.dumps({"id": "777001", "first_name": "Test"})
    with pytest.raises(InitDataError) as e:
        verify_init_data(sign_init_data(f, TOKEN), TOKEN)
    assert e.value.code == "bad_user"


def test_bad_auth_date_rejected():
    with pytest.raises(InitDataError) as e:
        verify_init_data(sign_init_data(fields(auth_date="abc"), TOKEN), TOKEN)
    assert e.value.code == "bad_auth_date"


def test_zero_auth_date_rejected():
    with pytest.raises(InitDataError) as e:
        verify_init_data(sign_init_data(fields(auth_date=0), TOKEN), TOKEN)
    assert e.value.code == "bad_auth_date"


def test_empty_input_rejected():
    with pytest.raises(InitDataError) as e:
        verify_init_data("", TOKEN)
    assert e.value.code == "empty"
    with pytest.raises(InitDataError):
        verify_init_data(sign_init_data(fields(), TOKEN), "")


def test_signature_field_order_independent():
    f = fields()
    signed = sign_init_data(f, TOKEN)
    pairs = parse_qsl(signed)
    reversed_qs = urlencode(list(reversed(pairs)))
    result = verify_init_data(reversed_qs, TOKEN)
    assert result["user"]["id"] == 777001

def sign_widget(fields: dict, token: str = TOKEN) -> dict:
    import hashlib, hmac
    data = {k: str(v) for k, v in fields.items()}
    check = "\n".join(f"{k}={data[k]}" for k in sorted(data))
    secret = hashlib.sha256(token.encode()).digest()
    data["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return data

def test_valid_telegram_login_widget_signature_passes():
    payload = sign_widget({"id": 777001, "first_name": "Test", "username": "testuser", "auth_date": int(time.time())})
    verified = verify_telegram_login(payload, TOKEN)
    assert verified["id"] == 777001
    assert verified["username"] == "testuser"

def test_telegram_login_widget_rejects_tampering():
    payload = sign_widget({"id": 777001, "first_name": "Test", "auth_date": int(time.time())})
    payload["id"] = "999999"
    with pytest.raises(InitDataError) as exc:
        verify_telegram_login(payload, TOKEN)
    assert exc.value.code == "bad_signature"

def test_telegram_login_widget_rejects_expired_payload():
    payload = sign_widget({"id": 777001, "first_name": "Test", "auth_date": int(time.time()) - 90000})
    with pytest.raises(InitDataError) as exc:
        verify_telegram_login(payload, TOKEN)
    assert exc.value.code == "expired"

def test_telegram_login_widget_rejects_unknown_fields():
    payload = sign_widget({"id": 777001, "first_name": "Test", "auth_date": int(time.time()), "is_admin": True})
    with pytest.raises(InitDataError) as exc:
        verify_telegram_login(payload, TOKEN)
    assert exc.value.code == "unknown_field"
