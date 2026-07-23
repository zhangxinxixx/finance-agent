from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from apps.analysis.agents.quality_gate import (
    AcceptedOutputReference,
    AgentLoopDecision,
)
from apps.analysis.agents.quality_gate_evaluator import (
    QualityGateAction,
    QualityGateDecision,
)
from apps.analysis.state import (
    AnalysisStateDocument,
    AnalysisStateDocumentV11,
    AnalysisTransitionDocumentV11,
    AnalysisTransitionDocument,
    StateChange,
    StateMaterializationAuthority,
    TransitionAction,
    TransitionCandidate,
    TransitionReviewError,
    advance_canonical_head,
    append_analysis_state,
    get_canonical_state,
    materialize_reviewed_transition,
    materialize_reviewed_transition_scoped,
    review_transition_candidate,
    review_transition_candidate_scoped,
    parse_analysis_state_document,
)
from apps.analysis.state.hashing import content_hash
from database.models.analysis import AnalysisBase
from database.models.analysis_state import AnalysisState, AnalysisStateHead, AnalysisTransition


NOW = datetime(2026, 7, 22, 8, tzinfo=UTC)
REF = {"snapshot_id": "market-20260722"}


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    AnalysisBase.metadata.create_all(engine)
    with Session(engine) as db:
        yield db


def _document(*, thesis: str, as_of: datetime = NOW) -> AnalysisStateDocument:
    return AnalysisStateDocument(
        asset="XAUUSD",
        as_of=as_of,
        market_stage="direction_decision",
        core_thesis=thesis,
        net_bias="mixed_bullish",
        dominant_drivers=[{"name": "real_yield", "direction": "headwind"}],
        key_levels=[{"price": 4000, "role": "support"}],
        scenario_states=[{"name": "base", "status": "active"}],
        unresolved_items=[{"item": "breakout", "status": "pending"}],
        invalidation_conditions=[{"condition": "close_below_4000"}],
        evidence_cursors={"market": {"ingested_at": NOW.isoformat()}},
        input_snapshot_ids={"market": "market-20260722"},
        source_refs=[REF],
    )


def _authority() -> StateMaterializationAuthority:
    return StateMaterializationAuthority(
        quality_gate_action="pass",
        publish_allowed=True,
        accepted_output_source="primary",
        accepted_output_agent_name="coordinator_agent",
        accepted_output_snapshot_id="market-20260722",
    )


def _seed_canonical(session: Session) -> tuple[AnalysisState, AnalysisStateDocument]:
    document = _document(thesis="等待突破")
    state = append_analysis_state(
        session,
        document=document,
        transition=AnalysisTransitionDocument(
            summary="bootstrap",
            changes=[
                StateChange(
                    target="core_thesis",
                    action=TransitionAction.MAINTAIN,
                    reason="bootstrap",
                    evidence_refs=[REF],
                )
            ],
            evidence_refs=[REF],
        ),
        authority=_authority(),
        previous_state_id=None,
        task_run_id="run-root",
    )
    advance_canonical_head(
        session,
        asset="XAUUSD",
        new_state_id=state.id,
        expected_state_id=None,
        expected_version=0,
        authority=_authority(),
    )
    return state, document


def _candidate(
    previous_state_id: str,
    *,
    thesis: str = "突破确认",
    as_of: datetime = NOW + timedelta(hours=1),
) -> TransitionCandidate:
    return TransitionCandidate(
        previous_state_id=previous_state_id,
        summary="价格突破后强化主线",
        changes=[
            StateChange(
                target="core_thesis",
                action=TransitionAction.STRENGTHEN,
                reason="价格确认",
                evidence_refs=[REF],
            ),
            StateChange(
                target="as_of",
                action=TransitionAction.STRENGTHEN,
                reason="新证据时间",
                evidence_refs=[REF],
            ),
        ],
        state_patch={"core_thesis": thesis, "as_of": as_of},
        evidence_refs=[REF],
    )


def _gate(action: QualityGateAction) -> QualityGateDecision:
    return QualityGateDecision(
        action=action,
        review_status="pass" if action is QualityGateAction.PASS else "needs_review",
        publish_allowed=action is QualityGateAction.PASS,
    )


def _loop(*, accepted: bool) -> AgentLoopDecision:
    return AgentLoopDecision(
        decision="passed" if accepted else "needs_review",
        review_status="pass" if accepted else "needs_review",
        publish_allowed=accepted,
        accepted_output=(
            AcceptedOutputReference(
                source="primary",
                agent_name="coordinator_agent",
                snapshot_id="market-20260722",
            )
            if accepted
            else AcceptedOutputReference()
        ),
    )


def _review(root: AnalysisState, document: AnalysisStateDocument):
    return review_transition_candidate(
        candidate=_candidate(root.id),
        previous_state_id=root.id,
        previous_state=document,
        available_evidence_refs=[REF],
    )


def test_scoped_review_upgrades_v1_predecessor_without_rehashing_it(session: Session) -> None:
    root, legacy = _seed_canonical(session)
    root_payload = dict(root.payload)
    root_hash = root.content_hash
    review = review_transition_candidate_scoped(
        candidate=_candidate(root.id),
        previous_state_id=root.id,
        previous_state=legacy,
        available_evidence_refs=[REF],
        state_scope="daily_close",
        state_machine_version="analysis_state.v1.1",
        session="daily_close",
        trade_date=NOW.date(),
    )

    assert isinstance(review.next_state, AnalysisStateDocumentV11)
    assert isinstance(review.transition, AnalysisTransitionDocumentV11)
    assert review.next_state.state_scope == "daily_close"
    assert review.previous_state_content_hash == root_hash
    other_scope = review.transition.model_copy(update={"state_scope": "intraday"})
    assert content_hash(other_scope) != review.transition_content_hash

    with pytest.raises(TypeError, match="state_scope"):
        materialize_reviewed_transition_scoped(  # type: ignore[call-arg]
            session,
            review=review,
            quality_gate=_gate(QualityGateAction.PASS),
            agent_loop=_loop(accepted=True),
            task_run_id="run-missing-scope",
            expected_head_version=1,
        )
    with pytest.raises(TransitionReviewError, match="materialization scope"):
        materialize_reviewed_transition_scoped(
            session,
            state_scope="intraday",
            review=review,
            quality_gate=_gate(QualityGateAction.PASS),
            agent_loop=_loop(accepted=True),
            task_run_id="run-cross-scope",
            expected_head_version=1,
        )

    result = materialize_reviewed_transition_scoped(
        session,
        state_scope="daily_close",
        review=review,
        quality_gate=_gate(QualityGateAction.PASS),
        agent_loop=_loop(accepted=True),
        task_run_id="run-v11-upgrade",
        expected_head_version=1,
    )
    child = session.get(AnalysisState, result.state_id)
    transition = session.scalar(
        select(AnalysisTransition).where(AnalysisTransition.to_state_id == child.id)
    )
    assert root.payload == root_payload
    assert root.content_hash == root_hash
    assert child.schema_version == "1.1"
    assert child.state_scope == "daily_close"
    assert transition.schema_version == "1.1"
    assert transition.state_scope == "daily_close"


def test_candidate_rejects_unknown_action_and_unreviewed_patch() -> None:
    payload = _candidate("state-1").model_dump(mode="json")
    payload["changes"][0]["action"] = "invented"
    with pytest.raises(ValidationError, match="action"):
        TransitionCandidate.model_validate(payload)

    payload = _candidate("state-1").model_dump(mode="json")
    payload["state_patch"]["net_bias"] = "bearish"
    with pytest.raises(ValidationError, match="lack matching changes"):
        TransitionCandidate.model_validate(payload)

    payload = _candidate("state-1").model_dump(mode="json")
    payload["changes"][0]["target"] = "invented_state_field"
    payload["state_patch"].pop("core_thesis")
    with pytest.raises(ValidationError, match="non-patchable targets"):
        TransitionCandidate.model_validate(payload)

    payload = _candidate("state-1").model_dump(mode="json")
    payload["changes"].append(dict(payload["changes"][0]))
    with pytest.raises(ValidationError, match="repeat a state target"):
        TransitionCandidate.model_validate(payload)


def test_fact_review_checks_previous_state_and_evidence_refs() -> None:
    document = _document(thesis="等待突破")
    with pytest.raises(TransitionReviewError, match="previous_state_id"):
        review_transition_candidate(
            candidate=_candidate("stale-state"),
            previous_state_id="canonical-state",
            previous_state=document,
            available_evidence_refs=[REF],
        )

    mutated = _candidate("canonical-state")
    mutated.state_patch["net_bias"] = "bearish"
    with pytest.raises(ValidationError, match="lack matching changes"):
        review_transition_candidate(
            candidate=mutated,
            previous_state_id="canonical-state",
            previous_state=document,
            available_evidence_refs=[REF],
        )
    with pytest.raises(TransitionReviewError, match="outside the reviewed bundle"):
        review_transition_candidate(
            candidate=_candidate("canonical-state"),
            previous_state_id="canonical-state",
            previous_state=document,
            available_evidence_refs=[{"snapshot_id": "different"}],
        )

    stale_time = _candidate("canonical-state").model_dump(mode="python")
    stale_time["state_patch"]["as_of"] = NOW
    with pytest.raises(TransitionReviewError, match="as_of"):
        review_transition_candidate(
            candidate=stale_time,
            previous_state_id="canonical-state",
            previous_state=document,
            available_evidence_refs=[REF],
        )


def test_pass_and_authoritative_output_advance_canonical(session: Session) -> None:
    root, document = _seed_canonical(session)
    result = materialize_reviewed_transition(
        session,
        review=_review(root, document),
        quality_gate=_gate(QualityGateAction.PASS),
        agent_loop=_loop(accepted=True),
        task_run_id="run-pass",
        expected_head_version=1,
    )

    assert result.disposition == "canonical_accepted"
    assert result.canonical_advanced is True
    assert result.canonical_version == 2
    canonical = get_canonical_state(session, "XAUUSD")
    assert canonical is not None
    assert canonical.payload["core_thesis"] == "突破确认"


def test_manual_review_appends_candidate_without_advancing_head(session: Session) -> None:
    root, document = _seed_canonical(session)
    result = materialize_reviewed_transition(
        session,
        review=_review(root, document),
        quality_gate=_gate(QualityGateAction.MANUAL_REVIEW),
        agent_loop=_loop(accepted=False),
        task_run_id="run-review",
        expected_head_version=1,
    )

    assert result.disposition == "manual_review_candidate"
    assert result.state_id is not None
    assert result.canonical_advanced is False
    assert get_canonical_state(session, "XAUUSD").id == root.id
    assert session.get(AnalysisState, result.state_id).publish_allowed is False


@pytest.mark.parametrize(
    ("action", "disposition"),
    [
        (QualityGateAction.RETRY, "retry"),
        (QualityGateAction.FALLBACK, "fallback"),
        (QualityGateAction.BLOCK_PUBLISH, "blocked"),
    ],
)
def test_non_materializing_gates_never_append_or_advance(
    session: Session, action: QualityGateAction, disposition: str
) -> None:
    root, document = _seed_canonical(session)
    before = session.scalar(select(func.count()).select_from(AnalysisState))

    result = materialize_reviewed_transition(
        session,
        review=_review(root, document),
        quality_gate=_gate(action),
        agent_loop=_loop(accepted=False),
        task_run_id=f"run-{action.value}",
        expected_head_version=1,
    )

    assert result.disposition == disposition
    assert session.scalar(select(func.count()).select_from(AnalysisState)) == before
    assert get_canonical_state(session, "XAUUSD").id == root.id


def test_pass_without_agentloop_accepted_output_is_rejected(session: Session) -> None:
    root, document = _seed_canonical(session)
    with pytest.raises(PermissionError, match="accepted_output"):
        materialize_reviewed_transition(
            session,
            review=_review(root, document),
            quality_gate=_gate(QualityGateAction.PASS),
            agent_loop=_loop(accepted=False),
            task_run_id="run-invalid-pass",
            expected_head_version=1,
        )


def test_materializer_rejects_forged_previous_document(session: Session) -> None:
    root, document = _seed_canonical(session)
    forged = document.model_copy(update={"core_thesis": "伪造前态"})
    review = review_transition_candidate(
        candidate=_candidate(root.id),
        previous_state_id=root.id,
        previous_state=forged,
        available_evidence_refs=[REF],
    )

    with pytest.raises(TransitionReviewError, match="persisted state"):
        materialize_reviewed_transition(
            session,
            review=review,
            quality_gate=_gate(QualityGateAction.PASS),
            agent_loop=_loop(accepted=True),
            task_run_id="run-forged",
            expected_head_version=1,
        )


def test_non_pass_gate_cannot_carry_accepted_output(session: Session) -> None:
    root, document = _seed_canonical(session)
    with pytest.raises(PermissionError, match="non-PASS"):
        materialize_reviewed_transition(
            session,
            review=_review(root, document),
            quality_gate=_gate(QualityGateAction.MANUAL_REVIEW),
            agent_loop=_loop(accepted=True),
            task_run_id="run-contradictory",
            expected_head_version=1,
        )


def test_materializer_revalidates_review_after_nested_mutation(session: Session) -> None:
    root, document = _seed_canonical(session)
    review = _review(root, document)
    review.next_state.key_levels.append({"price": 9999, "role": "tampered"})

    with pytest.raises(ValidationError, match="next_state changed after review"):
        materialize_reviewed_transition(
            session,
            review=review,
            quality_gate=_gate(QualityGateAction.PASS),
            agent_loop=_loop(accepted=True),
            task_run_id="run-mutated-review",
            expected_head_version=1,
        )


def test_materialization_replay_is_idempotent(session: Session) -> None:
    root, document = _seed_canonical(session)
    review = _review(root, document)
    first = materialize_reviewed_transition(
        session,
        review=review,
        quality_gate=_gate(QualityGateAction.PASS),
        agent_loop=_loop(accepted=True),
        task_run_id="run-pass",
        expected_head_version=1,
    )
    replay = materialize_reviewed_transition(
        session,
        review=review,
        quality_gate=_gate(QualityGateAction.PASS),
        agent_loop=_loop(accepted=True),
        task_run_id="run-pass",
        expected_head_version=1,
    )

    assert replay.state_id == first.state_id
    assert replay.canonical_version == 2
    assert session.scalar(select(func.count()).select_from(AnalysisStateHead)) == 1


def test_rollback_creates_new_state_without_mutating_history(session: Session) -> None:
    root, original = _seed_canonical(session)
    forward_review = _review(root, original)
    forward = materialize_reviewed_transition(
        session,
        review=forward_review,
        quality_gate=_gate(QualityGateAction.PASS),
        agent_loop=_loop(accepted=True),
        task_run_id="run-forward",
        expected_head_version=1,
    )
    forward_state = session.get(AnalysisState, forward.state_id)
    forward_document = parse_analysis_state_document(forward_state.payload)
    rollback = review_transition_candidate(
        candidate=_candidate(
            forward.state_id,
            thesis=original.core_thesis,
            as_of=NOW + timedelta(hours=2),
        ),
        previous_state_id=forward.state_id,
        previous_state=forward_document,
        available_evidence_refs=[REF],
    )
    rolled_back = materialize_reviewed_transition(
        session,
        review=rollback,
        quality_gate=_gate(QualityGateAction.PASS),
        agent_loop=_loop(accepted=True),
        task_run_id="run-rollback",
        expected_head_version=2,
    )

    assert rolled_back.state_id not in {root.id, forward.state_id}
    assert session.get(AnalysisState, forward.state_id).payload["core_thesis"] == "突破确认"
    assert get_canonical_state(session, "XAUUSD").payload["core_thesis"] == "等待突破"
