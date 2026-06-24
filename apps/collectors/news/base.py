from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


@dataclass(frozen=True)
class RawNewsItem:
    source_key: str
    source_name: str
    source_type: str
    feed_key: str
    title: str
    url: str
    domain: str
    published_at: str | None
    fetched_at: str
    summary: str | None = None
    source_country: str | None = None
    source_language: str | None = None
    event_type: str | None = None
    verification_status: str = "single_source"
    duplicate_key: str = ""
    raw_path: str | None = None
    parsed_path: str | None = None
    raw_payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class NewsCollectionResult:
    source_key: str
    status: str
    items: list[RawNewsItem]
    source_refs: list[dict[str, Any]]
    unavailable_feeds: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_news_item_id(*, source_key: str, title: str, url: str) -> str:
    normalized = f"{source_key}|{url.strip().lower()}|{title.strip().lower()}"
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]
    return f"news:{source_key}:{digest}"


def archive_news_payload(
    *,
    storage_root: Path,
    layer: str,
    source_key: str,
    retrieved_date: str,
    name: str,
    payload: dict[str, Any],
) -> str:
    if layer not in {"raw", "parsed"}:
        raise ValueError(f"Unsupported news archive layer: {layer}")
    target_dir = storage_root / layer / "news" / source_key / retrieved_date
    target_dir.mkdir(parents=True, exist_ok=True)
    suffix = datetime.now(timezone.utc).strftime("%H%M%S%f")
    target = target_dir / f"{name}-{suffix}-{uuid4().hex[:8]}.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target.relative_to(storage_root).as_posix()
