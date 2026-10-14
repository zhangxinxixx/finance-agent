from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import or_, select

from apps.api.schemas.common import ArtifactType
from apps.api.services import _storage
from apps.api.services._storage import _iso
from apps.api.services.report_jin10_service import (
    _is_jin10_daily_storage_payload,
    _jin10_report_status,
    _normalize_jin10_quality_audit,
    _read_optional_json,
)
from apps.api.services.report_storage_service import _safe_model_rows, _safe_row_artifacts
from apps.api.services.report_reading.common import (
    _REPORT_EPOCH,
    _generated_at_from_datetime,
    _generated_at_from_paths,
    _parse_report_timestamp,
    _report_index_family,
    _report_index_sort_key,
    _report_index_title,
)
from apps.api.services.report_reading.detail import (
    _final_report_status_valid,
    _final_report_verified_for_read,
    _gold_publish_allowed,
    _historical_final_report_fields,
    _load_macro_event_followup_payload,
    _load_macro_report_lineage,
    _load_non_authoritative_premarket_run_ids,
    _load_weekly_context_revision_payload,
    _macro_report_md_path,
    _non_authoritative_premarket_run_ids,
    _safe_final_report_path,
)
from apps.api.services.report_reading.gold_policy import (
    project_gold_policy_report,
    project_gold_policy_research_identity,
)
from apps.runtime.output_disposition import (
    FAIL_CLOSED_AGENT_NAMES,
    OUTPUT_CLEANUP_KEY,
    is_output_purged,
    purged_output_summary,
)
from database.models.report import ReportArtifact as ReportArtifactModel
from database.models.report import ReportItem
from database.models.analysis import AgentOutput, AnalysisSnapshot, FinalAnalysisResult

logger = logging.getLogger(__name__)


_OBSERVATION_REPORT_FAMILIES = {
    "observation_report_markdown",
    "observation_strategy_card",
}



def _collect_reports(
    base_rel: str, report_type: str, fmt: str, asset: str, md_filename: str | None = None
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    base = _storage._PROJECT_ROOT / "storage" / "outputs" / base_rel / asset
    if not base.exists():
        return results
    for date_dir in sorted(base.iterdir(), reverse=True):
        if not date_dir.is_dir():
            continue
        for run_dir in sorted(date_dir.iterdir(), reverse=True):
            if not run_dir.is_dir():
                continue
            available = (run_dir / md_filename).exists() if md_filename else (run_dir / "strategy_card.json").exists()
            if report_type == "final_report" and _safe_final_report_path(run_dir / "final_report.md") is None:
                continue
            generated_at = (
                _generated_at_from_paths(run_dir / md_filename)
                if md_filename
                else _generated_at_from_paths(run_dir / "strategy_card.json", run_dir / "strategy_card.md")
            )
            results.append(
                {
                    **(_historical_final_report_fields() if report_type == "final_report" else {}),
                    "type": report_type,
                    "trade_date": date_dir.name,
                    "run_id": run_dir.name,
                    "report_id": run_dir.name,
                    "family": _report_index_family(report_type),
                    "title": _report_index_title(report_type, date_dir.name),
                    "format": fmt,
                    "available": available,
                    "generated_at": generated_at,
                }
            )
    if results or report_type == "final_report":
        return results
    for date_dir in sorted(base.iterdir(), reverse=True):
        if date_dir.is_dir() and md_filename and (date_dir / md_filename).exists():
            results.append(
                {
                    "type": report_type,
                    "trade_date": date_dir.name,
                    "run_id": None,
                    "report_id": date_dir.name,
                    "family": _report_index_family(report_type),
                    "title": _report_index_title(report_type, date_dir.name),
                    "format": fmt,
                    "available": True,
                    "generated_at": _generated_at_from_paths(date_dir / md_filename),
                }
            )
    return results


def _collect_reports_from_db(report_type: str, fmt: str, asset: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    storage_root = _storage._PROJECT_ROOT / "storage"
    if not storage_root.exists():
        return results
    db = _storage._try_db_session()
    if db is None:
        return results
    try:
        from sqlalchemy import select

        from database.models.analysis import FinalAnalysisResult

        rows = db.execute(
            select(
                FinalAnalysisResult.id,
                FinalAnalysisResult.trade_date,
                FinalAnalysisResult.run_id,
                FinalAnalysisResult.snapshot_id,
                FinalAnalysisResult.final_report_path,
                FinalAnalysisResult.strategy_card_json_path,
                FinalAnalysisResult.strategy_card_md_path,
                FinalAnalysisResult.final_report_sha256,
                FinalAnalysisResult.created_at,
                FinalAnalysisResult.updated_at,
                FinalAnalysisResult.strategy_card.isnot(None).label("has_strategy_card"),
                FinalAnalysisResult.payload[OUTPUT_CLEANUP_KEY].label("output_cleanup"),
            )
            .where(FinalAnalysisResult.asset == asset)
            .order_by(FinalAnalysisResult.trade_date.desc(), FinalAnalysisResult.id.desc())
        ).mappings().all()
        for row in rows:
            if is_output_purged(row):
                continue
            # Old FinalAnalysisResult rows can point at internal observation bundles.
            paths = [row.final_report_path, row.strategy_card_json_path, row.strategy_card_md_path]
            if any(path and ({"observation_report", "observation_strategy_card"} & set(Path(path).parts)) for path in paths):
                continue
            if report_type == "final_report":
                if not row.final_report_path:
                    continue
                path = _safe_final_report_path(row.final_report_path)
                if path is None:
                    continue
                verified = _final_report_verified_for_read(db, run_id=row.run_id, snapshot_id=row.snapshot_id,
                                                         path=path, digest=row.final_report_sha256)
                available = True
            elif report_type == "strategy_card":
                candidate_paths = [row.strategy_card_json_path, row.strategy_card_md_path]
                if any(candidate_paths):
                    existing_paths = [
                        _storage._PROJECT_ROOT / path
                        for path in candidate_paths
                        if path is not None
                        and (_storage._PROJECT_ROOT / path).exists()
                        and (_storage._PROJECT_ROOT / path).is_relative_to(storage_root)
                    ]
                    if not existing_paths:
                        continue
                available = bool(row.has_strategy_card)
            else:
                available = False
            report_id = row.run_id or row.snapshot_id
            results.append(
                {
                    **(_historical_final_report_fields() if report_type == "final_report" and not verified else {}),
                    "type": report_type,
                    "trade_date": _iso(row.trade_date),
                    "run_id": row.run_id,
                    "report_id": report_id,
                    "family": _report_index_family(report_type),
                    "title": _report_index_title(report_type, _iso(row.trade_date)),
                    "format": fmt,
                    "available": available,
                    "generated_at": _generated_at_from_datetime(getattr(row, "updated_at", None))
                    or _generated_at_from_datetime(getattr(row, "created_at", None)),
                }
            )
    except Exception:
        pass
    finally:
        db.close()
    return results



def _infer_registry_report_format(artifacts: list[ReportArtifactModel]) -> str:
    artifact_types = {artifact.artifact_type for artifact in artifacts}
    has_markdown = bool(artifact_types & {ArtifactType.source_md, ArtifactType.analysis_md})
    has_json = ArtifactType.structured_json in artifact_types
    has_html = ArtifactType.visual_html in artifact_types
    if has_markdown and has_json:
        return "markdown+json"
    if has_html and has_json:
        return "json+html"
    if has_markdown:
        return "markdown"
    if has_json:
        return "json"
    return "registry"


def _generated_at_from_artifacts(artifacts: list[ReportArtifactModel]) -> str | None:
    latest_dt: datetime | None = None
    for artifact in artifacts:
        for candidate in (artifact.generated_at, artifact.updated_at, artifact.created_at):
            if isinstance(candidate, datetime):
                normalized = candidate.astimezone(timezone.utc)
                latest_dt = normalized if latest_dt is None else max(latest_dt, normalized)
                break
    return latest_dt.isoformat() if latest_dt is not None else None


def _collect_registered_reports_from_db(asset: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    db = _storage._try_db_session()
    if db is None:
        return results
    try:
        rows = _safe_model_rows(
            db,
            ReportItem,
            lambda: db.execute(
                select(
                    ReportItem.report_id,
                    ReportItem.family,
                    ReportItem.report_type,
                    ReportItem.title,
                    ReportItem.asset,
                    ReportItem.trade_date,
                    ReportItem.run_id,
                    ReportItem.snapshot_id,
                    ReportItem.data_status,
                    ReportItem.lifecycle_status,
                    ReportItem.report_metadata.label("report_metadata"),
                    ReportItem.created_at,
                    ReportItem.updated_at,
                )
                .where(or_(ReportItem.asset == asset, ReportItem.asset.is_(None)))
                .order_by(ReportItem.trade_date.desc(), ReportItem.updated_at.desc(), ReportItem.created_at.desc())
            ).mappings().all(),
        )
        report_ids = [item.report_id for item in rows if item.report_id]
        artifacts_by_report: dict[str, list[Any]] = defaultdict(list)
        if report_ids:
            artifact_rows = _safe_model_rows(
                db,
                ReportArtifactModel,
                lambda: db.execute(
                    select(
                        ReportArtifactModel.artifact_id,
                        ReportArtifactModel.report_id,
                        ReportArtifactModel.artifact_type,
                        ReportArtifactModel.file_path,
                        ReportArtifactModel.sha256,
                        ReportArtifactModel.generated_at,
                        ReportArtifactModel.status,
                        ReportArtifactModel.artifact_metadata.label("artifact_metadata"),
                        ReportArtifactModel.created_at,
                        ReportArtifactModel.updated_at,
                    ).where(ReportArtifactModel.report_id.in_(report_ids))
                ).mappings().all(),
            )
            for artifact in artifact_rows:
                artifacts_by_report[str(artifact.report_id)].append(artifact)
        non_authoritative_run_ids = _non_authoritative_premarket_run_ids(db, (item.run_id for item in rows))
        gold_snapshot_ids = {
            item.snapshot_id
            for item in rows
            if item.report_type == "gold_policy_daily" and item.family == "gold_policy_daily_report" and item.snapshot_id
        }
        snapshots_by_binding = {}
        if gold_snapshot_ids:
            snapshot_rows = _safe_model_rows(
                db,
                AnalysisSnapshot,
                lambda: db.execute(
                    select(AnalysisSnapshot.snapshot_id, AnalysisSnapshot.run_id, AnalysisSnapshot.payload)
                    .where(AnalysisSnapshot.snapshot_id.in_(gold_snapshot_ids))
                ).mappings().all(),
            )
            snapshots_by_binding = {
                (snapshot.snapshot_id, snapshot.run_id): snapshot.payload for snapshot in snapshot_rows
            }
        for item in rows:
            if is_output_purged(item) or str(item.lifecycle_status or "").lower() == "purged":
                continue
            registered_artifacts = artifacts_by_report.get(str(item.report_id), [])
            artifacts = [
                artifact
                for artifact in registered_artifacts
                if not is_output_purged(artifact)
            ]
            report_type = str(item.report_type or item.family or "").strip()
            if not report_type:
                continue
            is_gold = report_type == "gold_policy_daily" and item.family == "gold_policy_daily_report"
            if is_gold and any(is_output_purged(artifact) for artifact in registered_artifacts):
                continue
            is_final = (report_type == "final_report" or item.family == "final_report_markdown")
            if item.family in _OBSERVATION_REPORT_FAMILIES or report_type in {
                "observation_report", "observation_strategy_card",
            }:
                continue
            if is_final:
                readable = [artifact for artifact in artifacts
                            if artifact.artifact_type == "analysis_md"
                            and _safe_final_report_path(artifact.file_path) is not None]
                if not readable:
                    continue
                report_type = "final_report"
                verified = _final_report_status_valid(item) and any(
                    _final_report_verified_for_read(db, run_id=item.run_id, snapshot_id=item.snapshot_id,
                                                    path=artifact.file_path, digest=artifact.sha256)
                    for artifact in readable
                )
            trade_date = _iso(item.trade_date)
            if report_type == "macro_report" and (
                item.run_id in non_authoritative_run_ids
                or _gold_publish_allowed(trade_date, item.run_id) is False
                or (
                    _gold_publish_allowed(trade_date, item.run_id) is True
                    and _load_macro_report_lineage(trade_date, item.run_id) is None
                )
            ):
                continue
            index_item = {
                "type": report_type,
                "trade_date": trade_date,
                "run_id": item.run_id,
                "report_id": item.report_id,
                "family": item.family,
                "title": item.title or _report_index_title(report_type, trade_date),
                "format": _infer_registry_report_format(artifacts),
                "available": bool(artifacts),
                "generated_at": _generated_at_from_artifacts(artifacts)
                or _generated_at_from_datetime(item.updated_at)
                or _generated_at_from_datetime(item.created_at),
            }
            if is_final and not verified:
                index_item.update(_historical_final_report_fields())
            if is_gold:
                index_item.update(
                    snapshot_id=item.snapshot_id,
                    data_status=item.data_status,
                    lifecycle_status=item.lifecycle_status,
                    research_identity=project_gold_policy_research_identity(
                        item, snapshots_by_binding.get((item.snapshot_id, item.run_id)),
                    ),
                    **project_gold_policy_report(item, artifacts),
                )
            results.append(index_item)
    except Exception:
        pass
    finally:
        db.close()
    return results


def _collect_purged_report_anchors(asset: str) -> list[dict[str, Any]]:
    """Load only reader tombstone identities used to fence legacy fallbacks."""
    db = _storage._try_db_session()
    if db is None:
        return []
    anchors: list[dict[str, Any]] = []
    try:
        rows = _safe_model_rows(
            db,
            ReportItem,
            lambda: db.execute(
                select(
                    ReportItem.report_id,
                    ReportItem.run_id,
                    ReportItem.snapshot_id,
                    ReportItem.trade_date,
                    ReportItem.lifecycle_status,
                    ReportItem.report_metadata.label("report_metadata"),
                    ReportItem.created_at,
                ).where(or_(ReportItem.asset == asset, ReportItem.asset.is_(None)))
            ).mappings().all(),
        )
        for row in rows:
            if not (
                is_output_purged(row)
                or str(row.lifecycle_status or "").lower() == "purged"
                or any(is_output_purged(artifact) for artifact in _safe_row_artifacts(db, row))
            ):
                continue
            marker = purged_output_summary(row) or {}
            anchors.append(
                {
                    "report_id": str(row.report_id),
                    "run_id": str(row.run_id) if row.run_id else marker.get("run_id"),
                    "snapshot_id": str(row.snapshot_id) if row.snapshot_id else marker.get("snapshot_id"),
                    "trade_date": _iso(row.trade_date) if row.trade_date else None,
                    "created_at": getattr(row, "created_at", None),
                }
            )
        final_rows = _safe_model_rows(
            db,
            FinalAnalysisResult,
            lambda: db.execute(
                select(
                    FinalAnalysisResult.id,
                    FinalAnalysisResult.run_id,
                    FinalAnalysisResult.snapshot_id,
                    FinalAnalysisResult.trade_date,
                    FinalAnalysisResult.created_at,
                    FinalAnalysisResult.payload[OUTPUT_CLEANUP_KEY].label("output_cleanup"),
                ).where(FinalAnalysisResult.asset == asset)
            ).mappings().all(),
        )
        for row in final_rows:
            if not is_output_purged(row):
                continue
            marker = purged_output_summary(row) or {}
            anchors.append(
                {
                    "report_id": str(row.run_id),
                    "run_id": str(row.run_id),
                    "snapshot_id": str(row.snapshot_id) if row.snapshot_id else marker.get("snapshot_id"),
                    "trade_date": _iso(row.trade_date) if row.trade_date else None,
                    "created_at": getattr(row, "created_at", None),
                }
            )
        failure_rows = _safe_model_rows(
            db,
            AgentOutput,
            lambda: db.execute(
                select(
                    AgentOutput.id,
                    AgentOutput.snapshot_id,
                    AgentOutput.asset,
                    AgentOutput.trade_date,
                    AgentOutput.run_id,
                    AgentOutput.agent_name,
                    AgentOutput.created_at,
                    AgentOutput.payload[OUTPUT_CLEANUP_KEY].label("output_cleanup"),
                ).where(
                    AgentOutput.asset == asset,
                    AgentOutput.agent_name.in_(FAIL_CLOSED_AGENT_NAMES),
                )
            ).mappings().all(),
        )
        for row in failure_rows:
            if not is_output_purged(row):
                continue
            marker = purged_output_summary(row) or {}
            anchors.append(
                {
                    "report_id": str(row.run_id),
                    "run_id": str(row.run_id),
                    "snapshot_id": str(row.snapshot_id) if row.snapshot_id else marker.get("snapshot_id"),
                    "trade_date": _iso(row.trade_date) if row.trade_date else None,
                    "created_at": getattr(row, "created_at", None),
                }
            )
    except Exception:
        return []
    finally:
        db.close()
    return anchors


def _purged_index_identity(item: dict[str, Any], anchors: list[dict[str, Any]]) -> bool:
    if not anchors or str(item.get("type") or "") not in {"final_report", "strategy_card"}:
        return False
    identities = {
        str(item.get("report_id") or ""),
        str(item.get("run_id") or ""),
        str(item.get("snapshot_id") or ""),
    }
    return any(
        identities.intersection(
            {
                str(anchor.get("report_id") or ""),
                str(anchor.get("run_id") or ""),
                str(anchor.get("snapshot_id") or ""),
            }
        )
        for anchor in anchors
    )


def _dedupe_reports_index_items(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in reports:
        report_id = str(item.get("report_id") or "").strip()
        report_type = str(item.get("type") or "").strip()
        run_id = str(item.get("run_id") or "").strip()
        trade_date = str(item.get("trade_date") or "").strip()
        if report_type == "final_report" and run_id:
            key = (report_type, run_id)
        else:
            key = (report_type, f"{trade_date}:{run_id}") if run_id else (report_type, report_id)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _collect_jin10_reports() -> list[dict[str, Any]]:
    base = _storage._PROJECT_ROOT / "storage" / "outputs" / "jin10"
    results: list[dict[str, Any]] = []
    if base.exists():
        for date_dir in sorted((d for d in base.iterdir() if d.is_dir()), reverse=True):
            for run_dir in sorted((d for d in date_dir.iterdir() if d.is_dir()), reverse=True):
                payload = _read_optional_json(run_dir / "daily_analysis.json") or {}
                agent_payload = _read_optional_json(run_dir / "agent_analysis_report.json")
                quality_audit = _normalize_jin10_quality_audit(agent_payload, payload)
                is_weekly = (
                    str(payload.get("family") or "").strip() == "jin10_weekly_visual"
                    or str(payload.get("report_type") or "").strip().lower() == "weekly"
                )
                report_type = _jin10_index_report_type(
                    payload,
                    is_weekly=is_weekly,
                    title_candidates=(
                        (agent_payload or {}).get("title"),
                        payload.get("title"),
                    ),
                )
                if report_type is None:
                    continue
                item = {
                    "type": report_type,
                    "trade_date": date_dir.name,
                    "run_id": run_dir.name,
                    "report_id": run_dir.name,
                    "title": (
                        (agent_payload or {}).get("title")
                        or payload.get("title")
                    ),
                    "format": "json+html",
                    "available": (
                        (run_dir / "daily_analysis.json").exists()
                        and (run_dir / "daily_analysis.html").exists()
                        and _jin10_report_status(quality_audit) == "ready"
                    ),
                    "generated_at": _generated_at_from_paths(
                        run_dir / "daily_analysis.json",
                        run_dir / "daily_analysis.html",
                        run_dir / "agent_analysis_report.json",
                        run_dir / "agent_analysis_report.md",
                    ),
                    "status": _jin10_report_status(quality_audit),
                }
                if quality_audit is not None:
                    item["quality_audit"] = quality_audit
                results.append(item)
    return results


def _jin10_index_report_type(
    payload: dict[str, Any],
    *,
    is_weekly: bool,
    title_candidates: Iterable[Any] = (),
) -> str | None:
    if is_weekly:
        return "jin10_weekly_report"
    normalized = str(payload.get("report_type") or "").strip().lower()
    family = str(payload.get("family") or "").strip().lower()
    if _is_jin10_daily_storage_payload(payload, title_candidates=title_candidates):
        return "jin10_daily_report"
    if normalized == "positioning" or family == "jin10_positioning_report":
        return "jin10_positioning_report"
    if normalized in {"technical_levels", "technical_level"} or family == "jin10_technical_levels_report":
        return "jin10_technical_levels_report"
    if normalized == "oil" or family == "jin10_oil_report":
        return "jin10_oil_report"
    if normalized == "fx" or family == "jin10_fx_report":
        return "jin10_fx_report"
    if normalized == "market_observation" or family == "jin10_market_observation_report":
        return "jin10_market_observation_report"
    return None


def _jin10_dates_requires_legacy_metadata(
    payload: dict[str, Any],
    payload_report_type: str | None,
    *,
    daily_path: Path,
    raw_path: Path,
) -> bool:
    """Return whether dates classification needs legacy raw or external metadata.

    ``daily_analysis.json`` is the canonical indexed artifact when it carries
    an explicit family/type and title.  A newer legacy raw artifact is treated
    as an ambiguity because older runs could have written the source title
    after the daily projection; re-checking it preserves the historical title
    marker filter without parsing raw files for normal runs.
    """

    normalized = str(payload.get("report_type") or "").strip().lower()
    family = str(payload.get("family") or "").strip()
    if payload_report_type is None or (not normalized and not family):
        return True
    if payload_report_type != "jin10_daily_report":
        return False
    if not str(payload.get("title") or payload.get("source_title") or "").strip():
        return True
    if not raw_path.exists():
        return False
    try:
        return raw_path.stat().st_mtime_ns > daily_path.stat().st_mtime_ns
    except OSError:
        return True



def list_reports_index(asset: str = "XAUUSD") -> dict[str, Any]:
    reports: list[dict[str, Any]] = []
    reports.extend(_collect_registered_reports_from_db(asset))
    reports.extend(_collect_reports_from_db("final_report", "markdown", asset))
    reports.extend(_collect_reports("final_report", "final_report", "markdown", asset, "final_report.md"))
    reports.extend(_collect_reports_from_db("strategy_card", "json+markdown", asset))
    reports.extend(_collect_reports("strategy_card", "strategy_card", "json+markdown", asset))
    reports.extend(_collect_jin10_reports())

    options_base = _storage._PROJECT_ROOT / "storage" / "outputs" / "cme_options"
    if options_base.exists():
        for date_dir in sorted(options_base.iterdir(), reverse=True):
            if date_dir.is_dir():
                available = (date_dir / "options_analysis.json").exists() or (date_dir / "options_analysis.md").exists()
                reports.append(
                    {
                        "type": "options_report",
                        "trade_date": date_dir.name,
                        "run_id": None,
                        "report_id": date_dir.name,
                        "family": _report_index_family("options_report"),
                        "title": _report_index_title("options_report", date_dir.name),
                        "format": "json+markdown",
                        "available": available,
                        "generated_at": _generated_at_from_paths(
                            date_dir / "options_analysis.json",
                            date_dir / "options_analysis.md",
                        ),
                    }
                )

    options_run_base = _storage._PROJECT_ROOT / "storage" / "outputs" / "cme"
    if options_run_base.exists():
        for date_dir in sorted(options_run_base.iterdir(), reverse=True):
            if not date_dir.is_dir():
                continue
            for run_dir in sorted((run for run in date_dir.iterdir() if run.is_dir()), reverse=True):
                available = any(
                    (run_dir / filename).exists()
                    for filename in (
                        "options_analysis_agent_report.md",
                        "options_analysis.md",
                        "options_analysis.json",
                    )
                )
                if not available:
                    continue
                reports.append(
                    {
                        "type": "options_report",
                        "trade_date": date_dir.name,
                        "run_id": run_dir.name,
                        "report_id": run_dir.name,
                        "family": _report_index_family("options_report"),
                        "title": _report_index_title("options_report", date_dir.name),
                        "format": "json+markdown",
                        "available": True,
                        "generated_at": _generated_at_from_paths(
                            run_dir / "options_analysis_agent_report.md",
                            run_dir / "options_analysis.md",
                            run_dir / "options_analysis.json",
                        ),
                    }
                )

    cme_visual_base = _storage._PROJECT_ROOT / "storage" / "outputs" / "cme"
    if cme_visual_base.exists():
        for date_dir in sorted(cme_visual_base.iterdir(), reverse=True):
            if not date_dir.is_dir():
                continue
            for run_dir in sorted((run for run in date_dir.iterdir() if run.is_dir()), reverse=True):
                available = any(
                    (run_dir / filename).exists()
                    for filename in (
                        "options_visual_report.html",
                        "options_analysis_agent_report.md",
                        "options_analysis.md",
                        "options_analysis.json",
                    )
                )
                if available:
                    reports.append(
                        {
                            "type": "options_visual_report",
                            "trade_date": date_dir.name,
                            "run_id": run_dir.name,
                            "report_id": run_dir.name,
                            "family": _report_index_family("options_visual_report"),
                            "title": _report_index_title("options_visual_report", date_dir.name),
                            "format": "json+html",
                            "available": True,
                            "generated_at": _generated_at_from_paths(
                                run_dir / "options_visual_report.html",
                                run_dir / "options_analysis_agent_report.md",
                                run_dir / "options_analysis.md",
                                run_dir / "options_analysis.json",
                            ),
                        }
                    )

    macro_base = _storage._PROJECT_ROOT / "storage" / "outputs" / "macro"
    if macro_base.exists():
        macro_run_ids = [
            run_dir.name
            for date_dir in macro_base.iterdir()
            if date_dir.is_dir()
            for run_dir in date_dir.iterdir()
            if run_dir.is_dir()
        ]
        non_authoritative_run_ids = _load_non_authoritative_premarket_run_ids(macro_run_ids)
        for date_dir in sorted(macro_base.iterdir(), reverse=True):
            if not date_dir.is_dir():
                continue
            runs = [run_dir for run_dir in date_dir.iterdir() if run_dir.is_dir()]
            if runs:
                for run_dir in sorted(runs, reverse=True):
                    if run_dir.name in non_authoritative_run_ids:
                        continue
                    if _gold_publish_allowed(date_dir.name, run_dir.name) is False:
                        continue
                    if (
                        _gold_publish_allowed(date_dir.name, run_dir.name) is True
                        and _load_macro_report_lineage(date_dir.name, run_dir.name) is None
                    ):
                        continue
                    report_md = _macro_report_md_path(run_dir)
                    if report_md is not None:
                        reports.append(
                            {
                                "type": "macro_report",
                                "trade_date": date_dir.name,
                                "run_id": run_dir.name,
                                "report_id": _typed_report_id("macro_report", run_dir.name),
                                "family": _report_index_family("macro_report"),
                                "title": _report_index_title("macro_report", date_dir.name),
                                "format": "markdown",
                                "available": True,
                                "generated_at": _generated_at_from_paths(report_md),
                            }
                        )
            else:
                report_md = _macro_report_md_path(date_dir)
                if report_md is not None:
                    reports.append(
                        {
                            "type": "macro_report",
                            "trade_date": date_dir.name,
                            "run_id": None,
                            "report_id": _typed_report_id("macro_report", date_dir.name),
                            "family": _report_index_family("macro_report"),
                            "title": _report_index_title("macro_report", date_dir.name),
                            "format": "markdown",
                            "available": True,
                            "generated_at": _generated_at_from_paths(report_md),
                        }
                    )
    followup_base = _storage._PROJECT_ROOT / "storage" / "outputs" / "macro_event_followup" / asset
    if followup_base.exists():
        for date_dir in sorted((item for item in followup_base.iterdir() if item.is_dir()), reverse=True):
            for run_dir in sorted((run for run in date_dir.iterdir() if run.is_dir()), reverse=True):
                payload = _load_macro_event_followup_payload(run_dir)
                available = payload is not None and all(
                    (run_dir / filename).exists() for filename in ("source.md", "analysis.md", "report_structured.json")
                )
                if not available:
                    continue
                impact_assessment = payload.impact_assessment if isinstance(payload.impact_assessment, dict) else {}
                reports.append(
                    {
                        "type": "macro_event_followup",
                        "trade_date": date_dir.name,
                        "run_id": run_dir.name,
                        "report_id": _typed_report_id("macro_event_followup", f"{date_dir.name}:{run_dir.name}"),
                        "family": _report_index_family("macro_event_followup"),
                        "title": _report_index_title("macro_event_followup", date_dir.name),
                        "format": "markdown+json",
                        "available": True,
                        "anchor_trade_date": payload.anchor_trade_date,
                        "summary": impact_assessment.get("summary"),
                        "generated_at": _generated_at_from_paths(
                            run_dir / "source.md",
                            run_dir / "analysis.md",
                            run_dir / "report_structured.json",
                        ),
                    }
                )
    weekly_revision_base = _storage._PROJECT_ROOT / "storage" / "outputs" / "weekly_context_revision" / asset
    if weekly_revision_base.exists():
        for date_dir in sorted((item for item in weekly_revision_base.iterdir() if item.is_dir()), reverse=True):
            for run_dir in sorted((run for run in date_dir.iterdir() if run.is_dir()), reverse=True):
                payload = _load_weekly_context_revision_payload(run_dir)
                available = payload is not None and all(
                    (run_dir / filename).exists() for filename in ("source.md", "analysis.md", "report_structured.json")
                )
                if not available:
                    continue
                first_revision = payload.claim_revisions[0] if payload.claim_revisions else None
                reports.append(
                    {
                        "type": "weekly_context_revision",
                        "trade_date": date_dir.name,
                        "run_id": run_dir.name,
                        "report_id": _typed_report_id(
                            "weekly_context_revision",
                            f"{date_dir.name}:{run_dir.name}",
                        ),
                        "family": _report_index_family("weekly_context_revision"),
                        "title": _report_index_title("weekly_context_revision", date_dir.name),
                        "format": "markdown+json",
                        "available": True,
                        "anchor_trade_date": payload.anchor.report_date,
                        "anchor_article_id": payload.anchor.article_id,
                        "quality_status": payload.quality_status,
                        "publication_status": payload.publication_status,
                        "publish_allowed": payload.publish_allowed,
                        "summary": first_revision.reason if first_revision is not None else None,
                        "generated_at": _generated_at_from_paths(
                            run_dir / "source.md",
                            run_dir / "analysis.md",
                            run_dir / "report_structured.json",
                        ),
                    }
                )
    purged_anchors = _collect_purged_report_anchors(asset)
    reports = [
        r
        for r in reports
        if r.get("type") not in {"observation_report", "observation_strategy_card"}
        and r.get("family") not in _OBSERVATION_REPORT_FAMILIES
        and not _purged_index_identity(r, purged_anchors)
    ]
    reports = _dedupe_reports_index_items(reports)
    reports.sort(key=_report_index_sort_key, reverse=True)
    return {"asset": asset, "reports": [r for r in reports if r.get("available", False)]}



def _typed_report_id(report_type: str, raw_id: str) -> str:
    return f"{report_type}:{raw_id}"



def list_unified_dates(asset: str = "XAUUSD") -> dict[str, Any]:
    roots = {
        "snapshot": _storage._PROJECT_ROOT / "storage" / "features" / "snapshots" / asset,
        "final_report": _storage._PROJECT_ROOT / "storage" / "outputs" / "final_report" / asset,
        "strategy_card": _storage._PROJECT_ROOT / "storage" / "outputs" / "strategy_card" / asset,
        "observation_report": _storage._PROJECT_ROOT / "storage" / "outputs" / "observation_report" / asset,
        "observation_strategy_card": _storage._PROJECT_ROOT / "storage" / "outputs" / "observation_strategy_card" / asset,
        "jin10": _storage._PROJECT_ROOT / "storage" / "outputs" / "jin10",
    }
    date_modules: dict[str, set[str]] = defaultdict(set)
    date_latest_run: dict[str, str] = {}
    date_run_candidates: dict[tuple[str, str], tuple[datetime, bool]] = {}

    def consider_latest_run(
        date_str: str,
        run_id: str | None,
        generated_at: Any,
        *,
        registered: bool = False,
    ) -> None:
        if not run_id:
            return
        run_key = (date_str, str(run_id))
        candidate = (_parse_report_timestamp(generated_at) or _REPORT_EPOCH, registered)
        current = date_run_candidates.get(run_key)
        if (
            current is None
            or (registered and not current[1])
            or (registered == current[1] and candidate[0] > current[0])
        ):
            date_run_candidates[run_key] = candidate
        candidates = [
            (timestamp, candidate_run_id)
            for (candidate_date, candidate_run_id), (timestamp, _registered) in date_run_candidates.items()
            if candidate_date == date_str
        ]
        if candidates:
            latest = max(candidates)
            date_latest_run[date_str] = latest[1]

    if roots["snapshot"].exists():
        for date_dir in sorted(roots["snapshot"].iterdir()):
            if not date_dir.is_dir():
                continue
            for run_dir in sorted((run for run in date_dir.iterdir() if run.is_dir()), reverse=True):
                snap_path = run_dir / "premarket_snapshot.json"
                if not snap_path.exists():
                    continue
                try:
                    snap = json.loads(snap_path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if snap.get("options", {}).get("status") == "available":
                    date_modules[date_dir.name].add("options")
                if snap.get("macro", {}).get("status") == "available":
                    date_modules[date_dir.name].add("macro")
                if snap.get("market_odds", {}).get("status") == "available":
                    date_modules[date_dir.name].add("market_odds")
                consider_latest_run(date_dir.name, run_dir.name, _generated_at_from_paths(snap_path))

    if roots["final_report"].exists():
        for date_dir in sorted(roots["final_report"].iterdir()):
            if not date_dir.is_dir():
                continue
            for run_dir in date_dir.iterdir():
                report_path = run_dir / "final_report.md"
                if not run_dir.is_dir() or not report_path.exists():
                    continue
                date_modules[date_dir.name].add("final_report")
                consider_latest_run(date_dir.name, run_dir.name, _generated_at_from_paths(report_path))

    if roots["strategy_card"].exists():
        for date_dir in sorted(roots["strategy_card"].iterdir()):
            if not date_dir.is_dir():
                continue
            for run_dir in date_dir.iterdir():
                card_path = run_dir / "strategy_card.json"
                if not run_dir.is_dir() or not card_path.exists():
                    continue
                date_modules[date_dir.name].add("strategy_card")
                consider_latest_run(
                    date_dir.name, run_dir.name, _generated_at_from_paths(card_path, run_dir / "strategy_card.md")
                )

    for report_type, root, filename in (
        ("observation_report", roots["observation_report"], "final_report.md"),
        ("observation_strategy_card", roots["observation_strategy_card"], "strategy_card.json"),
    ):
        if not root.exists():
            continue
        for date_dir in sorted(root.iterdir()):
            if not date_dir.is_dir():
                continue
            for run_dir in date_dir.iterdir():
                artifact_path = run_dir / filename
                if not run_dir.is_dir() or not artifact_path.exists():
                    continue
                date_modules[date_dir.name].add(report_type)
                consider_latest_run(
                    date_dir.name,
                    run_dir.name,
                    _generated_at_from_paths(
                        artifact_path, run_dir / "structured_report.json", run_dir / "strategy_card.md"
                    ),
                )

    cme_base = _storage._PROJECT_ROOT / "storage" / "outputs" / "cme_options"
    if cme_base.exists():
        for date_dir in sorted(cme_base.iterdir()):
            if date_dir.is_dir() and (
                (date_dir / "options_analysis.json").exists() or (date_dir / "options_analysis.md").exists()
            ):
                date_modules[date_dir.name].add("options")

    macro_base = _storage._PROJECT_ROOT / "storage" / "outputs" / "macro"
    if macro_base.exists():
        for date_dir in sorted(macro_base.iterdir()):
            if not date_dir.is_dir():
                continue
            if _macro_report_md_path(date_dir) is not None or any(
                _macro_report_md_path(run_dir) is not None for run_dir in date_dir.iterdir() if run_dir.is_dir()
            ):
                date_modules[date_dir.name].add("macro")
            for run_dir in date_dir.iterdir():
                if not run_dir.is_dir():
                    continue
                report_path = _macro_report_md_path(run_dir)
                if report_path is not None:
                    consider_latest_run(date_dir.name, run_dir.name, _generated_at_from_paths(report_path))

    if roots["jin10"].exists():
        for date_dir in sorted(roots["jin10"].iterdir()):
            if not date_dir.is_dir():
                continue
            indexed_runs: list[Path] = []
            for run_dir in date_dir.iterdir():
                if not run_dir.is_dir() or not (run_dir / "daily_analysis.html").exists():
                    continue
                daily_path = run_dir / "daily_analysis.json"
                payload = _read_optional_json(daily_path) or {}
                is_weekly = (
                    str(payload.get("family") or "").strip() == "jin10_weekly_visual"
                    or str(payload.get("report_type") or "").strip().lower() == "weekly"
                )
                report_type = _jin10_index_report_type(payload, is_weekly=is_weekly)
                if report_type is None:
                    continue
                date_modules[date_dir.name].add(report_type)
                indexed_runs.append(run_dir)
            if indexed_runs:
                for run_dir in indexed_runs:
                    consider_latest_run(
                        date_dir.name,
                        run_dir.name,
                        _generated_at_from_paths(
                            run_dir / "daily_analysis.html",
                            run_dir / "daily_analysis.json",
                        ),
                    )

    # Registered report/artifact timestamps are authoritative for a known run.
    # A copied legacy file must not supersede the registry's generated time.
    for report in _collect_registered_reports_from_db(asset):
        trade_date = str(report.get("trade_date") or "").strip()
        if not trade_date or not report.get("available"):
            continue
        report_type = str(report.get("type") or "").strip()
        report_family = str(report.get("family") or "").strip()
        if report_type == "gold_policy_daily" and report_family == "gold_policy_daily_report":
            date_modules[trade_date].add("gold_policy_daily")
        elif report_type in {"observation_report", "observation_strategy_card"}:
            date_modules[trade_date].add(report_type)
        elif report_family in _OBSERVATION_REPORT_FAMILIES:
            date_modules[trade_date].add(report_family.removesuffix("_markdown"))
        consider_latest_run(
            trade_date,
            report.get("run_id"),
            report.get("generated_at"),
            registered=True,
        )

    dates_out = [
        {
            "trade_date": date_str,
            "modules": sorted(date_modules[date_str]),
            "latest_run_id": date_latest_run.get(date_str),
            "has_final_report": "final_report" in date_modules[date_str],
            "has_strategy_card": "strategy_card" in date_modules[date_str],
        }
        for date_str in sorted(date_modules.keys(), reverse=True)
    ]
    return {"asset": asset, "dates": dates_out, "total_dates": len(dates_out)}
