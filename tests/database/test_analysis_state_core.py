"""Focused contracts for immutable analysis state and canonical-head CAS."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, func, inspect, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateIndex, CreateTable

from apps.analysis.state import (
    ANALYSIS_STATE_SCHEMA_VERSION,
    AnalysisStateDocument,
    AnalysisTransitionDocument,
    CanonicalHeadConflictError,
    StateChange,
    StateIdempotencyConflictError,
    StateMaterializationAuthority,
    TransitionAction,
    advance_canonical_head,
    append_analysis_state,
    get_canonical_state,
    get_state_history,
    list_candidate_states,
)
from apps.analysis.state.hashing import canonical_json, content_hash
from database.models.analysis import AnalysisBase
from database.models.analysis_state import AnalysisState, AnalysisStateHead, AnalysisTransition


def _state_document(*, thesis: str, as_of: datetime | None = None) -> AnalysisStateDocument:
    return AnalysisStateDocument(
        asset="XAUUSD",
        as_of=as_of or datetime(2026, 7, 22, 8, tzinfo=UTC),
        market_stage="direction_decision",
        core_thesis=thesis,
        net_bias="mixed_bullish",
        dominant_drivers=[{"name": "real_yield", "direction": "headwind"}],
        key_levels=[{"price": 4126.63, "role": "gamma_zero"}],
        scenario_states=[{"name": "base", "status": "active"}],
        unresolved_items=[{"item": "breakout", "status": "pending"}],
        invalidation_conditions=[{"condition": "close_below_4000"}],
        evidence_cursors={"market": {"ingested_at": "2026-07-22T08:00:00Z"}},
        input_snapshot_ids={"market": "market-20260722"},
        source_refs=[{"source": "market_snapshot", "snapshot_id": "market-20260722"}],
    )


def _transition(*, action: TransitionAction = TransitionAction.MAINTAIN) -> AnalysisTransitionDocument:
    return AnalysisTransitionDocument(
        summary="State transition",
        changes=[
            StateChange(
                target="core_thesis",
                action=action,
                reason="New evidence confirmed the current thesis",
                evidence_refs=[{"snapshot_id": "market-20260722"}],
            )
        ],
        evidence_refs=[{"snapshot_id": "market-20260722"}],
    )


def _accepted_authority() -> StateMaterializationAuthority:
    return StateMaterializationAuthority(
        quality_gate_action="pass",
        publish_allowed=True,
        accepted_output_source="primary",
        accepted_output_agent_name="coordinator_agent",
        accepted_output_snapshot_id="market-20260722",
    )


def _candidate_authority() -> StateMaterializationAuthority:
    return StateMaterializationAuthority(
        quality_gate_action="manual_review",
        publish_allowed=False,
    )


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    AnalysisBase.metadata.create_all(engine)
    with Session(engine) as db:
        yield db


def test_contract_has_stable_schema_version_actions_and_aware_time() -> None:
    assert ANALYSIS_STATE_SCHEMA_VERSION == "1.0"
    assert {action.value for action in TransitionAction} == {
        "strengthen",
        "maintain",
        "weaken",
        "invalidate",
        "pending",
    }
    with pytest.raises(ValidationError, match="timezone"):
        _state_document(thesis="invalid", as_of=datetime(2026, 7, 22, 8))


def test_content_hash_ignores_only_top_level_identity_metadata() -> None:
    first = {"id": "row-a", "created_at": "old", "source_ref": {"id": "source-a"}}
    same_business_content = {"id": "row-b", "created_at": "new", "source_ref": {"id": "source-a"}}
    different_source = {"id": "row-b", "created_at": "new", "source_ref": {"id": "source-b"}}

    assert canonical_json(first) == canonical_json(same_business_content)
    assert content_hash(first) != content_hash(different_source)


def test_authority_requires_both_quality_pass_and_accepted_output() -> None:
    with pytest.raises(ValidationError, match="publish_allowed"):
        StateMaterializationAuthority(
            quality_gate_action="pass",
            publish_allowed=False,
            accepted_output_source="primary",
            accepted_output_agent_name="coordinator_agent",
            accepted_output_snapshot_id="market-20260722",
        )
    with pytest.raises(ValidationError, match="publish_allowed"):
        StateMaterializationAuthority(quality_gate_action="manual_review", publish_allowed=True)
    with pytest.raises(ValidationError, match="must not be blank"):
        StateMaterializationAuthority(
            quality_gate_action="pass",
            publish_allowed=True,
            accepted_output_source="primary",
            accepted_output_agent_name=" ",
            accepted_output_snapshot_id="market-20260722",
        )


def test_append_is_content_hashed_and_idempotent(session: Session) -> None:
    document = _state_document(thesis="Hold above 4000 while awaiting breakout")
    transition = _transition()

    first = append_analysis_state(
        session,
        document=document,
        transition=transition,
        authority=_candidate_authority(),
        previous_state_id=None,
        task_run_id="run-1",
    )
    replay = append_analysis_state(
        session,
        document=document,
        transition=transition,
        authority=_candidate_authority(),
        previous_state_id=None,
        task_run_id="run-1",
    )

    assert replay.id == first.id
    assert first.content_hash == content_hash(document)
    assert session.scalar(select(func.count()).select_from(AnalysisState)) == 1
    assert session.scalar(select(func.count()).select_from(AnalysisTransition)) == 1


def test_reusing_explicit_state_id_with_different_content_is_rejected(session: Session) -> None:
    state = append_analysis_state(
        session,
        document=_state_document(thesis="First thesis"),
        transition=_transition(),
        authority=_candidate_authority(),
        previous_state_id=None,
        task_run_id="run-1",
        state_id="fixed-state-id",
    )

    with pytest.raises(StateIdempotencyConflictError, match="different immutable content"):
        append_analysis_state(
            session,
            document=_state_document(thesis="Conflicting thesis"),
            transition=_transition(action=TransitionAction.WEAKEN),
            authority=_candidate_authority(),
            previous_state_id=None,
            task_run_id="run-1",
            state_id=state.id,
        )


def test_state_and_transition_are_append_only(session: Session) -> None:
    state = append_analysis_state(
        session,
        document=_state_document(thesis="Immutable thesis"),
        transition=_transition(),
        authority=_candidate_authority(),
        previous_state_id=None,
        task_run_id="run-1",
    )
    session.commit()

    state.asset = "GC"
    with pytest.raises(RuntimeError, match="append-only"):
        session.commit()
    session.rollback()

    transition = session.scalar(select(AnalysisTransition).where(AnalysisTransition.to_state_id == state.id))
    assert transition is not None
    session.delete(transition)
    with pytest.raises(RuntimeError, match="append-only"):
        session.commit()


def test_candidate_is_listed_but_cannot_advance_canonical_head(session: Session) -> None:
    authority = _candidate_authority()
    candidate = append_analysis_state(
        session,
        document=_state_document(thesis="Needs review"),
        transition=_transition(action=TransitionAction.PENDING),
        authority=authority,
        previous_state_id=None,
        task_run_id="run-review",
    )

    assert [state.id for state in list_candidate_states(session, "XAUUSD")] == [candidate.id]
    with pytest.raises(PermissionError, match="QualityGate PASS"):
        advance_canonical_head(
            session,
            asset="XAUUSD",
            new_state_id=candidate.id,
            expected_state_id=None,
            expected_version=0,
            authority=authority,
        )


def test_canonical_head_advance_and_replay_are_idempotent(session: Session) -> None:
    authority = _accepted_authority()
    state = append_analysis_state(
        session,
        document=_state_document(thesis="Accepted thesis"),
        transition=_transition(action=TransitionAction.STRENGTHEN),
        authority=authority,
        previous_state_id=None,
        task_run_id="run-pass",
    )

    first = advance_canonical_head(
        session,
        asset="XAUUSD",
        new_state_id=state.id,
        expected_state_id=None,
        expected_version=0,
        authority=authority,
    )
    replay = advance_canonical_head(
        session,
        asset="XAUUSD",
        new_state_id=state.id,
        expected_state_id=None,
        expected_version=0,
        authority=authority,
    )

    assert replay.id == first.id
    assert replay.version == 1
    assert get_canonical_state(session, "XAUUSD").id == state.id


def test_stale_worker_cannot_overwrite_canonical_head(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'cas.sqlite'}")
    AnalysisBase.metadata.create_all(engine)
    authority = _accepted_authority()

    with Session(engine) as seed:
        root = append_analysis_state(
            seed,
            document=_state_document(thesis="Root"),
            transition=_transition(),
            authority=authority,
            previous_state_id=None,
            task_run_id="run-root",
        )
        advance_canonical_head(
            seed,
            asset="XAUUSD",
            new_state_id=root.id,
            expected_state_id=None,
            expected_version=0,
            authority=authority,
        )
        first_candidate = append_analysis_state(
            seed,
            document=_state_document(
                thesis="First worker",
                as_of=datetime(2026, 7, 22, 9, tzinfo=UTC),
            ),
            transition=_transition(action=TransitionAction.STRENGTHEN),
            authority=authority,
            previous_state_id=root.id,
            task_run_id="run-worker-a",
        )
        second_candidate = append_analysis_state(
            seed,
            document=_state_document(
                thesis="Second worker",
                as_of=datetime(2026, 7, 22, 9, tzinfo=UTC) + timedelta(seconds=1),
            ),
            transition=_transition(action=TransitionAction.WEAKEN),
            authority=authority,
            previous_state_id=root.id,
            task_run_id="run-worker-b",
        )
        root_id = root.id
        first_id = first_candidate.id
        second_id = second_candidate.id
        seed.commit()

    with Session(engine) as worker_a, Session(engine) as worker_b:
        head_a = worker_a.scalar(select(AnalysisStateHead).where(AnalysisStateHead.asset == "XAUUSD"))
        head_b = worker_b.scalar(select(AnalysisStateHead).where(AnalysisStateHead.asset == "XAUUSD"))
        assert head_a is not None and head_b is not None
        assert (head_a.canonical_state_id, head_a.version) == (root_id, 1)
        assert (head_b.canonical_state_id, head_b.version) == (root_id, 1)

        advance_canonical_head(
            worker_a,
            asset="XAUUSD",
            new_state_id=first_id,
            expected_state_id=root_id,
            expected_version=1,
            authority=authority,
        )
        worker_a.commit()

        with pytest.raises(CanonicalHeadConflictError, match="compare-and-swap conflict"):
            advance_canonical_head(
                worker_b,
                asset="XAUUSD",
                new_state_id=second_id,
                expected_state_id=root_id,
                expected_version=1,
                authority=authority,
            )

    with Session(engine) as verify:
        head = verify.scalar(select(AnalysisStateHead).where(AnalysisStateHead.asset == "XAUUSD"))
        assert head is not None
        assert (head.canonical_state_id, head.version) == (first_id, 2)


def test_state_history_follows_previous_state_chain(session: Session) -> None:
    authority = _candidate_authority()
    root = append_analysis_state(
        session,
        document=_state_document(thesis="Root"),
        transition=_transition(),
        authority=authority,
        previous_state_id=None,
        task_run_id="run-root",
    )
    child = append_analysis_state(
        session,
        document=_state_document(
            thesis="Child",
            as_of=datetime(2026, 7, 22, 9, tzinfo=UTC),
        ),
        transition=_transition(action=TransitionAction.STRENGTHEN),
        authority=authority,
        previous_state_id=root.id,
        task_run_id="run-child",
    )

    assert [state.id for state in get_state_history(session, child.id)] == [child.id, root.id]


def test_models_compile_for_postgresql_with_jsonb() -> None:
    ddl = "\n".join(
        str(CreateTable(model.__table__).compile(dialect=postgresql.dialect()))
        for model in (AnalysisState, AnalysisStateHead, AnalysisTransition)
    )

    assert "CREATE TABLE analysis_states" in ddl
    assert "CREATE TABLE analysis_state_heads" in ddl
    assert "CREATE TABLE analysis_transitions" in ddl
    assert "JSONB" in ddl
    index_ddl = "\n".join(
        str(CreateIndex(index).compile(dialect=postgresql.dialect()))
        for model in (AnalysisState, AnalysisStateHead, AnalysisTransition)
        for index in model.__table__.indexes
    )
    assert "USING gin" in index_ddl


def test_alembic_upgrade_creates_analysis_state_core_tables(tmp_path: Path) -> None:
    from database.migrations.runtime import run_database_migrations

    database_url = f"sqlite:///{tmp_path / 'migration.sqlite'}"
    run_database_migrations(database_url)

    table_names = set(inspect(create_engine(database_url)).get_table_names())
    assert {"analysis_states", "analysis_state_heads", "analysis_transitions"} <= table_names
