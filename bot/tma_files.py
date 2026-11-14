"""Private on-disk storage for Mini App evidence uploads.

Files live outside any static route: they are streamed only through the
authenticated API (owner) or sent to admins via the bot. No public permanent
links are ever produced.
"""
import re
import uuid
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