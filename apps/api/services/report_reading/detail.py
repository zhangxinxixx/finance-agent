from __future__ import annotations

import json
import logging
import uuid
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable

from pydantic import ValidationError
from sqlalchemy import or_, select
from sqlalchemy.exc import OperationalError, ProgrammingError, SQLAlchemyError
from sqlalchemy.orm import Session

from apps.api.schemas.common import ArtifactType, DataStatus, ReportLifecycleStatus, ReviewStatus, WarningItem
from apps.api.schemas.report import (
    ReportAnalysisAgentOutput,
    ReportAnalysisInputs,
    ReportDetail,
    ReportDeterministicInput,
)
from apps.api.schemas.report import ReportArtifact as ReportArtifactSchema
from apps.api.schemas.source_trace import ArtifactRef, SnapshotRef, SourceRef
from apps.api.services import _storage
from apps.api.services import report_jin10_service as _jin10
from apps.api.services._report_lineage import resolve_report_lineage_context
from apps.api.services._storage import _iso
from apps.api.services._trace_refs import (
    coerce_artifact_type,
    dedupe_artifact_refs,
    dedupe_source_refs,
    parse_source_refs,
)
from apps.api.services.agent_output_service import build_agent_output_summary
from apps.api.services.gold_mainline_service import get_gold_mainlines_latest
from apps.api.services.gold_result_identity import build_report_result_identity
from apps.api.services.llm_audit_service import audit_summary, build_report_llm_audit_view
from apps.api.services.report_jin10_service import (
    _find_external_jin10_weekly_dir,
    _jin10_quality_blocks_content,
    _jin10_report_status,
    _normalize_jin10_quality_audit,
    _read_optional_json,
)
from apps.api.services.report_market_odds_service import load_report_market_odds_view
from apps.api.services.report_reading.common import (
    _report_index_family,
    _report_index_title,
)
from apps.api.services.research_identity import build_research_identity
from apps.renderer.contracts import MacroEventFollowupStructuredPayload, WeeklyContextRevisionPayload
from apps.runtime.storage_paths import project_artifact_path, remap_storage_path
from apps.runtime.output_disposition import OUTPUT_CLEANUP_KEY, is_output_purged
from database.models.analysis import AgentOutput, AnalysisSnapshot, FinalAnalysisResult
from database.models.report import ReportArtifact as ReportArtifactModel
from database.models.report import ReportItem
from database.models.task import TaskRun
from database.models.task import TaskStatus as TaskRunStatus
from database.queries.report import get_report_artifacts as query_report_artifacts
from database.queries.report import get_report_detail as query_report_detail

logger = logging.getLogger(__name__)


_STANDARD_ARTIFACT_TYPES = {
    ArtifactType.source_md,
    ArtifactType.analysis_md,
    ArtifactType.visual_html,
    ArtifactType.structured_json,
}
_FINAL_REPORT_MARKDOWN_ARTIFACT_TYPES = {
    ArtifactType.analysis_md,
    ArtifactType.structured_json,
}
_OBSERVATION_REPORT_FAMILIES = {
    "observation_report_markdown",
    "observation_strategy_card",
}
_OBSERVATION_REPORT_MARKDOWN_ARTIFACT_TYPES = {
    ArtifactType.analysis_md,
    ArtifactType.structured_json,
}
_OBSERVATION_STRATEGY_CARD_ARTIFACT_TYPES = {
    ArtifactType.structured_json,
}
def get_report_detail(db: Session, report_id: str) -> ReportDetail | None:
    detail = None
    item = None
    registered = False
    try:
        item = query_report_detail(db, report_id)
        if item is not None:
            registered_artifacts = query_report_artifacts(db, report_id)
            if (
                is_output_purged(item)
                or str(item.lifecycle_status or "").lower() == "purged"
                or any(is_output_purged(artifact) for artifact in registered_artifacts)
            ):
                return None
            detail = _build_report_detail_from_item(item, registered_artifacts)
            registered = True
    except SQLAlchemyError:
        pass
    if detail is None:
        if _is_report_read_purged(db, report_id):
            return None
        detail = _build_legacy_report_detail(db, report_id)
    if detail is None:
        return None
    if not registered:
        # A legacy adapter can resolve a basename/stem to the real research
        # identity after the first alias guard ran.  Recheck that identity
        # before any enrichment or filesystem-backed body is exposed.
        resolved_identities = {
            str(identity)
            for identity in (detail.run_id, detail.snapshot_id)
            if identity
        }
        if any(_is_report_read_purged(db, identity) for identity in resolved_identities):
            return None
    detail = _enrich_macro_report_lineage(detail)
    detail = _enforce_task_run_report_authority(db, detail)
    # Optional database enrichment must not prevent historical filesystem reads.
    enrichers = [_enrich_report_detail_with_llm_audits]
    if registered:
        enrichers.insert(0, _enrich_report_detail_with_lineage_warnings)
    for enrich in enrichers:
        try:
            detail = enrich(db, detail)
        except SQLAlchemyError:
            pass
    detail = _enforce_final_report_read_authority(db, detail)
    detail = _with_result_identity(
        _enrich_report_detail_with_market_odds(_enrich_report_detail_with_gold_macro_context(detail))
    )
    # This reserved reader field is derived in memory, never trusted from disk.
    if isinstance(detail.structured_payload, dict) and "_reader_trade_plan" in detail.structured_payload:
        payload = dict(detail.structured_payload)
        payload.pop("_reader_trade_plan")
        detail = detail.model_copy(update={"structured_payload": payload})
    if registered and item is not None and item.family == "observation_report_markdown":
        # Validate this registration, never a latest report. Only this optional
        # projection is exception-safe; existing detail service errors propagate.
        from apps.api.services.dashboard_research_service import _project_report
        try:
            plan = _project_report(db, item, _storage._PROJECT_ROOT).get("final_trade_plan")
        except Exception:
            logger.warning("Optional research trade plan unavailable", extra={"report_id": report_id})
            plan = None
        if plan is not None:
            payload = dict(detail.structured_payload or {})
            payload["_reader_trade_plan"] = plan
            detail = detail.model_copy(update={"structured_payload": payload})
    snapshot_payload = None
    if detail.snapshot_id and detail.run_id:
        try:
            snapshot_row = db.scalar(select(AnalysisSnapshot).where(
                AnalysisSnapshot.snapshot_id == detail.snapshot_id,
                AnalysisSnapshot.run_id == detail.run_id))
            if snapshot_row is not None:
                snapshot_payload = snapshot_row.payload
        except SQLAlchemyError:
            pass
    identity = build_research_identity(
        report_id=detail.report_id, run_id=detail.run_id, snapshot_id=detail.snapshot_id,
        trade_date=detail.trade_date, snapshot=snapshot_payload, generated_at=detail.generated_at,
        historical=(detail.report_identity or {}).get("authority") == "historical_only")
    return detail.model_copy(update={"research_identity": identity})


def _is_report_read_purged(db: Session, report_id: str) -> bool:
    """Check all persisted report aliases before any legacy filesystem fallback."""
    aliases = {str(report_id)}
    for prefix in ("final_report:", "strategy_card:"):
        if str(report_id).startswith(prefix):
            aliases.add(str(report_id)[len(prefix) :])
    try:
        report_rows = list(
            db.scalars(
                select(ReportItem).where(
                    or_(
                        ReportItem.report_id.in_(aliases),
                        ReportItem.run_id.in_(aliases),
                        ReportItem.snapshot_id.in_(aliases),
                    )
                )
            )
        )
        if any(
            is_output_purged(row)
            or str(row.lifecycle_status or "").lower() == "purged"
            for row in report_rows
        ):
            return True
        if any(is_output_purged(artifact) for row in report_rows for artifact in (row.artifacts or [])):
            return True

        all_report_rows = db.scalars(select(ReportItem)).all()
        for row in all_report_rows:
            row_purged = (
                is_output_purged(row)
                or str(row.lifecycle_status or "").lower() == "purged"
            )
            purged_artifacts = [artifact for artifact in (row.artifacts or []) if is_output_purged(artifact)]
            if not row_purged and not purged_artifacts:
                continue
            identities = {str(row.report_id), str(row.run_id or ""), str(row.snapshot_id or "")}
            identities.update(
                candidate
                for artifact in (row.artifacts or []) if row_purged or artifact in purged_artifacts
                for candidate in _path_candidate_ids(artifact.file_path)
            )
            if str(report_id) in identities:
                return True

        final_rows = list(
            db.execute(
                select(
                    FinalAnalysisResult.run_id,
                    FinalAnalysisResult.snapshot_id,
                    FinalAnalysisResult.payload[OUTPUT_CLEANUP_KEY].label("output_cleanup"),
                ).where(
                    or_(
                        FinalAnalysisResult.run_id.in_(aliases),
                        FinalAnalysisResult.snapshot_id.in_(aliases),
                    )
                )
            ).mappings()
        )
        if any(is_output_purged(row) for row in final_rows):
            return True

        # Legacy detail URLs also use a file path, basename, or parent run
        # directory as the report id.  Resolve those aliases before allowing
        # the filesystem adapter to open a residual tombstoned file.
        all_final_rows = db.execute(
            select(
                FinalAnalysisResult.run_id,
                FinalAnalysisResult.snapshot_id,
                FinalAnalysisResult.final_report_path,
                FinalAnalysisResult.run_summary_path,
                FinalAnalysisResult.payload[OUTPUT_CLEANUP_KEY].label("output_cleanup"),
            )
        ).mappings()
        return any(
            is_output_purged(row) and str(report_id) in _legacy_report_candidate_ids(row)
            for row in all_final_rows
        )
    except SQLAlchemyError:
        return False


def _historical_final_report_fields() -> dict[str, Any]:
    return {
        "output_mode": "historical",
        "authority": "historical_only",
        "publish_allowed": False,
        "data_status": "partial",
        "lifecycle_status": "needs_review",
        "review_status": "needs_review",
    }


def _safe_final_report_path(file_path: str | Path) -> Path | None:
    """Final reports may only read regular files within this storage root."""
    try:
        path = Path(file_path)
        path = project_artifact_path(path, project_root=_storage._PROJECT_ROOT).resolve(strict=True)
        if path.is_relative_to((_storage._PROJECT_ROOT / "storage").resolve()) and path.is_file():
            if not {"observation_report", "observation_strategy_card"}.intersection(path.parts):
                return path
    except (OSError, ValueError, RuntimeError):
        pass
    return None


def _final_report_verified_for_read(db: Session, **kwargs: Any) -> bool:
    try:
        return _verified_final_report(db, **kwargs)
    except SQLAlchemyError:
        # Missing tables/old schemas remove formal eligibility, never readability.
        return False


def _verified_final_report(db, *, run_id, snapshot_id, path, digest):
    """Existing files alone do not establish completed, sourced research."""
    try:
        run = db.get(TaskRun, uuid.UUID(str(run_id)))
        if run is None or run.status != TaskRunStatus.success or run.snapshot_id != snapshot_id:
            return False
        registered = db.scalar(
            select(ReportItem)
            .where(
                ReportItem.run_id == run_id,
                ReportItem.snapshot_id == snapshot_id,
                or_(ReportItem.report_type == "final_report", ReportItem.family == "final_report_markdown"),
            )
            .order_by(ReportItem.updated_at.desc())
            .limit(1)
        )
        if registered is not None and not _final_report_status_valid(registered):
            return False
        snapshot = db.scalar(
            select(AnalysisSnapshot).where(
                AnalysisSnapshot.run_id == run_id,
                AnalysisSnapshot.snapshot_id == snapshot_id,
            )
        )
        if snapshot is None or snapshot.status != "success":
            return False
        root = (_storage._PROJECT_ROOT / "storage").resolve()
        path = Path(path)
        path = project_artifact_path(path, project_root=_storage._PROJECT_ROOT).resolve(strict=True)
        if not path.is_relative_to(root) or not digest or sha256(path.read_bytes()).hexdigest() != digest:
            return False
        from apps.api.services.dashboard_research_service import _read_registered_json

        payload = _read_registered_json(snapshot.artifact_path, _storage._PROJECT_ROOT)
        if payload != snapshot.payload or sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest() != snapshot.payload_sha256:
            return False
        if payload.get("run_id") != run_id or payload.get("snapshot_id") != snapshot_id:
            return False
        from apps.analysis.snapshots.input_validation import research_enabled, research_report_rejection_reasons

        if research_enabled(payload):
            coordinator = db.scalar(
                select(AgentOutput).where(
                    AgentOutput.run_id == run_id,
                    AgentOutput.snapshot_id == snapshot_id,
                    AgentOutput.agent_name == "coordinator_agent",
                )
            )
            return not research_report_rejection_reasons(payload, coordinator.payload if coordinator else None)
        return True
    except (ValueError, TypeError, OSError, KeyError):
        return False


def _final_report_status_valid(item):
    return item.data_status in {"live", "available"} and item.lifecycle_status in {
        "generated",
        "snapshot_bound",
        "published",
        "exported",
    }


def _enforce_final_report_read_authority(db: Session, detail: ReportDetail) -> ReportDetail:
    if detail.family not in {"final_report", "final_report_markdown"}:
        return detail
    verified = any(
        artifact.artifact_type == ArtifactType.analysis_md
        and _safe_final_report_path(artifact.file_path) is not None
        and _final_report_verified_for_read(
            db, run_id=detail.run_id, snapshot_id=detail.snapshot_id,
            path=artifact.file_path, digest=artifact.sha256,
        )
        for artifact in detail.artifacts
    )
    if verified:
        return detail
    return detail.model_copy(update={
        "data_status": DataStatus.partial,
        "lifecycle_status": ReportLifecycleStatus.needs_review,
        "review_status": ReviewStatus.pending,
        "warnings": _merge_warning_items(detail.warnings, [WarningItem(
            code="historical-final-report-unverified",
            message="历史综合报告仅供回看，未通过当前研究完整性与来源校验，不能作为当前正式结论或交易依据。",
        )]),
    })


def _with_result_identity(detail: ReportDetail) -> ReportDetail:
    identity = build_report_result_identity(
        storage_root=_storage._PROJECT_ROOT / "storage",
        run_id=detail.run_id,
        trade_date=detail.trade_date,
        report_family=detail.family,
        report_snapshot_id=detail.snapshot_id,
        report_identity=detail.report_identity,
    )
    return detail.model_copy(update={"result_identity": identity})


def _non_authoritative_premarket_run_ids(db: Session, run_ids: Iterable[str | None]) -> set[str]:
    parsed_ids: dict[uuid.UUID, str] = {}
    for run_id in run_ids:
        if not run_id:
            continue
        try:
            parsed_ids[uuid.UUID(str(run_id))] = str(run_id)
        except ValueError:
            continue
    if not parsed_ids:
        return set()

    try:
        rows = db.scalars(select(TaskRun).where(TaskRun.id.in_(parsed_ids))).all()
    except (OperationalError, ProgrammingError):
        return set()
    return {str(row.id) for row in rows if row.name == "premarket" and row.status != TaskRunStatus.success}


def _load_non_authoritative_premarket_run_ids(run_ids: Iterable[str | None]) -> set[str]:
    db = _storage._try_db_session()
    if db is None:
        return set()
    try:
        return _non_authoritative_premarket_run_ids(db, run_ids)
    finally:
        db.close()


def _enforce_task_run_report_authority(db: Session, detail: ReportDetail) -> ReportDetail:
    if detail.family != "macro_report":
        return detail
    task_blocked = detail.run_id in _non_authoritative_premarket_run_ids(db, [detail.run_id])
    publish_allowed = _gold_publish_allowed(detail.trade_date, detail.run_id)
    quality_blocked = publish_allowed is False
    lineage_blocked = publish_allowed is True and (
        not detail.snapshot_id or not detail.source_refs or not detail.input_snapshot_ids
    )

    if not task_blocked and not quality_blocked and not lineage_blocked:
        return detail
    if task_blocked:
        code = "upstream-task-not-successful"
        message = "The premarket task did not complete successfully; this intermediate report is not authoritative."
    elif quality_blocked:
        code = "quality-gate-blocked"
        message = "The Gold analysis QualityGate blocked publication; this intermediate report is not authoritative."
    else:
        code = "macro-lineage-unavailable"
        message = (
            "The accepted macro report lacks a validated canonical snapshot or source lineage; it is not authoritative."
        )
    return detail.model_copy(
        update={
            "data_status": DataStatus.unavailable,
            "lifecycle_status": ReportLifecycleStatus.needs_review,
            "warnings": _merge_warning_items(
                detail.warnings,
                [
                    WarningItem(
                        code=code,
                        message=message,
                    )
                ],
            ),
        }
    )


def _enrich_macro_report_lineage(detail: ReportDetail) -> ReportDetail:
    if detail.family != "macro_report":
        return detail
    lineage = _load_macro_report_lineage(detail.trade_date, detail.run_id)
    if lineage is None:
        return detail
    snapshot_id, source_refs, input_snapshot_ids = lineage
    return detail.model_copy(
        update={
            "snapshot_id": snapshot_id,
            "source_refs": dedupe_source_refs([*detail.source_refs, *source_refs]),
            "input_snapshot_ids": list(dict.fromkeys([*detail.input_snapshot_ids, *input_snapshot_ids])),
        }
    )


def _load_macro_report_lineage(
    trade_date: str | None,
    run_id: str | None,
) -> tuple[str, list[SourceRef], list[str]] | None:
    if not trade_date or not run_id:
        return None
    snapshot = _read_optional_json(
        _storage._PROJECT_ROOT
        / "storage"
        / "features"
        / "snapshots"
        / "XAUUSD"
        / trade_date
        / run_id
        / "premarket_snapshot.json"
    )
    quality_gate = _read_optional_json(
        _storage._PROJECT_ROOT / "storage" / "analysis" / "gold_mainlines" / trade_date / run_id / "quality_gate_result.json"
    )
    if not isinstance(snapshot, dict) or not isinstance(quality_gate, dict):
        return None
    expected_snapshot_id = f"XAUUSD:{trade_date}:{run_id}"
    if (
        snapshot.get("asset") != "XAUUSD"
        or snapshot.get("trade_date") != trade_date
        or snapshot.get("run_id") != run_id
        or snapshot.get("snapshot_id") != expected_snapshot_id
        or quality_gate.get("trade_date") != trade_date
        or quality_gate.get("run_id") != run_id
        or quality_gate.get("snapshot_id") != expected_snapshot_id
    ):
        return None
    source_refs = parse_source_refs(snapshot.get("source_refs"))
    input_snapshot_ids = _normalize_snapshot_ids(snapshot.get("input_snapshot_ids"))
    if not source_refs or not input_snapshot_ids:
        return None
    return expected_snapshot_id, source_refs, input_snapshot_ids


def _gold_publish_allowed(trade_date: str | None, run_id: str | None) -> bool | None:
    if not trade_date or not run_id:
        return None
    payload = _read_optional_json(
        _storage._PROJECT_ROOT / "storage" / "analysis" / "gold_mainlines" / trade_date / run_id / "quality_gate_result.json"
    )
    value = payload.get("publish_allowed") if isinstance(payload, dict) else None
    return value if isinstance(value, bool) else None


def _enrich_report_detail_with_llm_audits(db: Session, detail: ReportDetail) -> ReportDetail:
    """Attach gateway audit summaries without making report detail depend on them."""

    from database.queries.llm_audit import list_llm_call_audits

    rows_by_id = {}
    for report_id, run_id in ((detail.report_id, None), (None, detail.run_id)):
        if not report_id and not run_id:
            continue
        rows, _ = list_llm_call_audits(db, limit=200, report_id=report_id, run_id=run_id)
        rows_by_id.update({row.id: row for row in rows})
    return detail.model_copy(update={"llm_audits": [audit_summary(row) for row in rows_by_id.values()]})


def _enrich_report_detail_with_market_odds(detail: ReportDetail) -> ReportDetail:
    if detail.market_odds_evidence is not None:
        return detail
    view = load_report_market_odds_view(
        storage_root=_storage._PROJECT_ROOT / "storage",
        trade_date=detail.trade_date,
        article_id=detail.report_id.rsplit(":", 1)[-1],
    )
    return detail.model_copy(update={"market_odds_evidence": view}) if view is not None else detail


def get_report_artifacts(db: Session, report_id: str) -> list[ReportArtifactSchema] | None:
    detail = get_report_detail(db, report_id)
    if detail is None:
        return None
    return detail.artifacts


def get_report_source(db: Session, report_id: str) -> dict[str, Any] | None:
    detail = get_report_detail(db, report_id)
    if detail is None:
        return None
    artifact = _pick_report_artifact(detail.artifacts, ArtifactType.source_md)
    if not _page_report_artifact_allowed(artifact):
        return None
    return _build_artifact_payload(artifact, report_id=detail.report_id)


def get_report_analysis(db: Session, report_id: str) -> dict[str, Any] | None:
    detail = get_report_detail(db, report_id)
    if detail is None:
        return None
    artifact = _pick_report_artifact(detail.artifacts, ArtifactType.analysis_md)
    if artifact is None:
        artifact = _pick_legacy_analysis_artifact(detail.artifacts)
    if (detail.family in {"final_report", "final_report_markdown"}
            and artifact is not None and _safe_final_report_path(artifact.file_path) is None):
        return None
    return _build_artifact_payload(artifact, report_id=detail.report_id)


def get_report_visual(db: Session, report_id: str) -> dict[str, Any] | None:
    return _build_report_artifact_payload(db, report_id, ArtifactType.visual_html)


def get_report_evidence(db: Session, report_id: str) -> dict[str, Any] | None:
    return _build_report_artifact_payload_by_basename(db, report_id, ArtifactType.structured_json, "evidence.json")


def get_report_analysis_inputs(db: Session, report_id: str) -> ReportAnalysisInputs | None:
    detail = get_report_detail(db, report_id)
    if detail is None:
        return None

    lineage = resolve_report_lineage_context(
        db,
        report_id=detail.report_id,
        report_run_id=detail.run_id,
        report_snapshot_id=detail.snapshot_id,
    )
    snapshot = lineage.snapshot
    detail_input_snapshot_ids = _normalize_snapshot_ids(detail.input_snapshot_ids)
    agent_rows, used_run_id_lineage_fallback = _list_report_agent_outputs(db, detail, snapshot=snapshot)
    all_agent_outputs = [_build_report_agent_output(row) for row in agent_rows]
    fact_reviews = [
        item for item in all_agent_outputs if item.registry_id == "fact_review_agent" or item.role == "review_agent"
    ]
    synthesis_outputs = [
        item for item in all_agent_outputs if item.registry_id == "synthesis_agent" or item.role == "synthesis_agent"
    ]
    agent_outputs = [
        item
        for item in all_agent_outputs
        if item.registry_id not in {"fact_review_agent", "synthesis_agent"}
        and item.role not in {"review_agent", "synthesis_agent"}
    ]

    warnings = _merge_warning_items(detail.warnings, lineage.warnings)
    deterministic_inputs: list[ReportDeterministicInput] = []
    if snapshot is not None:
        deterministic_inputs.append(_build_analysis_snapshot_input(snapshot))
        deterministic_inputs.extend(
            _build_input_snapshot_items(db, snapshot.input_snapshot_ids, run_id=snapshot.run_id)
        )
    elif detail_input_snapshot_ids:
        deterministic_inputs.extend(_build_input_snapshot_items(db, detail_input_snapshot_ids, run_id=detail.run_id))
    elif agent_rows:
        deterministic_inputs.extend(_build_agent_fallback_inputs(agent_rows))
        warnings.append(
            WarningItem(
                code="analysis-inputs-agent-fallback",
                message="No analysis snapshot found; deterministic inputs derived from persisted agent inputs",
            )
        )
    else:
        warnings.append(
            WarningItem(
                code="analysis-inputs-unavailable",
                message="No analysis snapshot or persisted agent inputs found for this report",
            )
        )

    if not agent_outputs:
        warnings.append(
            WarningItem(
                code="agent-outputs-unavailable",
                message="No persisted agent_outputs found for this report",
                hint="需重跑对应报告 Agent 才能在报告详情中展示分析输入链。",
            )
        )
    elif used_run_id_lineage_fallback:
        warnings.append(
            WarningItem(
                code="agent-outputs-lineage-fallback",
                message="Some agent outputs were matched by run_id because snapshot-aligned rows were unavailable",
                hint="报告血缘仍可展示，但应优先补齐与报告 snapshot_id 一致的 agent output 行。",
            )
        )

    source_refs = dedupe_source_refs(
        [
            *detail.source_refs,
            *[source for item in deterministic_inputs for source in item.source_refs],
            *[source for item in all_agent_outputs for source in item.source_refs],
        ]
    )
    artifact_refs = dedupe_artifact_refs(
        [
            *detail.artifacts,
            *[artifact for item in deterministic_inputs for artifact in item.artifact_refs],
            *[artifact for item in all_agent_outputs for artifact in item.artifact_refs],
        ]
    )

    data_status = detail.data_status
    if (not deterministic_inputs or not agent_outputs) and data_status == DataStatus.live:
        data_status = DataStatus.partial

    return ReportAnalysisInputs(
        report_id=detail.report_id,
        family=detail.family,
        title=detail.title,
        asset=detail.asset,
        trade_date=detail.trade_date,
        run_id=lineage.resolved_run_id,
        snapshot_id=lineage.resolved_snapshot_id,
        data_status=data_status,
        source_refs=source_refs,
        artifact_refs=artifact_refs,
        warnings=warnings,
        deterministic_inputs=deterministic_inputs,
        agent_outputs=agent_outputs,
        fact_reviews=fact_reviews,
        synthesis_outputs=synthesis_outputs,
    )


def _build_report_artifact_payload(db: Session, report_id: str, artifact_type: ArtifactType) -> dict[str, Any] | None:
    detail = get_report_detail(db, report_id)
    if detail is None:
        return None
    artifact = _pick_report_artifact(detail.artifacts, artifact_type)
    if not _page_report_artifact_allowed(artifact):
        return None
    return _build_artifact_payload(artifact, report_id=detail.report_id)


def _build_report_artifact_payload_by_basename(
    db: Session, report_id: str, artifact_type: ArtifactType, basename: str
) -> dict[str, Any] | None:
    """Pick an artifact by type, preferring one whose file basename matches.

    Falls back to the first artifact of the given type if no basename match
    exists, preserving legacy behavior for reports without named files.
    """
    detail = get_report_detail(db, report_id)
    if detail is None:
        return None
    artifact = _pick_artifact_by_basename(detail.artifacts, artifact_type, basename)
    if not _page_report_artifact_allowed(artifact):
        return None
    return _build_artifact_payload(artifact, report_id=detail.report_id)


def get_report_artifact_asset_path(
    db: Session, report_id: str, artifact_type: ArtifactType, asset_path: str
) -> Path | None:
    detail = get_report_detail(db, report_id)
    if detail is None:
        return None
    artifact = _pick_report_artifact(detail.artifacts, artifact_type)
    if not _page_report_artifact_allowed(artifact):
        return None
    if artifact is None:
        return None
    return _resolve_report_asset_path(artifact.file_path, asset_path)


def _page_report_artifact_allowed(artifact: ReportArtifactSchema | None) -> bool:
    if artifact is None:
        return False
    raw_path = Path(artifact.file_path)
    leaf = raw_path.name.lower()
    if leaf.startswith("raw") or "raw_article" in leaf or raw_path.suffix.lower() in {
        ".pdf",
        ".csv",
        ".xlsx",
        ".xls",
        ".zip",
        ".parquet",
    }:
        return False
    candidate = project_artifact_path(raw_path, project_root=_storage._PROJECT_ROOT)
    try:
        resolved = candidate.resolve()
        allowed_roots = [
            (_storage._PROJECT_ROOT / "storage" / layer).resolve()
            for layer in ("outputs", "features", "analysis", "reports")
        ]
    except OSError:
        return False
    return any(resolved.is_relative_to(root) for root in allowed_roots)


def _enrich_report_detail_with_lineage_warnings(db: Session, detail: ReportDetail) -> ReportDetail:
    lineage = resolve_report_lineage_context(
        db,
        report_id=detail.report_id,
        report_run_id=detail.run_id,
        report_snapshot_id=detail.snapshot_id,
    )
    warnings = _merge_warning_items(detail.warnings, lineage.warnings)
    normalized_run_id = lineage.resolved_run_id
    normalized_snapshot_id = lineage.resolved_snapshot_id
    if (
        warnings == detail.warnings
        and normalized_run_id == detail.run_id
        and normalized_snapshot_id == detail.snapshot_id
    ):
        return detail
    return detail.model_copy(
        update={"warnings": warnings, "run_id": normalized_run_id, "snapshot_id": normalized_snapshot_id}
    )


def _enrich_report_detail_with_gold_macro_context(detail: ReportDetail) -> ReportDetail:
    # A verified daily-close report explains its frozen bundle. The latest
    # independent mainline artifact is not evidence for this report's run.
    if detail.family == "gold_policy_daily_report":
        return detail
    if detail.asset and str(detail.asset).upper() not in {"XAUUSD", "GC", "GOLD"}:
        return detail
    original = (detail.structured_payload or {}).get("gold_macro_overview")
    if isinstance(original, dict):
        detail = detail.model_copy(update={"gold_macro_overview": original})
    try:
        payload = get_gold_mainlines_latest(project_root=_storage._PROJECT_ROOT)
    except Exception as exc:
        logger.warning(
            "Failed to load gold macro overview for report detail",
            exc_info=exc,
            extra={"service": "report_detail", "stage": "gold_macro_overview", "degraded": True},
        )
        return detail
    overview = payload.get("gold_macro_overview") if isinstance(payload, dict) else None
    if not isinstance(overview, dict) or not overview:
        return detail
    # The original report is immutable. Latest independent context is labelled
    # separately and cannot change its research identity or data timestamp.
    context = {"relationship": "current_context_only", "gold_macro_overview": overview,
               "market_odds": None,
               "context_as_of": overview.get("as_of") or overview.get("generated_at") or payload.get("generated_at")}
    return detail.model_copy(update={"current_context": context})


def _list_report_agent_outputs(
    db: Session,
    detail: ReportDetail,
    *,
    snapshot: AnalysisSnapshot | None,
) -> tuple[list[AgentOutput], bool]:
    snapshot_id = snapshot.snapshot_id if snapshot is not None else detail.snapshot_id
    if snapshot_id:
        snapshot_rows = list(
            db.scalars(
                select(AgentOutput)
                .where(AgentOutput.snapshot_id == snapshot_id)
                .order_by(AgentOutput.created_at.desc(), AgentOutput.agent_name.asc())
            )
        )
    else:
        snapshot_rows = []
    candidate_run_ids = [value for value in {detail.run_id, detail.report_id} if value]
    latest_by_agent: dict[str, AgentOutput] = {}
    for row in snapshot_rows:
        if row.agent_name not in latest_by_agent:
            latest_by_agent[row.agent_name] = row

    used_run_id_lineage_fallback = False
    if candidate_run_ids:
        fallback_rows = list(
            db.scalars(
                select(AgentOutput)
                .where(AgentOutput.run_id.in_(candidate_run_ids))
                .order_by(AgentOutput.created_at.desc(), AgentOutput.agent_name.asc())
            )
        )
        for row in fallback_rows:
            if row.agent_name in latest_by_agent:
                continue
            latest_by_agent[row.agent_name] = row
            if snapshot_id and row.snapshot_id != snapshot_id:
                used_run_id_lineage_fallback = True

    return list(latest_by_agent.values()), used_run_id_lineage_fallback


def _build_report_agent_output(row: AgentOutput) -> ReportAnalysisAgentOutput:
    summary = build_agent_output_summary(row)
    return ReportAnalysisAgentOutput(
        agent_output_id=summary["agent_output_id"],
        registry_id=summary["registry_id"],
        agent_name=summary["agent_name"],
        display_name=summary["display_name"],
        role=summary["role"],
        module=summary["module"],
        version=summary["version"],
        run_id=summary["run_id"],
        snapshot_id=summary["snapshot_id"],
        status=summary["status"],
        bias=summary["bias"],
        confidence=float(summary["confidence"] or 0.0),
        summary=summary["summary"],
        summary_zh=summary["summary_zh"],
        key_findings=[str(item) for item in summary["key_findings"]],
        risk_points=[str(item) for item in summary["risk_points"]],
        watchlist=[str(item) for item in summary["watchlist"]],
        invalid_conditions=[str(item) for item in summary["invalid_conditions"]],
        source_refs=parse_source_refs(summary["source_refs"]),
        artifact_refs=_normalize_agent_artifact_refs(
            summary["artifact_refs"], agent_output_id=summary["agent_output_id"]
        ),
        claims=summary["claims"],
        claim_reviews=summary["claim_reviews"],
        claim_count=int(summary["claim_count"]),
        fact_review_status=summary["fact_review_status"],
        prompt_version=summary["prompt_version"],
        generated_by=summary["generated_by"],
        llm_model=summary["llm_model"],
        llm_audit=build_report_llm_audit_view(row),
        created_at=row.created_at,
    )


def _build_analysis_snapshot_input(snapshot: AnalysisSnapshot) -> ReportDeterministicInput:
    sections = _snapshot_sections(snapshot.payload)
    source_refs = parse_source_refs(snapshot.source_refs)
    snapshot_ref = SnapshotRef(
        snapshot_id=snapshot.snapshot_id,
        snapshot_type="analysis",
        data_date=_iso(snapshot.trade_date),
        run_id=snapshot.run_id,
        data_status=_map_data_status(snapshot.status),
        created_at=snapshot.created_at,
        input_snapshot_ids=_normalize_snapshot_ids(snapshot.input_snapshot_ids),
    )
    artifact_refs = [
        ArtifactRef(
            artifact_id=f"{snapshot.snapshot_id}:snapshot",
            artifact_type=ArtifactType.feature_json,
            file_path=snapshot.artifact_path,
            generated_at=snapshot.created_at,
            sha256=snapshot.payload_sha256,
        )
    ]
    return ReportDeterministicInput(
        input_id=f"analysis:{snapshot.snapshot_id}",
        input_type="analysis_snapshot",
        title="分析快照",
        data_status=_map_data_status(snapshot.status),
        snapshot=snapshot_ref,
        sections=sections,
        source_refs=source_refs,
        artifact_refs=artifact_refs,
        payload={"input_snapshot_ids": snapshot.input_snapshot_ids or {}},
    )


def _build_input_snapshot_items(
    db: Session,
    raw_input_snapshot_ids: Any,
    *,
    run_id: str | None,
) -> list[ReportDeterministicInput]:
    items: list[ReportDeterministicInput] = []
    for snapshot_id in _normalize_snapshot_ids(raw_input_snapshot_ids):
        snapshot = db.scalar(select(AnalysisSnapshot).where(AnalysisSnapshot.snapshot_id == snapshot_id))
        if snapshot is not None:
            snapshot_ref = SnapshotRef(
                snapshot_id=snapshot.snapshot_id,
                snapshot_type="analysis",
                data_date=_iso(snapshot.trade_date),
                run_id=snapshot.run_id,
                data_status=_map_data_status(snapshot.status),
                created_at=snapshot.created_at,
                input_snapshot_ids=_normalize_snapshot_ids(snapshot.input_snapshot_ids),
            )
            sections = _snapshot_sections(snapshot.payload)
            source_refs = parse_source_refs(snapshot.source_refs)
            artifact_refs = [
                ArtifactRef(
                    artifact_id=f"{snapshot.snapshot_id}:snapshot",
                    artifact_type=ArtifactType.feature_json,
                    file_path=snapshot.artifact_path,
                    generated_at=snapshot.created_at,
                    sha256=snapshot.payload_sha256,
                )
            ]
            payload = {"input_snapshot_ids": snapshot.input_snapshot_ids or {}}
            data_status = _map_data_status(snapshot.status)
        else:
            snapshot_ref = SnapshotRef(
                snapshot_id=snapshot_id,
                snapshot_type="input",
                run_id=run_id,
                data_status=DataStatus.partial,
            )
            sections = []
            source_refs = []
            artifact_refs = []
            payload = None
            data_status = DataStatus.partial
        items.append(
            ReportDeterministicInput(
                input_id=f"input:{snapshot_id}",
                input_type="input_snapshot",
                title=f"输入快照 {snapshot_id}",
                data_status=data_status,
                snapshot=snapshot_ref,
                sections=sections,
                source_refs=source_refs,
                artifact_refs=artifact_refs,
                payload=payload,
            )
        )
    return items


def _build_agent_fallback_inputs(agent_rows: list[AgentOutput]) -> list[ReportDeterministicInput]:
    items: list[ReportDeterministicInput] = []
    for row in agent_rows:
        if is_output_purged(row):
            continue
        payload = row.payload or {}
        input_payload = payload.get("input_payload")
        if not input_payload and not row.input_snapshot_ids and not row.source_refs:
            continue
        summary = build_agent_output_summary(row)
        items.append(
            ReportDeterministicInput(
                input_id=f"agent:{row.id}:input",
                input_type="agent_input_payload",
                title=f"{summary['display_name']} 输入",
                data_status=_map_data_status(row.status),
                snapshot=SnapshotRef(
                    snapshot_id=row.snapshot_id,
                    snapshot_type="agent_input",
                    data_date=_iso(row.trade_date),
                    run_id=row.run_id,
                    data_status=_map_data_status(row.status),
                    created_at=row.created_at,
                    input_snapshot_ids=_normalize_snapshot_ids(row.input_snapshot_ids),
                ),
                sections=sorted(input_payload.keys()) if isinstance(input_payload, dict) else [],
                source_refs=parse_source_refs(row.source_refs),
                artifact_refs=[],
                payload=input_payload if isinstance(input_payload, dict) else None,
            )
        )
    return items


def _build_artifact_payload(artifact: ReportArtifactSchema | None, *, report_id: str) -> dict[str, Any] | None:
    if not _page_report_artifact_allowed(artifact):
        return None
    assert artifact is not None
    path = _resolve_report_path(artifact.file_path)
    if path is None or not path.exists():
        return None
    content = _read_artifact_content(path, artifact.artifact_type)
    payload = {
        "report_id": report_id,
        "artifact_id": artifact.artifact_id,
        "artifact_type": artifact.artifact_type.value,
        "content_type": artifact.content_type,
        "path": artifact.file_path,
        "content": content,
    }
    if artifact.artifact_type in {ArtifactType.source_md, ArtifactType.analysis_md}:
        payload["asset_base_url"] = f"/api/reports/{report_id}/asset/{artifact.artifact_type.value}/"
    return payload


def _build_report_detail_from_item(item: ReportItem, artifacts: list[ReportArtifactModel]) -> ReportDetail:
    schema_artifacts = [_to_report_artifact_schema(artifact) for artifact in artifacts]
    warnings: list[WarningItem] = []
    data_status = _coerce_data_status(item.data_status)
    observation_report = item.family in _OBSERVATION_REPORT_FAMILIES
    if not schema_artifacts:
        data_status = DataStatus.unavailable
        warnings.append(WarningItem(code="report-artifacts-missing", message="No report artifacts registered"))
    else:
        warnings.extend(_missing_file_warnings(schema_artifacts))
    if schema_artifacts and (
        _missing_standard_artifacts(schema_artifacts, family=item.family) or _missing_files(schema_artifacts)
    ):
        if data_status == DataStatus.live:
            data_status = DataStatus.partial
        warnings.append(
            WarningItem(code="report-artifacts-partial", message="Standard report artifacts are incomplete")
        )

    input_snapshot_ids: list[str] = []
    report_identity: dict[str, Any] | None = None
    metadata = item.report_metadata if isinstance(item.report_metadata, dict) else {}
    if item.family == "gold_policy_daily_report":
        input_snapshot_ids = _normalize_snapshot_ids(metadata.get("input_snapshot_ids"))
        report_identity = _project_gold_policy_report_identity(metadata)
    elif observation_report:
        # Observation reports are deliberately readable, but they never become
        # an accepted final result.  Keep the registry decision visible in the
        # read model even though ReportSummary.review_status has no ``blocked``
        # enum value of its own.
        data_status = DataStatus.partial if data_status == DataStatus.live else data_status
        input_snapshot_ids = _normalize_snapshot_ids(metadata.get("input_snapshot_ids"))
        report_identity = _project_observation_report_identity(
            metadata,
            report_type=item.report_type,
            family=item.family,
        )
        warnings.append(
            WarningItem(
                code="observation-report-non-authoritative",
                message="This report is observe-only and must not replace an accepted final report.",
            )
        )

    lifecycle_status = _coerce_lifecycle_status(item.lifecycle_status)
    review_status = ReviewStatus.not_required
    if observation_report:
        lifecycle_status = ReportLifecycleStatus.needs_review
        review_status = ReviewStatus.pending

    return ReportDetail(
        run_id=item.run_id,
        snapshot_id=item.snapshot_id,
        data_status=data_status,
        source_refs=parse_source_refs(item.source_refs),
        artifact_refs=schema_artifacts,
        warnings=warnings,
        report_id=item.report_id,
        family=item.family,
        title=item.title,
        asset=item.asset,
        trade_date=_iso(item.trade_date) if item.trade_date else None,
        lifecycle_status=lifecycle_status,
        review_status=review_status,
        generated_at=item.updated_at or item.created_at,
        artifacts=schema_artifacts,
        input_snapshot_ids=input_snapshot_ids,
        report_identity=report_identity,
        structured_payload=_load_structured_payload(schema_artifacts),
    )


_GOLD_POLICY_REPORT_IDENTITY_KEYS = (
    "report_context_id",
    "report_render_id",
    "authority_result_id",
    "canonical_receipt_id",
    "canonical_receipt_revision_no",
    "canonical_commit_action",
    "manifest_schema_version",
    "structured_schema_version",
    "publication_status",
)


def _project_gold_policy_report_identity(metadata: dict[str, Any]) -> dict[str, Any] | None:
    """Project non-empty registry metadata fields into a read-only report_identity."""
    identity: dict[str, Any] = {}
    for key in _GOLD_POLICY_REPORT_IDENTITY_KEYS:
        value = metadata.get(key)
        if value in (None, ""):
            continue
        identity[key] = value
    return identity or None


def _project_observation_report_identity(
    metadata: dict[str, Any], *, report_type: str | None, family: str
) -> dict[str, Any]:
    """Expose observe-only registry metadata without granting report authority."""
    return {
        "report_type": report_type or "observation_report",
        "family": family,
        "output_mode": "observe",
        "publish_allowed": False,
        "review_status": "blocked",
        "authority": "observation_only",
    }


def _merge_warning_items(*warning_groups: list[WarningItem]) -> list[WarningItem]:
    merged: list[WarningItem] = []
    seen: set[tuple[str, str | None, str]] = set()
    for group in warning_groups:
        for warning in group:
            key = (warning.code, warning.field, warning.message)
            if key in seen:
                continue
            seen.add(key)
            merged.append(warning)
    return merged


def _build_legacy_report_detail(db: Session, report_id: str) -> ReportDetail | None:
    try:
        legacy_final = _find_legacy_final_report(db, report_id)
    except SQLAlchemyError:
        legacy_final = None
    if legacy_final is not None:
        return _legacy_final_report_detail(legacy_final)

    legacy_fs_final = _legacy_final_report_detail_from_filesystem(report_id)
    if legacy_fs_final is not None:
        return legacy_fs_final

    legacy_macro = _legacy_macro_report_detail(report_id)
    if legacy_macro is not None:
        return legacy_macro

    legacy_macro_followup = _legacy_macro_event_followup_detail(report_id)
    if legacy_macro_followup is not None:
        return legacy_macro_followup

    legacy_weekly_revision = _legacy_weekly_context_revision_detail(report_id)
    if legacy_weekly_revision is not None:
        return legacy_weekly_revision

    legacy_jin10 = _legacy_jin10_report_detail(report_id)
    if legacy_jin10 is not None:
        return legacy_jin10

    return _legacy_cme_visual_detail(report_id)


def _legacy_final_report_detail(row: FinalAnalysisResult) -> ReportDetail | None:
    artifacts: list[ReportArtifactSchema] = []
    if row.final_report_path:
        artifacts.append(
            _artifact_schema(
                artifact_id=f"{row.run_id}:final_report",
                artifact_type=ArtifactType.analysis_md,
                file_path=row.final_report_path,
                generated_at=row.updated_at or row.created_at,
                sha256=row.final_report_sha256,
                report_id=row.run_id,
                is_primary=True,
                content_type="text/markdown",
            )
        )
    structured_path = _structured_report_path(row.final_report_path)
    if structured_path:
        artifacts.append(
            _artifact_schema(
                artifact_id=f"{row.run_id}:structured_report",
                artifact_type=ArtifactType.structured_json,
                file_path=structured_path,
                generated_at=row.updated_at or row.created_at,
                report_id=row.run_id,
                content_type="application/json",
            )
        )
    if row.run_summary_path:
        artifacts.append(
            _artifact_schema(
                artifact_id=f"{row.run_id}:run_summary",
                artifact_type=ArtifactType.structured_json,
                file_path=row.run_summary_path,
                generated_at=row.updated_at or row.created_at,
                report_id=row.run_id,
                content_type="application/json",
            )
        )
    if not artifacts:
        return None

    return ReportDetail(
        run_id=row.run_id,
        snapshot_id=row.snapshot_id,
        data_status=DataStatus.partial,
        source_refs=parse_source_refs(row.source_refs),
        artifact_refs=artifacts,
        warnings=[
            WarningItem(
                code="legacy-report-adapter",
                message="Legacy FinalAnalysisResult adapted without full Phase 4 standard artifacts",
            )
        ],
        report_id=row.run_id,
        family="final_report",
        title=f"{row.asset or 'Unknown'} final report",
        asset=row.asset,
        trade_date=_iso(row.trade_date),
        lifecycle_status=ReportLifecycleStatus.generated,
        generated_at=row.updated_at or row.created_at,
        artifacts=artifacts,
        input_snapshot_ids=_normalize_snapshot_ids(row.input_snapshot_ids),
        structured_payload=_load_structured_payload(artifacts),
    )


def _legacy_final_report_detail_from_filesystem(report_id: str) -> ReportDetail | None:
    run_id = _strip_report_type_prefix(report_id, "final_report")
    if Path(run_id).name != run_id or run_id in {".", ".."}:
        return None
    base = _find_run_dir(_storage._PROJECT_ROOT / "storage" / "outputs" / "final_report" / "XAUUSD", run_id)
    if base is None:
        return None
    trade_date, run_dir = base
    if _safe_final_report_path(run_dir / "final_report.md") is None:
        return None
    artifacts = _artifact_schemas_from_paths(
        report_id=report_id,
        generated_at=None,
        path_specs=[
            (ArtifactType.analysis_md, run_dir / "final_report.md", True, "text/markdown"),
            (ArtifactType.structured_json, run_dir / "structured_report.json", False, "application/json"),
        ],
    )
    if not artifacts:
        return None
    return ReportDetail(
        run_id=run_id,
        snapshot_id=None,
        data_status=DataStatus.partial if _missing_files(artifacts) else DataStatus.live,
        artifact_refs=artifacts,
        warnings=[],
        report_id=report_id,
        family="final_report_markdown",
        title="XAUUSD 综合报告",
        asset="XAUUSD",
        trade_date=trade_date,
        lifecycle_status=ReportLifecycleStatus.generated,
        artifacts=artifacts,
        structured_payload=_load_structured_payload(artifacts),
    )


def _legacy_macro_report_detail(report_id: str) -> ReportDetail | None:
    macro_id = _strip_report_type_prefix(report_id, "macro_report")
    base = _find_run_dir(_storage._PROJECT_ROOT / "storage" / "outputs" / "macro", macro_id)
    if base is None:
        date_dir = _storage._PROJECT_ROOT / "storage" / "outputs" / "macro" / macro_id
        if date_dir.is_dir() and _macro_report_md_path(date_dir) is not None:
            base = (macro_id, date_dir)
    if base is None:
        return None
    trade_date, run_dir = base
    report_md = _macro_report_md_path(run_dir)
    if report_md is None:
        return None
    artifacts = _artifact_schemas_from_paths(
        report_id=report_id,
        generated_at=None,
        path_specs=[
            (ArtifactType.analysis_md, report_md, True, "text/markdown"),
            (ArtifactType.structured_json, run_dir / "macro_snapshot.json", False, "application/json"),
            (ArtifactType.structured_json, run_dir / "macro_conclusion.json", False, "application/json"),
        ],
    )
    if not artifacts:
        return None
    return ReportDetail(
        run_id=macro_id if run_dir.name != trade_date else None,
        snapshot_id=None,
        data_status=DataStatus.partial if _missing_files(artifacts) else DataStatus.live,
        artifact_refs=artifacts,
        warnings=[],
        report_id=report_id,
        family="macro_report",
        title=f"XAUUSD 宏观分析报告（{trade_date}）",
        asset="XAUUSD",
        trade_date=trade_date,
        lifecycle_status=ReportLifecycleStatus.generated,
        artifacts=artifacts,
        structured_payload=_load_structured_payload(artifacts),
    )


def _legacy_macro_event_followup_detail(report_id: str) -> ReportDetail | None:
    followup_id = _strip_report_type_prefix(report_id, "macro_event_followup")
    followup_date: str | None = None
    followup_run_id = followup_id
    if ":" in followup_id:
        followup_date, followup_run_id = followup_id.split(":", 1)

    if followup_date:
        run_dir = (
            _storage._PROJECT_ROOT / "storage" / "outputs" / "macro_event_followup" / "XAUUSD" / followup_date / followup_run_id
        )
        base = (followup_date, run_dir) if run_dir.is_dir() else None
    else:
        base = _find_run_dir(_storage._PROJECT_ROOT / "storage" / "outputs" / "macro_event_followup" / "XAUUSD", followup_run_id)
    if base is None:
        return None
    trade_date, run_dir = base
    artifacts = _artifact_schemas_from_paths(
        report_id=report_id,
        generated_at=None,
        path_specs=[
            (ArtifactType.source_md, run_dir / "source.md", True, "text/markdown"),
            (ArtifactType.analysis_md, run_dir / "analysis.md", False, "text/markdown"),
            (ArtifactType.structured_json, run_dir / "report_structured.json", False, "application/json"),
        ],
    )
    if not artifacts:
        return None
    payload = _load_macro_event_followup_payload(run_dir)
    return ReportDetail(
        run_id=followup_run_id,
        snapshot_id=None,
        data_status=DataStatus.partial
        if _missing_standard_artifacts(artifacts) or _missing_files(artifacts)
        else DataStatus.live,
        artifact_refs=artifacts,
        warnings=[
            WarningItem(
                code="legacy-report-adapter", message="Legacy macro event follow-up report adapted to report detail"
            )
        ],
        report_id=report_id,
        family=_report_index_family("macro_event_followup"),
        title=_report_index_title("macro_event_followup", trade_date),
        asset="XAUUSD",
        trade_date=trade_date,
        lifecycle_status=ReportLifecycleStatus.generated,
        artifacts=artifacts,
        structured_payload=payload.model_dump(mode="json")
        if payload is not None
        else _load_structured_payload(artifacts),
    )


def _legacy_weekly_context_revision_detail(report_id: str) -> ReportDetail | None:
    revision_id = _strip_report_type_prefix(report_id, "weekly_context_revision")
    revision_date: str | None = None
    revision_run_id = revision_id
    if ":" in revision_id:
        revision_date, revision_run_id = revision_id.split(":", 1)

    if revision_date:
        run_dir = (
            _storage._PROJECT_ROOT
            / "storage"
            / "outputs"
            / "weekly_context_revision"
            / "XAUUSD"
            / revision_date
            / revision_run_id
        )
        base = (revision_date, run_dir) if run_dir.is_dir() else None
    else:
        base = _find_run_dir(
            _storage._PROJECT_ROOT / "storage" / "outputs" / "weekly_context_revision" / "XAUUSD",
            revision_run_id,
        )
    if base is None:
        return None
    trade_date, run_dir = base
    artifacts = _artifact_schemas_from_paths(
        report_id=report_id,
        generated_at=None,
        path_specs=[
            (ArtifactType.source_md, run_dir / "source.md", True, "text/markdown"),
            (ArtifactType.analysis_md, run_dir / "analysis.md", False, "text/markdown"),
            (ArtifactType.structured_json, run_dir / "report_structured.json", False, "application/json"),
        ],
    )
    if not artifacts:
        return None
    payload = _load_weekly_context_revision_payload(run_dir)
    observe_only = payload is None or not payload.publish_allowed
    warnings = [
        WarningItem(
            code="legacy-report-adapter",
            message="Legacy weekly context revision adapted to report detail",
        )
    ]
    if observe_only:
        warnings.append(
            WarningItem(
                code="weekly-revision-observe-only",
                message="Weekly context revision is observe-only and must not replace an accepted baseline report.",
            )
        )
    return ReportDetail(
        run_id=revision_run_id,
        snapshot_id=None,
        data_status=(DataStatus.partial if observe_only or _missing_files(artifacts) else DataStatus.live),
        artifact_refs=artifacts,
        warnings=warnings,
        report_id=report_id,
        family=_report_index_family("weekly_context_revision"),
        title=_report_index_title("weekly_context_revision", trade_date),
        asset="XAUUSD",
        trade_date=trade_date,
        lifecycle_status=ReportLifecycleStatus.generated,
        artifacts=artifacts,
        structured_payload=(
            payload.model_dump(mode="json") if payload is not None else _load_structured_payload(artifacts)
        ),
    )


def _legacy_jin10_report_detail(report_id: str) -> ReportDetail | None:
    base = _find_run_dir(_storage._PROJECT_ROOT / "storage" / "outputs" / "jin10", report_id)
    if base is None:
        return None
    trade_date, run_dir = base
    artifacts = _artifact_schemas_from_paths(
        report_id=report_id,
        generated_at=None,
        path_specs=[
            (ArtifactType.analysis_md, run_dir / "agent_analysis_report.md", False, "text/markdown"),
            (ArtifactType.visual_html, run_dir / "daily_analysis.html", False, "text/html"),
            (ArtifactType.structured_json, run_dir / "agent_analysis_report.json", False, "application/json"),
            (ArtifactType.structured_json, run_dir / "daily_analysis.json", False, "application/json"),
        ],
    )
    if not artifacts:
        return None
    agent_payload = _read_optional_json(run_dir / "agent_analysis_report.json") or {}
    daily_payload = _read_optional_json(run_dir / "daily_analysis.json") or {}
    family = str(daily_payload.get("family") or "").strip() or "jin10_daily_visual"
    if family in {
        "jin10_positioning_report",
        "jin10_technical_levels_report",
        "jin10_oil_report",
        "jin10_fx_report",
        "jin10_market_observation_report",
    }:
        resolved_family = family
        resolved_title = (
            str(agent_payload.get("title") or daily_payload.get("title") or "").strip()
            or _report_index_title(family, trade_date)
        )
    elif family == "jin10_weekly_visual" or str(daily_payload.get("report_type") or "").lower() == "weekly":
        resolved_family = "jin10_weekly_visual"
        resolved_title = (
            str(agent_payload.get("title") or daily_payload.get("title") or "").strip()
            or "Jin10 weekly report"
        )
    else:
        resolved_family = "jin10_daily_visual"
        resolved_title = (
            str(agent_payload.get("title") or daily_payload.get("title") or "").strip()
            or "Jin10 daily report"
        )
    structured_payload = _build_legacy_jin10_structured_payload(run_dir=run_dir, artifacts=artifacts)
    resolved_title = str((structured_payload or {}).get("title") or resolved_title)
    quality_audit = _normalize_jin10_quality_audit(structured_payload, agent_payload, daily_payload)
    quality_needs_review = quality_audit is None or _jin10_report_status(quality_audit) != "ready"
    quality_blocks_content = _jin10_quality_blocks_content(quality_audit)
    warnings = [WarningItem(code="legacy-report-adapter", message="Legacy Jin10 bundle adapted to report detail")]
    if quality_needs_review:
        reason_codes = ", ".join((quality_audit or {}).get("reason_codes") or []) or "quality_audit_failed"
        warnings.append(
            WarningItem(
                code="jin10-quality-gate-blocked" if quality_blocks_content else "jin10-quality-audit-needs-review",
                message=(
                    "Jin10 报告未提取到足够正文或图表证据，降级分析稿已停止展示"
                    if quality_blocks_content
                    else "Jin10 报告未通过质量审计，需要人工复核"
                ),
                field="structured_payload.quality_audit",
                hint=f"quality reason codes: {reason_codes}",
            )
        )

    trace = (structured_payload or {}).get("_generation_trace") or {}
    chart_review = (trace.get("quality_audit") or {}).get("semantic_review_status") == "needs_review"
    asset_review = (trace.get("asset_audit") or {}).get("status") in {"missing_assets", "needs_review"}
    if chart_review:
        warnings.append(WarningItem(code="jin10-chart-text-needs-review", message="图表文字校验需要复核"))
    if asset_review:
        warnings.append(WarningItem(code="jin10-chart-assets-needs-review", message="图表资源校验需要复核"))
    needs_review = quality_needs_review or chart_review or asset_review

    return ReportDetail(
        run_id=report_id,
        snapshot_id=None,
        data_status=(
            DataStatus.unavailable
            if quality_blocks_content
            else DataStatus.partial
            if needs_review or _missing_standard_artifacts(artifacts) or _missing_files(artifacts)
            else DataStatus.live
        ),
        artifact_refs=artifacts,
        warnings=warnings,
        report_id=report_id,
        family=resolved_family,
        title=resolved_title,
        trade_date=trade_date,
        lifecycle_status=ReportLifecycleStatus.needs_review if needs_review else ReportLifecycleStatus.generated,
        review_status=ReviewStatus.pending if needs_review else ReviewStatus.not_required,
        artifacts=artifacts,
        source_refs=dedupe_source_refs([
            *parse_source_refs(agent_payload.get("source_refs")),
            *parse_source_refs(daily_payload.get("source_refs")),
            *parse_source_refs((structured_payload or {}).get("source_refs")),
        ]),
        structured_payload=structured_payload,
        report_identity=_jin10_report_identity(daily_payload, agent_payload),
    )


def _jin10_report_identity(*payloads: dict[str, Any]) -> dict[str, Any] | None:
    for payload in payloads:
        identity = payload.get("report_identity") if isinstance(payload, dict) else None
        if isinstance(identity, dict) and identity:
            return dict(identity)
    return None


def _build_legacy_jin10_structured_payload(
    *, run_dir: Path, artifacts: list[ReportArtifactSchema]
) -> dict[str, Any] | None:
    agent_payload = _read_optional_json(run_dir / "agent_analysis_report.json") or {}
    daily_payload = _read_optional_json(run_dir / "daily_analysis.json") or {}
    payload = dict(daily_payload)
    for key in (
        "title",
        "analysis_summary",
        "scenario_paths",
        "trading_implications",
        "quality_audit",
        "source_refs",
        "report_identity",
        "generated_at",
    ):
        if key in agent_payload:
            payload[key] = agent_payload[key]
    if not payload:
        return None
    from apps.api.services.page_jin10_report_service import load_page_jin10_quality

    quality = load_page_jin10_quality(
        project_root=_storage._PROJECT_ROOT, date=run_dir.parent.name, run_id=run_dir.name,
        agent_payload=agent_payload, daily_payload=daily_payload,
    )
    if quality:
        payload["_generation_trace"] = quality.get("trace")
        payload["quality_audit"] = quality.get("quality_audit")
        payload.setdefault("title", quality.get("source_title"))
        payload["source_refs"] = [*(payload.get("source_refs") or []), *(quality.get("source_refs") or [])]
    return payload




def _legacy_external_jin10_weekly_detail(report_id: str) -> ReportDetail | None:
    base = _find_external_jin10_weekly_dir(report_id)
    if base is None:
        return None
    trade_date, run_dir = base
    artifacts = _artifact_schemas_from_paths(
        report_id=report_id,
        generated_at=None,
        path_specs=[
            (ArtifactType.source_md, run_dir / "report.md", True, "text/markdown"),
            (ArtifactType.structured_json, run_dir / "meta.json", False, "application/json"),
        ],
    )
    if not artifacts:
        return None
    return ReportDetail(
        run_id=report_id,
        snapshot_id=None,
        data_status=DataStatus.partial,
        artifact_refs=artifacts,
        warnings=[
            WarningItem(code="legacy-report-adapter", message="Legacy Jin10 weekly source adapted to report detail")
        ],
        report_id=report_id,
        family="jin10_weekly_visual",
        title="Jin10 weekly report",
        trade_date=trade_date,
        lifecycle_status=ReportLifecycleStatus.generated,
        artifacts=artifacts,
        structured_payload=_load_structured_payload(artifacts),
    )


def _legacy_cme_visual_detail(report_id: str) -> ReportDetail | None:
    base = _find_run_dir(_storage._PROJECT_ROOT / "storage" / "outputs" / "cme", report_id)
    if base is None:
        return None
    trade_date, run_dir = base
    artifacts = _artifact_schemas_from_paths(
        report_id=report_id,
        generated_at=None,
        path_specs=[
            (ArtifactType.analysis_md, run_dir / "options_analysis_agent_report.md", True, "text/markdown"),
            (ArtifactType.analysis_md, run_dir / "options_analysis.md", False, "text/markdown"),
            (ArtifactType.visual_html, run_dir / "options_visual_report.html", False, "text/html"),
            (ArtifactType.structured_json, run_dir / "options_visual_report.json", False, "application/json"),
            (ArtifactType.structured_json, run_dir / "options_analysis.json", False, "application/json"),
        ],
    )
    if not artifacts:
        return None
    return ReportDetail(
        run_id=report_id,
        snapshot_id=None,
        data_status=DataStatus.partial,
        artifact_refs=artifacts,
        warnings=[
            WarningItem(code="legacy-report-adapter", message="Legacy CME visual report adapted to report detail")
        ],
        report_id=report_id,
        family="cme_options_visual",
        title="CME options visual report",
        trade_date=trade_date,
        lifecycle_status=ReportLifecycleStatus.generated,
        artifacts=artifacts,
        structured_payload=_load_structured_payload(artifacts),
    )


def _artifact_schemas_from_paths(
    *,
    report_id: str,
    generated_at,
    path_specs: list[tuple[ArtifactType, Path, bool, str]],
) -> list[ReportArtifactSchema]:
    artifacts: list[ReportArtifactSchema] = []
    seen: set[tuple[str, str]] = set()
    for artifact_type, path, is_primary, content_type in path_specs:
        resolved = _resolve_report_path(path)
        if resolved is None or not resolved.exists():
            continue
        try:
            rel = str(resolved.relative_to(_storage._PROJECT_ROOT))
        except ValueError:
            rel = str(resolved)
        key = (artifact_type.value, rel)
        if key in seen:
            continue
        seen.add(key)
        artifacts.append(
            _artifact_schema(
                artifact_id=f"{report_id}:{path.name}",
                artifact_type=artifact_type,
                file_path=rel,
                generated_at=generated_at,
                report_id=report_id,
                is_primary=is_primary,
                content_type=content_type,
            )
        )
    return artifacts


def _find_legacy_final_report(db: Session, report_id: str) -> FinalAnalysisResult | None:
    direct = db.scalar(
        select(FinalAnalysisResult)
        .where(
            or_(
                FinalAnalysisResult.run_id == report_id,
                FinalAnalysisResult.snapshot_id == report_id,
            )
        )
        .order_by(FinalAnalysisResult.trade_date.desc(), FinalAnalysisResult.id.desc())
        .limit(1)
    )
    if direct is not None:
        return direct

    rows = db.scalars(
        select(FinalAnalysisResult).order_by(FinalAnalysisResult.trade_date.desc(), FinalAnalysisResult.id.desc())
    ).all()
    for row in rows:
        if report_id in _legacy_report_candidate_ids(row):
            return row
    return None


def _legacy_report_candidate_ids(row: FinalAnalysisResult) -> set[str]:
    ids = {row.run_id}
    if row.snapshot_id:
        ids.add(row.snapshot_id)
    for file_path in (row.final_report_path, _structured_report_path(row.final_report_path), row.run_summary_path):
        if not file_path:
            continue
        ids.update(_path_candidate_ids(file_path))
    return ids


def _path_candidate_ids(raw_path: str) -> set[str]:
    path = Path(raw_path)
    ids = {raw_path, path.name, path.stem}
    if path.parent.name:
        ids.add(path.parent.name)
    return ids


def _structured_report_path(final_report_path: str | None) -> str | None:
    if not final_report_path:
        return None
    return str(Path(final_report_path).with_name("structured_report.json"))


def _pick_report_artifact(
    artifacts: list[ReportArtifactSchema], artifact_type: ArtifactType
) -> ReportArtifactSchema | None:
    for artifact in artifacts:
        if artifact.artifact_type == artifact_type:
            return artifact
    return None


def _pick_legacy_analysis_artifact(artifacts: list[ReportArtifactSchema]) -> ReportArtifactSchema | None:
    for artifact in artifacts:
        if artifact.artifact_type != ArtifactType.analysis_md:
            continue
        if artifact.file_path.endswith("final_report.md"):
            return artifact
    return _pick_report_artifact(artifacts, ArtifactType.analysis_md)


def _to_report_artifact_schema(artifact: ReportArtifactModel) -> ReportArtifactSchema:
    return _artifact_schema(
        artifact_id=artifact.artifact_id,
        artifact_type=coerce_artifact_type(artifact.artifact_type, artifact.file_path),
        file_path=artifact.file_path,
        generated_at=artifact.generated_at or artifact.updated_at or artifact.created_at,
        sha256=artifact.sha256,
        report_id=artifact.report_id,
        is_primary=artifact.is_primary,
        content_type=artifact.content_type,
    )


def _artifact_schema(
    *,
    artifact_id: str,
    artifact_type: ArtifactType,
    file_path: str,
    generated_at,
    sha256: str | None = None,
    report_id: str | None = None,
    is_primary: bool = False,
    content_type: str | None = None,
) -> ReportArtifactSchema:
    # Registries may use absolute paths; expose the same validated storage
    # identity to the page projector without rejecting legitimate report bundles.
    path = remap_storage_path(file_path, storage_root=_storage._PROJECT_ROOT / "storage")
    if path.is_absolute():
        try:
            file_path = "storage/" + path.resolve().relative_to((_storage._PROJECT_ROOT / "storage").resolve()).as_posix()
        except (OSError, ValueError):
            pass
    return ReportArtifactSchema(
        artifact_id=artifact_id,
        artifact_type=artifact_type,
        file_path=file_path,
        generated_at=generated_at,
        sha256=sha256,
        report_id=report_id,
        is_primary=is_primary,
        content_type=content_type,
    )


def _snapshot_sections(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return []
    sections: list[str] = []
    for key, value in payload.items():
        if key in {"snapshot_id", "trade_date", "asset", "run_id", "status"}:
            continue
        if isinstance(value, (dict, list)) and value:
            sections.append(str(key))
    return sorted(sections)


def _normalize_agent_artifact_refs(raw_refs: Any, *, agent_output_id: str) -> list[ArtifactRef]:
    if not isinstance(raw_refs, list):
        return []
    artifacts: list[ArtifactRef] = []
    for index, item in enumerate(raw_refs, start=1):
        if isinstance(item, str):
            file_path = item
            artifact_type = coerce_artifact_type(None, file_path)
        elif isinstance(item, dict):
            file_path = item.get("file_path") or item.get("artifact_path") or item.get("path")
            if not file_path:
                continue
            artifact_type = coerce_artifact_type(item.get("artifact_type"), str(file_path))
        else:
            continue
        artifacts.append(
            ArtifactRef(
                artifact_id=f"{agent_output_id}:artifact:{index}",
                artifact_type=artifact_type,
                file_path=str(file_path),
            )
        )
    return dedupe_artifact_refs(artifacts)


def _coerce_data_status(raw: str | None) -> DataStatus:
    try:
        return DataStatus(raw or DataStatus.live.value)
    except ValueError:
        return DataStatus.live


def _map_data_status(raw_status: Any) -> DataStatus:
    if raw_status is None:
        return DataStatus.partial
    try:
        return DataStatus(str(raw_status))
    except ValueError:
        pass

    raw = str(raw_status).lower()
    if raw in {"success", "ok", "available", "generated"}:
        return DataStatus.live
    if raw in {"partial", "partial_success", "degraded"}:
        return DataStatus.partial
    if raw in {"stale"}:
        return DataStatus.stale
    if raw in {"fallback"}:
        return DataStatus.fallback
    if raw in {"mock"}:
        return DataStatus.mock
    if raw in {"manual_required", "needs_review"}:
        return DataStatus.manual_required
    if raw in {"failed", "error", "missing", "unavailable"}:
        return DataStatus.unavailable
    return DataStatus.partial


def _coerce_lifecycle_status(raw: str | None) -> ReportLifecycleStatus:
    try:
        return ReportLifecycleStatus(raw or ReportLifecycleStatus.generated.value)
    except ValueError:
        return ReportLifecycleStatus.generated


def _missing_standard_artifacts(
    artifacts: list[ReportArtifactSchema], *, family: str | None = None
) -> bool:
    present = {artifact.artifact_type for artifact in artifacts}
    required = (
        _FINAL_REPORT_MARKDOWN_ARTIFACT_TYPES
        if family == "final_report_markdown"
        else _OBSERVATION_REPORT_MARKDOWN_ARTIFACT_TYPES
        if family == "observation_report_markdown"
        else _OBSERVATION_STRATEGY_CARD_ARTIFACT_TYPES
        if family == "observation_strategy_card"
        else _STANDARD_ARTIFACT_TYPES
    )
    return not required.issubset(present)


def _missing_files(artifacts: list[ReportArtifactSchema]) -> bool:
    return any(
        (path := _resolve_report_path(artifact.file_path)) is None or not path.exists() for artifact in artifacts
    )


def _missing_file_warnings(artifacts: list[ReportArtifactSchema]) -> list[WarningItem]:
    warnings: list[WarningItem] = []
    for artifact in artifacts:
        path = _resolve_report_path(artifact.file_path)
        if path is not None and path.exists():
            continue
        warnings.append(
            WarningItem(
                code="report-artifact-missing-file",
                message=f"Registered report artifact file is missing: {artifact.file_path}",
                field=artifact.file_path,
            )
        )
    return warnings


def _pick_artifact_by_basename(
    artifacts: list[ReportArtifactSchema], artifact_type: ArtifactType, basename: str
) -> ReportArtifactSchema | None:
    """Pick an artifact by type, preferring one whose file basename matches.

    Falls back to the first artifact of the given type if no basename match
    exists, preserving legacy behavior for reports without named files.
    """
    fallback: ReportArtifactSchema | None = None
    target = basename.lower()
    for artifact in artifacts:
        if artifact.artifact_type != artifact_type:
            continue
        if fallback is None:
            fallback = artifact
        normalized = str(artifact.file_path).replace("\\", "/").lower()
        if normalized.rsplit("/", 1)[-1] == target:
            return artifact
    return fallback


def _load_structured_payload(artifacts: list[ReportArtifactSchema]) -> dict | None:
    artifact = _pick_artifact_by_basename(artifacts, ArtifactType.structured_json, "report_structured.json")
    if artifact is None:
        return None
    path = _resolve_report_path(artifact.file_path)
    if path is None or not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _normalize_snapshot_ids(raw: Any) -> list[str]:
    if isinstance(raw, dict):
        candidates = raw.values()
    elif isinstance(raw, list):
        candidates = raw
    else:
        return []

    snapshot_ids: list[str] = []
    for item in candidates:
        if isinstance(item, str) and item:
            snapshot_ids.append(item)
        elif isinstance(item, dict):
            for key in ("snapshot_id", "id"):
                value = item.get(key)
                if isinstance(value, str) and value:
                    snapshot_ids.append(value)
                    break
    return list(dict.fromkeys(snapshot_ids))


def _find_run_dir(base: Path, report_id: str) -> tuple[str, Path] | None:
    if not base.exists():
        return None
    for date_dir in sorted((item for item in base.iterdir() if item.is_dir()), reverse=True):
        run_dir = date_dir / report_id
        if run_dir.is_dir():
            return date_dir.name, run_dir
    return None


def _strip_report_type_prefix(report_id: str, report_type: str) -> str:
    prefix = f"{report_type}:"
    return report_id[len(prefix) :] if report_id.startswith(prefix) else report_id


def _resolve_report_path(file_path: str | Path) -> Path | None:
    raw_path = Path(file_path)
    if "://" in str(raw_path):
        return None
    candidate = project_artifact_path(raw_path, project_root=_storage._PROJECT_ROOT)
    try:
        resolved = candidate.resolve()
        allowed_roots = [
            (_storage._PROJECT_ROOT / "storage").resolve(),
            _jin10._JIN10_EXTERNAL_ROOT.resolve(),
        ]
    except OSError:
        return None
    return resolved if any(resolved.is_relative_to(root) for root in allowed_roots) else None


def _resolve_report_asset_path(file_path: str | Path, asset_path: str) -> Path | None:
    artifact_path = _resolve_report_path(file_path)
    if artifact_path is None:
        return None
    try:
        page_roots = [(_storage._PROJECT_ROOT / "storage" / layer).resolve() for layer in ("outputs", "features", "analysis", "reports")]
        if not any(artifact_path.is_relative_to(root) for root in page_roots):
            return None
        candidate = (artifact_path.parent / asset_path).resolve()
        parent = artifact_path.parent.resolve()
    except OSError:
        return None
    allowed_suffixes = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".css", ".js", ".woff", ".woff2", ".ttf"}
    if (
        not candidate.is_relative_to(parent)
        or not candidate.exists()
        or not candidate.is_file()
        or candidate.suffix.lower() not in allowed_suffixes
    ):
        return None
    return candidate


def _read_artifact_content(path: Path, artifact_type: ArtifactType) -> Any:
    if artifact_type == ArtifactType.structured_json:
        raw = path.read_text(encoding="utf-8")
        try:
            return json.loads(raw)
        except Exception:
            return raw
    return path.read_text(encoding="utf-8")


def _macro_report_md_path(run_dir: Path) -> Path | None:
    full_report = run_dir / "macro_full_report.md"
    if full_report.exists():
        return full_report
    snapshot_report = run_dir / "macro_snapshot.md"
    if snapshot_report.exists():
        return snapshot_report
    return None


def _load_macro_event_followup_payload(run_dir: Path) -> MacroEventFollowupStructuredPayload | None:
    payload = _read_optional_json(run_dir / "report_structured.json")
    if not isinstance(payload, dict):
        return None
    try:
        return MacroEventFollowupStructuredPayload.model_validate(payload)
    except ValidationError:
        return None


def _load_weekly_context_revision_payload(run_dir: Path) -> WeeklyContextRevisionPayload | None:
    payload = _read_optional_json(run_dir / "report_structured.json")
    if not isinstance(payload, dict):
        return None
    try:
        return WeeklyContextRevisionPayload.model_validate(payload)
    except ValidationError:
        return None
