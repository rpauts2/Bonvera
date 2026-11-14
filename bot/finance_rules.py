"""Pure state-transition rules for money operations."""


def clawback_withdrawal_action(status: str) -> str:
    """Return the safe action when a credited lead is revoked."""
    if status == "pending":
        return "cancel_and_release"
    if status == "processing":
        return "freeze_for_manual_review"
    return "no_change"
