from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from apps.api.schemas.common import ArtifactType, DataStatus, ReportLifecycleStatus, WarningItem
from apps.api.schemas.report import ReportAnalysisAgentOutput, ReportAnalysisInputs, ReportDeterministicInput
from apps.api.schemas.report import ReportArtifact as ReportArtifactSchema
from apps.api.schemas.report import ReportDetail
from apps.api.schemas.source_trace import ArtifactRef, SnapshotRef
from apps.api.services._report_lineage import resolve_report_lineage_context
from apps.api.services._storage import _PROJECT_ROOT, _iso, _latest_asset_date_run, _try_db_session
from apps.api.services._trace_refs import coerce_artifact_type, dedupe_artifact_refs, dedupe_source_refs, parse_source_refs
from apps.api.services.agent_output_service import build_agent_output_summary
from apps.analysis.macro.regime import classify_macro_regime
from database.models.analysis import AgentOutput, AnalysisSnapshot, FinalAnalysisResult
from database.models.report import ReportArtifact as ReportArtifactModel
from database.models.report import ReportItem
from database.queries.report import get_report_artifacts as query_report_artifacts
from database.queries.report import get_report_detail as query_report_detail


_STANDARD_ARTIFACT_TYPES = {
    ArtifactType.source_md,
    ArtifactType.analysis_md,
    ArtifactType.visual_html,
    ArtifactType.structured_json,
}


def get_report_detail(db: Session, report_id: str) -> ReportDetail | None:
    try:
        item = query_report_detail(db, report_id)
        if item is not None:
            artifacts = query_report_artifacts(db, report_id)
            detail = _build_report_detail_from_item(item, artifacts)
            return _enrich_report_detail_with_lineage_warnings(db, detail)
    except (OperationalError, ProgrammingError):
        pass
    return _build_legacy_report_detail(db, report_id)


def get_report_artifacts(db: Session, report_id: str) -> list[ReportArtifactSchema] | None:
    detail = get_report_detail(db, report_id)
    if detail is None:
        return None
    return detail.artifacts


def get_report_source(db: Session, report_id: str) -> dict[str, Any] | None:
    return _build_report_artifact_payload(db, report_id, ArtifactType.source_md)


def get_report_analysis(db: Session, report_id: str) -> dict[str, Any] | None:
    detail = get_report_detail(db, report_id)
    if detail is None:
        return None
    artifact = _pick_report_artifact(detail.artifacts, ArtifactType.analysis_md)
    if artifact is None:
        artifact = _pick_legacy_analysis_artifact(detail.artifacts)
    return _build_artifact_payload(artifact, report_id=detail.report_id)


def get_report_visual(db: Session, report_id: str) -> dict[str, Any] | None:
    return _build_report_artifact_payload(db, report_id, ArtifactType.visual_html)


def get_report_evidence(db: Session, report_id: str) -> dict[str, Any] | None:
    return _build_report_artifact_payload(db, report_id, ArtifactType.structured_json)


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
        deterministic_inputs.extend(_build_input_snapshot_items(db, snapshot.input_snapshot_ids, run_id=snapshot.run_id))
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
    return _build_artifact_payload(artifact, report_id=detail.report_id)


def get_report_artifact_asset_path(db: Session, report_id: str, artifact_type: ArtifactType, asset_path: str) -> Path | None:
    detail = get_report_detail(db, report_id)
    if detail is None:
        return None
    artifact = _pick_report_artifact(detail.artifacts, artifact_type)
    if artifact is None:
        return None
    return _resolve_report_asset_path(artifact.file_path, asset_path)


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
    if warnings == detail.warnings and normalized_run_id == detail.run_id and normalized_snapshot_id == detail.snapshot_id:
        return detail
    return detail.model_copy(update={"warnings": warnings, "run_id": normalized_run_id, "snapshot_id": normalized_snapshot_id})


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
        artifact_refs=_normalize_agent_artifact_refs(summary["artifact_refs"], agent_output_id=summary["agent_output_id"]),
        claims=summary["claims"],
        claim_reviews=summary["claim_reviews"],
        claim_count=int(summary["claim_count"]),
        fact_review_status=summary["fact_review_status"],
        prompt_version=summary["prompt_version"],
        generated_by=summary["generated_by"],
        llm_model=summary["llm_model"],
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
    if artifact is None:
        return None
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
    if not schema_artifacts:
        data_status = DataStatus.unavailable
        warnings.append(WarningItem(code="report-artifacts-missing", message="No report artifacts registered"))
    else:
        warnings.extend(_missing_file_warnings(schema_artifacts))
    if schema_artifacts and (_missing_standard_artifacts(schema_artifacts) or _missing_files(schema_artifacts)):
        if data_status == DataStatus.live:
            data_status = DataStatus.partial
        warnings.append(WarningItem(code="report-artifacts-partial", message="Standard report artifacts are incomplete"))

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
        lifecycle_status=_coerce_lifecycle_status(item.lifecycle_status),
        generated_at=item.updated_at or item.created_at,
        artifacts=schema_artifacts,
        structured_payload=_load_structured_payload(schema_artifacts),
    )


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
    legacy_final = _find_legacy_final_report(db, report_id)
    if legacy_final is not None:
        return _legacy_final_report_detail(legacy_final)

    legacy_fs_final = _legacy_final_report_detail_from_filesystem(report_id)
    if legacy_fs_final is not None:
        return legacy_fs_final

    legacy_macro = _legacy_macro_report_detail(report_id)
    if legacy_macro is not None:
        return legacy_macro

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
    base = _find_run_dir(_PROJECT_ROOT / "storage" / "outputs" / "final_report" / "XAUUSD", report_id)
    if base is None:
        return None
    trade_date, run_dir = base
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
        run_id=report_id,
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
    base = _find_run_dir(_PROJECT_ROOT / "storage" / "outputs" / "macro", macro_id)
    if base is None:
        date_dir = _PROJECT_ROOT / "storage" / "outputs" / "macro" / macro_id
        if date_dir.is_dir() and (date_dir / "macro_snapshot.md").exists():
            base = (macro_id, date_dir)
    if base is None:
        return None
    trade_date, run_dir = base
    artifacts = _artifact_schemas_from_paths(
        report_id=report_id,
        generated_at=None,
        path_specs=[
            (ArtifactType.analysis_md, run_dir / "macro_snapshot.md", True, "text/markdown"),
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
        title=f"XAUUSD 宏观数据报告（{trade_date}）",
        asset="XAUUSD",
        trade_date=trade_date,
        lifecycle_status=ReportLifecycleStatus.generated,
        artifacts=artifacts,
        structured_payload=_load_structured_payload(artifacts),
    )


def _legacy_jin10_report_detail(report_id: str) -> ReportDetail | None:
    base = _find_run_dir(_PROJECT_ROOT / "storage" / "outputs" / "jin10", report_id)
    if base is None:
        return _legacy_external_jin10_weekly_detail(report_id)
    trade_date, run_dir = base
    artifacts = _artifact_schemas_from_paths(
        report_id=report_id,
        generated_at=None,
        path_specs=[
            (ArtifactType.source_md, run_dir / "raw_article_report.md", True, "text/markdown"),
            (ArtifactType.analysis_md, run_dir / "agent_analysis_report.md", False, "text/markdown"),
            (ArtifactType.visual_html, run_dir / "daily_analysis.html", False, "text/html"),
            (ArtifactType.structured_json, run_dir / "raw_article_report.json", False, "application/json"),
        ],
    )
    if not artifacts:
        return None
    daily_payload = _read_optional_json(run_dir / "daily_analysis.json") or {}
    family = str(daily_payload.get("family") or "").strip() or "jin10_daily_visual"
    external_meta = _find_external_jin10_meta(trade_date, report_id)
    if family == "jin10_weekly_visual" or _is_explicit_jin10_weekly(external_meta or daily_payload):
        resolved_family = "jin10_weekly_visual"
        resolved_title = "Jin10 weekly report"
    else:
        resolved_family = "jin10_daily_visual"
        resolved_title = "Jin10 daily report"
    return ReportDetail(
        run_id=report_id,
        snapshot_id=None,
        data_status=DataStatus.partial if _missing_standard_artifacts(artifacts) or _missing_files(artifacts) else DataStatus.live,
        artifact_refs=artifacts,
        warnings=[WarningItem(code="legacy-report-adapter", message="Legacy Jin10 bundle adapted to report detail")],
        report_id=report_id,
        family=resolved_family,
        title=resolved_title,
        trade_date=trade_date,
        lifecycle_status=ReportLifecycleStatus.generated,
        artifacts=artifacts,
        structured_payload=_load_structured_payload(artifacts),
    )


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
        warnings=[WarningItem(code="legacy-report-adapter", message="Legacy Jin10 weekly source adapted to report detail")],
        report_id=report_id,
        family="jin10_weekly_visual",
        title="Jin10 weekly report",
        trade_date=trade_date,
        lifecycle_status=ReportLifecycleStatus.generated,
        artifacts=artifacts,
        structured_payload=_load_structured_payload(artifacts),
    )


def _legacy_cme_visual_detail(report_id: str) -> ReportDetail | None:
    base = _find_run_dir(_PROJECT_ROOT / "storage" / "outputs" / "cme", report_id)
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
        warnings=[WarningItem(code="legacy-report-adapter", message="Legacy CME visual report adapted to report detail")],
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
            rel = str(resolved.relative_to(_PROJECT_ROOT))
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


def _missing_standard_artifacts(artifacts: list[ReportArtifactSchema]) -> bool:
    present = {artifact.artifact_type for artifact in artifacts}
    return not _STANDARD_ARTIFACT_TYPES.issubset(present)


def _missing_files(artifacts: list[ReportArtifactSchema]) -> bool:
    return any((path := _resolve_report_path(artifact.file_path)) is None or not path.exists() for artifact in artifacts)


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


def _load_structured_payload(artifacts: list[ReportArtifactSchema]) -> dict | None:
    artifact = _pick_report_artifact(artifacts, ArtifactType.structured_json)
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
    return report_id[len(prefix):] if report_id.startswith(prefix) else report_id


def _resolve_report_path(file_path: str | Path) -> Path | None:
    raw_path = Path(file_path)
    if "://" in str(raw_path):
        return None
    candidate = raw_path if raw_path.is_absolute() else (_PROJECT_ROOT / raw_path)
    try:
        resolved = candidate.resolve()
        allowed_roots = [
            (_PROJECT_ROOT / "storage").resolve(),
            Path("~/jin10-reports").expanduser().resolve(),
        ]
    except OSError:
        return None
    return resolved if any(resolved.is_relative_to(root) for root in allowed_roots) else None


def _resolve_report_asset_path(file_path: str | Path, asset_path: str) -> Path | None:
    artifact_path = _resolve_report_path(file_path)
    if artifact_path is None:
        return None
    try:
        candidate = (artifact_path.parent / asset_path).resolve()
        parent = artifact_path.parent.resolve()
    except OSError:
        return None
    if not candidate.is_relative_to(parent) or not candidate.exists() or not candidate.is_file():
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

def _report_quality_score(md_path: Path) -> tuple[int, float, str]:
    try:
        content = md_path.read_text(encoding="utf-8")
    except Exception:
        return (-100, 0.0, md_path.parent.name)
    score = 0
    if "# XAUUSD 相关报告" in content:
        score += 120
    if "# XAUUSD 盘前专业研究报告" in content:
        score += 90
    if "## 执行摘要" in content:
        score += 25
    if "## 分项证据链" in content:
        score += 15
    if "# XAUUSD 盘前综合报告" in content:
        score += 70
    if "## 协调器总结" in content:
        score += 20
    if "## 数据口径" in content:
        score += 10
    if "## CME 期权结构视图" in content or "### CME 期权结构视图" in content:
        score += 10
    if "# XAUUSD Premarket Final Report" in content:
        score -= 40
    if "## Coordinator Summary" in content:
        score -= 20
    if "options: unavailable" in content or "options status is 'unavailable'" in content:
        score -= 40
    if "No complete final view" in content:
        score -= 10
    try:
        mtime = md_path.stat().st_mtime
    except OSError:
        mtime = 0.0
    return score, mtime, md_path.parent.name


def _build_final_report_response(asset: str, trade_date: str, run_id: str, md_path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "asset": asset,
        "trade_date": trade_date,
        "run_id": run_id,
        "content": md_path.read_text(encoding="utf-8"),
        "format": "markdown",
        "path": str(md_path.relative_to(_PROJECT_ROOT)),
    }
    json_path = md_path.parent / "structured_report.json"
    if json_path.exists():
        try:
            result["structured_sections"] = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            result["structured_sections"] = None
    return result


def _latest_final_report_from_filesystem(asset: str = "XAUUSD") -> tuple[str, str, Path] | None:
    base = _PROJECT_ROOT / "storage" / "outputs" / "final_report" / asset
    if not base.exists():
        return None
    candidates: list[tuple[str, str, Path]] = []
    for date_dir in sorted((d for d in base.iterdir() if d.is_dir()), reverse=True):
        for run_dir in (d for d in date_dir.iterdir() if d.is_dir()):
            md_path = run_dir / "final_report.md"
            if md_path.exists():
                candidates.append((date_dir.name, run_dir.name, md_path))
        if candidates:
            break
    return max(candidates, key=lambda item: _report_quality_score(item[2])) if candidates else None


def get_final_report_latest(asset: str = "XAUUSD") -> dict[str, Any] | None:
    fs_best = _latest_final_report_from_filesystem(asset)
    if fs_best is not None:
        trade_date, run_id, md_path = fs_best
        return _build_final_report_response(asset, trade_date, run_id, md_path)
    db = _try_db_session()
    if db is not None:
        try:
            from database.queries.analysis import get_final_analysis_latest

            row = get_final_analysis_latest(db, asset)
            if row is not None and row.final_report_path:
                path = _PROJECT_ROOT / row.final_report_path
                if path.exists():
                    return _build_final_report_response(asset, _iso(row.trade_date), row.run_id, path)
        except Exception:
            pass
        finally:
            db.close()
    return None


def get_final_report(date: str, run_id: str, asset: str = "XAUUSD") -> dict[str, Any] | None:
    db = _try_db_session()
    if db is not None:
        try:
            from database.queries.analysis import get_final_analysis

            row = get_final_analysis(db, asset, date, run_id)
            if row is not None and row.final_report_path:
                path = _PROJECT_ROOT / row.final_report_path
                if path.exists():
                    return {
                        "asset": asset,
                        "trade_date": date,
                        "run_id": run_id,
                        "content": path.read_text(encoding="utf-8"),
                        "format": "markdown",
                        "path": str(path.relative_to(_PROJECT_ROOT)),
                    }
        except Exception:
            pass
        finally:
            db.close()
    md_path = _PROJECT_ROOT / "storage" / "outputs" / "final_report" / asset / date / run_id / "final_report.md"
    return _build_final_report_response(asset, date, run_id, md_path) if md_path.exists() else None


def get_strategy_card_latest(asset: str = "XAUUSD") -> dict[str, Any] | None:
    base = _PROJECT_ROOT / "storage" / "outputs" / "strategy_card"
    trade_date, run_id, run_dir = _latest_asset_date_run(base, asset)
    if trade_date is not None and run_dir is not None:
        json_path = run_dir / "strategy_card.json"
        md_path = run_dir / "strategy_card.md"
        if json_path.exists():
            try:
                json_data = json.loads(json_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                json_data = None
            if json_data is not None:
                market_regime = _strategy_market_regime_from_json(json_path)
                if market_regime is not None:
                    json_data = dict(json_data)
                    json_data.setdefault("market_regime", market_regime)
                result: dict[str, Any] = {
                    "asset": asset,
                    "trade_date": trade_date,
                    "run_id": run_id,
                    "json": json_data,
                    "paths": {"json": str(json_path.relative_to(_PROJECT_ROOT))},
                }
                if market_regime is not None:
                    result["market_regime"] = market_regime
                if md_path.exists():
                    result["markdown"] = md_path.read_text(encoding="utf-8")
                    result["paths"]["markdown"] = str(md_path.relative_to(_PROJECT_ROOT))
                return result

    db = _try_db_session()
    if db is not None:
        try:
            from database.queries.analysis import get_final_analysis_latest

            row = get_final_analysis_latest(db, asset)
            if row is not None and row.strategy_card is not None:
                market_regime = _resolve_strategy_market_regime_from_row(row)
                json_payload = dict(row.strategy_card)
                if market_regime is not None:
                    json_payload.setdefault("market_regime", market_regime)
                result: dict[str, Any] = {
                    "asset": asset,
                    "trade_date": _iso(row.trade_date),
                    "run_id": row.run_id,
                    "json": json_payload,
                    "paths": {},
                }
                if market_regime is not None:
                    result["market_regime"] = market_regime
                if row.strategy_card_md_path:
                    md_path = _PROJECT_ROOT / row.strategy_card_md_path
                    if md_path.exists():
                        result["markdown"] = md_path.read_text(encoding="utf-8")
                        result["paths"]["markdown"] = str(md_path.relative_to(_PROJECT_ROOT))
                if row.strategy_card_json_path:
                    result["paths"]["json"] = row.strategy_card_json_path
                return result
        except Exception:
            pass
        finally:
            db.close()
    return None


def get_strategy_card(date: str, run_id: str, asset: str = "XAUUSD") -> dict[str, Any] | None:
    db = _try_db_session()
    if db is not None:
        try:
            from database.queries.analysis import get_final_analysis

            row = get_final_analysis(db, asset, date, run_id)
            if row is not None and row.strategy_card is not None:
                market_regime = _resolve_strategy_market_regime_from_row(row)
                json_payload = dict(row.strategy_card)
                if market_regime is not None:
                    json_payload.setdefault("market_regime", market_regime)
                result: dict[str, Any] = {
                    "asset": asset,
                    "trade_date": date,
                    "run_id": run_id,
                    "json": json_payload,
                    "paths": {},
                }
                if market_regime is not None:
                    result["market_regime"] = market_regime
                if row.strategy_card_md_path:
                    md_path = _PROJECT_ROOT / row.strategy_card_md_path
                    if md_path.exists():
                        result["markdown"] = md_path.read_text(encoding="utf-8")
                        result["paths"]["markdown"] = str(md_path.relative_to(_PROJECT_ROOT))
                if row.strategy_card_json_path:
                    result["paths"]["json"] = row.strategy_card_json_path
                return result
        except Exception:
            pass
        finally:
            db.close()
    base = _PROJECT_ROOT / "storage" / "outputs" / "strategy_card" / asset / date / run_id
    json_path = base / "strategy_card.json"
    md_path = base / "strategy_card.md"
    if not json_path.exists():
        return None
    try:
        json_data = json.loads(json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    market_regime = _strategy_market_regime_from_json(json_path)
    if market_regime is not None:
        json_data = dict(json_data)
        json_data.setdefault("market_regime", market_regime)
    result: dict[str, Any] = {
        "asset": asset,
        "trade_date": date,
        "run_id": run_id,
        "json": json_data,
        "paths": {"json": str(json_path.relative_to(_PROJECT_ROOT))},
    }
    if market_regime is not None:
        result["market_regime"] = market_regime
    if md_path.exists():
        result["markdown"] = md_path.read_text(encoding="utf-8")
        result["paths"]["markdown"] = str(md_path.relative_to(_PROJECT_ROOT))
    return result


def _build_strategy_card_summary(
    *,
    strategy_card_id: str,
    asset: str,
    trade_date: str,
    run_id: str,
    snapshot_id: str | None,
    sc_data: dict[str, Any],
    paths: dict[str, str],
    source_refs: list,
    artifact_refs: list[str],
    market_regime: str | None = None,
) -> dict[str, Any]:
    return {
        "strategy_card_id": strategy_card_id,
        "asset": asset,
        "trade_date": trade_date,
        "run_id": run_id,
        "snapshot_id": snapshot_id,
        "status": sc_data.get("status"),
        "bias": sc_data.get("bias"),
        "confidence": sc_data.get("confidence"),
        "market_regime": market_regime if market_regime is not None else sc_data.get("market_regime"),
        "paths": paths,
        "source_refs": source_refs or [],
        "artifact_refs": artifact_refs,
    }


def _build_strategy_card_detail(
    *,
    strategy_card_id: str,
    asset: str,
    trade_date: str,
    run_id: str,
    snapshot_id: str | None,
    sc_data: dict[str, Any],
    paths: dict[str, str],
    source_refs: list,
    artifact_refs: list[str],
    md_content: str | None = None,
    market_regime: str | None = None,
) -> dict[str, Any]:
    detail_source_refs = source_refs or (sc_data.get("source_refs") if isinstance(sc_data.get("source_refs"), list) else []) or []
    result: dict[str, Any] = {
        "strategy_card_id": strategy_card_id,
        "asset": asset,
        "trade_date": trade_date,
        "run_id": run_id,
        "snapshot_id": snapshot_id,
        "status": sc_data.get("status"),
        "bias": sc_data.get("bias"),
        "confidence": sc_data.get("confidence"),
        "market_regime": market_regime if market_regime is not None else sc_data.get("market_regime"),
        "updated_at": sc_data.get("created_at"),
        "paths": paths,
        "source_refs": detail_source_refs,
        "artifact_refs": artifact_refs,
        "hero": _build_strategy_hero(
            sc_data,
            trade_date=trade_date,
            run_id=run_id,
            snapshot_id=snapshot_id,
            source_refs=detail_source_refs,
            market_regime=market_regime,
        ),
        "scenario": _build_strategy_scenario(sc_data),
        "module_signals": sc_data.get("module_signals") or [],
        "playbook_matches": sc_data.get("playbook_matches") or [],
        "has_data": bool(sc_data or md_content or paths),
        "json": sc_data,
    }
    if md_content is not None:
        result["markdown"] = md_content
    return result


def _build_strategy_hero(
    sc_data: dict[str, Any],
    *,
    trade_date: str,
    run_id: str,
    snapshot_id: str | None,
    source_refs: list[Any],
    market_regime: str | None,
) -> dict[str, Any]:
    return {
        "status": sc_data.get("status") or "available",
        "bias": sc_data.get("bias") or "",
        "direction": sc_data.get("direction") or "unknown",
        "confidence": sc_data.get("confidence"),
        "market_regime": market_regime if market_regime is not None else sc_data.get("market_regime") or sc_data.get("macro_phase"),
        "trade_date": trade_date,
        "run_id": run_id,
        "snapshot_id": snapshot_id,
        "source_refs": source_refs,
    }


def _build_strategy_scenario(sc_data: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(sc_data, dict) or not sc_data:
        return None
    main_scenario = sc_data.get("main_scenario") or sc_data.get("scenario_summary") or ""
    has_scenario_fields = any(
        [
            bool(main_scenario),
            bool(sc_data.get("alternative_scenarios")),
            bool(sc_data.get("key_levels")),
            bool(sc_data.get("key_levels_from_options")),
            bool(sc_data.get("trigger_conditions") or sc_data.get("triggers")),
            bool(sc_data.get("invalidation_conditions") or sc_data.get("invalid_conditions")),
            bool(sc_data.get("confirmation_conditions")),
            bool(sc_data.get("risk_points")),
        ]
    )
    if not has_scenario_fields:
        return None
    key_levels = _build_strategy_key_levels(sc_data)
    return {
        "main_scenario": str(main_scenario),
        "alternative_scenarios": list(sc_data.get("alternative_scenarios") or []),
        "key_levels": key_levels,
        "trigger_conditions": list(sc_data.get("trigger_conditions") or sc_data.get("triggers") or []),
        "invalidation_conditions": list(sc_data.get("invalidation_conditions") or sc_data.get("invalid_conditions") or []),
        "confirmation_conditions": list(sc_data.get("confirmation_conditions") or []),
        "risk_points": list(sc_data.get("risk_points") or []),
    }


def _build_strategy_key_levels(sc_data: dict[str, Any]) -> dict[str, list[float]]:
    key_levels = sc_data.get("key_levels")
    if isinstance(key_levels, dict):
        return {
            "resistance": _coerce_numeric_list(key_levels.get("resistance")),
            "support": _coerce_numeric_list(key_levels.get("support")),
        }
    return {
        "resistance": _coerce_key_levels_from_options(sc_data.get("key_levels_from_options")),
        "support": [],
    }


def _coerce_numeric_list(raw: Any) -> list[float]:
    if not isinstance(raw, list):
        return []
    values: list[float] = []
    for item in raw:
        try:
            number = float(item)
        except (TypeError, ValueError):
            continue
        if number.is_integer():
            values.append(int(number))
        else:
            values.append(number)
    return values


def _coerce_key_levels_from_options(raw: Any) -> list[float]:
    if not isinstance(raw, list):
        return []
    values: list[float] = []
    for item in raw:
        if isinstance(item, (int, float)):
            values.append(int(item) if float(item).is_integer() else float(item))
            continue
        if not isinstance(item, str):
            continue
        for match in re.findall(r"\d+(?:\.\d+)?", item):
            number = float(match)
            values.append(int(number) if number.is_integer() else number)
    return values


def _derive_strategy_card_id(row: FinalAnalysisResult, sc_data: dict[str, Any]) -> str:
    return (
        sc_data.get("strategy_card_id")
        or row.run_id
        or row.snapshot_id
        or f"{row.asset}:{_iso(row.trade_date)}:{row.run_id}"
    )


def _collect_fs_strategy_cards(base: Path, asset: str, limit: int) -> list[dict[str, Any]]:
    """Scan filesystem for strategy card summaries when DB is unavailable."""
    items: list[dict[str, Any]] = []
    asset_dir = base / asset
    if not asset_dir.exists():
        return items
    for date_dir in sorted((d for d in asset_dir.iterdir() if d.is_dir()), reverse=True):
        for run_dir in sorted((d for d in date_dir.iterdir() if d.is_dir()), reverse=True):
            if len(items) >= limit:
                return items
            json_path = run_dir / "strategy_card.json"
            if not json_path.exists():
                continue
            try:
                sc_data = json.loads(json_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            paths: dict[str, str] = {"json": str(json_path.relative_to(_PROJECT_ROOT))}
            md_path = run_dir / "strategy_card.md"
            if md_path.exists():
                paths["markdown"] = str(md_path.relative_to(_PROJECT_ROOT))
            strategy_card_id = sc_data.get("strategy_card_id") or run_dir.name
            market_regime = _strategy_market_regime_from_json(json_path)
            items.append(
                _build_strategy_card_summary(
                    strategy_card_id=strategy_card_id,
                    asset=asset,
                    trade_date=date_dir.name,
                    run_id=run_dir.name,
                    snapshot_id=None,
                    sc_data=sc_data,
                    paths=paths,
                    source_refs=[],
                    artifact_refs=[str(json_path.relative_to(_PROJECT_ROOT))],
                    market_regime=market_regime,
                )
            )
    return items


def _collect_fs_strategy_assets(base: Path) -> list[dict[str, Any]]:
    if not base.exists():
        return []
    items: list[dict[str, Any]] = []
    for asset_dir in sorted((d for d in base.iterdir() if d.is_dir()), key=lambda path: path.name):
        sample_size = 0
        latest_trade_date: str | None = None
        latest_run_id: str | None = None
        latest_snapshot_id: str | None = None
        regime_counts: defaultdict[str, int] = defaultdict(int)
        for date_dir in sorted((d for d in asset_dir.iterdir() if d.is_dir()), reverse=True):
            for run_dir in sorted((d for d in date_dir.iterdir() if d.is_dir()), reverse=True):
                json_path = run_dir / "strategy_card.json"
                if not json_path.exists():
                    continue
                sample_size += 1
                if latest_trade_date is None:
                    latest_trade_date = date_dir.name
                    latest_run_id = run_dir.name
                    try:
                        payload = json.loads(json_path.read_text(encoding="utf-8"))
                    except Exception:
                        payload = {}
                    if isinstance(payload, dict):
                        snapshot_id = payload.get("snapshot_id")
                        latest_snapshot_id = snapshot_id if isinstance(snapshot_id, str) else None
                regime = _strategy_market_regime_from_json(json_path)
                if regime is not None:
                    regime_counts[regime] += 1
        if sample_size > 0:
            items.append(
                {
                    "asset": asset_dir.name,
                    "sample_size": sample_size,
                    "latest_trade_date": latest_trade_date,
                    "latest_run_id": latest_run_id,
                    "latest_snapshot_id": latest_snapshot_id,
                    "regime_counts": _strategy_regime_counts_payload(regime_counts),
                }
            )
    return items


def _summarize_strategy_assets(rows: list[FinalAnalysisResult]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not row.asset:
            continue
        item = grouped.setdefault(
            row.asset,
            {
                "asset": row.asset,
                "sample_size": 0,
                "latest_trade_date": None,
                "latest_run_id": None,
                "latest_snapshot_id": None,
                "_regime_counts": defaultdict(int),
            },
        )
        item["sample_size"] += 1
        regime = _resolve_strategy_market_regime_from_row(row)
        if regime is not None:
            item["_regime_counts"][regime] += 1
        if item["latest_trade_date"] is None:
            item["latest_trade_date"] = _iso(row.trade_date) if row.trade_date else None
            item["latest_run_id"] = row.run_id
            item["latest_snapshot_id"] = row.snapshot_id
    items: list[dict[str, Any]] = []
    for item in grouped.values():
        regime_counts = item.pop("_regime_counts", defaultdict(int))
        item["regime_counts"] = _strategy_regime_counts_payload(regime_counts)
        items.append(item)
    return items


def _strategy_market_regime_from_payload(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    value = payload.get("market_regime") or payload.get("macro_phase")
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _strategy_market_regime_from_analysis_snapshot_payload(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None

    for key in ("market_regime", "market_phase"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    macro = payload.get("macro")
    if not isinstance(macro, dict):
        return None

    for key in ("market_regime", "market_phase"):
        value = macro.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    if macro.get("status") != "available":
        return None

    data = macro.get("data")
    if not isinstance(data, dict):
        return None
    indicators = data.get("indicators")
    if not isinstance(indicators, dict):
        return None

    phase = classify_macro_regime(indicators).get("market_phase")
    if not isinstance(phase, str):
        return None
    phase = phase.strip()
    return phase or None


def _resolve_strategy_market_regime_from_row(row: FinalAnalysisResult) -> str | None:
    regime = _strategy_market_regime_from_payload(row.strategy_card)
    if regime is not None:
        return regime
    if row.analysis_snapshot is not None:
        if isinstance(row.analysis_snapshot.macro, dict):
            regime = _strategy_market_regime_from_analysis_snapshot_payload({"macro": row.analysis_snapshot.macro})
            if regime is not None:
                return regime
        if isinstance(row.analysis_snapshot.payload, dict):
            regime = _strategy_market_regime_from_analysis_snapshot_payload(row.analysis_snapshot.payload)
            if regime is not None:
                return regime
    return None


def _load_strategy_analysis_snapshot_payload(json_path: Path) -> dict[str, Any] | None:
    try:
        parts = json_path.resolve().parts
    except Exception:
        return None
    try:
        storage_idx = parts.index("storage")
    except ValueError:
        return None
    if len(parts) < storage_idx + 6:
        return None
    asset = parts[storage_idx + 3]
    trade_date = parts[storage_idx + 4]
    run_id = parts[storage_idx + 5]
    analysis_path = (
        _PROJECT_ROOT
        / "storage"
        / "features"
        / "snapshots"
        / asset
        / trade_date
        / run_id
        / "premarket_snapshot.json"
    )
    if not analysis_path.exists():
        return None
    try:
        payload = json.loads(analysis_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _strategy_market_regime_from_json(json_path: Path) -> str | None:
    try:
        payload = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    regime = _strategy_market_regime_from_payload(payload)
    if regime is not None:
        return regime
    return _strategy_market_regime_from_analysis_snapshot_payload(
        _load_strategy_analysis_snapshot_payload(json_path)
    )


def _strategy_regime_counts_payload(regime_counts: defaultdict[str, int]) -> list[dict[str, Any]]:
    return [
        {"market_regime": regime, "sample_size": sample_size}
        for regime, sample_size in sorted(regime_counts.items(), key=lambda item: (-item[1], item[0]))
        if sample_size > 0
    ]


def list_strategy_cards(asset: str = "XAUUSD", limit: int = 20) -> dict[str, Any]:
    """Return a list of strategy card summaries ordered by latest trade_date."""
    limit = min(max(limit, 1), 100)
    db = _try_db_session()
    if db is not None:
        try:
            rows = db.scalars(
                select(FinalAnalysisResult)
                .where(
                    FinalAnalysisResult.asset == asset,
                    FinalAnalysisResult.strategy_card.isnot(None),
                )
                .order_by(FinalAnalysisResult.trade_date.desc(), FinalAnalysisResult.id.desc())
                .limit(limit)
            ).all()
            if rows:
                items: list[dict[str, Any]] = []
                for row in rows:
                    sc_data = row.strategy_card
                    if not isinstance(sc_data, dict):
                        continue
                    td = _iso(row.trade_date)
                    market_regime = _resolve_strategy_market_regime_from_row(row)
                    strategy_card_id = _derive_strategy_card_id(row, sc_data)
                    paths: dict[str, str] = {}
                    if row.strategy_card_json_path:
                        paths["json"] = row.strategy_card_json_path
                    if row.strategy_card_md_path:
                        paths["markdown"] = row.strategy_card_md_path
                    artifact_refs: list[str] = []
                    if row.strategy_card_json_path:
                        artifact_refs.append(row.strategy_card_json_path)
                    if row.strategy_card_md_path:
                        artifact_refs.append(row.strategy_card_md_path)
                    items.append(
                        _build_strategy_card_summary(
                            strategy_card_id=strategy_card_id,
                            asset=asset,
                            trade_date=td,
                            run_id=row.run_id,
                            snapshot_id=row.snapshot_id,
                            sc_data=sc_data,
                            paths=paths,
                            source_refs=row.source_refs if isinstance(row.source_refs, list) else [],
                            artifact_refs=artifact_refs,
                            market_regime=market_regime,
                        )
                    )
                return {"asset": asset, "count": len(items), "items": items}
        except Exception:
            pass
        finally:
            db.close()

    base = _PROJECT_ROOT / "storage" / "outputs" / "strategy_card"
    items = _collect_fs_strategy_cards(base, asset, limit)
    return {"asset": asset, "count": len(items), "items": items}


def list_strategy_assets() -> dict[str, Any]:
    """Return discovered strategy assets with sample sizes and latest timestamps."""
    db = _try_db_session()
    if db is not None:
        try:
            rows = db.scalars(
                select(FinalAnalysisResult)
                .where(
                    FinalAnalysisResult.asset.isnot(None),
                    FinalAnalysisResult.strategy_card.isnot(None),
                )
                .order_by(FinalAnalysisResult.asset.asc(), FinalAnalysisResult.trade_date.desc(), FinalAnalysisResult.id.desc())
            ).all()
            if rows:
                items = _summarize_strategy_assets(rows)
                return {"count": len(items), "items": items}
        except Exception:
            pass
        finally:
            db.close()

    base = _PROJECT_ROOT / "storage" / "outputs" / "strategy_card"
    items = _collect_fs_strategy_assets(base)
    return {"count": len(items), "items": items}


def get_strategy_card_by_id(strategy_card_id: str, asset: str = "XAUUSD") -> dict[str, Any] | None:
    """Find a strategy card by strategy_card_id, run_id, or snapshot_id."""
    db = _try_db_session()
    if db is not None:
        try:
            rows = db.scalars(
                select(FinalAnalysisResult)
                .where(
                    FinalAnalysisResult.asset == asset,
                    FinalAnalysisResult.strategy_card.isnot(None),
                )
                .order_by(FinalAnalysisResult.trade_date.desc(), FinalAnalysisResult.id.desc())
            ).all()
            for row in rows:
                sc_data = row.strategy_card
                if not isinstance(sc_data, dict):
                    continue
                row_sc_id = _derive_strategy_card_id(row, sc_data)
                if strategy_card_id in (row_sc_id, row.run_id, row.snapshot_id):
                    td = _iso(row.trade_date)
                    market_regime = _resolve_strategy_market_regime_from_row(row)
                    paths: dict[str, str] = {}
                    if row.strategy_card_json_path:
                        paths["json"] = row.strategy_card_json_path
                    if row.strategy_card_md_path:
                        paths["markdown"] = row.strategy_card_md_path
                    md_content: str | None = None
                    if row.strategy_card_md_path:
                        md_path = _PROJECT_ROOT / row.strategy_card_md_path
                        if md_path.exists():
                            md_content = md_path.read_text(encoding="utf-8")
                    artifact_refs: list[str] = []
                    if row.strategy_card_json_path:
                        artifact_refs.append(row.strategy_card_json_path)
                    if row.strategy_card_md_path:
                        artifact_refs.append(row.strategy_card_md_path)
                    return _build_strategy_card_detail(
                        strategy_card_id=row_sc_id,
                        asset=asset,
                        trade_date=td,
                        run_id=row.run_id,
                        snapshot_id=row.snapshot_id,
                        sc_data=sc_data,
                        paths=paths,
                        source_refs=row.source_refs if isinstance(row.source_refs, list) else [],
                        artifact_refs=artifact_refs,
                        md_content=md_content,
                        market_regime=market_regime,
                    )
        except Exception:
            pass
        finally:
            db.close()

    # Filesystem fallback
    base = _PROJECT_ROOT / "storage" / "outputs" / "strategy_card" / asset
    if not base.exists():
        return None
    for date_dir in sorted((d for d in base.iterdir() if d.is_dir()), reverse=True):
        for run_dir in sorted((d for d in date_dir.iterdir() if d.is_dir()), reverse=True):
            json_path = run_dir / "strategy_card.json"
            if not json_path.exists():
                continue
            try:
                sc_data = json.loads(json_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            fs_id = sc_data.get("strategy_card_id") or run_dir.name
            if strategy_card_id not in (fs_id, run_dir.name):
                continue
            paths = {"json": str(json_path.relative_to(_PROJECT_ROOT))}
            md_path = run_dir / "strategy_card.md"
            md_content = None
            if md_path.exists():
                md_content = md_path.read_text(encoding="utf-8")
                paths["markdown"] = str(md_path.relative_to(_PROJECT_ROOT))
            market_regime = _strategy_market_regime_from_json(json_path)
            return _build_strategy_card_detail(
                strategy_card_id=fs_id,
                asset=asset,
                trade_date=date_dir.name,
                run_id=run_dir.name,
                snapshot_id=None,
                sc_data=sc_data,
                paths=paths,
                source_refs=[],
                artifact_refs=list(paths.values()),
                md_content=md_content,
                market_regime=market_regime,
            )
    return None


def get_strategy_card_read_model_latest(asset: str = "XAUUSD") -> dict[str, Any] | None:
    """Return the latest strategy card as a read model detail (reuses list + by_id)."""
    listing = list_strategy_cards(asset=asset, limit=1)
    if listing["count"] == 0:
        return None
    first = listing["items"][0]
    return get_strategy_card_by_id(first["strategy_card_id"], asset=asset)


def get_jin10_daily_report_latest() -> dict[str, Any] | None:
    base = _PROJECT_ROOT / "storage" / "outputs" / "jin10"
    if not base.exists():
        return None
    for date_dir in sorted((d for d in base.iterdir() if d.is_dir()), reverse=True):
        for run_dir in sorted((d for d in date_dir.iterdir() if d.is_dir()), reverse=True):
            payload = _load_jin10_daily_report(date_dir.name, run_dir.name)
            if payload is not None:
                return payload
    return None


def get_jin10_daily_report(date: str, run_id: str) -> dict[str, Any] | None:
    return _load_jin10_daily_report(date, run_id)


def _load_jin10_daily_report(date: str, run_id: str) -> dict[str, Any] | None:
    base = _PROJECT_ROOT / "storage" / "outputs" / "jin10" / date / run_id
    json_path = base / "daily_analysis.json"
    html_path = base / "daily_analysis.html"
    if not json_path.exists() or not html_path.exists():
        return None
    try:
        payload = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    payload["content"] = html_path.read_text(encoding="utf-8")
    payload["format"] = "html"
    payload["path"] = str(html_path.relative_to(_PROJECT_ROOT))
    return payload


def get_jin10_report_bundle_latest() -> dict[str, Any] | None:
    base = _PROJECT_ROOT / "storage" / "outputs" / "jin10"
    if not base.exists():
        return None
    for date_dir in sorted((d for d in base.iterdir() if d.is_dir()), reverse=True):
        for run_dir in sorted((d for d in date_dir.iterdir() if d.is_dir()), reverse=True):
            payload = _load_jin10_report_bundle(date_dir.name, run_dir.name)
            if payload is not None:
                return payload
    return None


def get_jin10_report_bundle(date: str, run_id: str) -> dict[str, Any] | None:
    return _load_jin10_report_bundle(date, run_id)


def get_jin10_report_bundle_asset_path(date: str, run_id: str, asset_path: str) -> Path | None:
    base = (_PROJECT_ROOT / "storage" / "outputs" / "jin10" / date / run_id).resolve()
    if not base.exists():
        return None
    candidate = (base / asset_path).resolve()
    if not candidate.exists() or not candidate.is_file():
        return None
    try:
        candidate.relative_to(base)
    except ValueError:
        return None
    return candidate


def _read_optional_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _read_optional_text(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _normalize_jin10_quality_audit(*payloads: dict[str, Any] | None) -> dict[str, Any] | None:
    for payload in payloads:
        audit = (payload or {}).get("quality_audit")
        if not isinstance(audit, dict):
            continue
        status = str(audit.get("status") or "accepted")
        reasons = audit.get("reasons")
        reason_items = [item for item in reasons if isinstance(item, dict)] if isinstance(reasons, list) else []
        return {
            "status": status,
            "checked_at": audit.get("checked_at"),
            "reasons": reason_items,
            "reason_codes": [str(item.get("code")) for item in reason_items if item.get("code")],
        }
    return None


def _jin10_report_status(quality_audit: dict[str, Any] | None) -> str:
    status = str((quality_audit or {}).get("status") or "accepted").strip().lower()
    if status in {"rejected", "needs_review", "failed"}:
        return "degraded"
    return "ready"


def _build_jin10_view_payload(*, kind: str, content: str | None, path: Path, asset_base_url: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": kind,
        "available": bool(content and content.strip()),
    }
    if content and content.strip():
        payload["content"] = content
        payload["path"] = str(path.relative_to(_PROJECT_ROOT))
        if asset_base_url:
            payload["asset_base_url"] = asset_base_url
    return payload


def _pick_jin10_default_view(views: dict[str, dict[str, Any]]) -> str:
    for key in ("agent_analysis", "daily_visual", "raw_article"):
        if views.get(key, {}).get("available"):
            return key
    return "agent_analysis"


def _load_jin10_report_bundle(date: str, run_id: str) -> dict[str, Any] | None:
    base = _PROJECT_ROOT / "storage" / "outputs" / "jin10" / date / run_id
    if not base.exists():
        return None
    asset_base_url = f"/api/jin10/report-bundle/{date}/{run_id}/asset/"

    daily_json = _read_optional_json(base / "daily_analysis.json")
    raw_json = _read_optional_json(base / "raw_article_report.json")
    agent_json = _read_optional_json(base / "agent_analysis_report.json")

    views = {
        "agent_analysis": _build_jin10_view_payload(
            kind="markdown",
            content=_read_optional_text(base / "agent_analysis_report.md"),
            path=base / "agent_analysis_report.md",
            asset_base_url=asset_base_url,
        ),
        "daily_visual": _build_jin10_view_payload(
            kind="html",
            content=_read_optional_text(base / "daily_analysis.html"),
            path=base / "daily_analysis.html",
        ),
        "raw_article": _build_jin10_view_payload(
            kind="markdown",
            content=_read_optional_text(base / "raw_article_report.md"),
            path=base / "raw_article_report.md",
            asset_base_url=asset_base_url,
        ),
    }

    if not any(view["available"] for view in views.values()):
        return None

    title = (
        (agent_json or {}).get("title")
        or (daily_json or {}).get("title")
        or (raw_json or {}).get("title")
    )
    source_url = (
        (agent_json or {}).get("source_url")
        or (daily_json or {}).get("source_url")
        or (raw_json or {}).get("source_url")
    )
    article_id = (
        (agent_json or {}).get("article_id")
        or (daily_json or {}).get("article_id")
        or (raw_json or {}).get("article_id")
        or run_id
    )
    quality_audit = _normalize_jin10_quality_audit(agent_json, daily_json, raw_json)

    payload = {
        "asset": "XAUUSD",
        "trade_date": date,
        "run_id": run_id,
        "article_id": article_id,
        "title": title,
        "source_url": source_url,
        "default_view": _pick_jin10_default_view(views),
        "views": views,
        "data_category": "external_opinion",
    }
    if quality_audit is not None:
        payload["quality_audit"] = quality_audit
    return payload

def _collect_reports(base_rel: str, report_type: str, fmt: str, asset: str, md_filename: str | None = None) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    base = _PROJECT_ROOT / "storage" / "outputs" / base_rel / asset
    if not base.exists():
        return results
    for date_dir in sorted(base.iterdir(), reverse=True):
        if not date_dir.is_dir():
            continue
        for run_dir in sorted(date_dir.iterdir(), reverse=True):
            if not run_dir.is_dir():
                continue
            available = (run_dir / md_filename).exists() if md_filename else (run_dir / "strategy_card.json").exists()
            results.append(
                {
                    "type": report_type,
                    "trade_date": date_dir.name,
                    "run_id": run_dir.name,
                    "report_id": run_dir.name,
                    "family": _report_index_family(report_type),
                    "title": _report_index_title(report_type, date_dir.name),
                    "format": fmt,
                    "available": available,
                }
            )
    if results:
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
                }
            )
    return results


def _collect_reports_from_db(report_type: str, fmt: str, asset: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    storage_root = _PROJECT_ROOT / "storage"
    if not storage_root.exists():
        return results
    db = _try_db_session()
    if db is None:
        return results
    try:
        from database.models.analysis import FinalAnalysisResult
        from sqlalchemy import select

        rows = db.scalars(
            select(FinalAnalysisResult)
            .where(FinalAnalysisResult.asset == asset)
            .order_by(FinalAnalysisResult.trade_date.desc(), FinalAnalysisResult.id.desc())
        ).all()
        for row in rows:
            if report_type == "final_report":
                if not row.final_report_path:
                    continue
                path = _PROJECT_ROOT / row.final_report_path
                if not path.exists() or not path.is_relative_to(storage_root):
                    continue
                available = True
            elif report_type == "strategy_card":
                candidate_paths = [row.strategy_card_json_path, row.strategy_card_md_path]
                if any(candidate_paths):
                    existing_paths = [
                        _PROJECT_ROOT / path for path in candidate_paths
                        if path is not None and (_PROJECT_ROOT / path).exists() and (_PROJECT_ROOT / path).is_relative_to(storage_root)
                    ]
                    if not existing_paths:
                        continue
                available = row.strategy_card is not None
            else:
                available = False
            report_id = row.run_id or row.snapshot_id
            results.append(
                {
                    "type": report_type,
                    "trade_date": _iso(row.trade_date),
                    "run_id": row.run_id,
                    "report_id": report_id,
                    "family": _report_index_family(report_type),
                    "title": _report_index_title(report_type, _iso(row.trade_date)),
                    "format": fmt,
                    "available": available,
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
    db = _try_db_session()
    if db is None:
        return results
    try:
        rows = db.scalars(
            select(ReportItem)
            .where(or_(ReportItem.asset == asset, ReportItem.asset.is_(None)))
            .order_by(ReportItem.trade_date.desc(), ReportItem.updated_at.desc(), ReportItem.created_at.desc())
        ).all()
        for item in rows:
            artifacts = list(item.artifacts or [])
            report_type = str(item.report_type or item.family or "").strip()
            if not report_type:
                continue
            trade_date = _iso(item.trade_date)
            results.append(
                {
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
            )
    except Exception:
        return []
    finally:
        db.close()
    return results


def _dedupe_reports_index_items(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in reports:
        report_id = str(item.get("report_id") or "").strip()
        report_type = str(item.get("type") or "").strip()
        run_id = str(item.get("run_id") or "").strip()
        trade_date = str(item.get("trade_date") or "").strip()
        key = (report_type, f"{trade_date}:{run_id}") if run_id else (report_type, report_id)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _collect_jin10_reports() -> list[dict[str, Any]]:
    base = _PROJECT_ROOT / "storage" / "outputs" / "jin10"
    results: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    if base.exists():
        for date_dir in sorted((d for d in base.iterdir() if d.is_dir()), reverse=True):
            for run_dir in sorted((d for d in date_dir.iterdir() if d.is_dir()), reverse=True):
                payload = _read_optional_json(run_dir / "daily_analysis.json") or {}
                agent_payload = _read_optional_json(run_dir / "agent_analysis_report.json")
                raw_payload = _read_optional_json(run_dir / "raw_article_report.json")
                quality_audit = _normalize_jin10_quality_audit(agent_payload, payload, raw_payload)
                external_meta = _find_external_jin10_meta(date_dir.name, run_dir.name)
                is_weekly = str(payload.get("family") or "").strip() == "jin10_weekly_visual" or _is_explicit_jin10_weekly(external_meta or payload)
                report_type = "jin10_weekly_report" if is_weekly else "jin10_daily_report"
                seen.add((date_dir.name, run_dir.name))
                item = {
                    "type": report_type,
                    "trade_date": date_dir.name,
                    "run_id": run_dir.name,
                    "report_id": run_dir.name,
                    "title": (
                        (agent_payload or {}).get("title")
                        or payload.get("title")
                        or (raw_payload or {}).get("title")
                        or (external_meta or {}).get("title")
                    ),
                    "format": "json+html",
                    "available": (run_dir / "daily_analysis.json").exists() and (run_dir / "daily_analysis.html").exists(),
                    "status": _jin10_report_status(quality_audit),
                }
                if quality_audit is not None:
                    item["quality_audit"] = quality_audit
                results.append(item)
    results.extend(_collect_jin10_external_weekly_reports(seen))
    return results


def _collect_jin10_external_weekly_reports(seen: set[tuple[str, str]] | None = None) -> list[dict[str, Any]]:
    external = Path("~/jin10-reports").expanduser()
    results: list[dict[str, Any]] = []
    seen = seen or set()
    if not external.exists():
        return results
    for date_dir in sorted((d for d in external.iterdir() if d.is_dir()), reverse=True):
        weekly_dir = date_dir / "weekly"
        if not weekly_dir.is_dir():
            continue
        for article_dir in sorted((d for d in weekly_dir.iterdir() if d.is_dir()), reverse=True):
            if (date_dir.name, article_dir.name) in seen:
                continue
            report_md = article_dir / "report.md"
            meta = _read_optional_json(article_dir / "meta.json") or {}
            if not _is_explicit_jin10_weekly(meta):
                continue
            results.append(
                {
                    "type": "jin10_weekly_report",
                    "trade_date": str(meta.get("date") or date_dir.name),
                    "run_id": article_dir.name,
                    "report_id": article_dir.name,
                    "article_id": str(meta.get("id") or article_dir.name),
                    "title": meta.get("title"),
                    "format": "markdown",
                    "available": report_md.exists(),
                }
            )
    return results


def _find_external_jin10_weekly_dir(report_id: str) -> tuple[str, Path] | None:
    external = Path("~/jin10-reports").expanduser()
    if not external.exists():
        return None
    for date_dir in sorted((item for item in external.iterdir() if item.is_dir()), reverse=True):
        run_dir = date_dir / "weekly" / report_id
        meta = _read_optional_json(run_dir / "meta.json") if run_dir.is_dir() else None
        if run_dir.is_dir() and _is_explicit_jin10_weekly(meta or {}):
            return date_dir.name, run_dir
    return None


def _find_external_jin10_meta(date: str, article_id: str) -> dict[str, Any] | None:
    external = Path("~/jin10-reports").expanduser()
    candidates = [
        external / date / "weekly" / article_id / "meta.json",
        external / date / "黄金周报" / article_id / "meta.json",
        external / date / "daily" / article_id / "meta.json",
        external / date / "金银报告" / article_id / "meta.json",
        external / date / "报告" / article_id / "meta.json",
    ]
    for path in candidates:
        meta = _read_optional_json(path)
        if isinstance(meta, dict):
            return meta
    return None


def _is_explicit_jin10_weekly(meta: dict[str, Any]) -> bool:
    category = str(meta.get("category") or "").strip()
    category_code = str(meta.get("category_code") or "").strip()
    title = str(meta.get("title") or "").strip()
    return category_code == "536" or "黄金周报" in category or "黄金周报" in title


def list_reports_index(asset: str = "XAUUSD") -> dict[str, Any]:
    reports: list[dict[str, Any]] = []
    reports.extend(_collect_registered_reports_from_db(asset))
    reports.extend(_collect_reports_from_db("final_report", "markdown", asset) or _collect_reports("final_report", "final_report", "markdown", asset, "final_report.md"))
    reports.extend(_collect_reports_from_db("strategy_card", "json+markdown", asset) or _collect_reports("strategy_card", "strategy_card", "json+markdown", asset))
    reports.extend(_collect_jin10_reports())

    options_base = _PROJECT_ROOT / "storage" / "outputs" / "cme_options"
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
                    }
                )

    options_run_base = _PROJECT_ROOT / "storage" / "outputs" / "cme"
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
                    }
                )

    cme_visual_base = _PROJECT_ROOT / "storage" / "outputs" / "cme"
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
                        }
                    )

    macro_base = _PROJECT_ROOT / "storage" / "outputs" / "macro"
    if macro_base.exists():
        for date_dir in sorted(macro_base.iterdir(), reverse=True):
            if not date_dir.is_dir():
                continue
            runs = [run_dir for run_dir in date_dir.iterdir() if run_dir.is_dir()]
            if runs:
                for run_dir in sorted(runs, reverse=True):
                    snap = run_dir / "macro_snapshot.md"
                    if snap.exists():
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
                            }
                        )
            else:
                snap = date_dir / "macro_snapshot.md"
                if snap.exists():
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
                        }
                    )
    reports = _dedupe_reports_index_items(reports)
    reports.sort(key=lambda x: (x["trade_date"], x.get("run_id") or "", x["type"]), reverse=True)
    return {"asset": asset, "reports": [r for r in reports if r.get("available", False)]}


def _report_index_family(report_type: str) -> str:
    return {
        "final_report": "final_report_markdown",
        "macro_report": "macro_report",
        "strategy_card": "strategy_card",
        "options_report": "options_report_markdown",
        "options_visual_report": "cme_options_visual",
    }.get(report_type, report_type)


def _typed_report_id(report_type: str, raw_id: str) -> str:
    return f"{report_type}:{raw_id}"


def _report_index_title(report_type: str, trade_date: str) -> str:
    return {
        "final_report": f"XAUUSD 综合报告（{trade_date}）",
        "macro_report": f"XAUUSD 宏观数据报告（{trade_date}）",
        "strategy_card": f"XAUUSD 策略卡片（{trade_date}）",
        "options_report": f"黄金期权结构报告（{trade_date}）",
        "options_visual_report": f"黄金期权可视报告（{trade_date}）",
    }.get(report_type, f"{report_type}（{trade_date}）")


def list_unified_dates(asset: str = "XAUUSD") -> dict[str, Any]:
    roots = {
        "snapshot": _PROJECT_ROOT / "storage" / "features" / "snapshots" / asset,
        "final_report": _PROJECT_ROOT / "storage" / "outputs" / "final_report" / asset,
        "strategy_card": _PROJECT_ROOT / "storage" / "outputs" / "strategy_card" / asset,
        "jin10": _PROJECT_ROOT / "storage" / "outputs" / "jin10",
    }
    date_modules: dict[str, set[str]] = defaultdict(set)
    date_latest_run: dict[str, str] = {}

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
                date_latest_run.setdefault(date_dir.name, run_dir.name)
                break

    if roots["final_report"].exists():
        for date_dir in sorted(roots["final_report"].iterdir()):
            if date_dir.is_dir() and any((run_dir / "final_report.md").exists() for run_dir in date_dir.iterdir() if run_dir.is_dir()):
                date_modules[date_dir.name].add("final_report")
                runs = sorted((run_dir for run_dir in date_dir.iterdir() if run_dir.is_dir()), reverse=True)
                if runs:
                    date_latest_run.setdefault(date_dir.name, runs[0].name)

    if roots["strategy_card"].exists():
        for date_dir in sorted(roots["strategy_card"].iterdir()):
            if date_dir.is_dir() and any((run_dir / "strategy_card.json").exists() for run_dir in date_dir.iterdir() if run_dir.is_dir()):
                date_modules[date_dir.name].add("strategy_card")

    cme_base = _PROJECT_ROOT / "storage" / "outputs" / "cme_options"
    if cme_base.exists():
        for date_dir in sorted(cme_base.iterdir()):
            if date_dir.is_dir() and ((date_dir / "options_analysis.json").exists() or (date_dir / "options_analysis.md").exists()):
                date_modules[date_dir.name].add("options")

    macro_base = _PROJECT_ROOT / "storage" / "outputs" / "macro"
    if macro_base.exists():
        for date_dir in sorted(macro_base.iterdir()):
            if not date_dir.is_dir():
                continue
            if (date_dir / "macro_snapshot.md").exists() or any((run_dir / "macro_snapshot.md").exists() for run_dir in date_dir.iterdir() if run_dir.is_dir()):
                date_modules[date_dir.name].add("macro")

    if roots["jin10"].exists():
        for date_dir in sorted(roots["jin10"].iterdir()):
            if not date_dir.is_dir():
                continue
            if any((run_dir / "daily_analysis.html").exists() for run_dir in date_dir.iterdir() if run_dir.is_dir()):
                date_modules[date_dir.name].add("jin10_daily_report")
                runs = sorted((run_dir for run_dir in date_dir.iterdir() if run_dir.is_dir()), reverse=True)
                if runs:
                    date_latest_run.setdefault(date_dir.name, runs[0].name)

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
