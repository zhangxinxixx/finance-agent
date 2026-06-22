"""TDD: Source trace read-only API routes for Phase 3."""

from __future__ import annotations

import json

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from database.models.execution import RunArtifact, ensure_execution_tables
from database.models.report import ensure_report_tables
from database.models.task import StepStatus, TaskRun, TaskStatus, TaskStep, ensure_task_tables
from database.models.analysis import ensure_analysis_tables


def _make_session_factory() -> sessionmaker:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    ensure_analysis_tables(engine)
    ensure_task_tables(engine)
    ensure_execution_tables(engine)
    ensure_report_tables(engine)
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


def _seed_task_run(session: Session, **overrides) -> TaskRun:
    run = TaskRun(
        name="premarket",
        task_type="premarket",
        workspace_id="workspace-001",
        status=TaskStatus.success,
        current_stage="analysis",
        progress=1.0,
        snapshot_id="snap-001",
        final_result_id="run-001",
        trade_date="2026-05-26",
    )
    for key, value in overrides.items():
        setattr(run, key, value)
    session.add(run)
    session.flush()
    return run


def _seed_standard_report(session: Session, **overrides) -> None:
    from database.queries.report import upsert_report_artifact, upsert_report_item

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
        "source_refs": [
            {
                "source_id": "src-report-001",
                "source_name": "Report Feed",
                "source_type": "api",
                "status": "available",
            }
        ],
    }
    payload.update(overrides)
    upsert_report_item(session, payload)
    for suffix, artifact_type, name in (
        ("source", "source_md", "source.md"),
        ("analysis", "analysis_md", "analysis.md"),
        ("structured", "structured_json", "report_structured.json"),
    ):
        upsert_report_artifact(
            session,
            {
                "artifact_id": f"report-std-001:{suffix}",
                "report_id": payload["report_id"],
                "artifact_type": artifact_type,
                "file_path": f"storage/outputs/reports/2026-05-26/{payload['report_id']}/{name}",
                "version": "1",
                "status": "generated",
                "content_type": "text/markdown" if name.endswith(".md") else "application/json",
                "is_primary": suffix == "source",
            },
        )


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


def test_get_source_trace_by_report_resolves_standard_report_item_lineage() -> None:
    from apps.api.main import api_source_trace_by_report

    factory = _make_session_factory()
    with factory() as session:
        _seed_snapshot(session)
        _seed_standard_report(session)
        session.commit()

    with factory() as db:
        payload = api_source_trace_by_report("report-std-001", db=db).model_dump(mode="json")

    assert payload["run_id"] == "run-001"
    assert payload["snapshot_id"] == "snap-001"
    assert payload["snapshot"]["snapshot_id"] == "snap-001"
    assert {item["source_id"] for item in payload["source_refs"]} == {"src-cme-001", "src-report-001"}
    artifact_paths = {item["file_path"] for item in payload["artifact_refs"]}
    assert "storage/features/snapshots/XAUUSD/2026-05-26/run-001/premarket_snapshot.json" in artifact_paths
    assert "storage/outputs/reports/2026-05-26/report-std-001/source.md" in artifact_paths
    assert "storage/outputs/reports/2026-05-26/report-std-001/report_structured.json" in artifact_paths
    assert payload["data_status"] == "partial"
    assert payload["warnings"] == []


def test_get_source_trace_by_report_warns_when_report_declared_snapshot_drifted() -> None:
    from apps.api.main import api_source_trace_by_report
    from database.models.report import ReportItem

    factory = _make_session_factory()
    with factory() as session:
        _seed_snapshot(session)
        _seed_standard_report(session)
        report_item = session.get(ReportItem, "report-std-001")
        assert report_item is not None
        report_item.snapshot_id = "snap-declared-999"
        session.commit()

    with factory() as db:
        payload = api_source_trace_by_report("report-std-001", db=db).model_dump(mode="json")

    warning_codes = {item["code"] for item in payload["warnings"]}
    assert "report-lineage-snapshot-mismatch" in warning_codes
    assert payload["snapshot_id"] == "snap-001"
    assert payload["snapshot"]["snapshot_id"] == "snap-001"


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


def test_get_source_trace_by_artifact_bridges_registry_artifact_to_snapshot_trace() -> None:
    from apps.api.main import api_source_trace_by_artifact

    factory = _make_session_factory()
    with factory() as session:
        _seed_snapshot(session)
        _seed_final_result(session)
        run = _seed_task_run(session)
        step = TaskStep(
            task_run_id=run.id,
            name="macro_collect",
            stage="collector",
            task_kind="collector",
            status=StepStatus.success,
            source_refs=json.dumps(
                [
                    {
                        "source_id": "src-001",
                        "source_name": "FRED",
                        "source_type": "api",
                    }
                ]
            ),
        )
        session.add(step)
        session.flush()
        session.add(
            RunArtifact(
                run_id=run.id,
                task_id=step.id,
                artifact_type="feature_json",
                file_path="storage/features/macro/2026-05-26/run-001/rollup.json",
                sha256="sha-rollup-001",
                source_refs=json.dumps(
                    [
                        {
                            "source_id": "src-registry-001",
                            "source_name": "FRED",
                            "source_type": "api",
                        }
                    ]
                ),
                metadata_json=json.dumps(
                    {
                        "snapshot_id": "snap-001",
                        "input_snapshot_ids": {
                            "macro": "snap-macro-001",
                            "options": "snap-options-001",
                            "extra": "snap-extra-001",
                        },
                    }
                ),
            )
        )
        session.commit()
        artifact_id = str(session.query(RunArtifact).one().artifact_id)

    with factory() as db:
        payload = api_source_trace_by_artifact(artifact_id, db=db).model_dump(mode="json")

    assert payload["run_id"] == "run-001"
    assert payload["snapshot_id"] == "snap-001"
    artifact_paths = {item["file_path"] for item in payload["artifact_refs"]}
    assert "storage/features/macro/2026-05-26/run-001/rollup.json" in artifact_paths
    assert {item["source_id"] for item in payload["source_refs"]} == {
        "src-cme-001",
        "src-final-001",
        "src-registry-001",
        "src-001",
    }
    assert {item["snapshot_id"] for item in payload["input_snapshots"]} == {
        "snap-macro-001",
        "snap-options-001",
        "snap-extra-001",
    }
    assert payload["snapshot"]["input_snapshot_ids"] == [
        "snap-macro-001",
        "snap-options-001",
        "snap-extra-001",
    ]


def test_run_artifact_round_trips_through_run_detail_artifact_detail_and_source_trace() -> None:
    from apps.api.main import api_artifact_detail, api_run_artifacts, api_run_detail, api_source_trace_by_artifact

    factory = _make_session_factory()
    with factory() as session:
        run = _seed_task_run(session, snapshot_id="snap-e2e-001")
        run_id = str(run.id)
        _seed_snapshot(
            session,
            snapshot_id="snap-e2e-001",
            run_id=run_id,
            input_snapshot_ids={"macro": "snap-macro-001", "options": "snap-options-001"},
        )
        _seed_final_result(session, snapshot_id="snap-e2e-001", run_id=run_id)
        step = TaskStep(
            task_run_id=run.id,
            name="macro_collect",
            stage="collector",
            task_kind="collector",
            status=StepStatus.success,
            source_refs=json.dumps(
                [
                    {
                        "source_id": "src-step-001",
                        "source_name": "Step Source",
                        "source_type": "api",
                    }
                ]
            ),
        )
        session.add(step)
        session.flush()
        row = RunArtifact(
            run_id=run.id,
            task_id=step.id,
            artifact_type="feature_json",
            file_path="storage/features/macro/2026-05-26/e2e/rollup.json",
            sha256="sha-e2e-001",
            source_refs=json.dumps(
                [
                    {
                        "source_id": "src-registry-001",
                        "source_name": "Registry Source",
                        "source_type": "api",
                    }
                ]
            ),
            metadata_json=json.dumps(
                {
                    "artifact_id": "art-e2e-001",
                    "snapshot_id": "snap-e2e-001",
                    "input_snapshot_ids": {
                        "macro": "snap-macro-001",
                        "options": "snap-options-001",
                    },
                }
            ),
        )
        session.add(row)
        session.commit()
        artifact_id = str(row.artifact_id)

    with factory() as db:
        run_detail = api_run_detail(run_id, db=db).model_dump(mode="json")
        run_artifacts = api_run_artifacts(run_id, db=db)
        artifact_detail = api_artifact_detail(artifact_id, db=db).model_dump(mode="json")
        source_trace = api_source_trace_by_artifact(artifact_id, db=db).model_dump(mode="json")

    assert run_detail["run_id"] == run_id
    assert run_detail["snapshot_id"] == "snap-e2e-001"
    assert any(item["artifact_id"] == artifact_id for item in run_detail["artifact_refs"])
    assert [item["artifact_id"] for item in run_artifacts["artifacts"]] == [artifact_id]

    assert artifact_detail["run_id"] == run_id
    assert artifact_detail["snapshot_id"] == "snap-e2e-001"
    assert artifact_detail["artifact"]["artifact_id"] == artifact_id
    assert artifact_detail["warnings"] == []

    assert source_trace["run_id"] == run_id
    assert source_trace["snapshot_id"] == "snap-e2e-001"
    assert source_trace["snapshot"]["snapshot_id"] == "snap-e2e-001"
    assert {item["snapshot_id"] for item in source_trace["input_snapshots"]} == {
        "snap-macro-001",
        "snap-options-001",
    }
    assert {item["source_id"] for item in source_trace["source_refs"]} == {
        "src-cme-001",
        "src-final-001",
        "src-registry-001",
        "src-step-001",
    }
    assert any(item["artifact_id"] == artifact_id for item in source_trace["artifact_refs"])
    assert any(item["artifact_id"] == artifact_id for item in source_trace["related_artifacts"])
    assert source_trace["warnings"] == []


def test_get_source_trace_by_artifact_falls_back_to_registry_metadata_snapshot_id() -> None:
    from apps.api.main import api_source_trace_by_artifact

    factory = _make_session_factory()
    with factory() as session:
        _seed_snapshot(session)
        _seed_final_result(session)
        run = _seed_task_run(session)
        run.snapshot_id = None
        step = TaskStep(
            task_run_id=run.id,
            name="macro_collect",
            stage="collector",
            task_kind="collector",
            status=StepStatus.success,
            source_refs=json.dumps(
                [
                    {
                        "source_id": "src-001",
                        "source_name": "FRED",
                        "source_type": "api",
                    }
                ]
            ),
        )
        session.add(step)
        session.flush()
        session.add(
            RunArtifact(
                run_id=run.id,
                task_id=step.id,
                artifact_type="feature_json",
                file_path="storage/features/macro/2026-05-26/run-001/fallback.json",
                sha256="sha-fallback-001",
                metadata_json=json.dumps(
                    {
                        "artifact_id": "fallback-art-001",
                        "snapshot_id": "snap-001",
                        "input_snapshot_ids": {
                            "macro": "snap-macro-001",
                            "options": "snap-options-001",
                        },
                    }
                ),
            )
        )
        session.commit()
        artifact_id = str(session.query(RunArtifact).order_by(RunArtifact.created_at.desc()).first().artifact_id)

    with factory() as db:
        payload = api_source_trace_by_artifact(artifact_id, db=db).model_dump(mode="json")

    assert payload["run_id"] == "run-001"
    assert payload["snapshot_id"] == "snap-001"
    assert any(item["file_path"] == "storage/features/macro/2026-05-26/run-001/fallback.json" for item in payload["artifact_refs"])
    assert {item["snapshot_id"] for item in payload["input_snapshots"]} == {
        "snap-macro-001",
        "snap-options-001",
    }
    assert payload["snapshot"]["input_snapshot_ids"] == ["snap-macro-001", "snap-options-001"]


def test_get_source_trace_by_artifact_propagates_registry_lineage_warnings() -> None:
    from apps.api.main import api_source_trace_by_artifact

    factory = _make_session_factory()
    with factory() as session:
        _seed_snapshot(session)
        _seed_final_result(session)
        run = _seed_task_run(session)
        step = TaskStep(
            task_run_id=run.id,
            name="macro_collect",
            stage="collector",
            task_kind="collector",
            status=StepStatus.success,
        )
        session.add(step)
        session.flush()
        session.add(
            RunArtifact(
                run_id=run.id,
                task_id=step.id,
                artifact_type="feature_json",
                file_path="storage/features/macro/2026-05-26/run-001/drift.json",
                sha256="sha-drift-001",
                metadata_json=json.dumps(
                    {
                        "snapshot_id": "snap-drift-001",
                        "input_snapshot_ids": {
                            "analysis_snapshot": "snap-drift-001",
                            "coordinator": "snap-drift-001",
                        },
                    }
                ),
            )
        )
        session.commit()
        artifact_id = str(session.query(RunArtifact).order_by(RunArtifact.created_at.desc()).first().artifact_id)

    with factory() as db:
        payload = api_source_trace_by_artifact(artifact_id, db=db).model_dump(mode="json")

    warning_codes = {item["code"] for item in payload["warnings"]}
    assert payload["snapshot_id"] == "snap-001"
    assert "artifact-lineage-snapshot-mismatch" in warning_codes
    assert "artifact-lineage-analysis_snapshot-mismatch" in warning_codes
    assert "artifact-lineage-coordinator-mismatch" in warning_codes


def test_get_source_trace_by_artifact_bridges_standard_report_artifact_to_report_trace() -> None:
    from apps.api.main import api_source_trace_by_artifact

    factory = _make_session_factory()
    with factory() as session:
        _seed_snapshot(session)
        _seed_standard_report(session)
        session.commit()

    with factory() as db:
        payload = api_source_trace_by_artifact("report-std-001:source", db=db).model_dump(mode="json")

    assert payload["run_id"] == "run-001"
    assert payload["snapshot_id"] == "snap-001"
    assert {item["source_id"] for item in payload["source_refs"]} == {"src-cme-001", "src-report-001"}
    artifact_paths = {item["file_path"] for item in payload["artifact_refs"]}
    assert "storage/outputs/reports/2026-05-26/report-std-001/source.md" in artifact_paths
    assert "storage/features/snapshots/XAUUSD/2026-05-26/run-001/premarket_snapshot.json" in artifact_paths


def test_source_trace_missing_snapshot_and_report_return_404() -> None:
    from apps.api.main import api_source_trace_by_artifact, api_source_trace_by_report, api_source_trace_detail

    factory = _make_session_factory()
    with factory() as db:
        with pytest.raises(HTTPException) as snapshot_exc:
            api_source_trace_detail("missing-snapshot", db=db)
    with factory() as db:
        with pytest.raises(HTTPException) as report_exc:
            api_source_trace_by_report("missing-report", db=db)
    with factory() as db:
        with pytest.raises(HTTPException) as artifact_exc:
            api_source_trace_by_artifact("11111111-1111-1111-1111-111111111111", db=db)

    assert snapshot_exc.value.status_code == 404
    assert snapshot_exc.value.detail == "Source trace not found"
    assert report_exc.value.status_code == 404
    assert report_exc.value.detail == "Source trace not found"
    assert artifact_exc.value.status_code == 404
    assert artifact_exc.value.detail == "Source trace not found"
