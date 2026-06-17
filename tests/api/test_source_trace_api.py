"""TDD: Source trace read-only API routes for Phase 3."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from database.models.analysis import ensure_analysis_tables
from database.models.task import ensure_task_tables


def _make_session_factory() -> sessionmaker:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    ensure_analysis_tables(engine)
    ensure_task_tables(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _seed_snapshot(session: Session, **overrides):
    from database.queries.analysis import upsert_analysis_snapshot

    payload = {
        "snapshot_id": "snap-001",
        "asset": "XAUUSD",
        "trade_date": "2026-05-26",
        "run_id": "run-001",
        "snapshot_time": "2026-05-26T08:00:00+00:00",
        "status": "success",
        "input_snapshot_ids": {"macro": "snap-macro-001", "options": "snap-options-001"},
        "source_refs": [
            {
                "source_id": "src-cme-001",
                "source_name": "CME Daily Bulletin",
                "source_type": "pdf",
                "data_date": "2026-05-26",
                "file_path": "storage/raw/cme/2026-05-26/bulletin.pdf",
                "status": "available",
            }
        ],
        "macro": {"summary": "macro ok"},
        "options": {"summary": "options ok"},
        "payload": {"summary": "premarket snapshot"},
    }
    payload.update(overrides)
    return upsert_analysis_snapshot(
        session,
        payload=payload,
        artifact_path="storage/features/snapshots/XAUUSD/2026-05-26/run-001/premarket_snapshot.json",
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
        "confidence": 0.82,
        "market_state": "trend_up",
        "scenario_summary": "Gold remains supported",
        "is_trade_instruction": False,
        "input_snapshot_ids": {"analysis": "snap-001"},
        "source_refs": [
            {
                "source_id": "src-final-001",
                "source_name": "Coordinator",
                "source_type": "agent_output",
                "status": "generated",
            }
        ],
        "source_agent_outputs": ["macro", "options"],
        "risk_points": ["usd rebound"],
        "watchlist": ["3360"],
        "invalid_conditions": ["drop below 3320"],
        "strategy_card": {"strategy_card_id": "run-001", "symbol": "XAUUSD", "bias": "bullish"},
        "run_summaries": {"renderer": "done"},
        "payload": {"final": "report"},
    }
    payload.update(overrides)

    paths = {
        "final_report_path": "storage/outputs/final_report/XAUUSD/2026-05-26/run-001/final_report.md",
        "strategy_card_json_path": "storage/outputs/strategy_card/XAUUSD/2026-05-26/run-001/strategy_card.json",
        "strategy_card_md_path": "storage/outputs/strategy_card/XAUUSD/2026-05-26/run-001/strategy_card.md",
        "run_summary_path": "storage/outputs/run/2026-05-26/run-001/step_summaries.json",
        "final_report_sha256": "finalsha",
        "strategy_card_sha256": "strategysha",
    }
    return upsert_final_analysis_result(session, payload=payload, paths=paths)


def test_get_source_trace_by_snapshot_returns_snapshot_and_refs() -> None:
    from apps.api.main import api_source_trace_detail

    factory = _make_session_factory()
    with factory() as session:
        _seed_snapshot(session)
        session.commit()

    with factory() as db:
        payload = api_source_trace_detail("snap-001", db=db).model_dump(mode="json")
    assert payload["run_id"] == "run-001"
    assert payload["snapshot_id"] == "snap-001"
    assert payload["snapshot"]["snapshot_id"] == "snap-001"
    assert payload["snapshot"]["snapshot_type"] == "analysis"
    assert payload["source_refs"][0]["source_id"] == "src-cme-001"
    assert payload["artifact_refs"][0]["file_path"].endswith("premarket_snapshot.json")
    assert {item["snapshot_id"] for item in payload["input_snapshots"]} == {
        "snap-macro-001",
        "snap-options-001",
    }


def test_get_source_trace_by_report_resolves_final_result_and_synthesized_artifacts() -> None:
    from apps.api.main import api_source_trace_by_report

    factory = _make_session_factory()
    with factory() as session:
        _seed_snapshot(session)
        _seed_final_result(session)
        session.commit()

    with factory() as db:
        payload = api_source_trace_by_report("run-001", db=db).model_dump(mode="json")
    assert payload["run_id"] == "run-001"
    assert payload["snapshot_id"] == "snap-001"
    artifact_paths = {item["file_path"] for item in payload["artifact_refs"]}
    assert "storage/outputs/final_report/XAUUSD/2026-05-26/run-001/final_report.md" in artifact_paths
    assert "storage/outputs/final_report/XAUUSD/2026-05-26/run-001/structured_report.json" in artifact_paths
    assert "storage/outputs/run/2026-05-26/run-001/step_summaries.json" in artifact_paths
    assert payload["data_status"] == "partial"


def test_get_source_trace_by_strategy_resolves_run_trace() -> None:
    from apps.api.main import api_source_trace_by_strategy

    factory = _make_session_factory()
    with factory() as session:
        _seed_snapshot(session)
        _seed_final_result(session)
        session.commit()

    with factory() as db:
        payload = api_source_trace_by_strategy("run-001", db=db).model_dump(mode="json")
    artifact_paths = {item["file_path"] for item in payload["artifact_refs"]}
    assert "storage/outputs/strategy_card/XAUUSD/2026-05-26/run-001/strategy_card.json" in artifact_paths
    assert "storage/outputs/strategy_card/XAUUSD/2026-05-26/run-001/strategy_card.md" in artifact_paths
    assert payload["snapshot"]["snapshot_id"] == "snap-001"


def test_source_trace_missing_snapshot_and_report_return_404() -> None:
    from apps.api.main import api_source_trace_by_report, api_source_trace_detail

    factory = _make_session_factory()
    with factory() as db:
        with pytest.raises(HTTPException) as snapshot_exc:
            api_source_trace_detail("missing-snapshot", db=db)
    with factory() as db:
        with pytest.raises(HTTPException) as report_exc:
            api_source_trace_by_report("missing-report", db=db)

    assert snapshot_exc.value.status_code == 404
    assert snapshot_exc.value.detail == "Source trace not found"
    assert report_exc.value.status_code == 404
    assert report_exc.value.detail == "Source trace not found"
