from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from sqlalchemy.orm import Session

from apps.api.schemas.common import ArtifactType, DataStatus
from apps.api.schemas.data_source import DataSourceTestRequest, DataSourceTestResponse
from apps.api.schemas.source_trace import ArtifactRef, SourceRef
from apps.collectors.jin10.datacenter import fetch_datacenter_report
from apps.collectors.jin10.mcp_client import Jin10MCPClient
from apps.collectors.news.jin10_detail_fetcher import DEFAULT_JIN10_BROWSER_PROFILE
from apps.runtime.artifact_registry import register_step_artifacts
from apps.runtime.state_machine import transition_task_run, transition_task_step
from database.models.task import StepStatus, TaskRun, TaskStatus, TaskStep, ensure_task_tables

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_DATACENTER_SLUG = "dc_etf_gold"
_DEFAULT_MARKET_CODE = "XAUUSD"
_SUPPORTED_SOURCE_KEYS = {
    "jin10_mcp_flash",
    "jin10_mcp_calendar",
    "jin10_mcp_market",
    "jin10_xnews_public",
    "jin10_datacenter_reports",
    "jin10_svip_reports",
}


@dataclass(slots=True)
class _ProbeOutcome:
    status: str
    data_status: DataStatus
    summary: dict[str, Any]
    preview: list[dict[str, Any]]
    raw_payload: dict[str, Any]
    source_type: str
    error_message: str | None = None
    error_type: str | None = None


def run_ingestion_source_test(
    db: Session,
    source_key: str,
    body: DataSourceTestRequest | None = None,
) -> DataSourceTestResponse:
    request = body or DataSourceTestRequest()
    ensure_task_tables(db)
    run, step = _create_running_audit(db, source_key=source_key, request=request)
    started = time.perf_counter()

    try:
        outcome = _run_probe(source_key=source_key, limit=request.limit, run_id=str(run.id))
    except Exception as exc:  # pragma: no cover - exercised by integration/runtime failures
        outcome = _failure_outcome(source_key=source_key, exc=exc)

    duration_ms = int((time.perf_counter() - started) * 1000)
    raw_path, parsed_path = _archive_probe_payloads(source_key=source_key, run_id=str(run.id), outcome=outcome)
    source_ref = _source_ref(source_key, status=outcome.status, source_type=outcome.source_type)
    artifact_refs = _artifact_refs(raw_path=raw_path, parsed_path=parsed_path)
    _complete_audit(
        db=db,
        run=run,
        step=step,
        request=request,
        source_ref=source_ref,
        artifact_refs=artifact_refs,
        outcome=outcome,
        duration_ms=duration_ms,
        raw_path=raw_path,
        parsed_path=parsed_path,
    )
    db.commit()
    db.refresh(run)

    return DataSourceTestResponse(
        status=outcome.status,
        action="test",
        source_key=source_key,
        run_id=str(run.id),
        audit_id=_audit_id(source_key, request, str(run.id)),
        duration_ms=duration_ms,
        summary=outcome.summary,
        preview=outcome.preview,
        artifacts={"raw_path": raw_path, "parsed_path": parsed_path},
        data_status=outcome.data_status,
        source_refs=[source_ref],
        artifact_refs=artifact_refs,
    )


def _run_probe(*, source_key: str, limit: int, run_id: str) -> _ProbeOutcome:
    if source_key not in _SUPPORTED_SOURCE_KEYS:
        return _ProbeOutcome(
            status="unsupported",
            data_status=DataStatus.unavailable,
            summary={
                "reason_code": "unsupported_source",
                "reason": f"{source_key} is not supported by immediate source test",
            },
            preview=[],
            raw_payload={"source_key": source_key, "status": "unsupported"},
            source_type="unknown",
            error_message="unsupported source",
            error_type="unsupported_source",
        )
    if source_key == "jin10_mcp_flash":
        return _probe_mcp_flash(limit=limit)
    if source_key == "jin10_mcp_calendar":
        return _probe_mcp_calendar(limit=limit)
    if source_key == "jin10_mcp_market":
        return _probe_mcp_market(limit=limit)
    if source_key == "jin10_xnews_public":
        return _probe_xnews_public(limit=limit)
    if source_key == "jin10_datacenter_reports":
        return _probe_datacenter(run_id=run_id)
    return _probe_svip_profile()


def _probe_mcp_flash(*, limit: int) -> _ProbeOutcome:
    with Jin10MCPClient() as client:
        payload = client.list_flash()
    items = _extract_list(payload, keys=("items", "list", "data"))
    preview = [
        {
            "id": str(item.get("id") or item.get("news_id") or index),
            "published_at": _first_text(item, "time", "published_at", "pub_time", "created_at"),
            "content_excerpt": _excerpt(_first_text(item, "content", "title", "message", "text"), 160),
        }
        for index, item in enumerate(items[:limit])
    ]
    return _ProbeOutcome(
        status="ok",
        data_status=DataStatus.live,
        summary={
            "item_count": len(items),
            "sample_count": len(preview),
            "method": "mcp.list_flash",
        },
        preview=preview,
        raw_payload=payload,
        source_type="mcp",
    )


def _probe_mcp_calendar(*, limit: int) -> _ProbeOutcome:
    with Jin10MCPClient() as client:
        payload = client.list_calendar()
    items = _extract_list(payload, keys=("items", "list", "data", "calendar"))
    preview = [
        {
            "published_at": _first_text(item, "time", "pub_time", "date", "datetime"),
            "event": _excerpt(_first_text(item, "title", "event", "name", "content"), 160),
            "importance": item.get("star") or item.get("importance") or item.get("impact"),
            "actual": item.get("actual"),
            "forecast": item.get("forecast"),
            "previous": item.get("previous"),
        }
        for item in items[:limit]
    ]
    return _ProbeOutcome(
        status="ok",
        data_status=DataStatus.live,
        summary={
            "item_count": len(items),
            "sample_count": len(preview),
            "method": "mcp.list_calendar",
        },
        preview=preview,
        raw_payload=payload,
        source_type="mcp",
    )


def _probe_mcp_market(*, limit: int) -> _ProbeOutcome:
    with Jin10MCPClient() as client:
        quote_payload = client.get_quote(_DEFAULT_MARKET_CODE)
        kline_payload = client.get_kline(_DEFAULT_MARKET_CODE, count=min(limit, 5))
    quote = quote_payload.get("data", quote_payload)
    klines = _extract_list(kline_payload, keys=("klines", "list", "data"))
    preview = [
        {
            "kind": "quote",
            "code": _DEFAULT_MARKET_CODE,
            "price": quote.get("close") or quote.get("price") if isinstance(quote, dict) else None,
            "change": quote.get("ups_price") if isinstance(quote, dict) else None,
            "change_percent": quote.get("ups_percent") if isinstance(quote, dict) else None,
        }
    ]
    preview.extend(
        {
            "kind": "kline",
            "code": _DEFAULT_MARKET_CODE,
            "time": _first_text(item, "time", "t", "datetime"),
            "close": item.get("close") or item.get("c"),
        }
        for item in klines[:limit]
    )
    return _ProbeOutcome(
        status="ok",
        data_status=DataStatus.live,
        summary={
            "code": _DEFAULT_MARKET_CODE,
            "kline_count": len(klines),
            "sample_count": len(preview),
            "method": "mcp.get_quote+mcp.get_kline",
        },
        preview=preview,
        raw_payload={"quote": quote_payload, "kline": kline_payload},
        source_type="mcp",
    )


def _probe_xnews_public(*, limit: int) -> _ProbeOutcome:
    artifact = _latest_article_briefs_artifact()
    if artifact is None:
        return _ProbeOutcome(
            status="no_latest_artifact",
            data_status=DataStatus.partial,
            summary={
                "reason_code": "no_latest_artifact",
                "reason": "No jin10_article_briefs.json artifact found for public article preview",
            },
            preview=[],
            raw_payload={"status": "no_latest_artifact", "source_key": "jin10_xnews_public"},
            source_type="scraper",
        )

    payload = json.loads(artifact.read_text(encoding="utf-8"))
    briefs = payload.get("briefs") if isinstance(payload, dict) else []
    briefs = [item for item in briefs if isinstance(item, dict)]
    preview = [
        {
            "headline": _excerpt(str(item.get("headline") or ""), 160),
            "display_bucket": item.get("display_bucket"),
            "access_status": item.get("access_status"),
            "source_url": item.get("source_url") or item.get("final_url"),
        }
        for item in briefs[:limit]
    ]
    return _ProbeOutcome(
        status="ok",
        data_status=DataStatus.live,
        summary={
            "artifact_path": _relative_path(artifact),
            "brief_count": len(briefs),
            "sample_count": len(preview),
            "method": "latest.jin10_article_briefs",
        },
        preview=preview,
        raw_payload=payload,
        source_type="scraper",
    )


def _probe_datacenter(*, run_id: str) -> _ProbeOutcome:
    retrieved_date = datetime.now(UTC).date().isoformat()
    probe_storage_root = _PROJECT_ROOT / "storage" / "probes" / "ingestion" / retrieved_date / "jin10_datacenter_reports" / run_id
    result = fetch_datacenter_report(
        slug=_DEFAULT_DATACENTER_SLUG,
        storage_root=probe_storage_root,
        retrieved_date=retrieved_date,
    )
    payload = result.to_dict()
    status = str(payload.get("status") or "unknown")
    data_status = DataStatus.live if status == "ok" else DataStatus.partial
    return _ProbeOutcome(
        status=status,
        data_status=data_status,
        summary={
            "slug": payload.get("slug") or _DEFAULT_DATACENTER_SLUG,
            "reason_code": status,
            "reason": payload.get("error_message"),
            "raw_html_path": payload.get("raw_html_path"),
            "raw_js_path": payload.get("raw_js_path"),
            "method": "datacenter.reportType",
        },
        preview=[],
        raw_payload=payload,
        source_type="structured",
        error_message=payload.get("error_message") if status != "ok" else None,
        error_type="schema_changed" if status == "schema_changed" else None,
    )


def _probe_svip_profile() -> _ProbeOutcome:
    profile_path = DEFAULT_JIN10_BROWSER_PROFILE
    profile_exists = profile_path.exists()
    status = "manual_required" if profile_exists else "login_required"
    reason = (
        f"browser_profile present at {profile_path}; paid content fetch is disabled for immediate tests"
        if profile_exists
        else f"browser_profile missing at {profile_path}; authorized SVIP session is required"
    )
    return _ProbeOutcome(
        status=status,
        data_status=DataStatus.manual_required,
        summary={
            "auto_fetch": False,
            "browser_profile": str(profile_path),
            "browser_profile_exists": profile_exists,
            "reason": reason,
        },
        preview=[],
        raw_payload={
            "status": status,
            "auto_fetch": False,
            "browser_profile": str(profile_path),
            "browser_profile_exists": profile_exists,
        },
        source_type="scraper",
        error_message=reason,
        error_type="manual_required",
    )


def _create_running_audit(
    db: Session,
    *,
    source_key: str,
    request: DataSourceTestRequest,
) -> tuple[TaskRun, TaskStep]:
    run = TaskRun(
        name=f"ingestion_source_test:{source_key}",
        task_type="ingestion_source_test",
        status=TaskStatus.pending,
        current_stage="collector",
        progress=0.0,
    )
    db.add(run)
    db.flush()
    step = TaskStep(
        task_run_id=run.id,
        name=f"source_probe:{source_key}",
        stage="collector",
        task_kind="source_probe",
        status=StepStatus.pending,
        input_json=_json_dumps(
            {
                "source_key": source_key,
                "actor": request.actor,
                "reason": request.reason,
                "request_id": request.request_id,
                "limit": request.limit,
            }
        ),
        retryable=True,
        retry_count=0,
    )
    db.add(step)
    db.flush()
    transition_task_run(db, run, TaskStatus.running, source="ingestion_source_test", reason="probe_started")
    transition_task_step(db, step, StepStatus.running, source="ingestion_source_test", reason="probe_started")
    return run, step


def _complete_audit(
    *,
    db: Session,
    run: TaskRun,
    step: TaskStep,
    request: DataSourceTestRequest,
    source_ref: SourceRef,
    artifact_refs: list[ArtifactRef],
    outcome: _ProbeOutcome,
    duration_ms: int,
    raw_path: str,
    parsed_path: str,
) -> None:
    step.duration_ms = duration_ms
    step.source_refs = _json_dumps([source_ref.model_dump(mode="json", exclude_none=True)])
    step.output_refs = _json_dumps([artifact.model_dump(mode="json", exclude_none=True) for artifact in artifact_refs])
    step.artifact_refs = step.output_refs
    step.output_ref = raw_path
    step.output_json = _json_dumps(
        {
            "status": outcome.status,
            "data_status": outcome.data_status.value,
            "summary": outcome.summary,
            "sample_count": len(outcome.preview),
            "artifacts": {"raw_path": raw_path, "parsed_path": parsed_path},
            "audit_id": _audit_id(source_ref.source_id, request, str(run.id)),
        }
    )
    register_step_artifacts(
        db,
        run_id=str(run.id),
        step=step,
        output_refs=[artifact.model_dump(mode="json", exclude_none=True) for artifact in artifact_refs],
        artifact_refs=[artifact.model_dump(mode="json", exclude_none=True) for artifact in artifact_refs],
        output_ref=raw_path,
        source_refs=[source_ref.model_dump(mode="json", exclude_none=True)],
    )
    target_step_status = _step_status(outcome)
    transition_task_step(
        db,
        step,
        target_step_status,
        source="ingestion_source_test",
        reason="probe_finished",
        error_message=outcome.error_message,
        error_type=outcome.error_type,
        retryable=False,
        blocked_reason=outcome.error_message if target_step_status == StepStatus.blocked else None,
    )
    transition_task_run(
        db,
        run,
        _task_status(outcome),
        source="ingestion_source_test",
        reason="probe_finished",
        error_message=outcome.error_message,
        progress=1.0,
    )


def _archive_probe_payloads(*, source_key: str, run_id: str, outcome: _ProbeOutcome) -> tuple[str, str]:
    retrieved_date = datetime.now(UTC).date().isoformat()
    base = PurePosixPath("storage") / "probes" / "ingestion" / retrieved_date / source_key / run_id
    raw_path = (base / "raw.json").as_posix()
    parsed_path = (base / "parsed.json").as_posix()
    _write_json(raw_path, outcome.raw_payload)
    _write_json(
        parsed_path,
        {
            "source_key": source_key,
            "status": outcome.status,
            "data_status": outcome.data_status.value,
            "summary": outcome.summary,
            "preview": outcome.preview,
        },
    )
    return raw_path, parsed_path


def _write_json(relative_path: str, payload: Any) -> None:
    target = _PROJECT_ROOT / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _source_ref(source_key: str, *, status: str, source_type: str) -> SourceRef:
    return SourceRef(
        source_id=source_key,
        source_name=source_key,
        source_type=source_type,
        captured_at=datetime.now(UTC),
        status=status,
    )


def _artifact_refs(*, raw_path: str, parsed_path: str) -> list[ArtifactRef]:
    generated_at = datetime.now(UTC)
    return [
        ArtifactRef(
            artifact_id=f"probe:{raw_path}",
            artifact_type=ArtifactType.raw_file,
            file_path=raw_path,
            generated_at=generated_at,
        ),
        ArtifactRef(
            artifact_id=f"probe:{parsed_path}",
            artifact_type=ArtifactType.parsed_file,
            file_path=parsed_path,
            generated_at=generated_at,
        ),
    ]


def _task_status(outcome: _ProbeOutcome) -> TaskStatus:
    if outcome.status == "ok":
        return TaskStatus.success
    if outcome.data_status == DataStatus.manual_required:
        return TaskStatus.blocked
    if outcome.data_status == DataStatus.partial:
        return TaskStatus.partial_success
    return TaskStatus.failed


def _step_status(outcome: _ProbeOutcome) -> StepStatus:
    if outcome.status == "ok" or outcome.data_status == DataStatus.partial:
        return StepStatus.success
    if outcome.data_status == DataStatus.manual_required:
        return StepStatus.blocked
    return StepStatus.failed


def _failure_outcome(*, source_key: str, exc: Exception) -> _ProbeOutcome:
    return _ProbeOutcome(
        status="failed",
        data_status=DataStatus.unavailable,
        summary={
            "reason_code": type(exc).__name__,
            "reason": str(exc),
        },
        preview=[],
        raw_payload={"source_key": source_key, "status": "failed", "error": f"{type(exc).__name__}: {exc}"},
        source_type="unknown",
        error_message=f"{type(exc).__name__}: {exc}",
        error_type=type(exc).__name__,
    )


def _extract_list(payload: dict[str, Any], *, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    candidates: list[Any] = [payload]
    data = payload.get("data") if isinstance(payload, dict) else None
    if isinstance(data, dict):
        candidates.append(data)
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        for key in keys:
            value = candidate.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
            if isinstance(value, dict):
                nested = _extract_list(value, keys=keys)
                if nested:
                    return nested
    return []


def _first_text(item: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = item.get(key)
        if value is not None and str(value).strip():
            return str(value)
    return None


def _excerpt(value: str | None, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _latest_article_briefs_artifact() -> Path | None:
    base = _PROJECT_ROOT / "storage" / "features" / "news"
    if not base.exists():
        return None
    candidates = [path for path in base.rglob("jin10_article_briefs.json") if path.is_file()]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _relative_path(path: Path) -> str:
    try:
        return path.relative_to(_PROJECT_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _audit_id(source_key: str, request: DataSourceTestRequest, run_id: str) -> str:
    return f"ingestion-source-test:{source_key}:{request.request_id or run_id}"


def _json_dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, default=str)
