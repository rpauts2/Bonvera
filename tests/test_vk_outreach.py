from datetime import datetime, timezone
from types import SimpleNamespace

from bot.vk.outreach import is_marketing_eligible, preview_contact_import

HEADER = (
    "vk_user_id,personal_data_consent_at,personal_data_consent_source,"
    "personal_data_consent_version,personal_data_consent_proof,"
    "marketing_consent_at,marketing_consent_source,marketing_consent_version,"
    "marketing_consent_proof"
)


def valid_row(vk_id="123456", suffix="001"):
    return (
        vk_id + ",2026-11-20T10:00:00Z,privacy-form,privacy-v1,privacy-proof-" + suffix
        + ",2026-11-20T10:00:00Z,marketing-form,marketing-v1,marketing-proof-" + suffix
    )


def test_contact_import_requires_row_level_consent_evidence():
    # The personal-data consent proof is deliberately absent.
    csv_text = HEADER + "\n" + (
        "123456,2026-11-20T10:00:00Z,privacy-form,privacy-v1,,"
        "2026-11-20T10:00:00Z,marketing-form,marketing-v1,marketing-proof"
    ) + "\n"
    preview = preview_contact_import(csv_text)
    assert preview["valid_count"] == 0
    assert preview["errors"][0]["line"] == 2


def test_contact_import_accepts_and_deduplicates_proven_opt_in_vk_ids():
    csv_text = HEADER + "\n" + valid_row() + "\n" + valid_row() + "\n"
    preview = preview_contact_import(csv_text)
    assert preview["valid_count"] == 1
    assert preview["duplicate_count"] == 1
    assert preview["errors"] == []


def test_contact_import_requires_both_data_and_advertising_consents():
    csv_text = HEADER + "\n" + (
        "123456,2026-11-20T10:00:00Z,privacy-form,privacy-v1,privacy-proof,"
        "2026-11-20T10:00:00Z,,,,"
    ) + "\n"
    preview = preview_contact_import(csv_text)
    assert preview["valid_count"] == 0
    assert preview["errors"]


def test_campaign_eligibility_requires_current_opt_in_and_no_suppression():
    now = datetime.now(timezone.utc)
    allowed = SimpleNamespace(personal_data_consent_at=now, marketing_consent_at=now, consent_review_status="verified", marketing_suppressed=False)
    missing = SimpleNamespace(personal_data_consent_at=now, marketing_consent_at=None, consent_review_status="verified", marketing_suppressed=False)
    suppressed = SimpleNamespace(personal_data_consent_at=now, marketing_consent_at=now, consent_review_status="verified", marketing_suppressed=True)
    assert is_marketing_eligible(allowed) is True
    assert is_marketing_eligible(missing) is False
    assert is_marketing_eligible(suppressed) is False
    pending = SimpleNamespace(personal_data_consent_at=now, marketing_consent_at=now, consent_review_status="pending_review", marketing_suppressed=False)
    assert is_marketing_eligible(pending) is False
