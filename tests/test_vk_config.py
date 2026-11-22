import pytest

from bot.config import cfg, validate_runtime_config


def valid_base_config(monkeypatch):
    monkeypatch.setattr(cfg, "token", "123456:valid-test-token")
    monkeypatch.setattr(cfg, "admins", [123456])
    monkeypatch.setattr(cfg, "db", "sqlite+aiosqlite:///test.db")
    monkeypatch.setenv("HASH_SALT", "a" * 64)
    monkeypatch.setenv("PHONE_ENCRYPTION_KEY", "b" * 64)
    monkeypatch.setenv("POSTBACK_SECRET", "c" * 64)


def test_vk_is_disabled_by_default():
    assert cfg.vk_enabled is False


def test_missing_vk_credentials_do_not_break_telegram_when_vk_disabled(monkeypatch):
    valid_base_config(monkeypatch)
    monkeypatch.setattr(cfg, "vk_enabled", False)
    monkeypatch.setattr(cfg, "vk_group_id", 0)
    monkeypatch.setattr(cfg, "vk_group_token", "")
    monkeypatch.setattr(cfg, "vk_callback_secret", "")
    monkeypatch.setattr(cfg, "vk_confirmation", "")
    validate_runtime_config()


def test_vk_enabled_requires_group_token_and_callback_secrets(monkeypatch):
    valid_base_config(monkeypatch)
    monkeypatch.setattr(cfg, "vk_enabled", True)
    monkeypatch.setattr(cfg, "vk_group_id", 0)
    monkeypatch.setattr(cfg, "vk_group_token", "")
    monkeypatch.setattr(cfg, "vk_callback_secret", "")
    monkeypatch.setattr(cfg, "vk_confirmation", "")
    monkeypatch.setattr(cfg, "vk_public_base_url", "")
    monkeypatch.setattr(cfg, "vk_privacy_url", "")
    with pytest.raises(RuntimeError) as exc:
        validate_runtime_config()
    message = str(exc.value)
    assert "VK_GROUP_ID" in message
    assert "VK_GROUP_TOKEN" in message
    assert "VK_CALLBACK_SECRET" in message
    assert "VK_CONFIRMATION" in message
    assert "VK_PUBLIC_BASE_URL" in message
    assert "VK_PRIVACY_URL" in message
