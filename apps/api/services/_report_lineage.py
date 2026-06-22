from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from apps.api.schemas.common import WarningItem
from apps.api.services._lineage_warnings import build_report_lineage_warnings
from database.models.analysis import AnalysisSnapshot, FinalAnalysisResult


@dataclass(frozen=True)
class ReportLineageContext:
    report_id: str
    report_run_id: str | None
    report_snapshot_id: str | None
    snapshot: AnalysisSnapshot | None
    final_result: FinalAnalysisResult | None
    warnings: list[WarningItem]

    @property
    def resolved_run_id(self) -> str | None:
        if self.snapshot is not None and self.snapshot.run_id:
            return self.snapshot.run_id
        if self.final_result is not None and self.final_result.run_id:
            return self.final_result.run_id
        return self.report_run_id

    @property
    def resolved_snapshot_id(self) -> str | None:
        if self.snapshot is not None and self.snapshot.snapshot_id:
            return self.snapshot.snapshot_id
        if self.final_result is not None and self.final_result.snapshot_id:
            return self.final_result.snapshot_id
        return self.report_snapshot_id


def resolve_report_lineage_context(
    db: Session,
    *,
    report_id: str,
    report_run_id: str | None,
    report_snapshot_id: str | None,
) -> ReportLineageContext:
    snapshot = _find_report_snapshot(
        db,
        report_run_id=report_run_id,
        report_snapshot_id=report_snapshot_id,
    )
    final_result = _find_final_result_for_report(
        db,
        report_id=report_id,
        report_run_id=report_run_id,
        report_snapshot_id=report_snapshot_id,
        snapshot=snapshot,
    )
    warnings = build_report_lineage_warnings(
        report_id=report_id,
        report_run_id=report_run_id,
        report_snapshot_id=report_snapshot_id,
        resolved_run_id=snapshot.run_id if snapshot is not None else None,
        resolved_snapshot_id=snapshot.snapshot_id if snapshot is not None else None,
        final_run_id=final_result.run_id if final_result is not None else None,
        final_snapshot_id=final_result.snapshot_id if final_result is not None else None,
    )
    return ReportLineageContext(
        report_id=report_id,
        report_run_id=report_run_id,
        report_snapshot_id=report_snapshot_id,
        snapshot=snapshot,
        final_result=final_result,
        warnings=warnings,
    )


def _find_report_snapshot(
    db: Session,
    *,
    report_run_id: str | None,
    report_snapshot_id: str | None,
) -> AnalysisSnapshot | None:
    if report_snapshot_id:
        snapshot = db.scalar(select(AnalysisSnapshot).where(AnalysisSnapshot.snapshot_id == report_snapshot_id))
        if snapshot is not None:
            return snapshot
    if report_run_id:
        return db.scalar(
            select(AnalysisSnapshot)
            .where(AnalysisSnapshot.run_id == report_run_id)
            .order_by(AnalysisSnapshot.trade_date.desc(), AnalysisSnapshot.created_at.desc(), AnalysisSnapshot.id.desc())
            .limit(1)
        )
    return None


def _find_final_result_for_report(
    db: Session,
    *,
    report_id: str,
    report_run_id: str | None,
    report_snapshot_id: str | None,
    snapshot: AnalysisSnapshot | None,
) -> FinalAnalysisResult | None:
    if snapshot is not None:
        final_result = db.scalar(
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
        if final_result is not None:
            return final_result
    if report_run_id:
        final_result = db.scalar(
            select(FinalAnalysisResult)
            .where(FinalAnalysisResult.run_id == report_run_id)
            .order_by(FinalAnalysisResult.trade_date.desc(), FinalAnalysisResult.id.desc())
            .limit(1)
        )
        if final_result is not None:
            return final_result
    if report_snapshot_id:
        return db.scalar(
            select(FinalAnalysisResult)
            .where(FinalAnalysisResult.snapshot_id == report_snapshot_id)
            .order_by(FinalAnalysisResult.trade_date.desc(), FinalAnalysisResult.id.desc())
            .limit(1)
        )
    return None
