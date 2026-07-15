from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from apps.api.services.daily_analysis_followup_service import get_daily_analysis_followups
from apps.analysis.agents.macro_event_followup import invoke_macro_event_followup_llm
from apps.output.macro_event_followup import write_macro_event_followup
from apps.renderer.markdown.macro_event_followup import (
    build_macro_event_followup_structured_payload,
    render_macro_event_followup_analysis_markdown,
    render_macro_event_followup_source_markdown,
)
from apps.runtime.artifact_storage import LocalFileSystemArtifactStorage
from database.queries.report import upsert_report_artifact, upsert_report_item

logger = logging.getLogger(__name__)


def build_macro_event_followup_input_snapshot(
    *,
    trade_date: str,
    asset: str = "XAUUSD",
    storage_root: Path = Path("./storage"),
) -> dict[str, Any]:
    request_date = date.fromisoformat(trade_date)
    if request_date.weekday() < 5:
        return {
            "status": "not_applicable",
            "trade_date": trade_date,
            "anchor_trade_date": None,
            "anchor_report_refs": [],
            "inputs": {},
            "availability": {},
            "quality_flags": [],
            "warnings": [],
            "blocking_reason": "macro_event_followup v1 only supports weekend/non-trading-day requests",
        }

    anchor = _find_anchor_trade_date(storage_root=storage_root, asset=asset, request_date=request_date)
    if anchor is None:
        return {
            "status": "blocked",
            "trade_date": trade_date,
            "anchor_trade_date": None,
            "anchor_report_refs": [],
            "inputs": {},
            "availability": {},
            "quality_flags": ["missing_anchor_reports"],
            "warnings": ["No formal anchor report artifacts were found for the latest open trading day."],
            "blocking_reason": "missing_anchor_trade_day_reports",
        }

    same_day_run_id = _latest_run_id(storage_root / "features" / "news" / trade_date)
    daily_market_brief = _load_daily_market_brief(storage_root=storage_root, trade_date=trade_date, run_id=same_day_run_id)
    article_briefs = _load_article_briefs(storage_root=storage_root, trade_date=trade_date, run_id=same_day_run_id)
    followups = (
        get_daily_analysis_followups(date=trade_date, run_id=same_day_run_id, project_root=storage_root.parent)
        if same_day_run_id
        else None
    )

    inputs = {
        "daily_market_brief": {
            "status": _input_status(daily_market_brief),
            "run_id": same_day_run_id,
            "payload": daily_market_brief,
        },
        "daily_analysis_followups": {
            "status": _input_status(followups),
            "run_id": same_day_run_id,
            "queue_count": int(followups.get("queue_count", 0)) if isinstance(followups, dict) else 0,
            "payload": followups,
        },
        "jin10_article_briefs": {
            "status": _input_status(article_briefs),
            "run_id": same_day_run_id,
            "payload": article_briefs,
        },
        "event_flow_overview": {
            "status": "unavailable",
            "run_id": None,
            "payload": None,
        },
    }

    availability = {key: str(value["status"]) for key, value in inputs.items()}
    warnings: list[str] = []
    quality_flags: list[str] = []
    core_input_keys = ("daily_market_brief", "daily_analysis_followups", "jin10_article_briefs")
    for source_key in core_input_keys:
        source_status = availability[source_key]
        if source_status == "unavailable":
            warnings.append(f"{source_key} unavailable for {trade_date}")
        elif source_status == "empty":
            warnings.append(f"{source_key} empty for {trade_date}")
    if any(availability[source_key] == "unavailable" for source_key in core_input_keys):
        quality_flags.append("missing_optional_inputs")
    if any(availability[source_key] == "empty" for source_key in core_input_keys):
        quality_flags.append("empty_optional_inputs")

    return {
        "status": "degraded" if quality_flags else "ready",
        "trade_date": trade_date,
        "anchor_trade_date": anchor["trade_date"],
        "anchor_report_refs": anchor["report_refs"],
        "inputs": inputs,
        "availability": availability,
        "quality_flags": quality_flags,
        "warnings": warnings,
    }


def render_and_write_macro_event_followup(
    *,
    input_snapshot: dict[str, Any],
    storage_root: Path = Path("./storage"),
    asset: str = "XAUUSD",
    run_id: str,
    db_session: Session | None = None,
) -> dict[str, Any]:
    trade_date = str(input_snapshot.get("trade_date") or "")
    structured = build_macro_event_followup_structured_payload(input_snapshot)
    deterministic_analysis = render_macro_event_followup_analysis_markdown(structured.model_dump(mode="python"))
    llm_result = invoke_macro_event_followup_llm(
        input_snapshot,
        audit_context={
            "run_id": run_id,
            "report_id": f"macro_event_followup:{trade_date}:{run_id}",
        },
    )
    analysis_markdown = llm_result.get("markdown") or deterministic_analysis
    result = write_macro_event_followup(
        storage_root=storage_root,
        asset=asset,
        trade_date=trade_date,
        run_id=run_id,
        source_markdown=render_macro_event_followup_source_markdown(input_snapshot),
        analysis_markdown=analysis_markdown,
        structured_payload=structured.model_dump(mode="json"),
    )
    result["llm_audit_id"] = llm_result.get("audit_id")
    result["report_registry_upserts"] = _register_macro_event_followup_report(
        db_session,
        result=result,
        structured_payload=structured.model_dump(mode="json"),
        asset=asset,
        trade_date=trade_date,
        run_id=run_id,
        input_status=str(input_snapshot.get("status") or "ready"),
    )
    return result


def generate_macro_event_followup(
    *,
    trade_date: str,
    asset: str = "XAUUSD",
    storage_root: Path = Path("./storage"),
    run_id: str,
    db_session: Session | None = None,
) -> dict[str, Any]:
    snapshot = build_macro_event_followup_input_snapshot(
        trade_date=trade_date,
        asset=asset,
        storage_root=storage_root,
    )
    if snapshot.get("status") not in {"ready", "degraded"}:
        return dict(snapshot)

    result = render_and_write_macro_event_followup(
        input_snapshot=snapshot,
        storage_root=storage_root,
        asset=asset,
        run_id=run_id,
        db_session=db_session,
    )
    return {
        **snapshot,
        **result,
    }


def _register_macro_event_followup_report(
    db_session: Session | None,
    *,
    result: dict[str, Any],
    structured_payload: dict[str, Any],
    asset: str,
    trade_date: str,
    run_id: str,
    input_status: str,
) -> int:
    if db_session is None:
        return 0

    paths = [Path(path) for path in result.get("paths") or [] if isinstance(path, str) and path]
    by_name = {path.name: path for path in paths}
    required_paths = [by_name.get("source.md"), by_name.get("analysis.md"), by_name.get("report_structured.json")]
    if any(path is None for path in required_paths):
        return 0

    report_id = f"macro_event_followup:{trade_date}:{run_id}"
    source_refs = list(structured_payload.get("source_refs") or [])
    data_status = "partial" if input_status == "degraded" else "live"

    try:
        with db_session.begin_nested():
            upsert_report_item(
                db_session,
                {
                    "report_id": report_id,
                    "family": "macro_event_followup_supplement",
                    "report_type": "macro_event_followup",
                    "title": f"{asset} 宏观事件跟进补充（{trade_date}）",
                    "asset": asset,
                    "trade_date": trade_date,
                    "run_id": run_id,
                    "snapshot_id": None,
                    "data_status": data_status,
                    "lifecycle_status": "generated",
                    "source_refs": source_refs,
                    "metadata": {
                        "writer": "macro_event_followup",
                        "anchor_trade_date": structured_payload.get("anchor_trade_date"),
                        "anchor_report_refs": list(structured_payload.get("anchor_report_refs") or []),
                    },
                },
            )
            artifact_count = 0
            for artifact_name, artifact_type, path, is_primary, content_type in (
                ("source", "source_md", by_name["source.md"], True, "text/markdown"),
                ("analysis", "analysis_md", by_name["analysis.md"], False, "text/markdown"),
                ("structured", "structured_json", by_name["report_structured.json"], False, "application/json"),
            ):
                upsert_report_artifact(
                    db_session,
                    _macro_event_followup_report_artifact_payload(
                        report_id=report_id,
                        artifact_name=artifact_name,
                        artifact_type=artifact_type,
                        path=path,
                        content_type=content_type,
                        is_primary=is_primary,
                        source_refs=source_refs,
                        structured_payload=structured_payload,
                    ),
                )
                artifact_count += 1
            db_session.flush()
            return 1 + artifact_count
    except Exception as exc:
        logger.warning(
            "Failed to register macro event followup report: run_id=%s trade_date=%s error=%s",
            run_id,
            trade_date,
            exc,
        )
        return 0


def _macro_event_followup_report_artifact_payload(
    *,
    report_id: str,
    artifact_name: str,
    artifact_type: str,
    path: Path,
    content_type: str,
    is_primary: bool,
    source_refs: list[dict[str, Any]],
    structured_payload: dict[str, Any],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "artifact_id": f"{report_id}:{artifact_name}",
        "report_id": report_id,
        "artifact_type": artifact_type,
        "file_path": str(path),
        "storage_backend": "local_fs",
        "status": "generated",
        "content_type": content_type,
        "is_primary": is_primary,
        "source_refs": source_refs,
        "metadata": {
            "macro_artifact_name": artifact_name,
            "anchor_trade_date": structured_payload.get("anchor_trade_date"),
        },
    }
    try:
        stat_result = path.stat()
    except OSError:
        return payload

    payload["byte_size"] = stat_result.st_size
    payload["generated_at"] = datetime.fromtimestamp(stat_result.st_mtime, tz=timezone.utc).isoformat()
    payload["sha256"] = LocalFileSystemArtifactStorage().compute_sha256(str(path))
    return payload


def _find_anchor_trade_date(*, storage_root: Path, asset: str, request_date: date) -> dict[str, Any] | None:
    for offset in range(1, 8):
        candidate = request_date - timedelta(days=offset)
        candidate_key = candidate.isoformat()
        run_ids = _shared_formal_run_ids(storage_root=storage_root, asset=asset, trade_date=candidate_key)
        if not run_ids:
            continue
        selected_run_id = run_ids[-1]

        final_path = storage_root / "outputs" / "final_report" / asset / candidate_key / selected_run_id / "final_report.md"
        strategy_path = storage_root / "outputs" / "strategy_card" / asset / candidate_key / selected_run_id / "strategy_card.json"
        if not final_path.exists() or not strategy_path.exists():
            continue

        return {
            "trade_date": candidate_key,
            "report_refs": [
                _artifact_ref(
                    artifact_type="final_report",
                    trade_date=candidate_key,
                    run_id=selected_run_id,
                    path=final_path,
                    storage_root=storage_root,
                ),
                _artifact_ref(
                    artifact_type="strategy_card",
                    trade_date=candidate_key,
                    run_id=selected_run_id,
                    path=strategy_path,
                    storage_root=storage_root,
                ),
            ],
        }
    return None


def _artifact_ref(*, artifact_type: str, trade_date: str, run_id: str, path: Path, storage_root: Path) -> dict[str, Any]:
    return {
        "artifact_type": artifact_type,
        "trade_date": trade_date,
        "run_id": run_id,
        "path": path.relative_to(storage_root).as_posix(),
        "available": path.exists(),
    }


def _load_daily_market_brief(*, storage_root: Path, trade_date: str, run_id: str | None) -> dict[str, Any] | None:
    if not run_id:
        return None
    payload = _load_json_bundle(storage_root / "features" / "news" / trade_date / run_id / "daily_market_brief.json")
    if not isinstance(payload, dict):
        return None
    brief = payload.get("daily_market_brief")
    return dict(brief) if isinstance(brief, dict) else None


def _load_article_briefs(*, storage_root: Path, trade_date: str, run_id: str | None) -> dict[str, Any] | None:
    if not run_id:
        return None
    payload = _load_json_bundle(storage_root / "features" / "news" / trade_date / run_id / "jin10_article_briefs.json")
    if not isinstance(payload, dict):
        return None

    briefs = payload.get("briefs")
    normalized_briefs = [dict(item) for item in briefs if isinstance(item, dict)] if isinstance(briefs, list) else []
    return {
        "status": "available" if normalized_briefs else "empty",
        "date": trade_date,
        "run_id": run_id,
        "artifact_path": f"features/news/{trade_date}/{run_id}/jin10_article_briefs.json",
        "as_of": payload.get("as_of"),
        "brief_count": int(payload.get("brief_count") or len(normalized_briefs)),
        "briefs": normalized_briefs,
        "data_quality": dict(payload.get("data_quality") or {}) if isinstance(payload.get("data_quality"), dict) else {},
    }


def _load_json_bundle(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return dict(payload) if isinstance(payload, dict) else None


def _latest_run_id(date_dir: Path) -> str | None:
    if not date_dir.exists() or not date_dir.is_dir():
        return None
    run_ids = sorted(path.name for path in date_dir.iterdir() if path.is_dir())
    return run_ids[-1] if run_ids else None


def _shared_formal_run_ids(*, storage_root: Path, asset: str, trade_date: str) -> list[str]:
    final_dir = storage_root / "outputs" / "final_report" / asset / trade_date
    strategy_dir = storage_root / "outputs" / "strategy_card" / asset / trade_date
    if not final_dir.exists() or not strategy_dir.exists():
        return []

    final_runs = {
        path.name
        for path in final_dir.iterdir()
        if path.is_dir() and (path / "final_report.md").exists()
    }
    strategy_runs = {
        path.name
        for path in strategy_dir.iterdir()
        if path.is_dir() and (path / "strategy_card.json").exists()
    }
    return sorted(final_runs & strategy_runs)


def _input_status(payload: dict[str, Any] | None) -> str:
    if payload is None:
        return "unavailable"
    status = str(payload.get("status") or "").strip()
    return status or "available"
