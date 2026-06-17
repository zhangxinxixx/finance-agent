from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from apps.api.schemas.common import ArtifactType, DataStatus
from apps.api.schemas.source_trace import ArtifactRef, SnapshotRef, SourceRef, SourceTraceResponse
from apps.api.services._storage import _PROJECT_ROOT, _iso
from database.models.analysis import AgentOutput, AnalysisSnapshot, FinalAnalysisResult


def get_source_trace_by_snapshot_id(db: Session, snapshot_id: str) -> SourceTraceResponse | None:
    snapshot = db.scalar(select(AnalysisSnapshot).where(AnalysisSnapshot.snapshot_id == snapshot_id))
    if snapshot is None:
        return None
    final_result = _find_final_for_snapshot(db, snapshot)
    return _build_source_trace_response(db, snapshot=snapshot, final_result=final_result)


def get_source_trace_by_report_id(db: Session, report_id: str) -> SourceTraceResponse | None:
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
) -> SourceTraceResponse:
    snapshot_id = snapshot.snapshot_id if snapshot is not None else final_result.snapshot_id if final_result else None
    run_id = snapshot.run_id if snapshot is not None else final_result.run_id if final_result else None
    input_snapshot_ids = _normalize_snapshot_ids(
        snapshot.input_snapshot_ids if snapshot is not None else final_result.input_snapshot_ids if final_result else {}
    )
    input_snapshots = [_build_input_snapshot_ref(db, item_id, run_id=run_id) for item_id in input_snapshot_ids]

    snapshot_ref = _build_snapshot_ref(snapshot, final_result=final_result, input_snapshot_ids=input_snapshot_ids)
    agent_outputs = _list_agent_outputs(db, snapshot_id)
    source_refs = _dedupe_sources(
        [
            *_parse_source_refs(snapshot.source_refs if snapshot is not None else []),
            *_parse_source_refs(final_result.source_refs if final_result is not None else []),
            *[
                source
                for agent_output in agent_outputs
                for source in _parse_source_refs(agent_output.source_refs)
            ],
        ]
    )

    snapshot_artifacts = _build_snapshot_artifacts(snapshot)
    related_artifacts = _build_final_result_artifacts(final_result)
    artifact_refs = _dedupe_artifacts([*snapshot_artifacts, *related_artifacts])

    data_status = _derive_data_status(
        snapshot=snapshot,
        final_result=final_result,
        artifact_refs=artifact_refs,
        source_refs=source_refs,
    )

    return SourceTraceResponse(
        run_id=run_id,
        snapshot_id=snapshot_id,
        data_status=data_status,
        source_refs=source_refs,
        artifact_refs=artifact_refs,
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
    return _dedupe_artifacts(refs)


def _structured_report_path(final_report_path: str | None) -> str | None:
    if not final_report_path:
        return None
    return str(Path(final_report_path).with_name("structured_report.json"))


def _derive_data_status(
    *,
    snapshot: AnalysisSnapshot | None,
    final_result: FinalAnalysisResult | None,
    artifact_refs: list[ArtifactRef],
    source_refs: list[SourceRef],
) -> DataStatus:
    status = DataStatus.live
    for candidate in (
        _map_data_status(snapshot.status) if snapshot is not None else None,
        _map_data_status(final_result.payload.get("data_status")) if final_result is not None else None,
    ):
        if candidate is not None:
            status = candidate
            break

    if snapshot is None or not source_refs:
        status = DataStatus.partial if status == DataStatus.live else status

    if any(not (_PROJECT_ROOT / artifact.file_path).exists() for artifact in artifact_refs):
        status = DataStatus.partial if status == DataStatus.live else status

    return status


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


def _parse_source_refs(payload: Any) -> list[SourceRef]:
    if not isinstance(payload, list):
        return []
    refs: list[SourceRef] = []
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            continue
        source_name = str(item.get("source_name") or item.get("source") or item.get("source_id") or f"source-{index}")
        source_id = str(item.get("source_id") or f"{source_name}:{index}")
        source_type = str(item.get("source_type") or item.get("type") or "unknown")
        refs.append(
            SourceRef(
                source_id=source_id,
                source_name=source_name,
                source_type=source_type,
                data_date=item.get("data_date"),
                endpoint=item.get("endpoint"),
                captured_at=item.get("captured_at"),
                file_path=item.get("file_path"),
                sha256=item.get("sha256"),
                url=item.get("url"),
                status=item.get("status"),
            )
        )
    return refs


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


def _dedupe_sources(sources: list[SourceRef]) -> list[SourceRef]:
    seen: set[tuple[str, str]] = set()
    deduped: list[SourceRef] = []
    for source in sources:
        key = (source.source_id, source.source_type)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(source)
    return deduped


def _dedupe_artifacts(artifacts: list[ArtifactRef]) -> list[ArtifactRef]:
    seen: set[tuple[str, str]] = set()
    deduped: list[ArtifactRef] = []
    for artifact in artifacts:
        key = (artifact.file_path, artifact.artifact_type.value)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(artifact)
    return deduped
