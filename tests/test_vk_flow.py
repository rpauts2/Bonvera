from bot.vk.flow import normalize_vk_phone


def test_normalize_vk_phone_accepts_russian_national_and_international_forms():
    assert normalize_vk_phone("8 (900) 123-45-67") == "79001234567"
    assert normalize_vk_phone("+7 900 123 45 67") == "79001234567"
    assert normalize_vk_phone("9001234567") == "79001234567"


def test_normalize_vk_phone_rejects_non_russian_or_invalid_lengths():
    assert normalize_vk_phone("123") is None
    assert normalize_vk_phone("790012345678") is None
    assert normalize_vk_phone("49001234567") is None


def test_payload_action_reads_vk_json_payload():
    from bot.vk.flow import payload_action
    import json

    assert payload_action({"payload": json.dumps({"action": "personal_data_consent"})}) == "personal_data_consent"
    assert payload_action({"payload": {"action": "marketing_opt_out"}}) == "marketing_opt_out"
    assert payload_action({"payload": "not-json"}) == ""
