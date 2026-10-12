from __future__ import annotations

from datetime import UTC, date, datetime
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import sessionmaker

from apps.data_layer import output_retention
from apps.data_layer.output_retention import apply_unqualified_outputs, preview_unqualified_outputs
from database.models.analysis import AgentOutput, AnalysisBase, AnalysisSnapshot, FinalAnalysisResult
from database.models.execution import ExecutionEvent, ExecutionBase, RunArtifact
from database.models.report import ReportArtifact, ReportBase, ReportItem
from database.models.task import Base as TaskBase
from database.models.task import StepStatus, TaskRun, TaskStatus, TaskStep


NOW = datetime(2026, 10, 12, 3, 0, tzinfo=UTC)


def _factory(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'retention.sqlite'}")
    TaskBase.metadata.create_all(engine)
    AnalysisBase.metadata.create_all(engine)
    ReportBase.metadata.create_all(engine)
    ExecutionBase.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _write(
    root: Path,
    run_id: str,
    name: str = "final_report.md",
    content: bytes | None = None,
) -> tuple[Path, str]:
    if content is None:
        content = f"secret body:{run_id}".encode()
    path = root / "outputs" / "final_report" / "XAUUSD" / "2026-10-10" / run_id / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path, _hash(content)


def _seed_run(
    factory,
    root: Path,
    *,
    failed: bool = True,
    agent_status: str = "success",
    report_status: str = "live",
    task_status: TaskStatus = TaskStatus.success,
):
    run_uuid = uuid4()
    run_id = str(run_uuid)
    snapshot_id = f"snapshot:{run_id}"
    path, digest = _write(root, run_id)
    synthesis = {"status": "failed" if failed else "observe", "macro_review": {"status": "pass"}}
    with factory() as session:
        task = TaskRun(
            id=run_uuid,
            name="premarket",
            task_type="premarket",
            status=task_status,
            trade_date="2026-10-10",
            snapshot_id=snapshot_id,
        )
        session.add(task)
        session.flush()
        step = TaskStep(
            task_run_id=run_uuid,
            name="report_render",
            status=StepStatus.success,
            output_ref=str(path),
        )
        session.add(step)
        snapshot = AnalysisSnapshot(
            snapshot_id=snapshot_id,
            asset="XAUUSD",
            trade_date=date(2026, 10, 10),
            run_id=run_id,
            status="success",
            input_snapshot_ids={},
            source_refs=[{"source": "kept"}],
            payload={"snapshot_id": snapshot_id},
            payload_sha256=_hash(b"snapshot"),
            artifact_path=str(root / "features" / "snapshot.json"),
        )
        session.add(snapshot)
        session.flush()
        coordinator_payload = {
            "summary": "directional secret",
            "claims": [{"text": "buy"}],
            "input_payload": {"research_synthesis": synthesis},
        }
        coordinator = AgentOutput(
            id=f"agent-{run_id}",
            snapshot_id=snapshot_id,
            analysis_snapshot_db_id=snapshot.id,
            asset="XAUUSD",
            trade_date=date(2026, 10, 10),
            run_id=run_id,
            agent_name="coordinator_agent",
            module="coordinator",
            version="1.0",
            status=agent_status,
            bias="bullish",
            confidence=0.9,
            input_snapshot_ids={"analysis_snapshot": snapshot_id},
            source_refs=[{"source": "kept"}],
            key_findings=["secret finding"],
            risk_points=["secret risk"],
            watchlist=["secret watch"],
            invalid_conditions=["secret invalid"],
            summary="secret summary",
            payload=coordinator_payload,
            payload_sha256=_hash(json.dumps(coordinator_payload).encode()),
        )
        final_payload = {
            "input_validation": {"can_analyze": True},
            "structured_report": {"body": "secret report"},
            "bias": "bullish",
        }
        final = FinalAnalysisResult(
            id=f"final-{run_id}",
            asset="XAUUSD",
            trade_date=date(2026, 10, 10),
            run_id=run_id,
            snapshot_id=snapshot_id,
            analysis_snapshot_db_id=snapshot.id,
            final_bias="bullish",
            confidence=0.9,
            market_state="premarket",
            scenario_summary="secret scenario",
            is_trade_instruction=False,
            input_snapshot_ids={"analysis_snapshot": snapshot_id},
            source_refs=[{"source": "kept"}],
            source_agent_outputs=[{"bias": "bullish"}],
            risk_points=["risk"],
            watchlist=["watch"],
            invalid_conditions=["invalid"],
            strategy_card={"bias": "bullish", "entry": 1},
            run_summaries={"body": "secret"},
            payload=final_payload,
            final_report_path=str(path),
            final_report_sha256=digest,
            payload_sha256=_hash(json.dumps(final_payload).encode()),
        )
        report = ReportItem(
            report_id=f"final_report:{run_id}",
            family="final_report_markdown",
            report_type="final_report",
            title="old title",
            asset="XAUUSD",
            trade_date=date(2026, 10, 10),
            run_id=run_id,
            snapshot_id=snapshot_id,
            data_status=report_status,
            lifecycle_status="generated",
            source_refs=[{"source": "kept"}],
            report_metadata={"body": "secret metadata", "publish_allowed": True},
            created_at=datetime(2026, 10, 10, tzinfo=UTC),
        )
        artifact = ReportArtifact(
            artifact_id=f"artifact-{run_id}",
            report_id=report.report_id,
            artifact_type="analysis_md",
            file_path=str(path),
            status="generated",
            sha256=digest,
            byte_size=path.stat().st_size,
            is_primary=True,
            source_refs=[{"source": "kept"}],
            artifact_metadata={"body": "secret metadata", "run_id": run_id},
            metadata_text="secret duplicate body",
        )
        run_artifact = RunArtifact(
            artifact_id=uuid4(),
            run_id=run_uuid,
            task_id=step.id,
            artifact_type="final_report",
            file_path=str(path),
            sha256=digest,
            byte_size=path.stat().st_size,
            source_refs_data=[{"source": "kept"}],
            artifact_metadata={"run_id": run_id, "snapshot_id": snapshot_id},
            structured_payload={"body": "secret duplicate body"},
            structured_payload_sha256=_hash(b"structured"),
            structured_status="accepted",
        )
        session.add_all([coordinator, final, report, artifact, run_artifact])
        session.commit()
    return run_id, snapshot_id, path


def test_preview_only_selects_explicit_failure_and_is_read_only(tmp_path: Path) -> None:
    root = tmp_path / "storage"
    root.mkdir()
    factory = _factory(tmp_path)
    failed_run, _, _ = _seed_run(factory, root, failed=True)
    observe_run, _, observe_path = _seed_run(factory, root, failed=False)

    with factory() as session:
        before = session.scalar(select(func.count()).select_from(ExecutionEvent))
        result = preview_unqualified_outputs(session, root, limit=100)
        after = session.scalar(select(func.count()).select_from(ExecutionEvent))

    assert [row["run_id"] for row in result["runs"]] == [failed_run]
    assert observe_run not in json.dumps(result)
    assert result["eligible_file_count"] == 1
    assert before == after == 0
    assert observe_path.exists()
    with factory() as session:
        assert session.get(ReportItem, f"final_report:{failed_run}").data_status == "live"


@pytest.mark.parametrize(
    ("payload_update", "expected_reason"),
    [
        ({"input_validation": {"can_analyze": False}}, "INPUT_VALIDATION_BLOCKED"),
        (
            {
                "input_payload": {
                    "research_synthesis": {
                        "status": "success",
                        "macro_review": {"status": "needs_revision"},
                    }
                }
            },
            "MACRO_REVIEW_NEEDS_REVISION",
        ),
        ({"synthesis_status": "rejected"}, "SYNTHESIS_STATUS_REJECTED"),
    ],
)
def test_only_documented_payload_failure_signals_qualify_run(
    tmp_path: Path, payload_update: dict, expected_reason: str
) -> None:
    root = tmp_path / "storage"
    root.mkdir()
    factory = _factory(tmp_path)
    run_id, _, _ = _seed_run(factory, root, failed=False)
    with factory() as session:
        agent = session.get(AgentOutput, f"agent-{run_id}")
        agent.payload = {**agent.payload, **payload_update}
        session.commit()

    with factory() as session:
        result = preview_unqualified_outputs(session, root, run_ids=[run_id])

    assert result["runs"][0]["reason_codes"] == [expected_reason]


def test_task_failure_and_artifact_registry_rejection_are_not_quality_evidence(tmp_path: Path) -> None:
    root = tmp_path / "storage"
    root.mkdir()
    factory = _factory(tmp_path)
    run_id, _, path = _seed_run(factory, root, failed=False)
    with factory() as session:
        task = session.get(TaskRun, output_retention._uuid(run_id))
        task.status = TaskStatus.failed
        artifact = session.scalar(select(RunArtifact).where(RunArtifact.run_id == output_retention._uuid(run_id)))
        artifact.structured_status = "rejected"
        session.commit()

    result = apply_unqualified_outputs(factory, root, [run_id], now=NOW)

    assert result["tombstoned_run_count"] == 0
    assert path.exists()


def test_explicit_report_failure_qualifies_report_and_composite_run(tmp_path: Path) -> None:
    root = tmp_path / "storage"
    root.mkdir()
    factory = _factory(tmp_path)
    run_id, _, path = _seed_run(factory, root, failed=False, report_status="invalid")

    result = apply_unqualified_outputs(factory, root, [run_id], now=NOW)

    assert result["tombstoned_run_count"] == 1
    assert not path.exists()
    with factory() as session:
        marker = session.get(ReportItem, f"final_report:{run_id}").report_metadata["output_cleanup"]
        assert marker["reason_codes"] == ["REPORT_STATUS_INVALID"]


def test_apply_purges_db_body_keeps_identity_and_deletes_verified_file(tmp_path: Path) -> None:
    root = tmp_path / "storage"
    root.mkdir()
    factory = _factory(tmp_path)
    run_id, snapshot_id, path = _seed_run(factory, root)

    result = apply_unqualified_outputs(factory, root, [run_id], now=NOW)

    assert result["deleted_file_count"] == 1
    assert not path.exists()
    with factory() as session:
        report = session.get(ReportItem, f"final_report:{run_id}")
        assert (report.data_status, report.lifecycle_status) == ("unavailable", "purged")
        assert report.trade_date == date(2026, 10, 10)
        assert report.source_refs == [{"source": "kept"}]
        marker = report.report_metadata["output_cleanup"]
        assert marker["run_id"] == run_id
        assert marker["snapshot_id"] == snapshot_id
        assert marker["reason_codes"] == ["RESEARCH_SYNTHESIS_FAILED"]

        artifact = session.get(ReportArtifact, f"artifact-{run_id}")
        assert artifact.status == "purged"
        assert artifact.file_path.startswith("purged://")
        assert artifact.metadata_text is None

        final = session.get(FinalAnalysisResult, f"final-{run_id}")
        assert final.payload["status"] == "blocked"
        assert final.payload["publish_allowed"] is False
        assert final.final_bias == "unavailable"
        assert final.confidence == 0
        assert final.strategy_card is None
        assert final.final_report_path is None
        assert final.source_refs == [{"source": "kept"}]

        agent = session.get(AgentOutput, f"agent-{run_id}")
        assert agent.summary == ""
        assert agent.key_findings == agent.risk_points == agent.watchlist == []
        assert agent.bias == "unavailable"
        assert agent.confidence == 0
        assert set(agent.payload) == {"output_cleanup"}

        run_artifact = session.scalar(select(RunArtifact).where(RunArtifact.run_id == output_retention._uuid(run_id)))
        assert run_artifact.structured_payload is None
        assert run_artifact.structured_status == "purged"
        assert run_artifact.file_path.startswith("purged://")

        snapshot = session.scalar(select(AnalysisSnapshot).where(AnalysisSnapshot.run_id == run_id))
        assert snapshot.payload == {"snapshot_id": snapshot_id}
        task = session.get(TaskRun, uuid4())
        del task  # The original task/step rows are asserted by count below.
        assert session.scalar(select(func.count()).select_from(TaskRun)) == 2
        assert session.scalar(select(func.count()).select_from(TaskStep)) == 2
        events = list(session.scalars(select(ExecutionEvent)))
        assert {event.event_type for event in events} >= {
            "output_cleanup_file_pending",
            "output_cleanup_file_deleted",
            "output_cleanup_summary",
        }


@pytest.mark.parametrize("state", ["partial", "stale", "needs_review", "observe"])
def test_non_failure_report_states_are_preserved(tmp_path: Path, state: str) -> None:
    root = tmp_path / "storage"
    root.mkdir()
    factory = _factory(tmp_path)
    run_id, _, path = _seed_run(factory, root, failed=False, report_status=state)

    result = apply_unqualified_outputs(factory, root, [run_id], now=NOW)

    assert result["tombstoned_run_count"] == 0
    assert result["tombstoned_report_count"] == 0
    assert path.exists()


def test_shared_reference_and_active_producer_block_cleanup(tmp_path: Path) -> None:
    root = tmp_path / "storage"
    root.mkdir()
    factory = _factory(tmp_path)
    shared_run, _, shared_path = _seed_run(factory, root)
    active_run, _, active_path = _seed_run(factory, root, task_status=TaskStatus.running)
    with factory() as session:
        session.add(
            ReportItem(
                report_id="valid:shared",
                family="macro_report",
                report_type="macro_report",
                title="valid",
                run_id="valid-external-run",
                data_status="live",
                lifecycle_status="generated",
                source_refs=[],
                report_metadata={},
            )
        )
        session.flush()
        session.add(
            ReportArtifact(
                artifact_id="valid:shared:artifact",
                report_id="valid:shared",
                artifact_type="analysis_md",
                file_path=shared_path.relative_to(root.parent).as_posix(),
                status="generated",
                sha256=_hash(shared_path.read_bytes()),
                is_primary=True,
                source_refs=[],
                artifact_metadata={},
            )
        )
        session.commit()

    shared = apply_unqualified_outputs(factory, root, [shared_run], now=NOW)
    active = apply_unqualified_outputs(factory, root, [active_run], now=NOW)

    assert shared_path.exists()
    assert any(item.get("reason") == "FILE_SHARED_REFERENCE" for item in shared["blocked"])
    assert active_path.exists()
    assert any(item.get("reason") == "ACTIVE_PRODUCER" for item in active["blocked"])
    with factory() as session:
        assert session.get(ReportItem, f"final_report:{active_run}").data_status == "live"


def test_blocked_candidate_rows_still_protect_another_requested_file(tmp_path: Path) -> None:
    root = tmp_path / "storage"
    root.mkdir()
    factory = _factory(tmp_path)
    deletable_run, _, shared_path = _seed_run(factory, root)
    active_run, _, active_path = _seed_run(factory, root, task_status=TaskStatus.running)
    digest = _hash(shared_path.read_bytes())
    with factory() as session:
        active_artifact = session.get(ReportArtifact, f"artifact-{active_run}")
        active_final = session.get(FinalAnalysisResult, f"final-{active_run}")
        active_registry = session.scalar(
            select(RunArtifact).where(RunArtifact.run_id == output_retention._uuid(active_run))
        )
        active_artifact.file_path = str(shared_path)
        active_artifact.sha256 = digest
        active_final.final_report_path = str(shared_path)
        active_final.final_report_sha256 = digest
        active_registry.file_path = str(shared_path)
        active_registry.sha256 = digest
        session.commit()

    result = apply_unqualified_outputs(factory, root, [deletable_run, active_run], now=NOW)

    assert shared_path.exists()
    assert active_path.exists()
    assert any(item.get("reason") == "ACTIVE_PRODUCER" for item in result["blocked"])
    assert any(item.get("reason") == "FILE_SHARED_REFERENCE" for item in result["blocked"])


def test_missing_registry_report_is_replaced_by_historical_identity_tombstone(tmp_path: Path) -> None:
    root = tmp_path / "storage"
    root.mkdir()
    factory = _factory(tmp_path)
    run_id, snapshot_id, _ = _seed_run(factory, root)
    with factory() as session:
        original_agent = session.get(AgentOutput, f"agent-{run_id}")
        original_created_at = original_agent.created_at
        session.execute(delete(ReportArtifact).where(ReportArtifact.report_id == f"final_report:{run_id}"))
        session.execute(delete(ReportItem).where(ReportItem.report_id == f"final_report:{run_id}"))
        session.commit()

    apply_unqualified_outputs(factory, root, [run_id], now=NOW)

    with factory() as session:
        report = session.get(ReportItem, f"final_report:{run_id}")
        assert report is not None
        assert report.trade_date == date(2026, 10, 10)
        assert report.snapshot_id == snapshot_id
        assert report.created_at == original_created_at
        assert report.created_at != NOW


def test_symlink_hardlink_and_hash_change_are_blocked(tmp_path: Path) -> None:
    root = tmp_path / "storage"
    root.mkdir()
    factory = _factory(tmp_path)
    symlink_run, _, symlink_path = _seed_run(factory, root)
    hardlink_run, _, hardlink_path = _seed_run(factory, root)
    changed_run, _, changed_path = _seed_run(factory, root)

    target = symlink_path.with_name("target.md")
    symlink_path.rename(target)
    symlink_path.symlink_to(target.name)
    os.link(hardlink_path, hardlink_path.with_name("second-link.md"))
    changed_path.write_bytes(b"changed after registration")

    with factory() as session:
        preview = preview_unqualified_outputs(session, root, run_ids=[symlink_run, hardlink_run, changed_run])
    reasons = {item["reason"] for item in preview["files"]}
    assert {"FILE_SYMLINK_BLOCKED", "FILE_HARDLINK_BLOCKED", "FILE_HASH_CHANGED"} <= reasons


def test_different_registered_path_aliases_with_conflicting_hashes_are_blocked(tmp_path: Path) -> None:
    root = tmp_path / "storage"
    root.mkdir()
    factory = _factory(tmp_path)
    run_id, _, path = _seed_run(factory, root)
    with factory() as session:
        final = session.get(FinalAnalysisResult, f"final-{run_id}")
        final.final_report_path = path.relative_to(root.parent).as_posix()
        final.final_report_sha256 = "f" * 64
        session.commit()

    with factory() as session:
        result = preview_unqualified_outputs(session, root, run_ids=[run_id])

    assert result["candidate_file_count"] == 1
    assert result["files"][0]["reason"] == "REGISTERED_HASH_CONFLICT"
    assert len(result["files"][0]["path_aliases"]) == 2


def test_interrupted_unlink_recovers_from_durable_pending_event(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "storage"
    root.mkdir()
    factory = _factory(tmp_path)
    run_id, _, path = _seed_run(factory, root)
    real_unlink = output_retention._safe_unlink

    def crash_after_unlink(root_arg, relative, expected_hash, expected_size):
        real_unlink(root_arg, relative, expected_hash, expected_size)
        raise KeyboardInterrupt("simulated crash")

    monkeypatch.setattr(output_retention, "_safe_unlink", crash_after_unlink)
    with pytest.raises(KeyboardInterrupt):
        apply_unqualified_outputs(factory, root, [run_id], now=NOW)
    assert not path.exists()
    with factory() as session:
        pending = list(
            session.scalars(select(ExecutionEvent).where(ExecutionEvent.event_type == "output_cleanup_file_pending"))
        )
        deleted = list(
            session.scalars(select(ExecutionEvent).where(ExecutionEvent.event_type == "output_cleanup_file_deleted"))
        )
        assert len(pending) == 1
        assert deleted == []

    monkeypatch.setattr(output_retention, "_safe_unlink", real_unlink)
    recovered = apply_unqualified_outputs(factory, root, [run_id], now=NOW)
    assert recovered["deleted_file_count"] == 1
    assert recovered["reconciled_file_count"] == 1
    again = apply_unqualified_outputs(factory, root, [run_id], now=NOW)
    assert again["deleted_file_count"] == 0
    assert again["pending_file_count"] == 0
    assert again["blocked_file_count"] == 0


def test_standalone_failed_agent_is_purged_without_invalidating_run(tmp_path: Path) -> None:
    root = tmp_path / "storage"
    root.mkdir()
    factory = _factory(tmp_path)
    run_id, _, path = _seed_run(factory, root, failed=False)
    with factory() as session:
        row = session.get(AgentOutput, f"agent-{run_id}")
        row.agent_name = "macro_liquidity_agent"
        row.module = "macro"
        row.status = "failed"
        session.commit()

    result = apply_unqualified_outputs(factory, root, [run_id], now=NOW)

    assert result["tombstoned_run_count"] == 0
    assert result["tombstoned_agent_output_count"] == 1
    assert path.exists()
    with factory() as session:
        assert session.get(ReportItem, f"final_report:{run_id}").data_status == "live"
        assert session.get(FinalAnalysisResult, f"final-{run_id}").final_bias == "bullish"
    repeated = apply_unqualified_outputs(factory, root, [run_id], now=NOW)
    assert repeated["tombstoned_run_count"] == 0


def test_valid_snapshot_hash_only_reference_protects_candidate_file(tmp_path: Path) -> None:
    root = tmp_path / "storage"
    root.mkdir()
    factory = _factory(tmp_path)
    failed_run, _, failed_path = _seed_run(factory, root)
    valid_run, _, _ = _seed_run(factory, root, failed=False)
    digest = _hash(failed_path.read_bytes())
    with factory() as session:
        valid_snapshot = session.scalar(select(AnalysisSnapshot).where(AnalysisSnapshot.run_id == valid_run))
        valid_snapshot.source_refs = [{"report_sha256": digest}]
        session.commit()

    with factory() as session:
        preview = preview_unqualified_outputs(session, root, [failed_run])

    assert preview["files"][0]["reason"] == "FILE_SHARED_REFERENCE"
    result = apply_unqualified_outputs(factory, root, [failed_run], now=NOW)
    assert failed_path.exists()
    assert any(item.get("reason") == "FILE_SHARED_REFERENCE" for item in result["blocked"])


def test_pending_retry_rechecks_producer_and_finishes_interrupted_audit(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "storage"
    root.mkdir()
    factory = _factory(tmp_path)
    run_id, _, path = _seed_run(factory, root)
    real_unlink = output_retention._safe_unlink

    def interrupt_before_unlink(*_args, **_kwargs):
        raise KeyboardInterrupt("simulated interruption")

    monkeypatch.setattr(output_retention, "_safe_unlink", interrupt_before_unlink)
    with pytest.raises(KeyboardInterrupt):
        apply_unqualified_outputs(factory, root, [run_id], now=NOW)
    assert path.exists()
    with factory() as session:
        cleanup_run = session.scalar(
            select(TaskRun).where(TaskRun.task_type == "output_retention").order_by(TaskRun.created_at.desc())
        )
        cleanup_step = session.scalar(select(TaskStep).where(TaskStep.task_run_id == cleanup_run.id))
        assert cleanup_run.status == TaskStatus.failed
        assert cleanup_step.status == StepStatus.failed
        producer = session.get(TaskRun, output_retention._uuid(run_id))
        producer.status = TaskStatus.running
        session.commit()

    monkeypatch.setattr(output_retention, "_safe_unlink", real_unlink)
    result = apply_unqualified_outputs(factory, root, [run_id], now=NOW)

    assert path.exists()
    assert any(item.get("reason") == "ACTIVE_PRODUCER" for item in result["blocked"])


def test_pending_retry_rechecks_running_task_step(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "storage"
    root.mkdir()
    factory = _factory(tmp_path)
    run_id, _, path = _seed_run(factory, root)
    real_unlink = output_retention._safe_unlink

    def interrupt_before_unlink(*_args, **_kwargs):
        raise KeyboardInterrupt("simulated interruption")

    monkeypatch.setattr(output_retention, "_safe_unlink", interrupt_before_unlink)
    with pytest.raises(KeyboardInterrupt):
        apply_unqualified_outputs(factory, root, [run_id], now=NOW)
    with factory() as session:
        producer = session.get(TaskRun, output_retention._uuid(run_id))
        producer.status = TaskStatus.success
        report_step = session.scalar(
            select(TaskStep).where(
                TaskStep.task_run_id == output_retention._uuid(run_id),
                TaskStep.name == "report_render",
            )
        )
        report_step.status = StepStatus.pending
        session.commit()

    monkeypatch.setattr(output_retention, "_safe_unlink", real_unlink)
    result = apply_unqualified_outputs(factory, root, [run_id], now=NOW)

    assert path.exists()
    assert any(item.get("reason") == "ACTIVE_PRODUCER" for item in result["blocked"])


def test_pending_is_bound_to_canonical_storage_root(tmp_path: Path, monkeypatch) -> None:
    root_a = tmp_path / "storage-a"
    root_b = tmp_path / "storage-b"
    root_a.mkdir()
    root_b.mkdir()
    factory = _factory(tmp_path)
    run_id, _, path_a = _seed_run(factory, root_a)
    relative = path_a.relative_to(root_a)
    path_b = root_b / relative
    path_b.parent.mkdir(parents=True)
    path_b.write_bytes(path_a.read_bytes())
    real_unlink = output_retention._safe_unlink

    def interrupt_before_unlink(*_args, **_kwargs):
        raise KeyboardInterrupt("simulated interruption")

    monkeypatch.setattr(output_retention, "_safe_unlink", interrupt_before_unlink)
    with pytest.raises(KeyboardInterrupt):
        apply_unqualified_outputs(factory, root_a, [run_id], now=NOW)
    monkeypatch.setattr(output_retention, "_safe_unlink", real_unlink)

    result = apply_unqualified_outputs(factory, root_b, [run_id], now=NOW)

    assert path_a.exists()
    assert path_b.exists()
    assert any(item.get("reason") == "PENDING_STORAGE_ROOT_MISMATCH" for item in result["blocked"])


def test_storage_alias_and_task_step_output_tombstone_preserve_macro(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "storage"
    legacy_root = Path("/legacy/workspace/app/storage")
    root.mkdir()
    factory = _factory(tmp_path)
    run_id, _, path = _seed_run(factory, root)
    legacy_path = legacy_root / path.relative_to(root)
    monkeypatch.setenv("FINANCE_AGENT_LEGACY_STORAGE_ROOTS", str(legacy_root))
    with factory() as session:
        artifact = session.get(ReportArtifact, f"artifact-{run_id}")
        final = session.get(FinalAnalysisResult, f"final-{run_id}")
        run_artifact = session.scalar(select(RunArtifact).where(RunArtifact.run_id == output_retention._uuid(run_id)))
        report_step = session.scalar(
            select(TaskStep).where(
                TaskStep.task_run_id == output_retention._uuid(run_id),
                TaskStep.name == "report_render",
            )
        )
        artifact.file_path = str(legacy_path)
        final.final_report_path = str(legacy_path)
        run_artifact.file_path = str(legacy_path)
        report_step.output_ref = str(legacy_path)
        report_step.output_json = json.dumps({"body": "bad report body"})
        report_step.output_refs = json.dumps({"path": str(legacy_path), "body": "bad"})
        report_step.artifact_refs = json.dumps({"path": str(legacy_path), "claim": "buy"})
        macro_step = TaskStep(
            task_run_id=output_retention._uuid(run_id),
            name="macro_collection",
            status=StepStatus.success,
            output_json=json.dumps({"macro": "keep"}),
            output_ref="outputs/macro/source.json",
        )
        macro_report = ReportItem(
            report_id=f"macro:{run_id}",
            family="macro_report",
            report_type="macro_report",
            title="macro keep",
            run_id=run_id,
            data_status="live",
            lifecycle_status="generated",
            source_refs=[],
            report_metadata={"body": "keep macro body"},
        )
        session.add_all([macro_step, macro_report])
        session.commit()

    result = apply_unqualified_outputs(factory, root, [run_id], now=NOW)

    assert result["deleted_file_count"] == 1
    assert not path.exists()
    with factory() as session:
        report_step = session.scalar(
            select(TaskStep).where(
                TaskStep.task_run_id == output_retention._uuid(run_id),
                TaskStep.name == "report_render",
            )
        )
        macro_step = session.scalar(
            select(TaskStep).where(
                TaskStep.task_run_id == output_retention._uuid(run_id),
                TaskStep.name == "macro_collection",
            )
        )
        assert json.loads(report_step.output_json)["output_cleanup"]["status"] == "purged"
        assert "bad" not in report_step.output_json
        assert report_step.output_ref.startswith("purged://task-step/")
        assert json.loads(macro_step.output_json) == {"macro": "keep"}
        macro_report = session.get(ReportItem, f"macro:{run_id}")
        assert macro_report.report_metadata == {"body": "keep macro body"}
        assert (macro_report.data_status, macro_report.lifecycle_status) == (
            "live",
            "generated",
        )
