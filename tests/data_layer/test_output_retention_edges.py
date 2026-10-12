"""Core-owned behavioral checks; fixture bodies are synthetic, never live research."""

from datetime import UTC, date, datetime
from hashlib import sha256
import json
import os
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from database.models.analysis import AnalysisBase, AnalysisSnapshot, AgentOutput
from database.models.execution import ExecutionBase, RunArtifact
from database.models.report import ReportBase, ReportItem, ReportArtifact
from database.models.task import Base, TaskRun, TaskStatus, TaskStep, StepStatus

ORIGINAL = datetime(2026, 9, 8, 12, tzinfo=UTC)
NOW = datetime(2026, 10, 12, 3, tzinfo=UTC)
BAD = "CORE_SYNTHETIC_REJECTED_BODY_DO_NOT_KEEP"


@pytest.fixture
def store(tmp_path):
    engine = create_engine("sqlite:///:memory:")
    for metadata in (AnalysisBase.metadata, ReportBase.metadata, ExecutionBase.metadata, Base.metadata):
        metadata.create_all(engine)
    root = tmp_path / "storage"
    root.mkdir()
    yield sessionmaker(engine, expire_on_commit=False), root
    engine.dispose()


def add(factory, root, *, bad=True, family="observation_report", run_id=None):
    run = run_id or str(uuid4())
    sid = f"XAUUSD:2026-09-08:{run}"
    report = f"{family}:{run}"
    path = root / "outputs" / family / "XAUUSD" / "2026-09-08" / run / "final_report.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    body = BAD if bad else "CORE_SYNTHETIC_VALID_HISTORY"
    path.write_text(body)
    digest = sha256(body.encode()).hexdigest()
    aid = str(uuid4())
    with factory.begin() as db:
        snapshot = AnalysisSnapshot(
            snapshot_id=sid,
            asset="XAUUSD",
            trade_date=date(2026, 9, 8),
            run_id=run,
            snapshot_time=ORIGINAL,
            status="success",
            input_snapshot_ids={},
            source_refs=[],
            payload={"frozen": "KEEP_SOURCE"},
            payload_sha256="1" * 64,
            artifact_path=str(root / "features" / f"{run}.json"),
            created_at=ORIGINAL,
        )
        db.add(snapshot)
        db.flush()
        db.add(TaskRun(id=UUID(run), name="fixture historical task", status=TaskStatus.success, created_at=ORIGINAL))
        db.add(
            AgentOutput(
                id=aid,
                snapshot_id=sid,
                analysis_snapshot_db_id=snapshot.id,
                asset="XAUUSD",
                trade_date=date(2026, 9, 8),
                run_id=run,
                agent_name="coordinator_agent",
                module="coordinator",
                version="1.0",
                status="partial",
                bias="bullish",
                confidence=0.7,
                input_snapshot_ids={},
                source_refs=[],
                key_findings=[body],
                risk_points=[body],
                watchlist=[body],
                invalid_conditions=[],
                summary=body,
                payload={
                    "input_payload": {
                        "research_synthesis": {
                            "status": "rule_fallback" if bad else "success",
                            "generated_by": "deterministic_coordinator" if bad else "llm",
                            "analysis": {"text": body},
                        }
                    },
                    "narrative_md": body,
                },
                payload_sha256="2" * 64,
                created_at=ORIGINAL,
            )
        )
        db.add(
            ReportItem(
                report_id=report,
                family=family + "_markdown",
                report_type=family,
                title="fixture",
                asset="XAUUSD",
                trade_date=date(2026, 9, 8),
                run_id=run,
                snapshot_id=sid,
                data_status="partial",
                lifecycle_status="generated",
                source_refs=[],
                report_metadata={"review_status": "blocked", "output_mode": "observe"},
                created_at=ORIGINAL,
            )
        )
        db.flush()
        db.add(
            ReportArtifact(
                artifact_id=report + ":0",
                report_id=report,
                artifact_type="analysis_md",
                file_path=str(path),
                sha256=digest,
                status="generated",
                is_primary=True,
                byte_size=len(body.encode()),
                artifact_metadata={},
                created_at=ORIGINAL,
            )
        )
        db.add(
            RunArtifact(
                run_id=UUID(run),
                artifact_type="analysis_md",
                file_path=str(path),
                sha256=digest,
                byte_size=len(body.encode()),
                structured_payload={"body": body},
                structured_status="loaded",
                artifact_metadata={},
                metadata_json="{}",
                created_at=ORIGINAL,
            )
        )
    return dict(run=run, sid=sid, report=report, path=path, aid=aid, digest=digest)


def apply(factory, root, *runs):
    from apps.data_layer.output_retention import apply_unqualified_outputs

    return apply_unqualified_outputs(factory, storage_root=root, run_ids=list(runs), now=NOW)


def test_clear_failed_body_keep_identity_and_valid_observation(store):
    factory, root = store
    bad = add(factory, root)
    good = add(factory, root, bad=False)
    from apps.data_layer.output_retention import preview_unqualified_outputs

    with factory() as db:
        preview_unqualified_outputs(db, storage_root=root, run_ids=[bad["run"], good["run"]])
        assert db.get(ReportItem, bad["report"]).lifecycle_status == "generated"
    assert bad["path"].exists()
    apply(factory, root, bad["run"], good["run"])
    assert not bad["path"].exists(), "Bad report file survived despite no valid consumer"
    assert sha256(good["path"].read_bytes()).hexdigest() == good["digest"]
    with factory() as db:
        ao = db.get(AgentOutput, bad["aid"])
        assert BAD not in json.dumps({c.name: getattr(ao, c.key) for c in AgentOutput.__table__.columns}, default=str)
        assert ao.payload["output_cleanup"]["status"] == "purged"
        assert ao.status in {"unavailable", "failed"} and ao.bias == "unavailable"
        tomb = db.get(ReportItem, bad["report"])
        original_time = (
            tomb.created_at.astimezone(UTC) if tomb.created_at.tzinfo else tomb.created_at.replace(tzinfo=UTC)
        )
        assert tomb.lifecycle_status == "purged" and original_time == ORIGINAL
        assert db.get(ReportItem, good["report"]).lifecycle_status == "generated"
        snapshots = db.scalars(select(AnalysisSnapshot)).all()
        assert all(s.payload == {"frozen": "KEEP_SOURCE"} for s in snapshots)
        for artifact in db.scalars(select(RunArtifact).where(RunArtifact.run_id == UUID(bad["run"]))):
            assert artifact.structured_payload is None or BAD not in json.dumps(artifact.structured_payload)
    apply(factory, root, bad["run"])
    assert not bad["path"].exists()


def test_preserve_independent_macro_report_same_run(store):
    factory, root = store
    target = add(factory, root)
    macro = root / "outputs" / "macro" / "valid.md"
    macro.parent.mkdir()
    macro.write_text("VALID_MACRO_FACTS")
    with factory.begin() as db:
        db.add(
            ReportItem(
                report_id="macro:" + target["run"],
                family="macro_report",
                report_type="macro_report",
                title="valid macro",
                run_id=target["run"],
                asset="XAUUSD",
                trade_date=date(2026, 9, 8),
                data_status="live",
                lifecycle_status="generated",
                source_refs=[],
            )
        )
        db.flush()
        db.add(
            ReportArtifact(
                artifact_id="macro-art",
                report_id="macro:" + target["run"],
                artifact_type="analysis_md",
                file_path=str(macro),
                sha256=sha256(macro.read_bytes()).hexdigest(),
                status="generated",
            )
        )
    apply(factory, root, target["run"])
    assert macro.read_text() == "VALID_MACRO_FACTS"
    with factory() as db:
        assert db.get(ReportItem, "macro:" + target["run"]).lifecycle_status == "generated"


@pytest.mark.parametrize("reference_kind", ["path", "hash"])
def test_valid_snapshot_reference_protects_file(store, reference_kind):
    factory, root = store
    target = add(factory, root)
    with factory.begin() as db:
        db.add(
            AnalysisSnapshot(
                snapshot_id="independent-valid-snapshot",
                asset="XAUUSD",
                trade_date=date(2026, 9, 9),
                run_id=str(uuid4()),
                status="success",
                payload={
                    "prior_research": {"artifact_ref": str(target["path"])}
                    if reference_kind == "path"
                    else {"sha256": target["digest"]}
                },
                payload_sha256="3" * 64,
                artifact_path=str(root / "features" / "valid.json"),
                input_snapshot_ids={},
                source_refs=[],
            )
        )
    apply(factory, root, target["run"])
    assert target["path"].exists(), "A valid consumer still references the file"


def test_active_producer_and_changed_file_are_not_deleted(store):
    factory, root = store
    target = add(factory, root)
    with factory.begin() as db:
        db.get(TaskRun, UUID(target["run"])).status = TaskStatus.running
    apply(factory, root, target["run"])
    assert target["path"].exists()
    with factory.begin() as db:
        assert db.get(ReportItem, target["report"]).lifecycle_status == "generated"
        db.get(TaskRun, UUID(target["run"])).status = TaskStatus.success
    target["path"].write_text("CHANGED_AFTER_REGISTRATION")
    apply(factory, root, target["run"])
    assert target["path"].read_text() == "CHANGED_AFTER_REGISTRATION"


@pytest.mark.parametrize("link_type", ["symbolic", "hard"])
def test_linked_output_never_deletes_external_content(store, link_type):
    factory, root = store
    target = add(factory, root)
    outside = root.parent / "outside.md"
    outside.write_text(BAD)
    target["path"].unlink()
    if link_type == "symbolic":
        target["path"].symlink_to(outside)
    else:
        os.link(outside, target["path"])
    apply(factory, root, target["run"])
    assert outside.read_text() == BAD
    assert target["path"].exists()


def test_rejected_render_error_body_is_removed(store):
    factory, root = store
    target = add(factory, root)
    step_id = uuid4()
    with factory.begin() as db:
        db.add(
            TaskStep(
                id=step_id,
                task_run_id=UUID(target["run"]),
                name="report_render",
                status=StepStatus.failed,
                output_json=json.dumps({"body": BAD}),
                error_json=json.dumps({"error_code": "REVIEW_REJECTED", "body": BAD}),
                input_json=json.dumps({"source_fact": "KEEP"}),
            )
        )
    apply(factory, root, target["run"])
    with factory() as db:
        step = db.get(TaskStep, step_id)
        assert BAD not in json.dumps({c.name: getattr(step, c.key) for c in TaskStep.__table__.columns}, default=str)
        assert json.loads(step.input_json) == {"source_fact": "KEEP"}
        assert step.status == StepStatus.failed


def test_other_task_error_reference_protects_file(store):
    factory, root = store
    target = add(factory, root)
    good = add(factory, root, bad=False)
    original_error = json.dumps({"quality_audit": {"source_ref": str(target["path"])}})
    step_id = uuid4()
    with factory.begin() as db:
        db.add(
            TaskStep(
                id=step_id,
                task_run_id=UUID(good["run"]),
                name="quality_audit",
                status=StepStatus.failed,
                error_json=original_error,
            )
        )
    apply(factory, root, target["run"])
    assert target["path"].exists()
    with factory() as db:
        assert db.get(TaskStep, step_id).error_json == original_error


def test_standalone_failed_agent_unique_output_is_removed(store):
    factory, root = store
    target = add(factory, root, bad=False)
    file = root / "outputs" / "failed_domain.json"
    file.write_text(BAD)
    ident = str(uuid4())
    with factory.begin() as db:
        source = db.get(AgentOutput, target["aid"])
        db.add(
            AgentOutput(
                id=ident,
                snapshot_id=target["sid"],
                analysis_snapshot_db_id=source.analysis_snapshot_db_id,
                asset=source.asset,
                trade_date=source.trade_date,
                run_id=source.run_id,
                agent_name="failed_domain_agent",
                module="domain",
                version="1.0",
                status="failed",
                bias="unavailable",
                confidence=0,
                input_snapshot_ids={},
                source_refs=[],
                key_findings=[],
                risk_points=[],
                watchlist=[],
                invalid_conditions=[],
                summary=BAD,
                payload={
                    "narrative_md": BAD,
                    "artifact_path": str(file),
                    "sha256": sha256(file.read_bytes()).hexdigest(),
                },
                payload_sha256="4" * 64,
            )
        )
    apply(factory, root, target["run"])
    assert not file.exists()
    assert target["path"].exists()
    with factory() as db:
        assert db.get(AgentOutput, ident).payload["output_cleanup"]["status"] == "purged"


def test_policy_input_lineage_does_not_protect_a_rejected_report(store):
    factory, root = store
    target = add(factory, root)
    with factory.begin() as db:
        artifact = db.scalar(select(RunArtifact).where(RunArtifact.run_id == UUID(target["run"])))
        artifact.artifact_metadata = {
            "input_snapshot_ids": {"gold_policy_feature_snapshot": "keep-upstream-id"},
            "output_mode": "observe",
        }
    result = apply(factory, root, target["run"])
    assert result["deleted_file_count"] == 1
    assert not target["path"].exists()
    with factory() as db:
        snapshot = db.scalar(select(AnalysisSnapshot).where(AnalysisSnapshot.run_id == target["run"]))
        assert snapshot.payload == {"frozen": "KEEP_SOURCE"}


@pytest.mark.parametrize("mode", ["eligible", "shared", "wrong_run"])
def test_registered_legacy_render_body_obeys_dependency_and_run_boundaries(store, mode):
    factory, root = store
    target = add(factory, root)
    good = add(factory, root, bad=False)
    path_run = str(uuid4()) if mode == "wrong_run" else target["run"]
    path = root / "analysis" / "gold_mainlines" / "2026-09-08" / path_run / "agent_outputs" / "report_render_output.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(BAD + " LEGACY RENDER")
    sibling = path.with_name("source_health_output.json")
    sibling.write_text("KEEP DOMAIN OUTPUT")
    with factory.begin() as db:
        db.add(RunArtifact(
            run_id=UUID(target["run"]), artifact_type="analysis_md", file_path=str(path),
            sha256=sha256(path.read_bytes()).hexdigest(), byte_size=path.stat().st_size,
            structured_status="loaded", structured_payload={"body": BAD}, artifact_metadata={}, metadata_json="{}",
        ))
        if mode == "shared":
            snapshot = db.scalar(select(AnalysisSnapshot).where(AnalysisSnapshot.snapshot_id == good["sid"]))
            snapshot.payload = {"source_refs": [path.relative_to(root).as_posix()]}
    result = apply(factory, root, target["run"])
    assert sibling.read_text() == "KEEP DOMAIN OUTPUT"
    assert not target["path"].exists()
    assert good["path"].exists()
    assert path.exists() is (mode != "eligible")
    if mode != "eligible":
        reason = "FILE_SHARED_REFERENCE" if mode == "shared" else "LEGACY_OUTPUT_RUN_MISMATCH"
        assert any(row["reason"] == reason for row in result["blocked"])


@pytest.mark.parametrize("step_status,started", [(StepStatus.pending, False), (StepStatus.pending, True), (StepStatus.running, True)])
def test_finished_failed_parent_only_running_step_blocks_cleanup(store, step_status, started):
    factory, root = store
    target = add(factory, root)
    with factory.begin() as db:
        task = db.get(TaskRun, UUID(target["run"]))
        task.status = TaskStatus.failed
        task.ended_at = ORIGINAL
        db.add(TaskStep(id=uuid4(), task_run_id=task.id, name="report_render", status=step_status,
                        started_at=ORIGINAL if started else None))
    result = apply(factory, root, target["run"])
    assert target["path"].exists() is started
    assert any(row["reason"] == "ACTIVE_PRODUCER" for row in result["blocked"]) is started
