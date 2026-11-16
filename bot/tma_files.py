"""Private on-disk storage for Mini App evidence uploads.

Files live outside any static route: they are streamed only through the
authenticated API (owner) or sent to admins via the bot. No public permanent
links are ever produced.

Lifecycle: a proof file lives while its deal is open, then is deleted by the
retention policy (`bot/retention.py`). Metadata about the upload stays in the
database for audit; only the personal bytes are removed.
"""
import io
import re
import uuid
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROOF_DIR = ROOT / "data" / "tma_proofs"

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_FILES_PER_UPLOAD = 10

ALLOWED_EXT = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".heic": "image/heic",
    ".pdf": "application/pdf",
}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic"}


class FileError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def safe_ext(filename: str) -> str:
    ext = Path(filename or "").suffix.lower()
    if ext not in ALLOWED_EXT:
        raise FileError("bad_type", "Допустимы только JPEG, PNG, WebP, HEIC и PDF.")
    return ext


def store_proof(app_id: int, filename: str, data: bytes) -> tuple[str, str]:
    """Persist one evidence file; returns (relative storage path, content type)."""
    if not data:
        raise FileError("empty_file", "Файл пуст.")
    if len(data) > MAX_FILE_BYTES:
        raise FileError("too_large", "Файл больше 10 МБ.")
    ext = safe_ext(filename)
    folder = PROOF_DIR / str(app_id)
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}{ext}"
    (folder / name).write_bytes(data)
    return f"{app_id}/{name}", ALLOWED_EXT[ext]


def resolve_proof(storage: str) -> Path:
    """Resolve a stored relative path, refusing anything outside PROOF_DIR."""
    if not storage or not re.fullmatch(r"\d+/[0-9a-f]{32}\.[a-z0-9]+", storage):
        raise FileError("bad_path", "Некорректный путь к файлу.")
    path = (PROOF_DIR / storage).resolve()
    if not path.is_relative_to(PROOF_DIR.resolve()) or not path.is_file():
        raise FileError("not_found", "Файл не найден.")
    return path


def delete_proof(storage: str) -> bool:
    """Remove one stored file from disk. Returns True when a file was deleted."""
    if not storage or not re.fullmatch(r"\d+/[0-9a-f]{32}\.[a-z0-9]+", storage or ""):
        return False
    path = (PROOF_DIR / storage).resolve()
    if not path.is_relative_to(PROOF_DIR.resolve()) or not path.is_file():
        return False
    path.unlink()
    return True


def purge_app_files(items: list) -> int:
    """Delete every stored file of one deal; returns the number of removed files."""
    removed = 0
    for item in items or []:
        if isinstance(item, dict) and item.get("storage") and delete_proof(item["storage"]):
            removed += 1
    return removed


def build_evidence_zip(items: list) -> bytes | None:
    """Pack the still existing evidence of one deal into a zip archive.

    Used by the admin export command: the archive is sent to an administrator
    in Telegram and never becomes a public link.
    """
    buffer = io.BytesIO()
    added = 0
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for index, item in enumerate(items or []):
            if not isinstance(item, dict) or not item.get("storage"):
                continue
            try:
                path = resolve_proof(item["storage"])
            except FileError:
                continue
            label = (item.get("label") or "proof").strip()[:60]
            suffix = path.suffix.lower()
            name = f"{index + 1:02d}_{label}{suffix}".replace("/", "_")
            archive.write(path, arcname=name)
            added += 1
    if not added:
        return None
    return buffer.getvalue()


def proof_disk_usage() -> tuple[int, int]:
    """(files, bytes) currently stored on disk."""
    files = 0
    total = 0
    if PROOF_DIR.exists():
        for path in PROOF_DIR.rglob("*"):
            if path.is_file():
                files += 1
                total += path.stat().st_size
    return files, total