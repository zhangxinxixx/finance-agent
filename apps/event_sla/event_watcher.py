from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from apps.event_sla.schemas import EventSnapshot
from apps.event_sla.update_detector import file_sha256, read_json, rel, safe_event_id, stable_event_hash

SourceType = Literal["jin10", "cme"]


def discover_events(
    *,
    storage_root: Path,
    trade_date: str,
    observed_at: datetime,
    source_types: tuple[str, ...] = ("jin10", "cme"),
) -> list[EventSnapshot]:
    observed = _ensure_utc(observed_at)
    events: list[EventSnapshot] = []
    if "jin10" in source_types:
        events.extend(_discover_jin10_events(storage_root=storage_root, trade_date=trade_date, observed_at=observed))
    if "cme" in source_types:
        events.extend(_discover_cme_events(storage_root=storage_root, trade_date=trade_date, observed_at=observed))
    return sorted(events, key=lambda item: (item.source_key, item.event_id))


def _discover_jin10_events(*, storage_root: Path, trade_date: str, observed_at: datetime) -> list[EventSnapshot]:
    output_root = storage_root / "outputs" / "jin10" / trade_date
    events: list[EventSnapshot] = []
    for report_path in sorted(output_root.glob("*/agent_analysis_report.json")):
        payload = read_json(report_path)
        article_id = str(payload.get("article_id") or report_path.parent.name)
        content_access = payload.get("content_access") if isinstance(payload.get("content_access"), dict) else {}
        report_type = str(content_access.get("report_type") or payload.get("report_type") or "report")
        series = str(content_access.get("series") or payload.get("series") or "")
        source_key = "jin10_research_master_review" if report_type == "research" and series == "master_review" else "jin10_report"
        title = str(payload.get("title") or payload.get("document_title") or f"Jin10 report {article_id}")
        published_at = payload.get("published_at") or payload.get("trade_date") or trade_date
        event_hash = stable_event_hash(source_key, article_id, title, published_at)
        event_id = safe_event_id(source_key, article_id, event_hash[:10])
        events.append(
            EventSnapshot(
                event_id=event_id,
                source_key=source_key,
                event_type="jin10_report",
                detected_at=observed_at.isoformat(),
                event_hash=event_hash,
                title=title,
                trade_date=trade_date,
                source_url=f"https://xnews.jin10.com/details/{article_id}",
                article_id=article_id,
                raw_refs=[{"artifact_type": "raw_index", "path": rel(storage_root / "raw" / "jin10" / trade_date / "index.json", storage_root)}],
                parsed_refs=[{"artifact_type": "parsed_index", "path": rel(storage_root / "parsed" / "jin10" / trade_date / "index.json", storage_root)}],
                output_refs=[{"artifact_type": "agent_analysis_report", "path": rel(report_path, storage_root)}],
                content_access=content_access,
                payload=payload,
            )
        )
    return events


def _discover_cme_events(*, storage_root: Path, trade_date: str, observed_at: datetime) -> list[EventSnapshot]:
    raw_root = storage_root / "raw" / "cme" / "daily_bulletin" / trade_date
    parsed = sorted((storage_root / "parsed" / "cme" / trade_date).glob("**/cme_parse_result.json"))
    parsed_ref = rel(parsed[-1], storage_root) if parsed else None
    events: list[EventSnapshot] = []
    for pdf_path in sorted(raw_root.glob("Section64_Metals_Option_Products*.pdf")):
        digest = file_sha256(pdf_path)
        event_id = safe_event_id("cme_gold_options_bulletin", trade_date, digest[:10])
        payload = read_json(parsed[-1]) if parsed else {}
        events.append(
            EventSnapshot(
                event_id=event_id,
                source_key="cme_gold_options_bulletin",
                event_type="cme_bulletin",
                detected_at=observed_at.isoformat(),
                event_hash=digest,
                title=f"CME Metals Option Products {trade_date}",
                trade_date=trade_date,
                file_date=trade_date,
                file_name=pdf_path.name,
                raw_refs=[{"artifact_type": "cme_daily_bulletin_pdf", "path": rel(pdf_path, storage_root), "sha256": digest}],
                parsed_refs=[{"artifact_type": "cme_parse_result", "path": parsed_ref}] if parsed_ref else [],
                output_refs=[],
                content_access={"content_scope": "full", "body_complete": bool(parsed_ref), "vip_locked": False},
                payload=payload,
            )
        )
    return events


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
