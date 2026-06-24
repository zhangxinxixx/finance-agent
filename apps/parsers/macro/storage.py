from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def archive_raw_payload(
    *,
    storage_root: Path,
    source: str,
    retrieved_date: str,
    symbol: str,
    payload: dict,
) -> str:
    raw_dir = storage_root / "raw" / "macro" / source / retrieved_date
    raw_dir.mkdir(parents=True, exist_ok=True)
    suffix = datetime.now(timezone.utc).strftime("%H%M%S%f")
    raw_path = raw_dir / f"{symbol}-{suffix}-{uuid4().hex[:8]}.json"
    raw_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return raw_path.relative_to(storage_root).as_posix()
