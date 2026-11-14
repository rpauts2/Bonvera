"""Pure validation rules for editable partner offers."""

BK_APPROVAL_FIELDS = (
    "name", "condition", "network_payout", "user_reward", "hold_days",
    "minimum", "age_min", "age_max", "tracking_param", "partner_url", "source_url",
)


def bk_approval_must_be_reset(category: str, before: dict, after: dict) -> bool:
    """Require a fresh written approval after any material BK offer change."""
    if category != "bk":
        return False
    return any(before.get(key) != after.get(key) for key in BK_APPROVAL_FIELDS)
