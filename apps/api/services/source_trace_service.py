from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from apps.api.schemas.common import ArtifactType, DataStatus, WarningItem
from apps.api.schemas.source_trace import ArtifactRef, SnapshotRef, SourceRef, SourceTraceResponse
from apps.api.services._lineage_warnings import merge_warning_items
from apps.api.services._report_lineage import resolve_report_lineage_context
from apps.api.services._storage import _PROJECT_ROOT, _iso
from apps.api.services._trace_refs import coerce_artifact_type, dedupe_artifact_refs, dedupe_source_refs, parse_source_refs
from apps.api.services.artifact_service import get_artifact_detail_response
from database.models.analysis import AgentOutput, AnalysisSnapshot, FinalAnalysisResult
from database.models.report import ReportArtifact, ReportItem


def get_source_trace_by_snapshot_id(db: Session, snapshot_id: str) -> SourceTraceResponse | None:
    snapshot = db.scalar(select(AnalysisSnapshot).where(AnalysisSnapshot.snapshot_id == snapshot_id))
    if snapshot is None:
        return None
    final_result = _find_final_for_snapshot(db, snapshot)
    return _build_source_trace_response(db, snapshot=snapshot, final_result=final_result)


def get_source_trace_by_report_id(db: Session, report_id: str) -> SourceTraceResponse | None:
    report_item = db.get(ReportItem, report_id)
    if report_item is not None:
        lineage = resolve_report_lineage_context(
            db,
            report_id=report_item.report_id,
            report_run_id=report_item.run_id,
            report_snapshot_id=report_item.snapshot_id,
        )
        report_artifacts = _list_report_artifacts(db, report_id)
        return _build_source_trace_response(
            db,
            snapshot=lineage.snapshot,
            final_result=lineage.final_result,
            report_item=report_item,
            report_artifacts=report_artifacts,
            report_lineage_warnings=lineage.warnings,
        )

    snapshot = db.scalar(select(AnalysisSnapshot).where(AnalysisSnapshot.snapshot_id == report_id))
    if snapshot is not None:
        final_result = _find_final_for_snapshot(db, snapshot)
        return _build_source_trace_response(db, snapshot=snapshot, final_result=final_result)

    snapshot = db.scalar(select(AnalysisSnapshot).where(AnalysisSnapshot.run_id == report_id))
    if snapshot is not None:
        final_result = _find_final_for_snapshot(db, snapshot)
        return _build_source_trace_response(db, snapshot=snapshot, final_result=final_result)

    final_result = _find_final_by_report_id(db, report_id)
    if final_result is None:
        return None
    snapshot = _find_snapshot_for_final(db, final_result)
    return _build_source_trace_response(db, snapshot=snapshot, final_result=final_result)


def get_source_trace_by_strategy_card_id(db: Session, strategy_card_id: str) -> SourceTraceResponse | None:
    final_result = _find_final_by_strategy_card_id(db, strategy_card_id)
    if final_result is None:
        return None
    snapshot = _find_snapshot_for_final(db, final_result)
    return _build_source_trace_response(db, snapshot=snapshot, final_result=final_result)


def get_source_trace_by_artifact_id(db: Session, artifact_id: str) -> SourceTraceResponse | None:
    try:
        uuid.UUID(artifact_id)
    except ValueError:
        detail = None
    else:
        detail = get_artifact_detail_response(db, artifact_id)
    if detail is not None:
        detail_input_snapshot_ids = _normalize_snapshot_ids(detail.metadata.get("input_snapshot_ids"))
        trace = get_source_trace_by_snapshot_id(db, detail.snapshot_id) if detail.snapshot_id else None
        if trace is None:
            input_snapshots = _merge_input_snapshot_refs(
                db,
                current=[],
                extra_snapshot_ids=detail_input_snapshot_ids,
                run_id=detail.run_id,
            )
            return SourceTraceResponse(
                run_id=detail.run_id,
                snapshot_id=detail.snapshot_id,
                data_status=DataStatus.partial,
                source_refs=detail.source_refs,
                artifact_refs=detail.artifact_refs,
                warnings=detail.warnings,
                snapshot=_build_detail_snapshot_ref(detail, input_snapshot_ids=detail_input_snapshot_ids),
                input_snapshots=input_snapshots,
                related_artifacts=detail.artifact_refs,
            )

        merged_input_snapshots = _merge_input_snapshot_refs(
            db,
            current=trace.input_snapshots,
            extra_snapshot_ids=detail_input_snapshot_ids,
            run_id=trace.run_id or detail.run_id,
        )
        snapshot_ref = trace.snapshot
        if snapshot_ref is not None and detail_input_snapshot_ids:
            snapshot_ref = snapshot_ref.model_copy(
                update={
                    "input_snapshot_ids": list(
                        dict.fromkeys([*snapshot_ref.input_snapshot_ids, *detail_input_snapshot_ids])
                    )
                }
            )
        return trace.model_copy(
            update={
                "source_refs": dedupe_source_refs([*trace.source_refs, *detail.source_refs]),
                "artifact_refs": dedupe_artifact_refs([*trace.artifact_refs, *detail.artifact_refs]),
                "warnings": merge_warning_items(trace.warnings, detail.warnings),
                "snapshot": snapshot_ref,
                "input_snapshots": merged_input_snapshots,
                "related_artifacts": dedupe_artifact_refs([*trace.related_artifacts, *detail.artifact_refs]),
            }
        )

    report_artifact = db.get(ReportArtifact, artifact_id)
    if report_artifact is None:
        return None

    report_item = db.get(ReportItem, report_artifact.report_id)
    trace = get_source_trace_by_report_id(db, report_artifact.report_id) if report_item is not None else None
    artifact_ref = _build_report_artifacts([report_artifact])[0]
    source_refs = parse_source_refs(report_item.source_refs) if report_item is not None else []
    warnings = merge_warning_items(trace.warnings if trace is not None else [], _missing_file_warnings(report_artifact.file_path))

    if trace is None:
        return SourceTraceResponse(
            run_id=report_item.run_id if report_item is not None else None,
            snapshot_id=report_item.snapshot_id if report_item is not None else None,
            data_status=_map_data_status(report_item.data_status) if report_item is not None and _map_data_status(report_item.data_status) is not None else DataStatus.partial,
            source_refs=source_refs,
            artifact_refs=[artifact_ref],
            related_artifacts=[artifact_ref],
            warnings=warnings,
        )

    return trace.model_copy(
        update={
            "source_refs": dedupe_source_refs([*trace.source_refs, *source_refs]),
            "artifact_refs": dedupe_artifact_refs([*trace.artifact_refs, artifact_ref]),
            "related_artifacts": dedupe_artifact_refs([*trace.related_artifacts, artifact_ref]),
            "warnings": warnings,
        }
    )


def _find_final_for_snapshot(db: Session, snapshot: AnalysisSnapshot) -> FinalAnalysisResult | None:
    return db.scalar(
        select(FinalAnalysisResult)
        .where(
            or_(
                FinalAnalysisResult.snapshot_id == snapshot.snapshot_id,
                FinalAnalysisResult.run_id == snapshot.run_id,
            )
        )
        .order_by(FinalAnalysisResult.trade_date.desc(), FinalAnalysisResult.id.desc())
        .limit(1)
    )


def _missing_file_warnings(file_path: str) -> list[WarningItem]:
    path = Path(file_path)
    resolved = path if path.is_absolute() else _PROJECT_ROOT / path
    if resolved.is_file():
        return []
    return [
        WarningItem(
            code="artifact-missing-file",
            message=f"Registered artifact file is missing: {file_path}",
            field=file_path,
        )
    ]


def _find_snapshot_for_final(db: Session, final_result: FinalAnalysisResult) -> AnalysisSnapshot | None:
    if final_result.snapshot_id:
        snapshot = db.scalar(select(AnalysisSnapshot).where(AnalysisSnapshot.snapshot_id == final_result.snapshot_id))
        if snapshot is not None:
            return snapshot
    return db.scalar(
        select(AnalysisSnapshot)
        .where(AnalysisSnapshot.run_id == final_result.run_id)
        .order_by(AnalysisSnapshot.trade_date.desc(), AnalysisSnapshot.id.desc())
        .limit(1)
    )


def _find_final_by_report_id(db: Session, report_id: str) -> FinalAnalysisResult | None:
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
        if report_id in _report_candidate_ids(row):
            return row
    return None


def _find_final_by_strategy_card_id(db: Session, strategy_card_id: str) -> FinalAnalysisResult | None:
    direct = db.scalar(
        select(FinalAnalysisResult)
        .where(
            or_(
                FinalAnalysisResult.run_id == strategy_card_id,
                FinalAnalysisResult.snapshot_id == strategy_card_id,
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
        if strategy_card_id in _strategy_candidate_ids(row):
            return row
    return None


def _report_candidate_ids(row: FinalAnalysisResult) -> set[str]:
    ids = {row.run_id}
    if row.snapshot_id:
        ids.add(row.snapshot_id)
    for path in (row.final_report_path, _structured_report_path(row.final_report_path), row.run_summary_path):
        if not path:
            continue
        ids.update(_path_candidate_ids(path))
    return ids


def _strategy_candidate_ids(row: FinalAnalysisResult) -> set[str]:
    ids = {row.run_id}
    if row.snapshot_id:
        ids.add(row.snapshot_id)
    strategy_card_id = row.strategy_card.get("strategy_card_id") if isinstance(row.strategy_card, dict) else None
    if strategy_card_id:
        ids.add(str(strategy_card_id))
    for path in (row.strategy_card_json_path, row.strategy_card_md_path):
        if not path:
            continue
        ids.update(_path_candidate_ids(path))
    return ids


def _path_candidate_ids(raw_path: str) -> set[str]:
    ids = {raw_path}
    path = Path(raw_path)
    ids.add(path.name)
    if path.parent.name:
        ids.add(path.parent.name)
    if path.stem and path.stem not in {"final_report", "strategy_card", "structured_report", "step_summaries"}:
        ids.add(path.stem)
    return ids


def _build_source_trace_response(
    db: Session,
    *,
    snapshot: AnalysisSnapshot | None,
    final_result: FinalAnalysisResult | None,
    report_item: ReportItem | None = None,
    report_artifacts: list[ReportArtifact] | None = None,
    report_lineage_warnings: list | None = None,
) -> SourceTraceResponse:
    snapshot_id = (
        snapshot.snapshot_id
        if snapshot is not None
        else final_result.snapshot_id
        if final_result
        else report_item.snapshot_id
        if report_item
        else None
    )
    run_id = (
        snapshot.run_id
        if snapshot is not None
        else final_result.run_id
        if final_result
        else report_item.run_id
        if report_item
        else None
    )
    input_snapshot_ids = _normalize_snapshot_ids(
        snapshot.input_snapshot_ids
        if snapshot is not None
        else final_result.input_snapshot_ids
        if final_result
        else {}
    )
    input_snapshots = [_build_input_snapshot_ref(db, item_id, run_id=run_id) for item_id in input_snapshot_ids]

    snapshot_ref = _build_snapshot_ref(snapshot, final_result=final_result, input_snapshot_ids=input_snapshot_ids)
    agent_outputs = _list_agent_outputs(db, snapshot_id)
    source_refs = dedupe_source_refs(
        [
            *parse_source_refs(snapshot.source_refs if snapshot is not None else []),
            *parse_source_refs(final_result.source_refs if final_result is not None else []),
            *parse_source_refs(report_item.source_refs if report_item is not None else []),
            *[
                source
                for agent_output in agent_outputs
                for source in parse_source_refs(agent_output.source_refs)
            ],
        ]
    )

    snapshot_artifacts = _build_snapshot_artifacts(snapshot)
    related_artifacts = _build_final_result_artifacts(final_result)
    report_artifact_refs = _build_report_artifacts(report_artifacts or [])
    artifact_refs = dedupe_artifact_refs([*snapshot_artifacts, *related_artifacts, *report_artifact_refs])
    related_artifacts = dedupe_artifact_refs([*related_artifacts, *report_artifact_refs])

    data_status = _derive_data_status(
        snapshot=snapshot,
        final_result=final_result,
        report_item=report_item,
        artifact_refs=artifact_refs,
        source_refs=source_refs,
    )
    warnings = report_lineage_warnings or []

    return SourceTraceResponse(
        run_id=run_id,
        snapshot_id=snapshot_id,
        data_status=data_status,
        source_refs=source_refs,
        artifact_refs=artifact_refs,
        warnings=warnings,
        snapshot=snapshot_ref,
        input_snapshots=input_snapshots,
        related_artifacts=related_artifacts,
    )


def _build_snapshot_ref(
    snapshot: AnalysisSnapshot | None,
    *,
    final_result: FinalAnalysisResult | None,
    input_snapshot_ids: list[str],
) -> SnapshotRef | None:
    if snapshot is not None:
        return SnapshotRef(
            snapshot_id=snapshot.snapshot_id,
            snapshot_type="analysis",
            data_date=_iso(snapshot.trade_date),
            run_id=snapshot.run_id,
            data_status=_map_data_status(snapshot.status) or DataStatus.live,
            created_at=snapshot.created_at,
            input_snapshot_ids=input_snapshot_ids,
        )
    if final_result is None or not final_result.snapshot_id:
        return None
    return SnapshotRef(
        snapshot_id=final_result.snapshot_id,
        snapshot_type="analysis",
        data_date=_iso(final_result.trade_date),
        run_id=final_result.run_id,
        data_status=DataStatus.partial,
        input_snapshot_ids=input_snapshot_ids,
    )


def _build_input_snapshot_ref(db: Session, snapshot_id: str, *, run_id: str | None) -> SnapshotRef:
    snapshot = db.scalar(select(AnalysisSnapshot).where(AnalysisSnapshot.snapshot_id == snapshot_id))
    if snapshot is not None:
        return SnapshotRef(
            snapshot_id=snapshot.snapshot_id,
            snapshot_type="analysis",
            data_date=_iso(snapshot.trade_date),
            run_id=snapshot.run_id,
            data_status=_map_data_status(snapshot.status) or DataStatus.live,
            created_at=snapshot.created_at,
            input_snapshot_ids=_normalize_snapshot_ids(snapshot.input_snapshot_ids),
        )
    return SnapshotRef(
        snapshot_id=snapshot_id,
        snapshot_type="input",
        run_id=run_id,
        data_status=DataStatus.partial,
    )


def _merge_input_snapshot_refs(
    db: Session,
    *,
    current: list[SnapshotRef],
    extra_snapshot_ids: list[str],
    run_id: str | None,
) -> list[SnapshotRef]:
    merged: list[SnapshotRef] = list(current)
    seen = {item.snapshot_id for item in merged}
    for snapshot_id in extra_snapshot_ids:
        if snapshot_id in seen:
            continue
        merged.append(_build_input_snapshot_ref(db, snapshot_id, run_id=run_id))
        seen.add(snapshot_id)
    return merged


def _build_detail_snapshot_ref(detail: Any, *, input_snapshot_ids: list[str]) -> SnapshotRef | None:
    if not detail.snapshot_id:
        return None
    return SnapshotRef(
        snapshot_id=detail.snapshot_id,
        snapshot_type="analysis",
        run_id=detail.run_id,
        data_status=DataStatus.partial,
        input_snapshot_ids=input_snapshot_ids,
    )


def _build_snapshot_artifacts(snapshot: AnalysisSnapshot | None) -> list[ArtifactRef]:
    if snapshot is None:
        return []
    return [
        ArtifactRef(
            artifact_id=f"{snapshot.snapshot_id}:snapshot",
            artifact_type=ArtifactType.feature_json,
            file_path=snapshot.artifact_path,
            generated_at=snapshot.created_at,
            sha256=snapshot.payload_sha256,
        )
    ]


def _build_report_artifacts(report_artifacts: list[ReportArtifact]) -> list[ArtifactRef]:
    refs: list[ArtifactRef] = []
    for artifact in report_artifacts:
        refs.append(
            ArtifactRef(
                artifact_id=artifact.artifact_id,
                artifact_type=coerce_artifact_type(artifact.artifact_type, artifact.file_path),
                file_path=artifact.file_path,
                version=artifact.version,
                generated_at=artifact.generated_at or artifact.updated_at or artifact.created_at,
                sha256=artifact.sha256,
            )
        )
    return dedupe_artifact_refs(refs)


def _build_final_result_artifacts(final_result: FinalAnalysisResult | None) -> list[ArtifactRef]:
    if final_result is None:
        return []
    refs: list[ArtifactRef] = []
    path_specs = [
        ("final_report", ArtifactType.analysis_md, final_result.final_report_path, final_result.final_report_sha256),
        (
            "structured_report",
            ArtifactType.structured_json,
            _structured_report_path(final_result.final_report_path),
            None,
        ),
        (
            "strategy_card_json",
            ArtifactType.structured_json,
            final_result.strategy_card_json_path,
            final_result.strategy_card_sha256,
        ),
        ("strategy_card_md", ArtifactType.analysis_md, final_result.strategy_card_md_path, None),
        ("run_summary", ArtifactType.structured_json, final_result.run_summary_path, None),
    ]
    for suffix, artifact_type, file_path, sha256 in path_specs:
        if not file_path:
            continue
        refs.append(
            ArtifactRef(
                artifact_id=f"{final_result.run_id}:{suffix}",
                artifact_type=artifact_type,
                file_path=file_path,
                generated_at=final_result.updated_at or final_result.created_at,
                sha256=sha256,
            )
        )
    return dedupe_artifact_refs(refs)


def _structured_report_path(final_report_path: str | None) -> str | None:
    if not final_report_path:
        return None
    return str(Path(final_report_path).with_name("structured_report.json"))


def _derive_data_status(
    *,
    snapshot: AnalysisSnapshot | None,
    final_result: FinalAnalysisResult | None,
    report_item: ReportItem | None,
    artifact_refs: list[ArtifactRef],
    source_refs: list[SourceRef],
) -> DataStatus:
    status = DataStatus.live
    for candidate in (
        _map_data_status(snapshot.status) if snapshot is not None else None,
        _map_data_status(final_result.payload.get("data_status")) if final_result is not None else None,
        _map_data_status(report_item.data_status) if report_item is not None else None,
    ):
        if candidate is not None:
            status = candidate
            break

    if snapshot is None or not source_refs:
        status = DataStatus.partial if status == DataStatus.live else status

    if any(not (_PROJECT_ROOT / artifact.file_path).exists() for artifact in artifact_refs):
        status = DataStatus.partial if status == DataStatus.live else status

    return status


def _list_report_artifacts(db: Session, report_id: str) -> list[ReportArtifact]:
    return list(
        db.scalars(
            select(ReportArtifact)
            .where(ReportArtifact.report_id == report_id)
            .order_by(ReportArtifact.is_primary.desc(), ReportArtifact.generated_at.desc(), ReportArtifact.artifact_id.asc())
        )
    )


def _map_data_status(raw_status: Any) -> DataStatus | None:
    if raw_status is None:
        return None
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
    return None


def _list_agent_outputs(db: Session, snapshot_id: str | None) -> list[AgentOutput]:
    if not snapshot_id:
        return []
    return list(
        db.scalars(
            select(AgentOutput)
            .where(AgentOutput.snapshot_id == snapshot_id)
            .order_by(AgentOutput.agent_name.asc(), AgentOutput.created_at.asc())
        )
    )


def _normalize_snapshot_ids(payload: Any) -> list[str]:
    if isinstance(payload, dict):
        candidates = payload.values()
    elif isinstance(payload, list):
        candidates = payload
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
