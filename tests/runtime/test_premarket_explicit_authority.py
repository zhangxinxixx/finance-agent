import json
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from apps.runtime.premarket_snapshot_authority import resolve_gold_daily_report_premarket_snapshot
from database.models.execution import RunArtifact
from database.models.task import TaskStatus
from tests.runtime.test_premarket_snapshot_authority import _factory, _stage_limited_gold_daily_report, _stage_success


def test_explicit_run_resolves_multiple_successes_without_changing_default(tmp_path: Path):
    with _factory(tmp_path)() as db:
        run, payload, path = _stage_success(db, tmp_path)
        _stage_success(db, tmp_path)
        assert resolve_gold_daily_report_premarket_snapshot(
            db, storage_root=tmp_path, trade_date="2026-08-11",
        ).status == "ambiguous"
        result = resolve_gold_daily_report_premarket_snapshot(
            db, storage_root=tmp_path, trade_date="2026-08-11", premarket_run_id=str(run.id),
        )
        assert result.status == "found"
        assert result.snapshot_id == payload["snapshot_id"]
        assert result.snapshot_path == path


@pytest.mark.parametrize("case", ["failed", "running", "blocked", "date", "type", "missing", "uuid", "tamper"])
def test_explicit_run_does_not_bypass_input_validation(tmp_path: Path, case: str):
    with _factory(tmp_path)() as db:
        run, payload, path = _stage_success(db, tmp_path)
        selected = str(run.id)
        if case in {"failed", "running", "blocked"}:
            run.status = TaskStatus(case)
        elif case == "date":
            run.trade_date = "2026-08-12"
        elif case == "type":
            run.task_type = "research"
        elif case == "missing":
            selected = str(uuid.uuid4())
        elif case == "uuid":
            selected = "../bad"
        elif case == "tamper":
            payload["macro"] = {"tampered": True}
            path.write_text(json.dumps(payload))
        db.commit()
        result = resolve_gold_daily_report_premarket_snapshot(
            db, storage_root=tmp_path, trade_date="2026-08-11", premarket_run_id=selected,
        )
        assert result.status in {"invalid", "missing"}
        assert result.snapshot_path is None


def test_explicit_limited_run_still_requires_scoped_receipt(tmp_path: Path):
    with _factory(tmp_path)() as db:
        run, _, _, step = _stage_limited_gold_daily_report(db, tmp_path)
        result = resolve_gold_daily_report_premarket_snapshot(
            db, storage_root=tmp_path, trade_date="2026-08-11", premarket_run_id=str(run.id),
        )
        assert result.status == "found"
        step.output_json = "{}"
        db.commit()
        assert resolve_gold_daily_report_premarket_snapshot(
            db, storage_root=tmp_path, trade_date="2026-08-11", premarket_run_id=str(run.id),
        ).status == "invalid"


def test_other_features_do_not_compete_but_duplicate_snapshot_artifacts_do(tmp_path: Path):
    with _factory(tmp_path)() as db:
        run, _, path = _stage_success(db, tmp_path)
        extra = RunArtifact(run_id=run.id, artifact_type="feature_json", file_path=str(tmp_path / "feature_snapshot.v2.json"))
        db.add(extra)
        db.commit()
        assert resolve_gold_daily_report_premarket_snapshot(
            db, storage_root=tmp_path, trade_date="2026-08-11", premarket_run_id=str(run.id),
        ).status == "found"
        extra.file_path = str(path)
        db.commit()
        result = resolve_gold_daily_report_premarket_snapshot(
            db, storage_root=tmp_path, trade_date="2026-08-11", premarket_run_id=str(run.id),
        )
        assert result.reason_code == "run_artifact_not_unique"
        assert len(db.scalars(select(RunArtifact)).all()) == 2
