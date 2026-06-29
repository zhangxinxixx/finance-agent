from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from apps.parsers.macro.models import MacroPoint
from apps.worker.pipelines.macro import MacroPipelineState, run_macro_step
from dagster_finance.ops.macro import MacroConfig, report_render_op
from database.models.execution import RunArtifact, ensure_execution_tables
from database.models.task import TaskRun, TaskStatus, ensure_task_tables


def _make_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    ensure_task_tables(engine)
    ensure_execution_tables(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return factory()


def _macro_state() -> MacroPipelineState:
    state = MacroPipelineState(
        all_points=[
            MacroPoint(
                symbol="DGS10",
                date="2026-05-14",
                value=4.30,
                source="fred",
                source_url="https://fred.stlouisfed.org/series/DGS10",
                retrieved_at="2026-05-14T12:00:00+00:00",
                raw_path="storage/raw/macro/fred/2026-05-14/DGS10.json",
            ),
            MacroPoint(
                symbol="DGS2",
                date="2026-05-14",
                value=4.00,
                source="fred",
                source_url="https://fred.stlouisfed.org/series/DGS2",
                retrieved_at="2026-05-14T12:00:00+00:00",
                raw_path="storage/raw/macro/fred/2026-05-14/DGS2.json",
            ),
            MacroPoint(
                symbol="SOFR",
                date="2026-05-14",
                value=4.40,
                source="fred",
                source_url="https://fred.stlouisfed.org/series/SOFR",
                retrieved_at="2026-05-14T12:00:00+00:00",
                raw_path="storage/raw/macro/fred/2026-05-14/SOFR.json",
            ),
        ],
        as_of="2026-05-14",
        all_source_refs=[
            {
                "source": "fred",
                "symbol": "DGS10",
                "source_url": "https://fred.stlouisfed.org/series/DGS10",
                "raw_path": "storage/raw/macro/fred/2026-05-14/DGS10.json",
            }
        ],
    )
    run_macro_step("macro_feature", state, storage_root=Path("/tmp/unused"))
    return state


def test_report_render_op_registers_macro_artifacts_in_run_artifact_registry(tmp_path) -> None:
    session = _make_session()
    run_id = uuid.uuid4()
    session.add(
        TaskRun(
            id=run_id,
            name="premarket_job",
            task_type="premarket",
            status=TaskStatus.running,
            snapshot_id="macro:2026-05-14",
            trade_date="2026-05-14",
        )
    )
    session.commit()
    context = SimpleNamespace(
        run_id=str(run_id),
        resources=SimpleNamespace(db_session=session),
        log=SimpleNamespace(info=lambda *_args, **_kwargs: None, warning=lambda *_args, **_kwargs: None),
    )

    report_render_op.compute_fn.decorated_fn(
        context,
        _macro_state(),
        MacroConfig(storage_root=str(tmp_path)),
    )

    artifacts = session.query(RunArtifact).order_by(RunArtifact.file_path.asc()).all()
    assert {artifact.artifact_type for artifact in artifacts} == {"analysis_md", "feature_json"}
    assert {artifact.run_id for artifact in artifacts} == {run_id}
    assert all(artifact.source_refs_data for artifact in artifacts)
    assert all(artifact.artifact_metadata["lineage_kind"] in {"derived_artifact", "snapshot_bound"} for artifact in artifacts)
