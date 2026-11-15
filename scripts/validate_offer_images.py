#!/usr/bin/env python3
"""Validate BONVERA offer assets and byte-for-byte embedded official card sources."""
from __future__ import annotations

import base64
import csv
import hashlib
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ROOT = REPO / "assets" / "offers"
REVIEW_REGISTER = REPO / "docs" / "offer-image-review-register.csv"
EXPECTED = {"cards", "bk", "mfo", "cpl"}
errors: list[str] = []
seen: dict[str, Path] = {}
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
        if path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp", ".svg"}:
            errors.append(f"unsupported format: {path}")
        data = path.read_bytes()
        if len(data) < 1024:
            errors.append(f"suspiciously small asset ({len(data)} bytes): {path}")
        if path.suffix.lower() == ".svg":
            lower = data.lower()
            if b"<svg" not in lower[:500]:
                errors.append(f"invalid SVG header: {path}")
            if re.search(rb'(?:xlink:)?href=[\"\']https?://', data, re.I):
                errors.append(f"remote-linked SVG is not self-contained: {path}")
        digest = hashlib.sha256(data).hexdigest()
        if digest in seen:
            errors.append(f"duplicate image: {path} == {seen[digest]}")
        else:
            seen[digest] = path

verified_embeds = 0
if REVIEW_REGISTER.is_file():
    with REVIEW_REGISTER.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("production_status") != "catalog_svg_installed":
                continue
            slug = row.get("slug", "")
            source_rel = row.get("review_source_file", "")
            svg_path = ROOT / "cards" / f"{slug}.svg"
            source_path = REPO / source_rel
            if not svg_path.is_file() or not source_path.is_file():
                errors.append(f"official source or catalog SVG missing for {slug}")
                continue
            svg = svg_path.read_bytes()
            matches = re.findall(rb"data:image/[a-zA-Z0-9.+-]+;base64,([A-Za-z0-9+/=]+)", svg)
            if len(matches) != 1:
                errors.append(f"expected exactly one embedded source image in {svg_path}; found {len(matches)}")
                continue
            try:
                embedded = base64.b64decode(matches[0], validate=True)
            except Exception:
                errors.append(f"invalid embedded base64 source in {svg_path}")
                continue
            if embedded != source_path.read_bytes():
                errors.append(f"embedded product source differs from reviewed original for {slug}")
                continue
            verified_embeds += 1

print(f"Offer image assets checked: {count}; unique: {len(seen)}")
print(f"Official product images verified byte-for-byte inside catalog SVGs: {verified_embeds}")
if errors:
    print("\n".join(f"ERROR: {item}" for item in errors))
    sys.exit(1)
print("OK: formats, minimum sizes, uniqueness, self-contained SVGs and source integrity")
