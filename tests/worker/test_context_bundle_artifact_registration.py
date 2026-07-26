from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import apps.worker.artifact_registration as artifact_registration
from apps.analysis.context_bundle import assemble_context_bundle
from apps.output.context_bundle import write_context_bundle
from apps.runtime.artifact_registry import (
    select_context_bundle_artifact_for_run,
    select_previous_context_bundle_artifact,
)
from apps.worker.artifact_registration import (
    register_composite_output_artifacts,
    register_context_bundle_artifact,
)
from apps.worker.runner import _resolve_state_shadow_registry_inputs
from database.models.execution import RunArtifact, ensure_execution_tables
from database.models.task import StepStatus, TaskRun, TaskStep, TaskStatus, ensure_task_tables


NOW = datetime(2026, 7, 26, 8, tzinfo=UTC)


def _assert_descriptor_identity(selected: dict, expected: dict) -> None:
    for key in (
        "artifact_family",
        "schema_version",
        "bundle_id",
        "content_hash",
        "asset",
        "state_scope",
        "run_id",
        "canonical_state_id",
    ):
        assert selected["metadata"][key] == expected["metadata"][key]


def _session(*, execution_tables: bool = True):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    ensure_task_tables(engine)
    if execution_tables:
        ensure_execution_tables(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _run_step(db):
    run = TaskRun(name="premarket", status=TaskStatus.pending, snapshot_id="snapshot-79")
    db.add(run)
    db.flush()
    step = TaskStep(task_run_id=run.id, name="report_render", status=StepStatus.success)
    db.add(step)
    db.flush()
    return run, step


def _valid_descriptor(
    tmp_path,
    *,
    run_id: str,
    cutoff_at: datetime = NOW,
    asset: str = "XAUUSD",
    state_scope: str = "daily_close",
    canonical_state_id: str = "state-79",
) -> dict:
    bundle = assemble_context_bundle(
        run_id=run_id,
        asset=asset,
        state_scope=state_scope,
        canonical_state_id=canonical_state_id,
        canonical_state={"asset": asset, "state_scope": state_scope, "core_thesis": "等待确认"},
        evidence=[],
        evidence_cursors={},
        cutoff_at=cutoff_at,
        assembled_at=cutoff_at + timedelta(minutes=1),
        expected_session="daily_close",
    )
    return write_context_bundle(storage_root=tmp_path, bundle=bundle).registry_artifact


def _register_valid_bundle(
    db,
    tmp_path,
    *,
    cutoff_at: datetime = NOW,
    asset: str = "XAUUSD",
    state_scope: str = "daily_close",
    canonical_state_id: str = "state-79",
):
    run, step = _run_step(db)
    descriptor = _valid_descriptor(
        tmp_path,
        run_id=str(run.id),
        cutoff_at=cutoff_at,
        asset=asset,
        state_scope=state_scope,
        canonical_state_id=canonical_state_id,
    )
    row = register_context_bundle_artifact(
        db, run_id=str(run.id), step=step, descriptor=descriptor, storage_root=tmp_path
    )
    db.flush()
    return run, step, descriptor, row


def _recompute_descriptor(tmp_path, *, predecessor: dict, canonical_state_id: str = "state-80") -> dict:
    descriptor = _valid_descriptor(
        tmp_path,
        run_id=predecessor["metadata"]["run_id"],
        cutoff_at=NOW + timedelta(minutes=2),
        canonical_state_id=canonical_state_id,
    )
    return {
        **descriptor,
        "metadata": {
            **descriptor["metadata"],
            "artifact_role": "canary_recompute",
            "canary_recompute_attempt": 1,
            "supersedes_bundle_id": predecessor["metadata"]["bundle_id"],
            "supersedes_bundle_hash": predecessor["metadata"]["content_hash"],
            "supersedes_canonical_state_id": predecessor["metadata"]["canonical_state_id"],
        },
    }


def test_context_bundle_registry_is_exactly_once_and_idempotent(tmp_path) -> None:
    db = _session()
    run, step = _run_step(db)
    descriptor = _valid_descriptor(tmp_path, run_id=str(run.id))

    first = register_context_bundle_artifact(
        db, run_id=str(run.id), step=step, descriptor=descriptor, storage_root=tmp_path
    )
    replay = register_context_bundle_artifact(
        db, run_id=str(run.id), step=step, descriptor=descriptor, storage_root=tmp_path
    )
    db.commit()

    rows = db.query(RunArtifact).filter(RunArtifact.run_id == run.id).all()
    assert first is not None and replay is not None
    assert first.artifact_id == replay.artifact_id
    assert first.artifact_id == uuid5(
        NAMESPACE_URL,
        f"finance-agent:run-context-bundle:{run.id}",
    )
    assert len(rows) == 1
    assert str(rows[0].artifact_id) != descriptor["metadata"]["bundle_id"]
    assert rows[0].sha256 == descriptor["sha256"]
    assert rows[0].artifact_metadata["bundle_id"] == descriptor["metadata"]["bundle_id"]


def test_context_bundle_registry_rejects_conflicting_replay(tmp_path) -> None:
    db = _session()
    run, step = _run_step(db)
    descriptor = _valid_descriptor(tmp_path, run_id=str(run.id))
    register_context_bundle_artifact(db, run_id=str(run.id), step=step, descriptor=descriptor, storage_root=tmp_path)

    with pytest.raises(ValueError, match="descriptor payload identity conflicts"):
        register_context_bundle_artifact(
            db,
            run_id=str(run.id),
            step=step,
            descriptor={**descriptor, "metadata": {**descriptor["metadata"], "content_hash": "b" * 64}},
            storage_root=tmp_path,
        )


def test_context_bundle_registry_rejects_generic_artifact_dedupe_collision(tmp_path) -> None:
    db = _session()
    run, step = _run_step(db)
    descriptor = _valid_descriptor(tmp_path, run_id=str(run.id))
    db.add(
        RunArtifact(
            run_id=run.id,
            task_id=step.id,
            artifact_type="structured_json",
            file_path=descriptor["file_path"],
            sha256=descriptor["sha256"],
            artifact_metadata={"artifact_family": "unrelated_output"},
        )
    )
    db.flush()

    with pytest.raises(ValueError, match="identity conflicts"):
        register_context_bundle_artifact(
            db,
            run_id=str(run.id),
            step=step,
            descriptor=descriptor,
            storage_root=tmp_path,
        )


def test_context_bundle_registry_allows_one_validated_canary_supersession(tmp_path) -> None:
    db = _session()
    run, step = _run_step(db)
    original = _valid_descriptor(tmp_path, run_id=str(run.id))
    register_context_bundle_artifact(
        db,
        run_id=str(run.id),
        step=step,
        descriptor=original,
        storage_root=tmp_path,
    )
    fresh = _recompute_descriptor(tmp_path, predecessor=original)

    first = register_context_bundle_artifact(
        db,
        run_id=str(run.id),
        step=step,
        descriptor=fresh,
        storage_root=tmp_path,
        allow_canary_recompute=True,
    )
    replay = register_context_bundle_artifact(
        db,
        run_id=str(run.id),
        step=step,
        descriptor=fresh,
        storage_root=tmp_path,
        allow_canary_recompute=True,
    )
    db.commit()

    assert first is not None and replay is not None
    assert first.artifact_id == replay.artifact_id
    assert first.artifact_id == uuid5(
        NAMESPACE_URL,
        f"finance-agent:run-context-bundle:{run.id}:canary-recompute:1",
    )
    assert db.query(RunArtifact).filter(RunArtifact.run_id == run.id).count() == 2
    selected = select_context_bundle_artifact_for_run(
        db,
        run_id=str(run.id),
        storage_root=tmp_path,
    )
    _assert_descriptor_identity(selected, fresh)
    assert selected["metadata"]["supersedes_bundle_id"] == original["metadata"]["bundle_id"]


def test_context_bundle_registry_rejects_unapproved_or_invalid_canary_supersession(tmp_path) -> None:
    db = _session()
    run, step = _run_step(db)
    original = _valid_descriptor(tmp_path, run_id=str(run.id))
    register_context_bundle_artifact(
        db,
        run_id=str(run.id),
        step=step,
        descriptor=original,
        storage_root=tmp_path,
    )
    fresh = _recompute_descriptor(tmp_path, predecessor=original)

    with pytest.raises(ValueError, match="explicit registry authority"):
        register_context_bundle_artifact(
            db,
            run_id=str(run.id),
            step=step,
            descriptor=fresh,
            storage_root=tmp_path,
        )

    wrong = {
        **fresh,
        "metadata": {**fresh["metadata"], "supersedes_bundle_id": "wrong-bundle"},
    }
    with pytest.raises(ValueError, match="supersedes_bundle_id"):
        register_context_bundle_artifact(
            db,
            run_id=str(run.id),
            step=step,
            descriptor=wrong,
            storage_root=tmp_path,
            allow_canary_recompute=True,
        )


def test_context_bundle_registry_rejects_second_canary_supersession(tmp_path) -> None:
    db = _session()
    run, step = _run_step(db)
    original = _valid_descriptor(tmp_path, run_id=str(run.id))
    register_context_bundle_artifact(
        db,
        run_id=str(run.id),
        step=step,
        descriptor=original,
        storage_root=tmp_path,
    )
    fresh = _recompute_descriptor(tmp_path, predecessor=original)
    register_context_bundle_artifact(
        db,
        run_id=str(run.id),
        step=step,
        descriptor=fresh,
        storage_root=tmp_path,
        allow_canary_recompute=True,
    )
    second = _recompute_descriptor(
        tmp_path,
        predecessor=fresh,
        canonical_state_id="state-80-second",
    )
    with pytest.raises(ValueError, match="exactly one superseded Bundle"):
        register_context_bundle_artifact(
            db,
            run_id=str(run.id),
            step=step,
            descriptor=second,
            storage_root=tmp_path,
            allow_canary_recompute=True,
        )


@pytest.mark.parametrize("conflicting_winner", [False, True])
def test_context_bundle_registry_validates_concurrent_insert_winner(
    tmp_path, monkeypatch, conflicting_winner: bool
) -> None:
    db = _session()
    run, step = _run_step(db)
    descriptor = _valid_descriptor(tmp_path, run_id=str(run.id))
    registry_id = uuid5(NAMESPACE_URL, f"finance-agent:run-context-bundle:{run.id}")
    metadata = dict(descriptor["metadata"])
    if conflicting_winner:
        metadata["content_hash"] = "f" * 64
    winner = RunArtifact(
        artifact_id=registry_id,
        run_id=run.id,
        task_id=step.id,
        artifact_type="structured_json",
        file_path=descriptor["file_path"],
        sha256=descriptor["sha256"],
        artifact_metadata=metadata,
    )

    def lose_concurrent_insert(*args, **kwargs):
        raise IntegrityError("INSERT", {}, RuntimeError("duplicate primary key"))

    monkeypatch.setattr(artifact_registration, "register_artifact", lose_concurrent_insert)
    monkeypatch.setattr(db, "get", lambda model, identity: winner if identity == registry_id else None)

    if conflicting_winner:
        with pytest.raises(ValueError, match="identity conflicts"):
            register_context_bundle_artifact(
                db,
                run_id=str(run.id),
                step=step,
                descriptor=descriptor,
                storage_root=tmp_path,
            )
    else:
        assert (
            register_context_bundle_artifact(
                db,
                run_id=str(run.id),
                step=step,
                descriptor=descriptor,
                storage_root=tmp_path,
            )
            is winner
        )


def test_context_bundle_registration_rejects_step_lineage_and_invalid_payload(tmp_path) -> None:
    db = _session()
    run, step = _run_step(db)
    descriptor = _valid_descriptor(tmp_path, run_id=str(run.id))

    with pytest.raises(ValueError, match="step.task_run_id"):
        register_context_bundle_artifact(
            db,
            run_id=str(uuid4()),
            step=step,
            descriptor=descriptor,
            storage_root=tmp_path,
        )

    tampered = {**descriptor, "sha256": "A" * 64}
    with pytest.raises(ValueError, match="file identity is incomplete"):
        register_context_bundle_artifact(db, run_id=str(run.id), step=step, descriptor=tampered, storage_root=tmp_path)


def test_context_bundle_registry_is_compatible_when_table_is_absent(tmp_path) -> None:
    db = _session(execution_tables=False)
    run, step = _run_step(db)
    assert (
        register_context_bundle_artifact(
            db,
            run_id=str(run.id),
            step=step,
            descriptor=_valid_descriptor(tmp_path, run_id=str(run.id)),
            storage_root=tmp_path,
        )
        is None
    )


def test_same_run_selector_returns_validated_descriptor_and_rejects_tampering(tmp_path) -> None:
    db = _session()
    run, _step, descriptor, row = _register_valid_bundle(db, tmp_path)

    selected = select_context_bundle_artifact_for_run(db, run_id=str(run.id), storage_root=tmp_path)
    _assert_descriptor_identity(selected, descriptor)
    assert selected["sha256"] == descriptor["sha256"]

    path = tmp_path / row.file_path
    path.write_text(path.read_text(encoding="utf-8").replace("XAUUSD", "XAUUSZ", 1), encoding="utf-8")
    with pytest.raises(ValueError, match="file hash mismatch"):
        select_context_bundle_artifact_for_run(db, run_id=str(run.id), storage_root=tmp_path)


def test_same_run_selector_rejects_metadata_payload_identity_conflict(tmp_path) -> None:
    db = _session()
    run, _step, _descriptor_value, row = _register_valid_bundle(db, tmp_path)
    row.artifact_metadata = {**row.artifact_metadata, "content_hash": "0" * 64}
    db.flush()

    with pytest.raises(ValueError, match="payload identity conflicts"):
        select_context_bundle_artifact_for_run(db, run_id=str(run.id), storage_root=tmp_path)


def test_same_run_selector_rejects_multiple_bundle_rows(tmp_path) -> None:
    db = _session()
    run, step, _descriptor_one, _row = _register_valid_bundle(db, tmp_path)
    descriptor_two = _valid_descriptor(tmp_path, run_id=str(run.id), cutoff_at=NOW + timedelta(minutes=2))
    second = RunArtifact(
        run_id=run.id,
        task_id=step.id,
        artifact_type="structured_json",
        file_path=descriptor_two["file_path"],
        sha256=descriptor_two["sha256"],
        artifact_metadata=descriptor_two["metadata"],
    )
    db.add(second)
    db.flush()
    with pytest.raises(ValueError, match="ambiguous ContextBundle"):
        select_context_bundle_artifact_for_run(db, run_id=str(run.id), storage_root=tmp_path)


def test_worker_registry_input_resolver_distinguishes_restart_and_prior_run(tmp_path) -> None:
    db = _session()
    prior, _step, prior_descriptor, _row = _register_valid_bundle(db, tmp_path)
    canonical_input = {
        "state_scope": "daily_close",
        "canonical_state_id": "state-79",
        "canonical_state": {"asset": "XAUUSD"},
        "cutoff_at": NOW + timedelta(hours=1),
        "previous_bundle_path": "caller-must-not-be-authority.json",
    }

    restart = _resolve_state_shadow_registry_inputs(
        db=db,
        run_id=str(prior.id),
        storage_root=tmp_path,
        state_shadow_input=canonical_input,
    )
    _assert_descriptor_identity(restart["context_bundle_artifact"], prior_descriptor)
    assert "previous_bundle_path" not in restart

    current, _current_step = _run_step(db)
    previous = _resolve_state_shadow_registry_inputs(
        db=db,
        run_id=str(current.id),
        storage_root=tmp_path,
        state_shadow_input=canonical_input,
    )
    _assert_descriptor_identity(previous["previous_context_bundle_artifact"], prior_descriptor)
    assert "context_bundle_artifact" not in previous


@pytest.mark.parametrize(
    "field, value", [("asset", "EURUSD"), ("state_scope", "intraday"), ("canonical_state_id", "other-state")]
)
def test_previous_selector_excludes_wrong_lineage(tmp_path, field, value) -> None:
    db = _session()
    current, _ = _run_step(db)
    kwargs = {field: value}
    _register_valid_bundle(db, tmp_path, **kwargs)
    assert (
        select_previous_context_bundle_artifact(
            db,
            current_run_id=str(current.id),
            asset="XAUUSD",
            state_scope="daily_close",
            canonical_state_id="state-79",
            cutoff_at=NOW + timedelta(hours=1),
            storage_root=tmp_path,
        )
        is None
    )


def test_previous_selector_excludes_current_run_and_returns_none_without_match(tmp_path) -> None:
    db = _session()
    run, _step, descriptor, _row = _register_valid_bundle(db, tmp_path)
    assert (
        select_previous_context_bundle_artifact(
            db,
            current_run_id=str(run.id),
            asset="XAUUSD",
            state_scope="daily_close",
            canonical_state_id="state-79",
            cutoff_at=NOW + timedelta(hours=1),
            storage_root=tmp_path,
        )
        is None
    )
    selected = select_context_bundle_artifact_for_run(db, run_id=str(run.id), storage_root=tmp_path)
    _assert_descriptor_identity(selected, descriptor)


def test_previous_selector_excludes_bundles_after_cutoff(tmp_path) -> None:
    db = _session()
    current, _ = _run_step(db)
    _register_valid_bundle(db, tmp_path, cutoff_at=NOW + timedelta(hours=1))
    assert (
        select_previous_context_bundle_artifact(
            db,
            current_run_id=str(current.id),
            asset="XAUUSD",
            state_scope="daily_close",
            canonical_state_id="state-79",
            cutoff_at=NOW,
            storage_root=tmp_path,
        )
        is None
    )


def test_previous_selector_ignores_more_than_limit_unrelated_structured_artifacts(tmp_path) -> None:
    db = _session()
    current, _ = _run_step(db)
    _prior, _step, descriptor, _row = _register_valid_bundle(db, tmp_path)
    for index in range(129):
        db.add(
            RunArtifact(
                run_id=uuid4(),
                artifact_type="structured_json",
                file_path=f"outputs/unrelated/{index}.json",
                artifact_metadata={"artifact_family": "unrelated"},
            )
        )
    db.flush()

    selected = select_previous_context_bundle_artifact(
        db,
        current_run_id=str(current.id),
        asset="XAUUSD",
        state_scope="daily_close",
        canonical_state_id="state-79",
        cutoff_at=NOW + timedelta(hours=1),
        storage_root=tmp_path,
    )
    _assert_descriptor_identity(selected, descriptor)


def test_previous_selector_returns_latest_and_fails_closed_on_ambiguous_latest(tmp_path) -> None:
    db = _session()
    current, _ = _run_step(db)
    older, _step, older_descriptor, _ = _register_valid_bundle(db, tmp_path, cutoff_at=NOW - timedelta(hours=2))
    latest, latest_step, latest_descriptor, latest_row = _register_valid_bundle(
        db, tmp_path, cutoff_at=NOW - timedelta(hours=1)
    )

    selected = select_previous_context_bundle_artifact(
        db,
        current_run_id=str(current.id),
        asset="XAUUSD",
        state_scope="daily_close",
        canonical_state_id="state-79",
        cutoff_at=NOW,
        storage_root=tmp_path,
    )
    _assert_descriptor_identity(selected, latest_descriptor)
    assert selected["metadata"]["bundle_id"] != older_descriptor["metadata"]["bundle_id"]

    duplicate = RunArtifact(
        run_id=latest.id,
        task_id=latest_step.id,
        artifact_type="structured_json",
        file_path=latest_descriptor["file_path"],
        sha256=latest_descriptor["sha256"],
        artifact_metadata=latest_descriptor["metadata"],
        created_at=latest_row.created_at,
    )
    db.add(duplicate)
    db.flush()
    with pytest.raises(ValueError, match="latest candidate is ambiguous"):
        select_previous_context_bundle_artifact(
            db,
            current_run_id=str(current.id),
            asset="XAUUSD",
            state_scope="daily_close",
            canonical_state_id="state-79",
            cutoff_at=NOW,
            storage_root=tmp_path,
        )


def test_bundle_registry_failure_does_not_skip_legacy_artifact_registration(monkeypatch) -> None:
    registered = []

    def fail_bundle(*args, **kwargs):
        raise ValueError("conflicting bundle identity")

    def capture_legacy(*args, **kwargs):
        registered.append(kwargs)
        return []

    monkeypatch.setattr("apps.worker.artifact_registration.register_context_bundle_artifact", fail_bundle)
    monkeypatch.setattr("apps.worker.artifact_registration.register_step_artifacts", capture_legacy)
    outputs = {
        "context_bundle_registry_artifact": {"metadata": {"bundle_id": "bundle-conflict"}},
        "report_result": {"paths": ["outputs/final_report/report.md"]},
        "card_result": {"paths": ["outputs/strategy_card/card.json"]},
        "agent_loop_decision": SimpleNamespace(publish_allowed=True),
    }

    register_composite_output_artifacts(
        SimpleNamespace(), run_id="run-79", steps=[SimpleNamespace(name="report_render")], composite_outputs=outputs
    )

    assert outputs["context_bundle_registry_status"] == {
        "status": "failed",
        "bundle_id": "bundle-conflict",
        "reason": "ValueError:conflicting bundle identity",
    }
    assert len(registered) == 1


def test_nested_transaction_rolls_back_bundle_failure_and_legacy_registration_survives(tmp_path, monkeypatch) -> None:
    db = _session()
    run, step = _run_step(db)
    legacy_calls = []

    def capture_legacy(*args, **kwargs):
        legacy_calls.append(kwargs)
        return []

    def write_then_fail(db, **_kwargs):
        db.add(
            RunArtifact(
                run_id=run.id,
                task_id=step.id,
                artifact_type="structured_json",
                file_path="outputs/context_bundles/failed.json",
            )
        )
        db.flush()
        raise ValueError("forced nested failure")

    monkeypatch.setattr("apps.worker.artifact_registration.register_step_artifacts", capture_legacy)
    monkeypatch.setattr("apps.worker.artifact_registration.register_context_bundle_artifact", write_then_fail)
    outputs = {
        "context_bundle_registry_artifact": {"metadata": {"bundle_id": "bad"}},
        "report_result": {"paths": ["outputs/final_report/report.md"]},
        "card_result": {"paths": ["outputs/strategy_card/card.json"]},
        "agent_loop_decision": SimpleNamespace(publish_allowed=False),
    }
    register_composite_output_artifacts(
        db, run_id=str(run.id), steps=[step], composite_outputs=outputs, storage_root=tmp_path
    )
    db.commit()
    assert outputs["context_bundle_registry_status"]["status"] == "failed"
    assert db.get(TaskRun, run.id) is not None
    assert db.query(RunArtifact).filter(RunArtifact.run_id == run.id).count() == 0
    assert len(legacy_calls) == 1
