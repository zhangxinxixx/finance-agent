from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

NotificationKind = Literal[
    "test",
    "hourly_report",
    "incident",
    "sla_completed",
    "event_sla_completed",
    "event_sla_partial",
    "event_sla_blocked",
    "pre_analysis_readiness",
]
NotificationSeverity = Literal["info", "success", "warning", "critical"]
NotificationStatus = Literal["sent", "dry_run", "disabled", "failed"]


@dataclass(frozen=True)
class FeishuNotificationConfig:
    enabled: bool
    webhook_url: str = ""
    secret: str | None = None
    timeout_seconds: float = 10.0


@dataclass(frozen=True)
class NotificationRequest:
    kind: NotificationKind
    title: str
    summary: str
    severity: NotificationSeverity = "info"
    facts: dict[str, Any] = field(default_factory=dict)
    sections: list[str] = field(default_factory=list)
    source_refs: list[dict[str, Any]] = field(default_factory=list)
    dry_run: bool = False
    trade_date: str | None = None


@dataclass(frozen=True)
class NotificationResult:
    ok: bool
    status: NotificationStatus
    kind: NotificationKind
    title: str
    dry_run: bool
    enabled: bool
    run_id: str | None = None
    status_code: int | None = None
    response_json: dict[str, Any] | None = None
    response_text: str | None = None
    error: str | None = None
    payload_preview: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "status": self.status,
            "kind": self.kind,
            "title": self.title,
            "dry_run": self.dry_run,
            "enabled": self.enabled,
            "run_id": self.run_id,
            "status_code": self.status_code,
            "response_json": self.response_json,
            "response_text": self.response_text,
            "error": self.error,
            "payload_preview": self.payload_preview,
        }
