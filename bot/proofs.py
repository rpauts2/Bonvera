"""Evidence progress rules, independent from Telegram and persistence frameworks."""
from datetime import datetime


def proof_requirements(app, offer=None):
    snap = app.offer_snapshot or {}
    return list(snap.get("proofs") or (getattr(offer, "required_proofs", None) or []))


def proof_progress(app, offer=None):
    required = proof_requirements(app, offer)
    items = [x for x in (app.proof_files or []) if isinstance(x, dict)]
    received = {int(x["proof_index"]) for x in items if x.get("proof_index") is not None}
    legacy = bool(app.proof or items) and not received
    missing = [i for i, _ in enumerate(required) if i not in received]
    # A single legacy generic screenshot can satisfy only a one-step checklist.
    # For multi-step checklists it cannot prove which requirement it represents.
    if legacy and len(required) == 1:
        received = {0}
        missing = []
    return required, received, missing


def proofs_complete(app, offer=None, require_submission=True):
    required, received, missing = proof_progress(app, offer)
    verification = app.verification or {}
    submitted = bool(verification.get("proof_submitted_at"))
    items = [x for x in (app.proof_files or []) if isinstance(x, dict)]
    legacy = bool(app.proof or items) and not any(x.get("proof_index") is not None for x in items)
    if legacy and len(required) == 1:
        if require_submission and not submitted:
            return False, ["Нажми «Отправить на проверку» после загрузки подтверждения"]
        return True, []
    if not required:
        return bool(app.proof or items), ["Подтверждение выполнения условия"] if not (app.proof or items) else []
    if missing or (require_submission and not submitted):
        labels = [required[i] for i in missing]
        if require_submission and not submitted and not missing:
            labels.append("Нажми «Отправить на проверку» после загрузки всех файлов")
        return False, labels
    requested_at = verification.get("more_info_requested_at")
    if requested_at:
        try:
            request_dt = datetime.fromisoformat(requested_at)
            extra = [x for x in items if x.get("uploaded_at") and datetime.fromisoformat(x["uploaded_at"]) >= request_dt]
        except (TypeError, ValueError):
            extra = []
        if not extra:
            return False, ["Дополнительное подтверждение по запросу администратора"]
    return True, []


def awaiting_admin_review(app, offer=None):
    """True only for a complete, newly submitted proof package not yet reviewed."""
    verification = app.verification or {}
    submitted_at = verification.get("proof_submitted_at")
    if not submitted_at:
        return False
    reviewed_at = verification.get("proof_reviewed_at")
    if reviewed_at and submitted_at <= reviewed_at:
        return False
    complete, _ = proofs_complete(app, offer, require_submission=True)
    return complete
