from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def build_notification_plan(
    *,
    storage_root: Path,
    trade_date: str,
    hour: str,
    trigger: str,
    inputs: dict[str, str | None],
    observed_at: str,
) -> dict[str, Any]:
    requests: list[dict[str, Any]] = []
    hourly_report = _read_optional(storage_root, inputs.get("hourly_report"))
    if trigger == "hourly" and hourly_report and isinstance(hourly_report.get("notification_request"), dict):
        requests.append(hourly_report["notification_request"])

    readiness = _read_optional(storage_root, inputs.get("downstream_readiness"))
    if trigger == "pre_analysis" and readiness:
        requests.append(_pre_analysis_request(trade_date=trade_date, hour=hour, readiness=readiness))
    if readiness and readiness.get("readiness") == "blocked":
        requests.append(_incident_request(trade_date=trade_date, hour=hour, readiness=readiness))

    if trigger == "event_sla":
        requests.extend(_event_sla_requests(storage_root=storage_root, trade_date=trade_date))

    delivery_log = _read_delivery_log(storage_root=storage_root, trade_date=trade_date)
    requests = [_apply_notification_policy(request, trade_date=trade_date, hour=hour, observed_at=observed_at, delivery_log=delivery_log) for request in requests]
    return {
        "trade_date": trade_date,
        "hour": hour,
        "trigger": trigger,
        "channel": "feishu",
        "send_policy": "manual_or_orchestrator_dispatch",
        "requests": requests,
        "request_count": len(requests),
    }


def _pre_analysis_request(*, trade_date: str, hour: str, readiness: dict[str, Any]) -> dict[str, Any]:
    blocked_outputs = readiness.get("blocked_outputs") if isinstance(readiness.get("blocked_outputs"), list) else []
    is_blocked = readiness.get("readiness") == "blocked"
    return {
        "kind": "pre_analysis_readiness",
        "title": f"Pre-analysis readiness {trade_date} {hour}:00",
        "summary": f"readiness={readiness.get('readiness')}; blocked_outputs={', '.join(blocked_outputs) or '-'}",
        "severity": "critical" if is_blocked else "info",
        "facts": {
            "trade_date": trade_date,
            "hour": hour,
            "readiness": readiness.get("readiness"),
            "blocked_outputs": blocked_outputs,
            "blocking_issues": readiness.get("blocking_issues") or [],
        },
        "sections": [],
        "source_refs": [{"source": "downstream_readiness", "trade_date": trade_date}],
        "dry_run": False,
        "trade_date": trade_date,
    }


def _incident_request(*, trade_date: str, hour: str, readiness: dict[str, Any]) -> dict[str, Any]:
    blocked_outputs = readiness.get("blocked_outputs") if isinstance(readiness.get("blocked_outputs"), list) else []
    return {
        "kind": "incident",
        "title": f"Data quality incident {trade_date} {hour}:00",
        "summary": f"downstream readiness blocked; blocked_outputs={', '.join(blocked_outputs) or '-'}",
        "severity": "critical",
        "facts": {
            "trade_date": trade_date,
            "hour": hour,
            "readiness": readiness.get("readiness"),
            "blocked_outputs": blocked_outputs,
            "blocking_issues": readiness.get("blocking_issues") or [],
        },
        "sections": [],
        "source_refs": [{"source": "downstream_readiness", "trade_date": trade_date}],
        "dry_run": False,
        "trade_date": trade_date,
    }


def _event_sla_requests(*, storage_root: Path, trade_date: str) -> list[dict[str, Any]]:
    requests = []
    for path in sorted((storage_root / "event_sla" / trade_date).glob("*/notification_request.json")):
        payload = _read_json(path)
        if payload:
            requests.append(payload)
    return requests


def _apply_notification_policy(
    request: dict[str, Any],
    *,
    trade_date: str,
    hour: str,
    observed_at: str,
    delivery_log: list[dict[str, Any]],
) -> dict[str, Any]:
    item = dict(request)
    dedupe_key = str(item.get("dedupe_key") or _dedupe_key(item, trade_date=trade_date, hour=hour))
    cooldown_minutes = int(item.get("cooldown_minutes") or _cooldown_minutes(item))
    last_delivery = _last_delivery(delivery_log=delivery_log, dedupe_key=dedupe_key)
    skipped_reason = None
    eligible_to_send = True
    if last_delivery is not None and _within_cooldown(sent_at=str(last_delivery.get("sent_at")), observed_at=observed_at, cooldown_minutes=cooldown_minutes):
        eligible_to_send = False
        skipped_reason = "cooldown_active"
    item.update(
        {
            "dedupe_key": dedupe_key,
            "cooldown_minutes": cooldown_minutes,
            "eligible_to_send": eligible_to_send,
            "skipped_reason": skipped_reason,
        }
    )
    return item


def _dedupe_key(request: dict[str, Any], *, trade_date: str, hour: str) -> str:
    kind = str(request.get("kind") or "notification")
    facts = request.get("facts") if isinstance(request.get("facts"), dict) else {}
    if _is_event_sla_kind(kind) and facts.get("event_id"):
        return f"{kind}:{facts['event_id']}:{facts.get('status') or 'unknown'}"
    if kind == "incident":
        return f"{kind}:{trade_date}:{facts.get('readiness') or 'unknown'}"
    return f"{kind}:{trade_date}:{hour}"


def _cooldown_minutes(request: dict[str, Any]) -> int:
    kind = str(request.get("kind") or "")
    if kind == "incident":
        return 15
    if _is_event_sla_kind(kind):
        return 30
    if kind == "pre_analysis_readiness":
        return 60
    return 60


def _is_event_sla_kind(kind: str) -> bool:
    return kind in {"sla_completed", "event_sla_completed", "event_sla_partial", "event_sla_blocked"}


def _read_delivery_log(*, storage_root: Path, trade_date: str) -> list[dict[str, Any]]:
    payload = _read_json(storage_root / "orchestration" / trade_date / "notification_delivery_log.json")
    deliveries = payload.get("deliveries") if isinstance(payload.get("deliveries"), list) else []
    return [item for item in deliveries if isinstance(item, dict)]


def _last_delivery(*, delivery_log: list[dict[str, Any]], dedupe_key: str) -> dict[str, Any] | None:
    matches = [item for item in delivery_log if item.get("dedupe_key") == dedupe_key]
    return matches[-1] if matches else None


def _within_cooldown(*, sent_at: str, observed_at: str, cooldown_minutes: int) -> bool:
    sent = _parse_datetime(sent_at)
    observed = _parse_datetime(observed_at)
    if sent is None or observed is None:
        return False
    return (observed - sent).total_seconds() < cooldown_minutes * 60


def _parse_datetime(value: str) -> datetime | None:
    text = value
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _read_optional(storage_root: Path, relative_path: str | None) -> dict[str, Any] | None:
    if not relative_path:
        return None
    payload = _read_json(storage_root / relative_path)
    return payload or None


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}
