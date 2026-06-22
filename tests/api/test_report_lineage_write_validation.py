from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from database.models.analysis import ensure_analysis_tables
from database.models.report import ensure_report_tables


def _make_session_factory() -> sessionmaker:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    ensure_analysis_tables(engine)
    ensure_report_tables(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _seed_snapshot(session: Session, **overrides):
    from database.queries.analysis import upsert_analysis_snapshot

    payload = {
        "snapshot_id": "snap-001",
        "asset": "XAUUSD",
        "trade_date": "2026-05-26",
        "run_id": "run-001",
        "snapshot_time": "2026-05-26T10:00:00+00:00",
        "status": "success",
        "input_snapshot_ids": {},
        "source_refs": [],
        "macro": {"regime": "tightening"},
        "payload": {"snapshot_id": "snap-001"},
    }
    payload.update(overrides)
    return upsert_analysis_snapshot(
        session,
        payload=payload,
        artifact_path="storage/features/2026-05-26/snap-001/analysis_snapshot.json",
    )


def _seed_final_result(session: Session, **overrides):
    from database.queries.analysis import upsert_final_analysis_result

    payload = {
        "asset": "XAUUSD",
        "trade_date": "2026-05-26",
        "run_id": "run-001",
        "snapshot_id": "snap-001",
        "analysis_snapshot_db_id": None,
        "final_bias": "bullish",
        "confidence": 0.81,
        "market_state": "trend_up",
        "scenario_summary": "Structured report",
        "is_trade_instruction": False,
        "input_snapshot_ids": {},
        "source_refs": [],
        "source_agent_outputs": [],
        "risk_points": [],
        "watchlist": [],
        "invalid_conditions": [],
        "strategy_card": None,
        "run_summaries": {},
        "payload": {"final": "report"},
    }
    payload.update(overrides)
    paths = {
        "final_report_path": "storage/outputs/final_report/XAUUSD/2026-05-26/run-001/final_report.md",
        "strategy_card_json_path": None,
        "strategy_card_md_path": None,
        "run_summary_path": "storage/outputs/run/2026-05-26/run-001/step_summaries.json",
        "final_report_sha256": "abc123",
        "strategy_card_sha256": None,
    }
    return upsert_final_analysis_result(session, payload=payload, paths=paths)


def _upsert_report(session: Session, **overrides):
    from database.queries.report import upsert_report_item

    payload = {
        "report_id": "report-std-001",
        "family": "macro",
        "report_type": "daily_macro",
        "title": "Macro Daily Report",
        "asset": "XAUUSD",
        "trade_date": "2026-05-26",
        "run_id": "run-001",
        "snapshot_id": "snap-001",
        "data_status": "live",
        "lifecycle_status": "generated",
        "source_refs": [],
        "metadata": {"template_version": "v1"},
    }
    payload.update(overrides)
    return upsert_report_item(session, payload)


def test_report_write_fails_fast_when_snapshot_run_conflicts() -> None:
    from database.queries.report import upsert_report_item

    factory = _make_session_factory()
    with factory() as session:
        _seed_snapshot(session, snapshot_id="snap-snapshot-conflict", run_id="run-snapshot")

        with pytest.raises(ValueError, match="AnalysisSnapshot"):
            upsert_report_item(
                session,
                {
                    "report_id": "report-conflict-001",
                    "family": "macro",
                    "title": "Macro Daily Report",
                    "asset": "XAUUSD",
                    "trade_date": "2026-05-26",
                    "run_id": "run-report",
                    "snapshot_id": "snap-snapshot-conflict",
                    "data_status": "live",
                    "lifecycle_status": "generated",
                    "source_refs": [],
                },
            )


def test_report_write_fails_fast_when_final_result_conflicts() -> None:
    factory = _make_session_factory()
    with factory() as session:
        _seed_final_result(session, snapshot_id="snap-final-conflict", run_id="run-final")

        with pytest.raises(ValueError, match="FinalAnalysisResult"):
            _upsert_report(
                session,
                run_id="run-final",
                snapshot_id="snap-report",
            )


def test_report_write_accepts_consistent_lineage() -> None:
    factory = _make_session_factory()
    with factory() as session:
        snapshot = _seed_snapshot(session)
        final_result = _seed_final_result(session)

        report = _upsert_report(session)

    assert report.report_id == "report-std-001"
    assert report.run_id == "run-001"
    assert report.snapshot_id == "snap-001"
    assert snapshot.run_id == "run-001"
    assert final_result.snapshot_id == "snap-001"
