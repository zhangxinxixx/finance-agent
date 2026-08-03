from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from apps.runtime.premarket_snapshot_authority import (
    canonicalize_premarket_snapshot_payload,
    resolve_authoritative_premarket_snapshot,
    resolve_gold_daily_report_premarket_snapshot,
    stage_premarket_snapshot_authority,
)
from database.models.analysis import AnalysisBase, AnalysisSnapshot
from database.models.execution import ExecutionBase, RunArtifact
from database.models.task import Base, StepStatus, TaskRun, TaskStatus, TaskStep


def _factory(tmp_path: Path, name: str = "authority.db") -> sessionmaker[Session]:
    engine = create_engine(f"sqlite:///{tmp_path / name}")
    Base.metadata.create_all(engine)
    AnalysisBase.metadata.create_all(engine)
    ExecutionBase.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _snapshot(run_id: str, trade_date: str = "2026-08-11") -> dict:
    return {
        "asset": "XAUUSD",
        "trade_date": trade_date,
        "run_id": run_id,
        "snapshot_id": f"XAUUSD:{trade_date}:{run_id}",
        "input_snapshot_ids": {"macro": f"macro:{trade_date}:{run_id}"},
        "source_refs": [],
        "macro": {"status": "available", "data": {"as_of": trade_date}},
        "options": {"status": "unavailable"},
    }


def _path(root: Path, run_id: str, trade_date: str = "2026-08-11") -> Path:
    return root / "features" / "snapshots" / "XAUUSD" / trade_date / run_id / "premarket_snapshot.json"


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _running_run(session: Session, *, trade_date: str | None = None) -> TaskRun:
    run = TaskRun(
        id=uuid.uuid4(),
        name="premarket",
        task_type="premarket",
        status=TaskStatus.running,
        trade_date=trade_date,
    )
    session.add(run)
    session.flush()
    return run


def _stage_success(session: Session, root: Path, *, trade_date: str = "2026-08-11") -> tuple[TaskRun, dict, Path]:
    run = _running_run(session)
    payload = _snapshot(str(run.id), trade_date)
    path = _path(root, str(run.id), trade_date)
    _write(path, payload)
    stage_premarket_snapshot_authority(
        session,
        run_id=str(run.id),
        snapshot=payload,
        snapshot_path=path,
        storage_root=root,
    )
    run.status = TaskStatus.success
    session.commit()
    return run, payload, path


def _stage_limited_gold_daily_report(
    session: Session,
    root: Path,
    *,
    trade_date: str = "2026-08-11",
) -> tuple[TaskRun, dict, Path, TaskStep]:
    run = _running_run(session)
    payload = _snapshot(str(run.id), trade_date)
    path = _path(root, str(run.id), trade_date)
    _write(path, payload)
    stage_premarket_snapshot_authority(
        session,
        run_id=str(run.id),
        snapshot=payload,
        snapshot_path=path,
        storage_root=root,
    )
    reason_code = "downstream_readiness_not_ready"
    receipt = {
        "schema_version": "gold_daily_report_premarket_authority.v1",
        "authority_scope": "gold_daily_report_only",
        "run_id": str(run.id),
        "snapshot_id": payload["snapshot_id"],
        "trade_date": trade_date,
        "readiness_decision": "block",
        "readiness": "blocked",
        "reason_code": reason_code,
        "can_run_daily_report": True,
        "can_run_full_analysis": False,
        "publish_allowed": False,
        "source_ref": f"monitoring/{trade_date}/downstream_readiness.json",
        "observed_at": f"{trade_date}T01:00:00+00:00",
    }
    step = TaskStep(
        task_run_id=run.id,
        name="strategy_card",
        status=StepStatus.blocked,
        blocked_reason=reason_code,
        output_json=json.dumps(
            {
                "output_mode": "blocked",
                "publish_allowed": False,
                "reason_code": reason_code,
                "gold_daily_report_authority": receipt,
            },
            sort_keys=True,
        ),
    )
    session.add(step)
    run.status = TaskStatus.blocked
    run.error_summary = reason_code
    session.commit()
    return run, payload, path, step


def test_stage_and_commit_links_all_three_authority_tables(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    root = tmp_path / "storage"
    with factory() as session:
        run = _running_run(session)
        payload = _snapshot(str(run.id))
        path = _path(root, str(run.id))
        _write(path, payload)

        row = stage_premarket_snapshot_authority(
            session,
            run_id=str(run.id),
            snapshot=payload,
            snapshot_path=path,
            storage_root=root,
        )
        session.commit()

        artifact = session.scalar(select(RunArtifact))
        saved_run = session.get(TaskRun, run.id)

    assert row.snapshot_id == payload["snapshot_id"]
    assert row.payload == payload
    assert row.artifact_path == str(path)
    assert saved_run is not None and saved_run.trade_date == "2026-08-11"
    assert saved_run.snapshot_id == payload["snapshot_id"]
    assert artifact is not None and artifact.run_id == run.id
    assert artifact.artifact_type == "feature_json"
    assert artifact.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert artifact.artifact_metadata["input_snapshot_ids"]["analysis_snapshot"] == payload["snapshot_id"]


def test_stage_uses_canonical_json_for_integer_strike_keys(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    root = tmp_path / "storage"
    with factory() as session:
        run = _running_run(session)
        payload = _snapshot(str(run.id))
        payload["options"] = {
            "status": "available",
            "data": {
                "calibration": {
                    "wall_map": {4100: {"call_oi": 12}, 4105: {"call_oi": 8}},
                }
            },
        }
        path = _path(root, str(run.id))
        _write(path, payload)

        row = stage_premarket_snapshot_authority(
            session,
            run_id=str(run.id),
            snapshot=payload,
            snapshot_path=path,
            storage_root=root,
        )

    canonical = canonicalize_premarket_snapshot_payload(payload)
    assert row.payload == canonical == json.loads(path.read_text(encoding="utf-8"))
    assert row.payload["options"]["data"]["calibration"]["wall_map"] == {
        "4100": {"call_oi": 12},
        "4105": {"call_oi": 8},
    }


def test_stage_preserves_default_relative_storage_path_without_double_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    factory = _factory(tmp_path)
    monkeypatch.chdir(tmp_path)
    root = Path("storage")
    with factory() as session:
        run = _running_run(session)
        payload = _snapshot(str(run.id))
        path = _path(root, str(run.id))
        _write(path, payload)

        row = stage_premarket_snapshot_authority(
            session,
            run_id=str(run.id),
            snapshot=payload,
            snapshot_path=path,
            storage_root=root,
        )
        artifact = session.scalar(select(RunArtifact))

    expected = f"storage/features/snapshots/XAUUSD/2026-08-11/{run.id}/premarket_snapshot.json"
    assert row.artifact_path == expected
    assert artifact is not None and artifact.file_path == expected


def test_stage_does_not_commit_callers_transaction(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    root = tmp_path / "storage"
    first = factory()
    try:
        run = _running_run(first)
        payload = _snapshot(str(run.id))
        path = _path(root, str(run.id))
        _write(path, payload)
        stage_premarket_snapshot_authority(
            first,
            run_id=str(run.id),
            snapshot=payload,
            snapshot_path=path,
            storage_root=root,
        )

        with factory() as observer:
            assert observer.scalar(select(AnalysisSnapshot)) is None
            assert observer.scalar(select(RunArtifact)) is None
        first.rollback()
        with factory() as observer:
            assert observer.scalar(select(AnalysisSnapshot)) is None
            assert observer.scalar(select(RunArtifact)) is None
    finally:
        first.close()


def test_stage_is_idempotent_without_duplicate_rows(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    root = tmp_path / "storage"
    with factory() as session:
        run = _running_run(session)
        payload = _snapshot(str(run.id))
        path = _path(root, str(run.id))
        _write(path, payload)

        first = stage_premarket_snapshot_authority(
            session, run_id=str(run.id), snapshot=payload, snapshot_path=path, storage_root=root
        )
        second = stage_premarket_snapshot_authority(
            session, run_id=str(run.id), snapshot=payload, snapshot_path=path, storage_root=root
        )

        assert first.id == second.id
        assert len(session.scalars(select(AnalysisSnapshot)).all()) == 1
        assert len(session.scalars(select(RunArtifact)).all()) == 1


@pytest.mark.parametrize("case", ["missing", "pending", "wrong_name", "wrong_type", "invalid_uuid"])
def test_stage_rejects_noncanonical_running_run(tmp_path: Path, case: str) -> None:
    factory = _factory(tmp_path, f"{case}.db")
    root = tmp_path / f"storage-{case}"
    with factory() as session:
        run_id = str(uuid.uuid4())
        if case != "missing" and case != "invalid_uuid":
            run = TaskRun(
                id=uuid.UUID(run_id),
                name="other" if case == "wrong_name" else "premarket",
                task_type="other" if case == "wrong_type" else "premarket",
                status=TaskStatus.pending if case == "pending" else TaskStatus.running,
            )
            session.add(run)
            session.flush()
        if case == "invalid_uuid":
            run_id = "not-a-uuid"
        payload = _snapshot(run_id)
        path = _path(root, run_id)
        _write(path, payload)

        with pytest.raises(ValueError):
            stage_premarket_snapshot_authority(
                session, run_id=run_id, snapshot=payload, snapshot_path=path, storage_root=root
            )


@pytest.mark.parametrize("case", ["asset", "trade_date", "run_id", "snapshot_id", "path", "file_payload"])
def test_stage_rejects_snapshot_identity_path_or_payload_drift(tmp_path: Path, case: str) -> None:
    factory = _factory(tmp_path, f"identity-{case}.db")
    root = tmp_path / f"storage-identity-{case}"
    with factory() as session:
        run = _running_run(session)
        payload = _snapshot(str(run.id))
        path = _path(root, str(run.id))
        if case == "asset":
            payload["asset"] = "DXY"
        elif case == "trade_date":
            payload["trade_date"] = "bad-date"
        elif case == "run_id":
            payload["run_id"] = str(uuid.uuid4())
        elif case == "snapshot_id":
            payload["snapshot_id"] = "wrong"
        supplied_path = path.parent / "other.json" if case == "path" else path
        _write(path, {**payload, "extra": True} if case == "file_payload" else payload)

        with pytest.raises(ValueError):
            stage_premarket_snapshot_authority(
                session,
                run_id=str(run.id),
                snapshot=payload,
                snapshot_path=supplied_path,
                storage_root=root,
            )


def test_stage_rejects_symlink_snapshot(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    root = tmp_path / "storage"
    with factory() as session:
        run = _running_run(session)
        payload = _snapshot(str(run.id))
        real_path = tmp_path / "real.json"
        _write(real_path, payload)
        path = _path(root, str(run.id))
        path.parent.mkdir(parents=True)
        path.symlink_to(real_path)

        with pytest.raises(ValueError, match="symlink"):
            stage_premarket_snapshot_authority(
                session, run_id=str(run.id), snapshot=payload, snapshot_path=path, storage_root=root
            )


def test_stage_rejects_existing_snapshot_authority_conflict(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    root = tmp_path / "storage"
    with factory() as session:
        run = _running_run(session)
        payload = _snapshot(str(run.id))
        path = _path(root, str(run.id))
        _write(path, payload)
        session.add(
            AnalysisSnapshot(
                snapshot_id=payload["snapshot_id"],
                asset="XAUUSD",
                trade_date=__import__("datetime").date(2026, 8, 11),
                run_id=str(run.id),
                status="success",
                input_snapshot_ids={},
                source_refs=[],
                payload={"drift": True},
                payload_sha256="0" * 64,
                artifact_path="features/wrong.json",
            )
        )
        session.flush()

        with pytest.raises(ValueError, match="AnalysisSnapshot authority conflict"):
            stage_premarket_snapshot_authority(
                session, run_id=str(run.id), snapshot=payload, snapshot_path=path, storage_root=root
            )


def test_selector_finds_exact_committed_authority(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    root = tmp_path / "storage"
    with factory() as session:
        run, payload, path = _stage_success(session, root)

        result = resolve_authoritative_premarket_snapshot(session, storage_root=root, trade_date="2026-08-11")

    assert result.status == "found"
    assert result.reason_code == "authoritative_premarket_snapshot_found"
    assert result.snapshot_path == path
    assert result.run_id == str(run.id)
    assert result.snapshot_id == payload["snapshot_id"]


def test_selector_reports_missing_and_excludes_non_success_runs(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    with factory() as session:
        for status in (TaskStatus.blocked, TaskStatus.failed):
            session.add(
                TaskRun(
                    name="premarket",
                    task_type="premarket",
                    trade_date="2026-08-11",
                    status=status,
                )
            )
        session.commit()

        result = resolve_authoritative_premarket_snapshot(
            session, storage_root=tmp_path / "storage", trade_date="2026-08-11"
        )

    assert result.status == "missing"
    assert result.reason_code == "successful_premarket_run_missing"


def test_gold_daily_report_selector_accepts_exact_limited_blocked_authority(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    root = tmp_path / "storage"
    with factory() as session:
        run, payload, path, _step = _stage_limited_gold_daily_report(session, root)

        general = resolve_authoritative_premarket_snapshot(session, storage_root=root, trade_date="2026-08-11")
        result = resolve_gold_daily_report_premarket_snapshot(
            session,
            storage_root=root,
            trade_date="2026-08-11",
        )

    assert general.status == "missing"
    assert result.status == "found"
    assert result.reason_code == "authoritative_gold_daily_report_premarket_snapshot_found"
    assert result.snapshot_path == path
    assert result.run_id == str(run.id)
    assert result.snapshot_id == payload["snapshot_id"]


def test_gold_daily_report_selector_ignores_blocked_run_without_limited_receipt(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    with factory() as session:
        session.add(
            TaskRun(
                name="premarket",
                task_type="premarket",
                trade_date="2026-08-11",
                status=TaskStatus.blocked,
            )
        )
        session.commit()

        result = resolve_gold_daily_report_premarket_snapshot(
            session,
            storage_root=tmp_path / "storage",
            trade_date="2026-08-11",
        )

    assert result.status == "missing"
    assert result.reason_code == "successful_premarket_run_missing"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("snapshot_id", "tampered"),
        ("can_run_daily_report", False),
        ("can_run_full_analysis", True),
        ("publish_allowed", True),
        ("source_ref", "monitoring/wrong/downstream_readiness.json"),
        ("observed_at", "not-a-date"),
    ],
)
def test_gold_daily_report_selector_rejects_tampered_limited_receipt(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    factory = _factory(tmp_path)
    root = tmp_path / "storage"
    with factory() as session:
        run, _payload, _path, step = _stage_limited_gold_daily_report(session, root)
        output = json.loads(step.output_json)
        output["gold_daily_report_authority"][field] = value
        step.output_json = json.dumps(output, sort_keys=True)
        session.commit()

        result = resolve_gold_daily_report_premarket_snapshot(
            session,
            storage_root=root,
            trade_date="2026-08-11",
        )

    assert result.status == "invalid"
    assert result.reason_code == "gold_daily_report_authority_receipt_invalid"
    assert result.run_id == str(run.id)


def test_gold_daily_report_selector_rejects_multiple_limited_runs_as_ambiguous(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    root = tmp_path / "storage"
    with factory() as session:
        _stage_limited_gold_daily_report(session, root)
        _stage_limited_gold_daily_report(session, root)

        result = resolve_gold_daily_report_premarket_snapshot(
            session,
            storage_root=root,
            trade_date="2026-08-11",
        )

    assert result.status == "ambiguous"
    assert result.reason_code == "multiple_gold_daily_report_premarket_runs"


def test_selector_rejects_multiple_successful_runs_as_ambiguous(tmp_path: Path) -> None:
    factory = _factory(tmp_path)
    with factory() as session:
        for _ in range(2):
            session.add(
                TaskRun(
                    name="premarket",
                    task_type="premarket",
                    trade_date="2026-08-11",
                    status=TaskStatus.success,
                )
            )
        session.commit()

        result = resolve_authoritative_premarket_snapshot(
            session, storage_root=tmp_path / "storage", trade_date="2026-08-11"
        )

    assert result.status == "ambiguous"


@pytest.mark.parametrize(
    "drift",
    ["snapshot_path", "snapshot_payload", "snapshot_hash", "artifact_path", "artifact_hash", "file"],
)
def test_selector_rejects_database_or_file_integrity_drift(tmp_path: Path, drift: str) -> None:
    factory = _factory(tmp_path, f"drift-{drift}.db")
    root = tmp_path / f"storage-drift-{drift}"
    with factory() as session:
        _, payload, path = _stage_success(session, root)
        snapshot_row = session.scalar(select(AnalysisSnapshot))
        artifact = session.scalar(select(RunArtifact))
        assert snapshot_row is not None and artifact is not None
        if drift == "snapshot_path":
            snapshot_row.artifact_path = "features/wrong.json"
        elif drift == "snapshot_payload":
            snapshot_row.payload = {**payload, "drift": True}
        elif drift == "snapshot_hash":
            snapshot_row.payload_sha256 = "0" * 64
        elif drift == "artifact_path":
            artifact.file_path = "features/wrong.json"
        elif drift == "artifact_hash":
            artifact.sha256 = "0" * 64
        else:
            _write(path, {**payload, "drift": True})
        session.commit()

        result = resolve_authoritative_premarket_snapshot(session, storage_root=root, trade_date="2026-08-11")

    assert result.status == "invalid"


def test_selector_reports_database_failures_as_unavailable(tmp_path: Path) -> None:
    class BrokenSession:
        def scalars(self, _statement):
            raise RuntimeError("database offline")

    result = resolve_authoritative_premarket_snapshot(
        BrokenSession(),  # type: ignore[arg-type]
        storage_root=tmp_path / "storage",
        trade_date="2026-08-11",
    )

    assert result.status == "unavailable"
    assert result.reason_code == "authority_database_unavailable"


def test_selector_source_has_no_filesystem_recency_fallback() -> None:
    source = Path("apps/runtime/premarket_snapshot_authority.py").read_text(encoding="utf-8")

    assert ".glob(" not in source
    assert "st_mtime" not in source
    assert ".order_by(" not in source
