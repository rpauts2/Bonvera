#!/usr/bin/env python3
"""Validate the legacy BONVERA offer image set without changing files."""
from pathlib import Path
import hashlib
import sys

ROOT = Path(__file__).resolve().parents[1] / "assets" / "offers"
EXPECTED = {"cards", "bk", "mfo", "cpl"}
errors = []
seen = {}
count = 0
for category in sorted(EXPECTED):
    folder = ROOT / category
    if not folder.is_dir():
        errors.append(f"missing category folder: {folder}")
        continue
    for path in sorted(folder.iterdir()):
        if not path.is_file():
            continue
        count += 1
        if path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
            errors.append(f"unsupported format: {path}")
        data = path.read_bytes()
        if len(data) < 1024:
            errors.append(f"suspiciously small asset ({len(data)} bytes): {path}")
        digest = hashlib.sha256(data).hexdigest()
        if digest in seen:
            errors.append(f"duplicate image: {path} == {seen[digest]}")
        else:
            seen[digest] = path
print(f"Offer image assets checked: {count}; unique: {len(seen)}")
if errors:
    print("\\n".join(f"ERROR: {item}" for item in errors))
    sys.exit(1)
print("OK: formats, minimum sizes and uniqueness")
