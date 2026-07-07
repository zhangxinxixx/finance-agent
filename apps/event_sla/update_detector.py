from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


def stable_event_hash(*parts: object) -> str:
    text = "|".join("" if part is None else str(part) for part in parts)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_event_id(*parts: object) -> str:
    raw = "_".join("" if part is None else str(part) for part in parts if part is not None)
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("_")
    return safe[:160]


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def rel(path: Path | None, storage_root: Path) -> str:
    if path is None:
        return ""
    try:
        return path.relative_to(storage_root).as_posix()
    except ValueError:
        return path.as_posix()
