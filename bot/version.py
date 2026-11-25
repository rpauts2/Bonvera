"""Штамп сборки для ответа /health и админ-панели.

Владельцу нужно отличать свежий деплой от закэшированной старой страницы.
Коммит берём из переменной окружения GIT_COMMIT (её передаёт деплой), иначе
пытаемся прочитать git в рабочем каталоге, иначе честно пишем unknown.
Время сборки — mtime этого файла: он меняется вместе с кодом.
"""
import os
import subprocess
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _git_commit() -> str:
    commit = (os.getenv("GIT_COMMIT") or "").strip()
    if commit:
        return commit[:40]
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return res.stdout.strip()[:40] if res.returncode == 0 and res.stdout.strip() else "unknown"


@lru_cache(maxsize=1)
def build_info() -> dict:
    """Короткая сводка: какой коммит и когда попал в образ."""
    try:
        built_at = datetime.fromtimestamp(Path(__file__).stat().st_mtime, tz=timezone.utc)
        built_iso = built_at.replace(microsecond=0).isoformat()
    except OSError:
        built_iso = None
    return {"commit": _git_commit(), "built_at": built_iso}
