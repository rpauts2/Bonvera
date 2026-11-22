from bot.vk.copy_policy import validate_campaign_copy


def test_campaign_copy_requires_advertiser_and_mandatory_warning():
    result = validate_campaign_copy(
        "Предложения микрофинансовых организаций. Ознакомьтесь с условиями.",
        advertiser_name="",
        warning_text="",
    )
    assert result["ok"] is False
    assert "advertiser" in result["errors"]
    assert "warning" in result["errors"]


def test_campaign_copy_blocks_unverified_preapproval_claims():
    for text in [
        "Вам одобрен займ до 30000 рублей!",
        "Одобряем всем без исключения.",
        "100% одобрение даже с плохой кредитной историей.",
        "Вам предодобрен займ.",
    ]:
        result = validate_campaign_copy(
            text,
            advertiser_name="ООО Рекламодатель",
            warning_text="Оценивайте свои финансовые возможности и риски.",
        )
        assert result["ok"] is False
        assert "approval_claim" in result["errors"]


def test_campaign_copy_accepts_non_deceptive_offer_with_advertiser_and_warning():
    result = validate_campaign_copy(
        "Посмотрите предложения микрофинансовых организаций и ознакомьтесь с условиями.",
        advertiser_name="ООО Рекламодатель",
        warning_text="Оценивайте свои финансовые возможности и риски.",
    )
    assert result["ok"] is True
    assert result["errors"] == []


def test_campaign_copy_requires_warning_to_occupy_at_least_five_percent():
    result = validate_campaign_copy(
        "Предложение МФО. " * 100,
        advertiser_name="ООО Рекламодатель",
        warning_text="Оценивайте свои финансовые возможности и риски.",
    )
    assert result["ok"] is False
    assert "warning_area_below_five_percent" in result["errors"]
