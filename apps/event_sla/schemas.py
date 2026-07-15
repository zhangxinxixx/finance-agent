from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

EventStatus = Literal["success", "partial_success", "blocked", "stale", "failed"]


@dataclass(frozen=True)
class EventSnapshot:
    event_id: str
    source_key: str
    event_type: str
    detected_at: str
    event_hash: str
    title: str
    trade_date: str
    published_at: str | None = None
    first_seen_at: str | None = None
    source_url: str | None = None
    article_id: str | None = None
    file_date: str | None = None
    file_name: str | None = None
    raw_refs: list[dict[str, Any]] = field(default_factory=list)
    parsed_refs: list[dict[str, Any]] = field(default_factory=list)
    output_refs: list[dict[str, Any]] = field(default_factory=list)
    source_refs: list[dict[str, Any]] = field(default_factory=list)
    content_access: dict[str, Any] = field(default_factory=dict)
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "source_key": self.source_key,
            "event_type": self.event_type,
            "detected_at": self.detected_at,
            "event_hash": self.event_hash,
            "title": self.title,
            "trade_date": self.trade_date,
            "published_at": self.published_at,
            "first_seen_at": self.first_seen_at,
            "source_url": self.source_url,
            "article_id": self.article_id,
            "file_date": self.file_date,
            "file_name": self.file_name,
            "raw_refs": self.raw_refs,
            "parsed_refs": self.parsed_refs,
            "output_refs": self.output_refs,
            "source_refs": self.source_refs,
            "content_access": self.content_access,
            "payload": self.payload,
        }


@dataclass(frozen=True)
class EventSlaArtifacts:
    event_snapshot_path: str
    analysis_report_path: str
    trading_strategy_path: str
    trading_strategy_json_path: str
    notification_request_path: str
    live_strategy_recompute_request_path: str
    sla_trace_path: str

    def to_dict(self) -> dict[str, str]:
        return {
            "event_snapshot": self.event_snapshot_path,
            "analysis_report": self.analysis_report_path,
            "trading_strategy": self.trading_strategy_path,
            "trading_strategy_json": self.trading_strategy_json_path,
            "notification_request": self.notification_request_path,
            "live_strategy_recompute_request": self.live_strategy_recompute_request_path,
            "sla_trace": self.sla_trace_path,
        }
