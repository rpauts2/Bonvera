"""Политика хранения доказательств и мониторинг живости сервиса.

Проверяем, что файлы закрытых сделок удаляются по сроку, незакрытые живут
дольше, метаданные и события аудита остаются, а выгрузка администратора
собирает комплект в архив.
"""
import os
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from bot import monitoring, tma_files
from bot.config import cfg
from bot.db import App, Bank, DealEvent, Offer, PayoutReq, Session, Tier
from bot.retention import purge_expired_evidence
from bot.logic import phone_encrypt
from test_tma_api import (  # noqa: F401  (fixtures reused per-module)
    BotStub, _reset_limiters, client, db, get_json, login, loop, post_json, put_json,
)


@pytest.fixture(scope="module")
def ret_offers(loop, db):  # noqa: F811
    async def seed():
        async with Session() as s:
            if (await s.execute(select(Offer).where(Offer.code == "ret_card"))).scalar_one_or_none():
                return
            bank = Bank(slug="retbank", name="Retention Bank", category="cards")
            s.add(bank)
            await s.flush()
            offer = Offer(
                bank_id=bank.id, code="ret_card", name="Оффер для ретенции", enabled=True,
                url="https://partner.example/ret", slots=10, hold=30,
            )
            s.add(offer)
            await s.flush()
            s.add(Tier(offer_id=offer.id, payout=1000, cashback=500))
            await s.commit()

    loop.run_until_complete(seed())
    yield


@pytest.fixture
def proof_dir(tmp_path, monkeypatch):
    """Изолированное хранилище доказательств вместо боевого data/tma_proofs."""
    folder = tmp_path / "tma_proofs"
    folder.mkdir()
    monkeypatch.setattr(tma_files, "PROOF_DIR", folder)
    return folder


def _make_app(loop, *, status: str, days_old: int, files: int = 1) -> int:
    """Создаёт сделку с загруженными доказательствами и возвращает её id."""
    async def create():
        async with Session() as s:
            offer = (await s.execute(select(Offer).where(Offer.code == "ret_card"))).scalar_one()
            user = (await s.execute(select(App).limit(1))).scalars().first()
            app = App(
                user_id=1, offer_id=offer.id, status=status, subid=f"ret-{status}-{days_old}-{files}",
                created=datetime.utcnow() - timedelta(days=days_old),
                proof_files=[], offer_snapshot={"name": "Оффер для ретенции"},
            )
            s.add(app)
            await s.flush()
            items = []
            for index in range(files):
                data = b"%PDF-1.4 proof" + str(index).encode()
                storage, _ctype = tma_files.store_proof(app.id, f"proof{index}.pdf", data)
                items.append({
                    "file_id": None, "storage": storage, "source": "tma", "kind": "document",
                    "name": f"proof{index}.pdf", "hash": "a" * 32, "proof_index": index,
                    "label": "Скриншот активации", "duplicate_suspected": False,
                    "duplicate_matches": [], "uploaded_at": datetime.utcnow().isoformat(),
                })
            app.proof_files = items
            await s.commit()
            return app.id

    app_id = loop.run_until_complete(create())
    return app_id


def _files_on_disk(proof_dir) -> int:
    return sum(1 for path in proof_dir.rglob("*") if path.is_file())


def test_closed_deal_evidence_is_deleted_after_the_retention_period(loop, client, ret_offers, proof_dir, monkeypatch):
    monkeypatch.setattr(cfg, "proof_retention_days", 180)
    monkeypatch.setattr(cfg, "proof_open_grace_days", 365)

    app_id = _make_app(loop, status="paid", days_old=200)

    async def run():
        return await purge_expired_evidence()

    summary = loop.run_until_complete(run())
    assert summary["apps"] == 1
    assert summary["files"] == 1
    assert _files_on_disk(proof_dir) == 0, "файл закрытой сделки должен быть удалён с диска"

    async def check():
        async with Session() as s:
            app = await s.get(App, app_id)
            item = (app.proof_files or [])[0]
            events = (await s.execute(
                select(DealEvent).where(DealEvent.app_id == app_id, DealEvent.event == "evidence_purged")
            )).scalars().all()
            return item, events

    item, events = loop.run_until_complete(check())
    assert item["storage"] is None, "ссылка на удалённый файл не должна оставаться"
    assert item["purged_at"], "в метаданных остаётся отметка об удалении"
    assert item["label"] == "Скриншот активации", "метаданные доказательства сохраняются для аудита"
    assert len(events) == 1, "удаление фиксируется событием сделки"


def test_recent_evidence_is_kept(loop, client, ret_offers, proof_dir, monkeypatch):
    monkeypatch.setattr(cfg, "proof_retention_days", 180)
    monkeypatch.setattr(cfg, "proof_open_grace_days", 365)

    _make_app(loop, status="paid", days_old=10)
    _make_app(loop, status="rejected", days_old=30)

    async def run():
        return await purge_expired_evidence()

    summary = loop.run_until_complete(run())
    assert summary["apps"] == 0
    assert _files_on_disk(proof_dir) == 2, "свежие доказательства не трогаем"


def test_open_deal_evidence_lives_longer(loop, client, ret_offers, proof_dir, monkeypatch):
    monkeypatch.setattr(cfg, "proof_retention_days", 180)
    monkeypatch.setattr(cfg, "proof_open_grace_days", 365)

    _make_app(loop, status="new", days_old=200)   # в работе — ещё не истёк льготный срок
    _make_app(loop, status="hold", days_old=400)  # пользователь исчез — срок вышел

    async def run():
        return await purge_expired_evidence()

    summary = loop.run_until_complete(run())
    assert summary["apps"] == 1
    assert _files_on_disk(proof_dir) == 1, "удаляется только сделка, вышедшая за льготный срок"


def test_purge_is_disabled_by_configuration(loop, client, ret_offers, proof_dir, monkeypatch):
    monkeypatch.setattr(cfg, "proof_purge_enabled", False)
    _make_app(loop, status="paid", days_old=900)

    async def run():
        return await purge_expired_evidence()

    summary = loop.run_until_complete(run())
    assert summary["apps"] == 0
    assert _files_on_disk(proof_dir) == 1


def test_admin_export_packs_the_evidence(loop, client, ret_offers, proof_dir):
    app_id = _make_app(loop, status="proof", days_old=1, files=2)

    async def build():
        async with Session() as s:
            app = await s.get(App, app_id)
            return tma_files.build_evidence_zip(app.proof_files or [])

    data = loop.run_until_complete(build())
    assert data, "архив собран"
    import io
    import zipfile

    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = archive.namelist()
        assert len(names) == 2
        assert any("Скриншот" in name for name in names)


def test_delete_proof_refuses_a_path_outside_the_storage(proof_dir):
    assert tma_files.delete_proof("../../etc/passwd") is False
    assert tma_files.delete_proof("") is False
    assert tma_files.delete_proof("9999/deadbeef.jpg") is False


def test_health_endpoint_reports_the_service_state(loop, client):
    status, body = get_json(loop, client, "/health")
    assert status == 200
    assert body["ok"] is True
    assert body["db_live"] is True
    assert body["web"] == "ok"
    assert "last_check" in body


def test_health_payload_marks_a_broken_database(loop, client, monkeypatch):
    async def broken():
        return False

    monkeypatch.setattr(monitoring, "check_db", broken)
    status, body = get_json(loop, client, "/health")
    assert status == 503
    assert body["ok"] is False
    assert body["db_live"] is False


class _ExportMsg:
    """Минимальная заглушка сообщения admin-команды: захватывает ответы и документы."""

    def __init__(self, uid: int, text: str):
        self.from_user = type("U", (), {"id": uid})()
        self.text = text
        self.answers: list = []
        self.documents: list = []

    async def answer(self, text, **kw):
        self.answers.append(text)

    async def answer_document(self, doc, caption=None, **kw):
        self.documents.append((doc, caption))


def test_export_command_sends_zip_only_to_admin(loop, client, ret_offers, proof_dir, monkeypatch):
    from bot.admin import export_evidence

    monkeypatch.setattr(cfg, "admins", [999001])
    app_id = _make_app(loop, status="proof", days_old=2, files=2)

    admin_msg = _ExportMsg(999001, f"/export {app_id}")
    loop.run_until_complete(export_evidence(admin_msg, None))
    assert len(admin_msg.documents) == 1, "админ получает архив доказательств"
    doc, caption = admin_msg.documents[0]
    assert doc.filename == f"evidence-{app_id}.zip"
    assert str(app_id) in caption
    import io
    import zipfile

    with zipfile.ZipFile(io.BytesIO(doc.data)) as archive:
        assert len(archive.namelist()) == 2

    stranger_msg = _ExportMsg(12345, f"/export {app_id}")
    loop.run_until_complete(export_evidence(stranger_msg, None))
    assert not stranger_msg.documents and not stranger_msg.answers, "не-админ не получает ничего"

    bad_msg = _ExportMsg(999001, "/export")
    loop.run_until_complete(export_evidence(bad_msg, None))
    assert bad_msg.answers and "/export" in bad_msg.answers[0], "без id — подсказка по использованию"
    assert not bad_msg.documents


class _ExportCallback:
    def __init__(self, uid: int):
        self.from_user = type("U", (), {"id": uid})()
        self.data = "adm:csv"
        self.documents = []
        self.answers = []
        self.message = self

    async def answer_document(self, doc, caption=None, **kw):
        self.documents.append((doc, caption))

    async def answer(self, text=None, **kw):
        self.answers.append(text)


def test_payout_csv_export_is_admin_only_and_memory_only(loop, client, ret_offers, monkeypatch, tmp_path):
    from bot.admin import export_csv

    monkeypatch.setattr(cfg, "admins", [999002])

    async def seed():
        async with Session() as s:
            s.add(PayoutReq(
                user_id=880001, amount=450, phone=phone_encrypt("79991234567"),
                bank="Т-Банк", status="paid", admin_note="Тестовый платёж",
            ))
            await s.commit()

    loop.run_until_complete(seed())
    admin = _ExportCallback(999002)
    loop.run_until_complete(export_csv(admin))
    assert len(admin.documents) == 1
    document, caption = admin.documents[0]
    assert document.filename.endswith(".csv")
    data = document.data.decode("utf-8-sig")
    assert "79991234567" in data
    assert "Тестовый платёж" in data
    assert "Храните файл безопасно" in caption
    assert not list(tmp_path.rglob("payments-*.csv")), "экспорт не должен создавать plaintext-файл"

    stranger = _ExportCallback(123456)
    loop.run_until_complete(export_csv(stranger))
    assert not stranger.documents
