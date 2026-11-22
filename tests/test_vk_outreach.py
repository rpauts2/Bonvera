from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from bot.vk.outreach import is_marketing_eligible, preview_contact_import


def test_contact_import_requires_row_level_consent_evidence():
    csv_text = "vk_user_id,consent_at,consent_source,consent_version,consent_proof\n123456,2026-11-20T10:00:00Z,,,\n"
    preview = preview_contact_import(csv_text)
    assert preview["valid_count"] == 0
    assert preview["errors"][0]["line"] == 2


def test_contact_import_accepts_and_deduplicates_proven_opt_in_vk_ids():
    csv_text = (
        "vk_user_id,consent_at,consent_source,consent_version,consent_proof\n"
        "123456,2026-11-20T10:00:00Z,web-form,2026-11-v1,consent-proof-001\n"
        "123456,2026-11-20T10:00:00Z,web-form,2026-11-v1,consent-proof-001\n"
    )
    preview = preview_contact_import(csv_text)
    assert preview["valid_count"] == 1
    assert preview["duplicate_count"] == 1


def test_campaign_eligibility_requires_current_opt_in_and_no_suppression():
    now = datetime.now(timezone.utc)
    allowed = SimpleNamespace(marketing_consent_at=now, marketing_suppressed=False)
    missing = SimpleNamespace(marketing_consent_at=None, marketing_suppressed=False)
    suppressed = SimpleNamespace(marketing_consent_at=now, marketing_suppressed=True)
    assert is_marketing_eligible(allowed) is True
    assert is_marketing_eligible(missing) is False
    assert is_marketing_eligible(suppressed) is False
