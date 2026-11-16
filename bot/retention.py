"""Политика хранения доказательств Mini App.

Скриншоты и документы — персональные данные пользователя: они могут содержать
реквизиты, номер карты, имя. Поэтому файлы доказательств не живут вечно.

Правила (настраиваются через `.env`):

* закрытая сделка (paid / confirmed / rejected / expired) — файлы удаляются
  через `PROOF_RETENTION_DAYS` (по умолчанию 180 дней) с момента создания
  сделки;
* незакрытая сделка (new / proof / hold) — через `PROOF_OPEN_GRACE_DAYS`
  (по умолчанию 365 дней): пользователь мог вернуться позже;
* метаданные (что было загружено, хеши, даты, события) остаются в базе —
  аудит сделки не должен рваться, персональные байты — исчезают;
* выгрузка для администратора — команда `/export <id>` в боте: zip с файлами
  сделки приходит в Telegram админу, публичных ссылок не создаётся.

Удаление идемпотентно и безопасно: удаляются только файлы внутри
`data/tma_proofs`, путь каждого проверяется регулярным выражением.
"""
from datetime import datetime, timedelta

from sqlalchemy import select

from bot.config import cfg
from bot.db import App, DealEvent, Session
from bot.logic import notify
from bot.tma_files import purge_app_files

# Сделки, по которым решение уже принято: доказательства больше не нужны.
CLOSED_STATUSES = ("paid", "confirmed", "rejected", "expired")
# Сделки в работе: ждут пользователя или администратора.
OPEN_STATUSES = ("new", "proof", "hold")


def _cutoff(days: int, now: datetime) -> datetime:
    return now - timedelta(days=days)


async def purge_expired_evidence(bot=None, now: datetime | None = None) -> dict:
    """Remove evidence files that outlived the retention period.

    Returns a summary: {"apps": n, "files": m, "skipped": k}.
    """
    summary = {"apps": 0, "files": 0, "skipped": 0}
    if not cfg.proof_purge_enabled:
        return summary
    now = now or datetime.utcnow()
    closed_cutoff = _cutoff(cfg.proof_retention_days, now)
    open_cutoff = _cutoff(cfg.proof_open_grace_days, now)

    async with Session() as s:
        rows = (await s.execute(select(App))).scalars().all()
        for app in rows:
            items = app.proof_files or []
            if not items or not isinstance(items, list):
                continue
            if app.status in CLOSED_STATUSES:
                cutoff = closed_cutoff
            elif app.status in OPEN_STATUSES:
                cutoff = open_cutoff
            else:
                summary["skipped"] += 1
                continue
            created = app.created or now
            if created >= cutoff:
                continue

            removed = purge_app_files(items)
            if not removed:
                summary["skipped"] += 1
                continue

            # Метаданные сохраняем: помечаем файлы удалёнными, чтобы в истории
            # было видно, что доказательства были и когда их стёрли.
            kept = []
            for item in items:
                if isinstance(item, dict):
                    entry = dict(item)
                    entry["storage"] = None
                    entry["purged_at"] = now.isoformat()
                    kept.append(entry)
                else:
                    kept.append(item)
            app.proof_files = kept
            s.add(DealEvent(
                app_id=app.id, actor_id=None, event="evidence_purged",
                from_status=app.status, to_status=app.status,
                comment=f"Доказательства удалены по политике хранения ({removed} файл, "
                        f"срок {cfg.proof_retention_days} дн.)",
            ))
            summary["apps"] += 1
            summary["files"] += removed
        if summary["apps"]:
            await s.commit()

    if summary["apps"] and bot is not None:
        for ad in cfg.admins:
            try:
                await notify(
                    bot, ad,
                    f"🧹 <b>Политика хранения доказательств</b>\n"
                    f"Удалено сделок: {summary['apps']}, файлов: {summary['files']}.\n"
                    f"Срок для закрытых сделок — {cfg.proof_retention_days} дн., "
                    f"для незакрытых — {cfg.proof_open_grace_days} дн.",
                )
            except Exception:  # noqa: BLE001 — алерт не должен ломать чистку
                pass
    return summary
