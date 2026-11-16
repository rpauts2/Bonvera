from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT))
DATA = yaml.safe_load((ROOT / "catalog.yaml").read_text(encoding="utf-8"))["offers"]

def test_exact_user_catalog_counts():
    assert len(DATA) == 93
    counts = {cat: sum(x["category"] == cat for x in DATA) for cat in ("cards", "bk", "mfo", "cpl")}
    assert counts == {"cards": 16, "bk": 6, "mfo": 52, "cpl": 19}

def test_offer_codes_are_unique():
    codes = [x["code"] for x in DATA]
    assert len(codes) == len(set(codes))

def test_each_offer_has_unique_asset():
    paths = []
    for offer in DATA:
        base = ROOT / "assets" / "offers" / offer["category"] / offer["code"]
        active = next((base.with_suffix(ext) for ext in (".svg", ".jpg", ".jpeg", ".webp", ".png") if base.with_suffix(ext).is_file()), None)
        assert active is not None, offer["code"]
        minimum_size = 5000 if active.suffix == ".svg" else 8000
        assert active.stat().st_size > minimum_size, offer["code"]
        paths.append(active)
    assert len({p.stem for p in paths}) == 93


def test_all_catalog_offer_images_resolve_to_existing_assets():
    from types import SimpleNamespace
    from bot.services import offer_image_url

    for item in DATA:
        offer = SimpleNamespace(
            image_path=f"assets/offers/{item['category']}/{item['code']}.jpg",
            code=item["code"],
        )
        bank = SimpleNamespace(category=item["category"], slug=item["code"])
        resolved = offer_image_url(offer, bank)
        assert resolved.startswith("/assets/offers/"), item["code"]
        assert (ROOT / resolved.lstrip("/")).is_file(), item["code"]
        if (ROOT / "assets" / "offers" / item["category"] / f"{item['code']}.svg").is_file():
            assert resolved.endswith(".svg"), item["code"]


def test_offer_image_url_prefers_reviewed_svg_and_falls_back_to_jpg(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from bot.services import offer_image_url

    monkeypatch.chdir(tmp_path)
    folder = Path("assets/offers/cards")
    folder.mkdir(parents=True)
    svg = folder / "demo.svg"
    jpg = folder / "demo.jpg"
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg"></svg>', encoding="utf-8")
    jpg.write_bytes(b"legacy")
    # The production seed records the default JPG path in Offer.image_path.
    offer = SimpleNamespace(image_path="assets/offers/cards/demo.jpg", code="demo")
    bank = SimpleNamespace(category="cards", slug="demo")

    assert offer_image_url(offer, bank) == "/assets/offers/cards/demo.svg"
    svg.unlink()
    assert offer_image_url(offer, bank) == "/assets/offers/cards/demo.jpg"

    custom = folder / "custom.jpg"
    custom.write_bytes(b"custom")
    offer.image_path = str(custom)
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg"></svg>', encoding="utf-8")
    assert offer_image_url(offer, bank) == "/assets/offers/cards/custom.jpg"

def test_user_reward_and_hold_are_exact_and_nonzero():
    assert all(x["reward"] > 0 for x in DATA)
    assert all(x["hold"] in (14, 30, 45, 60) for x in DATA)

def test_age_ranges_are_exact():
    by_code = {x["code"]: (x["age_min"], x["age_max"]) for x in DATA}
    assert by_code["marafon_bet"] == (21, 120)
    assert by_code["mikrorezerv"] == (21, 75)
    assert by_code["kviku"] == (18, 65)
    assert by_code["vozmika"] == (18, 65)
    assert by_code["davaka"] == (18, 75)
    for code in ("baltbet", "melbet", "mts_dengi", "alfa_bank_apelsinovaya"):
        assert by_code[code] == (18, 120)
    assert sum(1 for x in DATA if (x["age_min"],x["age_max"]) == (18,120)) == 88

def test_bk_rewards_separate_from_network_commission_and_promos():
    bks = [x for x in DATA if x["category"] == "bk"]
    assert {x["name"] for x in bks} == {"PARI", "Марафон Бет", "Fonbet", "Мелбет", "Балтбет", "Леон"}
    # Affiliate URL, cashback reward and bookmaker promo are stored as distinct data.
    assert all(x["url"].startswith("https://") for x in bks)
    assert all(x["reward"] > 0 and x["hold"] > 0 and x["source_url"].startswith("https://") for x in bks)
    assert "фрибет" in next(x for x in bks if x["name"] == "PARI")["note"].lower()
    assert "25 000" in next(x for x in bks if x["name"] == "Марафон Бет")["note"]
    assert "Не совмещай эту приветственную акцию" in next(x for x in bks if x["name"] == "Балтбет")["note"]


def test_mfo_requires_fio_and_actual_loan_disbursement():
    from bot.evidence import required_proofs
    items = required_proofs("mfo", "Выдача займа новому клиенту")
    assert len(items) == 2
    assert "ФИО полностью" in items[0]
    assert "Займ выдан" in items[1]
    assert "Одобрено" in items[0]
    assert "Одобрено» недостаточно" in items[1]


def test_card_proofs_include_fio_and_transaction_for_purchase_cd():
    from bot.evidence import required_proofs
    items = required_proofs("cards", "Выдача карты + покупка от 1 000 ₽")
    assert len(items) == 2
    assert "ФИО видно полностью" in items[0]
    assert "дата, сумма и название магазина" in items[1]
    without_purchase = required_proofs("cards", "Только выдача карты")
    assert len(without_purchase) == 1


def test_bookmaker_proofs_cover_identity_deposit_and_settled_bet():
    from bot.evidence import required_proofs
    items = required_proofs("bk", "Регистрация + депозит + ставка")
    assert len(items) == 3
    assert "ФИО видно полностью" in items[0]
    assert "сумма депозита" in items[1]
    assert "статус расчёта" in items[2]


def test_proof_checklist_requires_each_step_and_submission():
    from types import SimpleNamespace
    from bot.proofs import proofs_complete
    required = ["ФИО/статус займа", "Фактическая выдача"]
    app = SimpleNamespace(offer_snapshot={"proofs": required}, proof_files=[], proof=None, verification={})
    ok, missing = proofs_complete(app)
    assert not ok and len(missing) == 2
    app.proof_files = [
        {"proof_index": 0, "label": required[0], "file_id": "file1"},
        {"proof_index": 1, "label": required[1], "file_id": "file2"},
    ]
    ok, missing = proofs_complete(app)
    assert not ok and "Отправить на проверку" in missing[0]
    app.verification = {"proof_submitted_at": "2026-11-14T10:00:00"}
    ok, missing = proofs_complete(app)
    assert ok and not missing


def test_followup_proof_request_requires_new_additional_file():
    from types import SimpleNamespace
    from bot.proofs import proofs_complete
    requested_at = "2026-11-14T10:00:00"
    app = SimpleNamespace(
        offer_snapshot={"proofs": ["Профиль", "Операция"]}, proof=None,
        proof_files=[
            {"proof_index": 0, "file_id": "1", "uploaded_at": "2026-11-14T09:00:00"},
            {"proof_index": 1, "file_id": "2", "uploaded_at": "2026-11-14T09:01:00"},
        ],
        verification={"more_info_requested_at": requested_at}
    )
    ok, missing = proofs_complete(app, require_submission=False)
    assert not ok and "Дополнительное подтверждение" in missing[0]
    app.proof_files.append({"proof_index": None, "file_id": "3", "uploaded_at": "2026-11-14T10:05:00"})
    ok, missing = proofs_complete(app, require_submission=False)
    assert ok and not missing


def test_clawback_withdrawal_policy_never_pays_a_processing_request_blindly():
    from bot.finance_rules import clawback_withdrawal_action
    assert clawback_withdrawal_action("pending") == "cancel_and_release"
    assert clawback_withdrawal_action("processing") == "freeze_for_manual_review"
    assert clawback_withdrawal_action("review_required") == "no_change"
    assert clawback_withdrawal_action("paid") == "no_change"


def test_legacy_single_proof_does_not_bypass_multi_step_review():
    from types import SimpleNamespace
    from bot.proofs import proofs_complete, proof_progress
    app = SimpleNamespace(
        offer_snapshot={"proofs": ["ФИО и одобрение МФО", "Фактическая выдача займа"]},
        proof="legacy-file-id", proof_files=[], verification={}
    )
    required, received, missing = proof_progress(app)
    assert received == set()
    assert missing == [0, 1]
    ok, labels = proofs_complete(app)
    assert not ok
    assert len(labels) == 2


def test_evidence_checklists_exist_for_all_93_offers():
    from bot.evidence import required_proofs, verification
    for offer in DATA:
        proofs = required_proofs(offer["category"], offer["condition"], offer.get("kind", ""))
        steps = verification(offer["category"], offer["condition"], offer.get("kind", ""))
        assert proofs and steps, offer["code"]
        if offer["category"] == "mfo":
            assert len(proofs) == 2, offer["code"]
            assert "ФИО полностью" in proofs[0]
            assert "Займ выдан" in proofs[1]
        elif offer["category"] == "bk":
            assert len(proofs) == 3, offer["code"]
        elif offer["category"] == "cpl":
            assert len(proofs) == 1, offer["code"]
        elif offer["category"] == "cards":
            assert len(proofs) >= 1, offer["code"]


def test_all_purchase_cards_require_transaction_proof():
    from bot.evidence import required_proofs
    cards = [o for o in DATA if o["category"] == "cards"]
    for offer in cards:
        proofs = required_proofs("cards", offer["condition"])
        condition = offer["condition"].lower()
        if "покупк" in condition or "расход" in condition:
            assert len(proofs) >= 2, offer["code"]
            assert "дата, сумма" in proofs[1], offer["code"]


def test_followup_can_fill_a_missing_indexed_requirement():
    from types import SimpleNamespace
    from bot.proofs import proofs_complete
    app = SimpleNamespace(
        offer_snapshot={"proofs": ["Профиль с ФИО", "Подтверждение операции"]},
        proof=None,
        proof_files=[
            {"proof_index": 0, "file_id": "1", "uploaded_at": "2026-11-14T09:00:00"},
            {"proof_index": 1, "file_id": "2", "uploaded_at": "2026-11-14T10:05:00"},
        ],
        verification={"more_info_requested_at": "2026-11-14T10:00:00"},
    )
    ok, missing = proofs_complete(app, require_submission=False)
    assert ok and not missing


def test_placeholder_env_secrets_are_rejected(monkeypatch):
    from bot.config import cfg, validate_runtime_config
    monkeypatch.setattr(cfg, "token", "123456:real-shaped-token")
    monkeypatch.setattr(cfg, "admins", [123])
    monkeypatch.setattr(cfg, "db", "sqlite+aiosqlite:///test.db")
    monkeypatch.setenv("HASH_SALT", "GENERATE_64_HEX_CHARS")
    monkeypatch.setenv("PHONE_ENCRYPTION_KEY", "GENERATE_64_HEX_CHARS_AND_BACKUP_IT")
    monkeypatch.setenv("POSTBACK_SECRET", "GENERATE_64_HEX_CHARS")
    monkeypatch.setenv("POSTGRES_PASSWORD", "GENERATE_64_HEX_CHARS")
    try:
        validate_runtime_config()
    except RuntimeError as exc:
        message = str(exc)
        assert "HASH_SALT" in message
        assert "PHONE_ENCRYPTION_KEY" in message
        assert "POSTBACK_SECRET" in message
    else:
        raise AssertionError("placeholder secrets must never pass runtime validation")


def test_legacy_single_proof_still_requires_explicit_submission():
    from types import SimpleNamespace
    from bot.proofs import proofs_complete
    app = SimpleNamespace(
        offer_snapshot={"proofs": ["Подтверждение одного шага"]},
        proof="legacy-file-id", proof_files=[], verification={}
    )
    complete, missing = proofs_complete(app, require_submission=True)
    assert not complete
    assert "Отправить на проверку" in missing[0]
    app.verification = {"proof_submitted_at": "2026-11-14T10:00:00"}
    complete, missing = proofs_complete(app, require_submission=True)
    assert complete and not missing


def test_new_hold_proof_package_enters_review_queue_once():
    from types import SimpleNamespace
    from bot.proofs import awaiting_admin_review
    required = ["Профиль с ФИО", "Подтверждение операции"]
    app = SimpleNamespace(
        status="hold", offer_snapshot={"proofs": required},
        proof_files=[
            {"proof_index": 0, "file_id": "a", "uploaded_at": "2026-11-14T10:01:00"},
            {"proof_index": 1, "file_id": "b", "uploaded_at": "2026-11-14T10:02:00"},
        ], proof=None,
        verification={"proof_submitted_at": "2026-11-14T10:03:00"}
    )
    assert awaiting_admin_review(app)
    app.verification["proof_reviewed_at"] = "2026-11-14T10:03:00"
    assert not awaiting_admin_review(app)
    app.verification["proof_submitted_at"] = "2026-11-14T10:04:00"
    assert awaiting_admin_review(app)


def test_material_bk_changes_require_fresh_written_approval():
    from bot.offer_rules import bk_approval_must_be_reset
    before = {
        "name": "PARI", "condition": "Регистрация + депозит от 500 ₽",
        "network_payout": 5200, "user_reward": 1800, "hold_days": 60,
        "minimum": 500, "age_min": 18, "age_max": 120,
        "tracking_param": "subid", "partner_url": "https://partner.example/a",
        "source_url": "https://pari.ru/rules",
    }
    after = dict(before)
    assert not bk_approval_must_be_reset("bk", before, after)
    after["partner_url"] = "https://partner.example/b"
    assert bk_approval_must_be_reset("bk", before, after)
    assert not bk_approval_must_be_reset("cards", before, after)


def test_alembic_chain_has_one_latest_head():
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    cfg = Config(str(ROOT / "alembic.ini"))
    scripts = ScriptDirectory.from_config(cfg)
    assert scripts.get_heads() == ["0006_deal_messages"]
    revisions = {rev.revision: rev.down_revision for rev in scripts.walk_revisions()}
    assert revisions["0006_deal_messages"] == "0005_tma_sessions"
    assert revisions["0005_tma_sessions"] == "0004_offer_audit"
    assert revisions["0004_offer_audit"] == "0003_age_withdrawal_audit"
