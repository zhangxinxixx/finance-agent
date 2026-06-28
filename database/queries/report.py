"""Portable report item / artifact upsert and query helpers."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models.analysis import AnalysisSnapshot, FinalAnalysisResult
from database.models.report import ReportArtifact, ReportItem

_SOURCE_REF_IDENTITY_KEYS = frozenset({"source_id", "source_name", "source", "source_key", "source_ref"})
_SOURCE_REF_TRACE_KEYS = frozenset(
    {
        "article_id",
        "captured_at",
        "data_date",
        "endpoint",
        "file_path",
        "raw_path",
        "ref",
        "report_date",
        "sha256",
        "snapshot_id",
        "source_ref",
        "source_type",
        "source_url",
        "status",
        "symbol",
        "url",
    }
)


def _parse_iso_date(value: str | date | None) -> date | None:
    if value is None or isinstance(value, date):
        return value
    return date.fromisoformat(value)


def _parse_iso_datetime(value: str | datetime | None) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _raise_lineage_conflict(message: str) -> None:
    raise ValueError(message)


def _validate_report_entity_lineage(
    *,
    entity_name: str,
    report_id: str,
    payload: dict[str, Any],
    resolved_snapshot_id: str | None,
    resolved_run_id: str | None,
    resolved_asset: str | None,
    resolved_trade_date: date | None,
) -> None:
    snapshot_id = payload.get("snapshot_id")
    run_id = payload.get("run_id")
    asset = payload.get("asset")
    trade_date = _parse_iso_date(payload.get("trade_date"))

    if snapshot_id and resolved_snapshot_id and resolved_snapshot_id != snapshot_id:
        _raise_lineage_conflict(
            "report lineage conflict: "
            f"report_id={report_id} snapshot_id={snapshot_id} resolves to {entity_name}("
            f"snapshot_id={resolved_snapshot_id}, run_id={resolved_run_id})"
        )
    if run_id and resolved_run_id and resolved_run_id != run_id:
        _raise_lineage_conflict(
            "report lineage conflict: "
            f"report_id={report_id} run_id={run_id} resolves to {entity_name}("
            f"snapshot_id={resolved_snapshot_id}, run_id={resolved_run_id})"
        )
    if asset is not None and resolved_asset is not None and resolved_asset != str(asset):
        _raise_lineage_conflict(
            "report lineage conflict: "
            f"report_id={report_id} asset={asset} resolves to {entity_name}("
            f"snapshot_id={resolved_snapshot_id}, asset={resolved_asset})"
        )
    if trade_date is not None and resolved_trade_date is not None and resolved_trade_date != trade_date:
        _raise_lineage_conflict(
            "report lineage conflict: "
            f"report_id={report_id} trade_date={trade_date.isoformat()} resolves to {entity_name}("
            f"snapshot_id={resolved_snapshot_id}, trade_date={resolved_trade_date.isoformat()})"
        )


def _find_analysis_snapshot_by_payload(session: Session, payload: dict[str, Any]) -> AnalysisSnapshot | None:
    snapshot_id = payload.get("snapshot_id")
    if snapshot_id:
        snapshot = session.scalar(select(AnalysisSnapshot).where(AnalysisSnapshot.snapshot_id == snapshot_id))
        if snapshot is not None:
            return snapshot

    run_id = payload.get("run_id")
    if run_id:
        return session.scalar(
            select(AnalysisSnapshot)
            .where(AnalysisSnapshot.run_id == run_id)
            .order_by(
                AnalysisSnapshot.trade_date.desc(),
                AnalysisSnapshot.snapshot_time.desc().nullslast(),
                AnalysisSnapshot.id.desc(),
            )
            .limit(1)
        )
    return None


def _find_final_result_by_payload(session: Session, payload: dict[str, Any]) -> FinalAnalysisResult | None:
    snapshot_id = payload.get("snapshot_id")
    if snapshot_id:
        final_result = session.scalar(
            select(FinalAnalysisResult)
            .where(FinalAnalysisResult.snapshot_id == snapshot_id)
            .order_by(
                FinalAnalysisResult.trade_date.desc(),
                FinalAnalysisResult.id.desc(),
            )
            .limit(1)
        )
        if final_result is not None:
            return final_result

    run_id = payload.get("run_id")
    if run_id is None:
        return None

    asset = payload.get("asset")
    trade_date = _parse_iso_date(payload.get("trade_date"))
    stmt = select(FinalAnalysisResult).where(FinalAnalysisResult.run_id == run_id)
    if asset is not None and trade_date is not None:
        stmt = stmt.where(FinalAnalysisResult.asset == str(asset), FinalAnalysisResult.trade_date == trade_date)
    return session.scalar(
        stmt.order_by(
            FinalAnalysisResult.trade_date.desc(),
            FinalAnalysisResult.id.desc(),
        ).limit(1)
    )


def _validate_report_lineage(session: Session, payload: dict[str, Any]) -> None:
    report_id = str(payload["report_id"])
    run_id = payload.get("run_id")
    snapshot_id = payload.get("snapshot_id")

    if run_id is None and snapshot_id is None:
        return

    analysis_snapshot = _find_analysis_snapshot_by_payload(session, payload)
    if analysis_snapshot is not None:
        _validate_report_entity_lineage(
            entity_name="AnalysisSnapshot",
            report_id=report_id,
            payload=payload,
            resolved_snapshot_id=analysis_snapshot.snapshot_id,
            resolved_run_id=analysis_snapshot.run_id,
            resolved_asset=analysis_snapshot.asset,
            resolved_trade_date=analysis_snapshot.trade_date,
        )

    final_result = _find_final_result_by_payload(session, payload)
    if final_result is None:
        return

    _validate_report_entity_lineage(
        entity_name="FinalAnalysisResult",
        report_id=report_id,
        payload=payload,
        resolved_snapshot_id=final_result.snapshot_id,
        resolved_run_id=final_result.run_id,
        resolved_asset=final_result.asset,
        resolved_trade_date=final_result.trade_date,
    )


def _validate_report_artifact_parent(session: Session, payload: dict[str, Any], existing: ReportArtifact | None) -> None:
    artifact_id = str(payload["artifact_id"])
    report_id = str(payload["report_id"])
    report_item = session.get(ReportItem, report_id)
    if report_item is None:
        _raise_lineage_conflict(
            "report artifact lineage conflict: "
            f"artifact_id={artifact_id} report_id={report_id} missing parent report"
        )

    if existing is not None and existing.report_id != report_id:
        _raise_lineage_conflict(
            "report artifact lineage conflict: "
            f"artifact_id={artifact_id} report_id={report_id} conflicts with existing report_id={existing.report_id}"
        )


def _first_present_source_ref_key(ref: dict[str, Any], keys: frozenset[str]) -> str | None:
    for key in keys:
        value = ref.get(key)
        if value is not None and str(value).strip():
            return key
    return None


def _validate_report_source_refs(source_refs: list[dict[str, Any]] | None) -> None:
    if source_refs is None:
        return

    for index, ref in enumerate(source_refs):
        if not isinstance(ref, dict):
            raise ValueError(f"report source_refs[{index}] must be an object")

        identity = _first_present_source_ref_key(ref, _SOURCE_REF_IDENTITY_KEYS)
        if identity is None:
            raise ValueError(
                "report source_refs minimum field violation: "
                f"source_refs[{index}] must include one of {sorted(_SOURCE_REF_IDENTITY_KEYS)}"
            )

        trace_key = _first_present_source_ref_key(ref, _SOURCE_REF_TRACE_KEYS)
        if trace_key is None:
            raise ValueError(
                "report source_refs minimum field violation: "
                f"source_refs[{index}] must include one trace/detail field"
            )


def upsert_report_item(session: Session, payload: dict[str, Any]) -> ReportItem:
    report_id = str(payload["report_id"])
    _validate_report_lineage(session, payload)
    _validate_report_source_refs(payload.get("source_refs"))
    existing = session.get(ReportItem, report_id)
    trade_date = _parse_iso_date(payload.get("trade_date"))

    if existing is None:
        existing = ReportItem(report_id=report_id, family=str(payload["family"]), title=str(payload["title"]))
        session.add(existing)

    existing.family = str(payload["family"])
    existing.report_type = payload.get("report_type")
    existing.title = str(payload["title"])
    existing.asset = payload.get("asset")
    existing.trade_date = trade_date
    existing.run_id = payload.get("run_id")
    existing.snapshot_id = payload.get("snapshot_id")
    existing.data_status = str(payload.get("data_status") or "live")
    existing.lifecycle_status = str(payload.get("lifecycle_status") or "generated")
    existing.source_refs = list(payload.get("source_refs") or [])
    existing.report_metadata = dict(payload.get("metadata") or {})
    session.flush()
    return existing


def upsert_report_artifact(session: Session, payload: dict[str, Any]) -> ReportArtifact:
    artifact_id = str(payload["artifact_id"])
    existing = session.get(ReportArtifact, artifact_id)
    _validate_report_artifact_parent(session, payload, existing)
    _validate_report_source_refs(payload.get("source_refs"))
    generated_at = _parse_iso_datetime(payload.get("generated_at"))

    if existing is None:
        existing = ReportArtifact(
            artifact_id=artifact_id,
            report_id=str(payload["report_id"]),
            artifact_type=str(payload["artifact_type"]),
            file_path=str(payload["file_path"]),
        )
        session.add(existing)

    existing.report_id = str(payload["report_id"])
    existing.artifact_type = str(payload["artifact_type"])
    existing.file_path = str(payload["file_path"])
    existing.storage_backend = str(payload.get("storage_backend") or "local_fs")
    existing.version = payload.get("version")
    existing.model_name = payload.get("model_name")
    existing.template_version = payload.get("template_version")
    existing.generated_at = generated_at
    existing.status = str(payload.get("status") or "generated")
    existing.sha256 = payload.get("sha256")
    existing.content_type = payload.get("content_type")
    existing.byte_size = _parse_optional_int(payload.get("byte_size"))
    existing.is_primary = bool(payload.get("is_primary", False))
    existing.source_refs = list(payload.get("source_refs") or [])
    metadata_payload = payload.get("metadata")
    existing.artifact_metadata = dict(metadata_payload or {})
    existing.metadata_text = None if metadata_payload is None else str(metadata_payload)
    session.flush()
    return existing


def get_report_detail(session: Session, report_id: str) -> ReportItem | None:
    return session.get(ReportItem, report_id)


def get_report_artifacts(session: Session, report_id: str) -> list[ReportArtifact]:
    return list(
        session.scalars(
            select(ReportArtifact)
            .where(ReportArtifact.report_id == report_id)
            .order_by(
                ReportArtifact.is_primary.desc(),
                ReportArtifact.generated_at.desc().nullslast(),
                ReportArtifact.artifact_id.asc(),
            )
        )
    )


def _parse_optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
