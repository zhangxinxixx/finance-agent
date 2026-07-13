from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from apps.monitoring.freshness_rules import (
    MONITORED_JIN10_SOURCES,
    capability_impact_for_source,
    required_capabilities_for_source,
)
from apps.monitoring.schemas import DataHealthCheck


def build_artifact_completeness_checks(
    *,
    storage_root: Path,
    trade_date: str,
    observed_at: datetime,
    source_keys: tuple[str, ...] = MONITORED_JIN10_SOURCES,
) -> list[DataHealthCheck]:
    checks: list[DataHealthCheck] = []
    for source_key in source_keys:
        checks.append(_source_completeness(storage_root=storage_root, trade_date=trade_date, observed_at=observed_at, source_key=source_key))
    return checks


def jin10_report_access_checks(*, storage_root: Path, trade_date: str, observed_at: datetime) -> list[DataHealthCheck]:
    output_date_dir = storage_root / "outputs" / "jin10" / trade_date
    checks: list[DataHealthCheck] = []
    for agent_json in sorted(output_date_dir.glob("*/agent_analysis_report.json")):
        payload = _read_json(agent_json)
        content_access = payload.get("content_access") if isinstance(payload, dict) and isinstance(payload.get("content_access"), dict) else {}
        report_type = str(content_access.get("report_type") or "")
        if report_type not in {"research", "daily", "weekly", "market_observation", "positioning", "technical_levels", "oil", "fx"}:
            continue
        body_complete = bool(content_access.get("body_complete"))
        content_scope = str(content_access.get("content_scope") or "unknown")
        vip_locked = bool(content_access.get("vip_locked"))
        if content_scope == "full" and body_complete and not vip_locked:
            status = "ok"
            severity = "info"
            reason_code = None
            message = "Jin10 report content is full and complete"
        else:
            status = "blocked"
            severity = "critical" if report_type == "research" else "high"
            reason_code = "jin10_report_preview_or_incomplete"
            message = "Jin10 report is preview, VIP locked, or body incomplete"
        checks.append(
            DataHealthCheck(
                source_key="jin10_svip_reports",
                check_type="permission",
                status=status,
                severity=severity,
                observed_at=observed_at.isoformat(),
                latest_artifact_ref=_rel(agent_json, storage_root),
                reason_code=reason_code,
                message=message,
                repair_suggestion="Do not allow research interpretation or knowledge distillation until full content is available." if status != "ok" else None,
                artifact_refs=[{"artifact_type": "agent_analysis_report", "path": _rel(agent_json, storage_root)}],
                blocked_capabilities=("research_report_interpretation", "knowledge_distillation") if status != "ok" else (),
                required_for=("research_report_interpretation", "knowledge_distillation"),
                metadata={
                    "article_id": payload.get("article_id") or payload.get("run_id"),
                    "trade_date": payload.get("trade_date") or trade_date,
                    "report_type": report_type,
                    "series": content_access.get("series"),
                    "vip_locked": vip_locked,
                    "content_scope": content_scope,
                    "body_complete": body_complete,
                    "quality_audit": payload.get("quality_audit") if isinstance(payload.get("quality_audit"), dict) else {},
                },
            )
        )
    return checks


def _source_completeness(*, storage_root: Path, trade_date: str, observed_at: datetime, source_key: str) -> DataHealthCheck:
    if source_key == "jin10_mcp_market":
        return _file_check(
            storage_root=storage_root,
            observed_at=observed_at,
            source_key=source_key,
            paths=[storage_root / "outputs" / "jin10" / "quotes_cache.json"],
            message_ok="Jin10 market quote cache exists",
        )
    if source_key == "jin10_mcp_flash":
        return _file_check(
            storage_root=storage_root,
            observed_at=observed_at,
            source_key=source_key,
            paths=[storage_root / "outputs" / "jin10" / "flash_cache.json"],
            message_ok="Jin10 flash cache exists",
        )
    if source_key == "jin10_xnews_public":
        latest = _latest_path(storage_root / "features" / "news", "jin10_article_briefs.json")
        return _file_check(
            storage_root=storage_root,
            observed_at=observed_at,
            source_key=source_key,
            paths=[latest] if latest else [],
            message_ok="Latest Jin10 article briefs artifact exists",
        )
    if source_key == "jin10_datacenter_reports":
        latest = _latest_path(storage_root / "raw", "*.json", contains="datacenter") or _latest_path(storage_root / "parsed", "*.json", contains="datacenter")
        return _file_check(
            storage_root=storage_root,
            observed_at=observed_at,
            source_key=source_key,
            paths=[latest] if latest else [],
            message_ok="Jin10 datacenter artifact exists",
        )
    if source_key == "jin10_svip_reports":
        required = [
            storage_root / "raw" / "jin10" / trade_date / "index.json",
            storage_root / "parsed" / "jin10" / trade_date / "index.json",
            storage_root / "outputs" / "jin10" / trade_date / "analysis.json",
        ]
        agent_jsons = list((storage_root / "outputs" / "jin10" / trade_date).glob("*/agent_analysis_report.json"))
        if agent_jsons:
            required.append(agent_jsons[0])
        return _file_check(
            storage_root=storage_root,
            observed_at=observed_at,
            source_key=source_key,
            paths=required,
            message_ok="Jin10 report raw/parsed/output/agent artifacts exist",
            require_all=True,
            expected_count=4,
        )
    return DataHealthCheck(
        source_key=source_key,
        check_type="completeness",
        status="unknown",
        severity="warning",
        observed_at=observed_at.isoformat(),
        reason_code="unsupported_completeness_source",
        message=f"No completeness rule configured for {source_key}",
    )


def _file_check(
    *,
    storage_root: Path,
    observed_at: datetime,
    source_key: str,
    paths: list[Path],
    message_ok: str,
    require_all: bool = False,
    expected_count: int = 1,
) -> DataHealthCheck:
    existing = [path for path in paths if path and path.is_file()]
    missing = [path for path in paths if path and not path.is_file()]
    if require_all and len(existing) < expected_count:
        status = "partial" if existing else "unavailable"
    elif existing:
        status = "ok"
    else:
        status = "unavailable"
    severity = "info" if status == "ok" else ("high" if source_key in {"jin10_svip_reports", "jin10_mcp_market"} else "warning")
    latest = max(existing, key=lambda item: item.stat().st_mtime) if existing else None
    message = message_ok if status == "ok" else f"{source_key} artifact chain is incomplete"
    blocked_capabilities, degraded_capabilities = capability_impact_for_source(source_key, status=status)
    return DataHealthCheck(
        source_key=source_key,
        check_type="completeness",
        status=status,
        severity=severity,
        observed_at=observed_at.isoformat(),
        latest_artifact_ref=_rel(latest, storage_root) if latest else None,
        reason_code=None if status == "ok" else "artifact_missing",
        message=message,
        repair_suggestion=None if status == "ok" else "Run the collector/parser/output pipeline for this source.",
        artifact_refs=[{"artifact_type": "file", "path": _rel(path, storage_root)} for path in existing],
        blocked_capabilities=blocked_capabilities,
        degraded_capabilities=degraded_capabilities,
        required_for=required_capabilities_for_source(source_key),
        metadata={
            "expected_count": expected_count,
            "existing_count": len(existing),
            "missing": [_rel(path, storage_root) for path in missing],
        },
    )


def _latest_path(root: Path, pattern: str, *, contains: str | None = None) -> Path | None:
    if not root.exists():
        return None
    candidates = [path for path in root.rglob(pattern) if path.is_file() and (contains is None or contains in path.as_posix())]
    if not candidates:
        return None
    return max(candidates, key=lambda item: item.stat().st_mtime)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _rel(path: Path | None, storage_root: Path) -> str:
    if path is None:
        return ""
    try:
        return path.relative_to(storage_root).as_posix()
    except ValueError:
        return path.as_posix()
