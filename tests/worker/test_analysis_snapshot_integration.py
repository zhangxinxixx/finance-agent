from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database.models.task import Base, StepStatus, TaskRun, TaskStatus, TaskStep


def _make_db_session(tmp_path: Path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}", echo=False)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_run_premarket_writes_analysis_snapshot_after_macro_and_options(tmp_path: Path):
    db = _make_db_session(tmp_path)
    task = TaskRun(name="premarket", status=TaskStatus.pending)
    db.add(task)
    db.flush()

    for name in ["macro_collect", "macro_feature", "cme_download", "cme_parse", "cme_ingest", "option_wall", "report_render"]:
        db.add(TaskStep(task_run_id=task.id, name=name, status=StepStatus.pending))
    db.commit()

    def mock_cme_step(step_name, state, **kwargs):
        if step_name == "option_wall":
            state.snapshot_dict = {
                "trade_date": "2026-05-14",
                "data_source": {"input_snapshot_ids": {"raw_file_sha256": "abc123"}},
                "wall_scores": [{"strike": 3300}],
            }
        return {"step": step_name, "status": "success"}

    def mock_macro_step(step_name, state, **kwargs):
        if step_name == "report_render":
            state.snapshot_dict = {
                "as_of": "2026-05-14",
                "source_refs": [{"symbol": "DGS10", "source": "fred"}],
            }
        return {"step": step_name, "status": "success"}

    with (
        patch("apps.worker.pipelines.cme.run_cme_step", side_effect=mock_cme_step),
        patch("apps.worker.pipelines.macro.run_macro_step", side_effect=mock_macro_step),
    ):
        from apps.worker.runner import run_premarket

        result = run_premarket(db, task.id, storage_root=tmp_path)

    assert result == TaskStatus.success
    snapshot_path = (
        tmp_path
        / "features"
        / "snapshots"
        / "XAUUSD"
        / "2026-05-14"
        / str(task.id)
        / "premarket_snapshot.json"
    )
    assert snapshot_path.exists()
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert snapshot["snapshot_id"] == f"XAUUSD:2026-05-14:{task.id}"
    assert snapshot["macro"]["status"] == "available"
    assert snapshot["options"]["status"] == "available"
    assert snapshot["positioning"]["status"] == "unavailable"
    assert snapshot["input_snapshot_ids"]["options_detail"] == {"raw_file_sha256": "abc123"}


def test_run_premarket_includes_cme_source_refs(tmp_path: Path):
    db = _make_db_session(tmp_path)
    task = TaskRun(name="premarket", status=TaskStatus.pending)
    db.add(task)
    db.flush()

    for name in ["cme_download", "cme_parse", "cme_ingest", "option_wall"]:
        db.add(TaskStep(task_run_id=task.id, name=name, status=StepStatus.pending))
    db.commit()

    class RawFile:
        source_url = "https://cme.example/bulletin.pdf"
        raw_path = "storage/raw/cme/bulletin.pdf"
        sha256 = "abc123"
        report_date = "2026-05-14"

    class ParseResult:
        trade_date = "2026-05-14"
        status = "PRELIMINARY"

    def mock_cme_step(step_name, state, **kwargs):
        state.raw_file = RawFile()
        state.parse_result = ParseResult()
        if step_name == "option_wall":
            state.snapshot_dict = {
                "trade_date": "2026-05-14",
                "data_source": {"input_snapshot_ids": {"raw_file_sha256": "abc123"}},
            }
        return {"step": step_name, "status": "success"}

    with patch("apps.worker.pipelines.cme.run_cme_step", side_effect=mock_cme_step):
        from apps.worker.runner import run_premarket

        result = run_premarket(db, task.id, storage_root=tmp_path)

    assert result == TaskStatus.success
    snapshot_path = (
        tmp_path
        / "features"
        / "snapshots"
        / "XAUUSD"
        / "2026-05-14"
        / str(task.id)
        / "premarket_snapshot.json"
    )
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert {ref["source"] for ref in snapshot["source_refs"]} >= {"cme_daily_bulletin", "cme_pg64_parse"}


def test_run_premarket_marks_partial_success_when_analysis_snapshot_write_fails(tmp_path: Path):
    db = _make_db_session(tmp_path)
    task = TaskRun(name="premarket", status=TaskStatus.pending)
    db.add(task)
    db.flush()

    for name in ["macro_collect", "macro_feature", "report_render"]:
        db.add(TaskStep(task_run_id=task.id, name=name, status=StepStatus.pending))
    db.commit()

    def mock_macro_step(step_name, state, **kwargs):
        if step_name == "report_render":
            state.snapshot_dict = {"as_of": "2026-05-14"}
        return {"step": step_name, "status": "success"}

    with (
        patch("apps.worker.pipelines.macro.run_macro_step", side_effect=mock_macro_step),
        patch("apps.worker.runner.write_analysis_snapshot", side_effect=RuntimeError("disk full")),
    ):
        from apps.worker.runner import run_premarket

        result = run_premarket(db, task.id, storage_root=tmp_path)

    assert result == TaskStatus.partial_success
    db.refresh(task)
    assert task.status == TaskStatus.partial_success
