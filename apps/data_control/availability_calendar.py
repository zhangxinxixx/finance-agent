from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from apps.data_control.schemas import AvailabilityItem, AvailabilityRule

DEFAULT_AVAILABILITY_RULES: tuple[AvailabilityRule, ...] = (
    AvailabilityRule(
        source_key="jin10_mcp_market",
        label="Jin10 market quotes",
        source_type="market_quote",
        artifact_globs=("outputs/jin10/quotes_cache.json",),
        freshness_threshold_minutes=5,
        required_for=("intraday_snapshot", "trigger_level_confirmation"),
        missing_policy="block_price_trigger_only",
    ),
    AvailabilityRule(
        source_key="jin10_mcp_flash",
        label="Jin10 flash",
        source_type="flash",
        artifact_globs=("outputs/jin10/flash_cache.json",),
        freshness_threshold_minutes=30,
        required_for=("event_watchlist",),
    ),
    AvailabilityRule(
        source_key="jin10_xnews_public",
        label="Jin10 xnews public",
        source_type="news",
        artifact_globs=("features/news/**/jin10_article_briefs.json",),
        freshness_threshold_minutes=60,
        required_for=("event_watchlist", "limited_daily_analysis"),
    ),
    AvailabilityRule(
        source_key="jin10_daily_report",
        label="Jin10 daily report",
        source_type="report",
        artifact_globs=("outputs/jin10/{trade_date}/daily/**/agent_analysis_report.json",),
        due_time_utc="21:00",
        required_for=("daily_report_interpretation",),
    ),
    AvailabilityRule(
        source_key="jin10_svip_reports",
        label="Jin10 SVIP reports",
        source_type="report",
        artifact_globs=("outputs/jin10/{trade_date}/*/agent_analysis_report.json",),
        due_time_utc="08:00",
        required_for=("full_daily_analysis", "knowledge_distillation"),
        missing_policy="block_research_distillation",
    ),
    AvailabilityRule(
        source_key="jin10_datacenter_reports",
        label="Jin10 datacenter reports",
        source_type="datacenter",
        artifact_globs=("raw/**/*datacenter*.json", "parsed/**/*datacenter*.json"),
        due_time_utc="08:00",
        required_for=("positioning_context",),
    ),
    AvailabilityRule(
        source_key="cme_options_bulletin",
        label="CME options bulletin",
        source_type="structure",
        artifact_globs=("raw/cme/**/*{trade_date}*.pdf", "parsed/cme/**/*{trade_date}*.json"),
        due_time_utc="23:00",
        required_for=("options_wall", "event_sla"),
    ),
)


def build_data_availability_snapshot(
    *,
    storage_root: Path,
    trade_date: str,
    observed_at: datetime,
    rules: tuple[AvailabilityRule, ...] = DEFAULT_AVAILABILITY_RULES,
) -> dict[str, Any]:
    observed = _ensure_utc(observed_at)
    items = [_evaluate_rule(storage_root=storage_root, trade_date=trade_date, observed_at=observed, rule=rule) for rule in rules]
    counts = {state: sum(1 for item in items if item.state == state) for state in ("available", "waiting", "missing", "stale", "blocked")}
    return {
        "trade_date": trade_date,
        "observed_at": observed.isoformat(),
        "hour": observed.strftime("%H"),
        "timezone": "UTC",
        "overall_state": _overall_state(items),
        "counts": counts,
        "items": [item.to_dict() for item in items],
    }


def _evaluate_rule(*, storage_root: Path, trade_date: str, observed_at: datetime, rule: AvailabilityRule) -> AvailabilityItem:
    artifact = _latest_artifact(storage_root=storage_root, trade_date=trade_date, rule=rule)
    expected_at = _expected_at(trade_date=trade_date, due_time_utc=rule.due_time_utc)
    due = expected_at is None or observed_at >= expected_at
    latest_observed_at = _artifact_observed_at(artifact) if artifact else None
    lag_minutes = int((observed_at - latest_observed_at).total_seconds() // 60) if latest_observed_at else None

    if artifact and _is_blocked_report(artifact):
        state = "blocked"
        reason_code = "content_access_blocked"
        message = f"{rule.source_key} artifact is preview, VIP locked, or incomplete"
    elif artifact and rule.freshness_threshold_minutes is not None and lag_minutes is not None and lag_minutes > rule.freshness_threshold_minutes:
        state = "stale"
        reason_code = "freshness_stale"
        message = f"{rule.source_key} is stale; lag={lag_minutes}m threshold={rule.freshness_threshold_minutes}m"
    elif artifact:
        state = "available"
        reason_code = None
        message = f"{rule.source_key} is available"
    elif not due:
        state = "waiting"
        reason_code = "not_yet_expected"
        message = f"{rule.source_key} is waiting for publication window"
    else:
        state = "missing"
        reason_code = "expected_artifact_missing"
        message = f"{rule.source_key} is expected but missing"

    return AvailabilityItem(
        source_key=rule.source_key,
        label=rule.label,
        source_type=rule.source_type,
        state=state,  # type: ignore[arg-type]
        observed_at=observed_at.isoformat(),
        expected_at=expected_at.isoformat() if expected_at else None,
        latest_artifact_ref=_rel(artifact, storage_root) if artifact else None,
        latest_observed_at=latest_observed_at.isoformat() if latest_observed_at else None,
        lag_minutes=lag_minutes,
        reason_code=reason_code,
        message=message,
        required_for=rule.required_for,
        missing_policy=rule.missing_policy,
        metadata={"freshness_threshold_minutes": rule.freshness_threshold_minutes},
    )


def _latest_artifact(*, storage_root: Path, trade_date: str, rule: AvailabilityRule) -> Path | None:
    candidates: list[Path] = []
    for pattern in rule.artifact_globs:
        rendered = pattern.format(trade_date=trade_date)
        candidates.extend(path for path in storage_root.glob(rendered) if path.is_file())
    if not candidates:
        return None
    return max(candidates, key=lambda item: item.stat().st_mtime)


def _artifact_observed_at(path: Path) -> datetime:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    if isinstance(payload, dict):
        for key in ("updated_at", "observed_at", "as_of", "generated_at"):
            parsed = _parse_datetime(payload.get(key))
            if parsed is not None:
                return parsed
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)


def _is_blocked_report(path: Path) -> bool:
    if path.name != "agent_analysis_report.json":
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict) or not isinstance(payload.get("content_access"), dict):
        return False
    content_access = payload["content_access"]
    return bool(content_access.get("vip_locked")) or str(content_access.get("content_scope") or "") == "preview" or not bool(content_access.get("body_complete"))


def _expected_at(*, trade_date: str, due_time_utc: str | None) -> datetime | None:
    if due_time_utc is None:
        return None
    hour, minute = (int(part) for part in due_time_utc.split(":", maxsplit=1))
    return datetime.fromisoformat(trade_date).replace(tzinfo=timezone.utc, hour=hour, minute=minute)


def _overall_state(items: list[AvailabilityItem]) -> str:
    if any(item.state == "blocked" for item in items):
        return "blocked"
    if any(item.state in {"missing", "stale"} for item in items):
        return "degraded"
    if any(item.state == "waiting" for item in items):
        return "waiting"
    return "normal"


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _rel(path: Path | None, storage_root: Path) -> str:
    if path is None:
        return ""
    try:
        return path.relative_to(storage_root).as_posix()
    except ValueError:
        return path.as_posix()
