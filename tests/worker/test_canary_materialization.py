from __future__ import annotations

import json
import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from apps.analysis.agents.quality_gate import (
    AcceptedOutputArtifactRef,
    AcceptedOutputReference,
    AgentLoopDecision,
)
from apps.analysis.agents.quality_gate_evaluator import QualityGateAction, QualityGateDecision
from apps.analysis.context_bundle import assemble_context_bundle, project_context_bundle
from apps.analysis.agents.schemas import AgentBias, AgentOutput, AgentStatus
from apps.analysis.state import (
    ANALYSIS_STATE_MACHINE_VERSION,
    AnalysisStateDocumentV11,
    AnalysisTransitionDocumentV11,
    StateChange,
    StateMaterializationAuthority,
    SystemStateMetadataPatch,
    TransitionAction,
    TransitionCandidate,
    advance_canonical_head_scoped,
    append_analysis_state_scoped,
    review_transition_candidate_scoped,
)
from apps.analysis.state.hashing import content_hash
from apps.analysis.state.transition_generator import ScopedTransitionCandidate
from apps.output.context_bundle import write_context_bundle
from apps.runtime.artifact_registry import (
    select_canary_terminal_result_for_run,
    select_context_bundle_artifact_for_run,
    select_exact_context_bundle_artifact,
)
from apps.worker.canary_materialization import (
    CANARY_CONSUMERS,
    CanaryActivation,
    CanaryAuthorityPayload,
    CanaryMaterializationRequest,
    CanaryMaterializationResult,
    compute_canary_agent_loop_hash,
    compute_canary_quality_gate_hash,
    mark_canary_recompute_result,
    materialize_canary_request,
    resolve_canary_activation,
)
from apps.worker.artifact_registration import register_context_bundle_artifact
from database.models.analysis import AnalysisBase, AnalysisSnapshot
from database.models.analysis_state import (
    AnalysisState,
    AnalysisStateHead,
    AnalysisTransition,
    CanaryAttempt,
)
from database.queries.canary_approvals import (
    CanaryApprovalConsumptionError,
    consume_canary_approval,
    issue_canary_approval,
)
from database.queries.canary_attempts import (
    authorize_canary_recompute,
    create_or_resume_canary_attempt,
)
from database.models.execution import RunArtifact, ensure_execution_tables
from database.models.task import Base as TaskBase
from database.models.task import StepStatus, TaskRun, TaskStep, TaskStatus


NOW = datetime(2026, 7, 26, 8, tzinfo=UTC)
REF = {"snapshot_id": "market-20260726"}
RUN_ID = "canary-run-26"


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    AnalysisBase.metadata.create_all(engine)
    with Session(engine) as db:
        yield db


def _authority() -> StateMaterializationAuthority:
    return StateMaterializationAuthority(
        quality_gate_action="pass",
        publish_allowed=True,
        accepted_output_source="primary",
        accepted_output_agent_name="coordinator_agent",
        accepted_output_snapshot_id="market-20260726",
    )


def _document(*, scope: str, thesis: str) -> AnalysisStateDocumentV11:
    return AnalysisStateDocumentV11(
        state_scope=scope,
        state_machine_version=ANALYSIS_STATE_MACHINE_VERSION,
        session="regular" if scope == "intraday" else scope,
        trade_date=NOW.date(),
        asset="XAUUSD",
        as_of=NOW,
        market_stage="direction_decision",
        core_thesis=thesis,
        net_bias="mixed_bullish",
        dominant_drivers=[],
        key_levels=[],
        scenario_states=[],
        unresolved_items=[],
        invalidation_conditions=[],
        evidence_cursors={},
        input_snapshot_ids={"market": "market-20260726"},
        source_refs=[REF],
    )


def _seed_head(session: Session, *, scope: str) -> AnalysisState:
    document = _document(scope=scope, thesis=f"{scope} root")
    transition = AnalysisTransitionDocumentV11(
        state_scope=scope,
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
    )
    state = append_analysis_state_scoped(
        session,
        state_scope=scope,
        document=document,
        transition=transition,
        authority=_authority(),
        previous_state_id=None,
        task_run_id=f"root-{scope}",
    )
    advance_canonical_head_scoped(
        session,
        asset="XAUUSD",
        state_scope=scope,
        new_state_id=state.id,
        expected_state_id=None,
        expected_version=0,
        authority=_authority(),
    )
    session.flush()
    return state


def _gate() -> QualityGateDecision:
    return QualityGateDecision(
        action=QualityGateAction.PASS,
        review_status="pass",
        publish_allowed=True,
    )


def _loop() -> AgentLoopDecision:
    return AgentLoopDecision(
        decision="passed",
        review_status="pass",
        publish_allowed=True,
        accepted_output=AcceptedOutputReference(
            source="primary",
            agent_name="coordinator_agent",
            snapshot_id="market-20260726",
            artifact_ref=AcceptedOutputArtifactRef(
                final_report_paths=["outputs/reports/XAUUSD/2026-07-26/report.md"],
                strategy_card_paths=["outputs/strategy/XAUUSD/2026-07-26/card.json"],
            ),
        ),
    )


def _accepted_output(review, *, typed: bool = True, conclusion_update: dict | None = None) -> AgentOutput:
    conclusion = {
        "net_bias": review.next_state.net_bias,
        "market_stage": review.next_state.market_stage,
        "core_thesis": review.next_state.core_thesis,
        "dominant_drivers": [item.model_dump(mode="json") for item in review.next_state.dominant_drivers],
    }
    conclusion.update(conclusion_update or {})
    return AgentOutput(
        version="v1",
        agent_name="coordinator_agent",
        module="tests",
        snapshot_id="market-20260726",
        input_snapshot_ids={},
        input_payload={"accepted_state_conclusion": conclusion} if typed else {},
        bias=AgentBias(conclusion["net_bias"]),
        confidence=0.8,
        key_findings=[],
        risk_points=[],
        watchlist=[],
        summary="typed accepted conclusion fixture",
        source_refs=[REF],
        status=AgentStatus.SUCCESS,
        created_at=NOW,
    )


def _authority_payload(
    *,
    root: AnalysisState,
    run_id: str,
    review,
    bundle=None,
    accepted_typed: bool = True,
    conclusion_update: dict | None = None,
) -> CanaryAuthorityPayload:
    bundle = bundle or assemble_context_bundle(
        run_id=run_id,
        asset="XAUUSD",
        state_scope="daily_close",
        canonical_state_id=root.id,
        canonical_state=dict(root.payload),
        evidence=[],
        evidence_cursors={},
        cutoff_at=NOW,
        assembled_at=NOW,
        expected_session="daily_close",
    )
    projections = {consumer: project_context_bundle(bundle, consumer=consumer) for consumer in CANARY_CONSUMERS}

    def bind_projection(
        output: AgentOutput,
        *,
        consumer: str,
    ) -> AgentOutput:
        projection = projections[consumer]
        return output.model_copy(
            update={
                "input_snapshot_ids": {
                    "context_bundle_id": bundle.bundle_id,
                    "context_bundle_hash": bundle.content_hash,
                    "context_bundle_run_id": run_id,
                    "context_bundle_projection_hash": projection.projection_hash,
                    "canonical_state_id": root.id,
                    "state_scope": "daily_close",
                    "retained_evidence_ids": [
                        {"source": item["source"], "evidence_id": item["evidence_id"]}
                        for item in sorted(
                            projection.retained_evidence,
                            key=lambda item: (item["source"], item["evidence_id"]),
                        )
                    ],
                    "evidence_delta_decision_id": projection.decision_id,
                },
                "input_payload": {
                    **dict(output.input_payload or {}),
                    "context_bundle_consumer": consumer,
                    "context_bundle_projection": projection.model_dump(mode="json"),
                },
            }
        )

    def output_for(agent_name: str, consumer: str) -> AgentOutput:
        return bind_projection(
            AgentOutput(
                version="v1",
                agent_name=agent_name,
                module="tests",
                snapshot_id=("fact-review-80" if agent_name == "fact_review_agent" else "market-20260726"),
                input_snapshot_ids={},
                input_payload={},
                bias=AgentBias.NEUTRAL,
                confidence=0.5,
                key_findings=[],
                risk_points=[],
                watchlist=[],
                summary=f"{agent_name} reviewed",
                source_refs=[REF],
                status=AgentStatus.SUCCESS,
                created_at=NOW,
            ),
            consumer=consumer,
        )

    accepted = bind_projection(
        _accepted_output(
            review,
            typed=accepted_typed,
            conclusion_update=conclusion_update,
        ),
        consumer="coordinator",
    )
    gate_inputs = [
        output_for("macro_liquidity_agent", "macro"),
        output_for("cme_options_agent", "options"),
        output_for("risk_agent", "risk"),
        output_for("technical_agent", "technical"),
        output_for("positioning_agent", "positioning"),
        output_for("news_agent", "news"),
        output_for("market_odds_agent", "market_odds"),
        output_for("fact_review_agent", "fact_review"),
        accepted,
    ]
    return CanaryAuthorityPayload.build(
        context_bundle_id=bundle.bundle_id,
        context_bundle_hash=bundle.content_hash,
        run_id=run_id,
        canonical_state_id=root.id,
        consumer_projections=projections,
        quality_gate_inputs=gate_inputs,
        accepted_output_reference=_loop().accepted_output,
        accepted_output=accepted,
        transition_review=review,
    )


def _request(
    root: AnalysisState,
    *,
    expected_version: int = 1,
    run_id: str = RUN_ID,
    next_as_of: datetime = NOW + timedelta(hours=1),
    thesis: str = "daily close breakout confirmed",
    bundle=None,
    accepted_typed: bool = True,
    conclusion_update: dict | None = None,
):
    previous = AnalysisStateDocumentV11.model_validate(root.payload)
    candidate = TransitionCandidate(
        previous_state_id=root.id,
        summary="daily close breakout",
        changes=[
            StateChange(
                target="core_thesis",
                action=TransitionAction.STRENGTHEN,
                reason="confirmed market evidence",
                evidence_refs=[REF],
            ),
            StateChange(
                target="net_bias",
                action=TransitionAction.MAINTAIN,
                reason="typed accepted conclusion bias",
                evidence_refs=[REF],
            ),
        ],
        state_patch={"core_thesis": thesis, "net_bias": "mixed"},
        evidence_refs=[REF],
    )
    review = review_transition_candidate_scoped(
        candidate=candidate,
        previous_state_id=root.id,
        previous_state=previous,
        available_evidence_refs=[REF],
        state_scope="daily_close",
        state_machine_version=ANALYSIS_STATE_MACHINE_VERSION,
        session="daily_close",
        trade_date=NOW.date(),
        system_metadata=SystemStateMetadataPatch(
            as_of=next_as_of,
            evidence_cursors={},
            input_snapshot_ids=(
                {
                    "context_bundle_id": bundle.bundle_id,
                    "context_bundle_hash": bundle.content_hash,
                    "context_bundle_run_id": bundle.run_id,
                    "canonical_state_id": bundle.canonical_state_id,
                }
                if bundle is not None
                else {"context_bundle_id": "bundle-test"}
            ),
            source_refs=[REF],
            state_scope="daily_close",
            state_machine_version=ANALYSIS_STATE_MACHINE_VERSION,
            session="daily_close",
            trade_date=NOW.date(),
        ),
    )
    gate, loop = _gate(), _loop()
    authority = _authority_payload(
        root=root,
        run_id=run_id,
        review=review,
        bundle=bundle,
        accepted_typed=accepted_typed,
        conclusion_update=conclusion_update,
    )
    request = CanaryMaterializationRequest(
        asset="XAUUSD",
        trade_date=NOW.date(),
        run_id=run_id,
        state_scope="daily_close",
        canonical_state_id=root.id,
        expected_head_version=expected_version,
        approval_id=f"approval-{run_id}",
        approval_hash="f" * 64,
        activation_source="persistent_approval",
        activation_identity=f"approval-{run_id}",
        context_bundle_id=authority.context_bundle_id,
        context_bundle_hash=authority.context_bundle_hash,
        consumer_projection_hashes={
            name: projection.projection_hash for name, projection in authority.consumer_projections.items()
        },
        fact_review_snapshot_id=authority.fact_review_output.snapshot_id,
        authority_hash=authority.authority_hash,
        quality_gate_hash=compute_canary_quality_gate_hash(gate, authority_hash=authority.authority_hash),
        agent_loop_hash=compute_canary_agent_loop_hash(loop, authority_hash=authority.authority_hash),
        review=review,
    )
    return request, gate, loop, authority


def _activation_input(**controls: object) -> dict[str, object]:
    return {
        "asset": "XAUUSD",
        "trade_date": NOW.date().isoformat(),
        "state_scope": "daily_close",
        "canonical_state_id": "state-80",
        "expected_head_version": 3,
        **controls,
    }


def test_scoped_candidate_cannot_escape_xauusd_daily_close_lineage() -> None:
    candidate = TransitionCandidate(
        previous_state_id="state-80",
        summary="unchanged",
        changes=[
            StateChange(
                target="core_thesis",
                action=TransitionAction.MAINTAIN,
                reason="no material delta",
                evidence_refs=[REF],
            )
        ],
        evidence_refs=[REF],
    )
    scoped = ScopedTransitionCandidate(
        asset="XAUUSD",
        state_scope="daily_close",
        run_id=RUN_ID,
        canonical_state_id="state-80",
        context_bundle_id="bundle-80",
        context_bundle_hash="a" * 64,
        candidate=candidate,
    )
    assert scoped.candidate.previous_state_id == scoped.canonical_state_id
    with pytest.raises(ValueError, match="previous_state_id"):
        ScopedTransitionCandidate.model_validate(
            {**scoped.model_dump(mode="json"), "canonical_state_id": "other-state"}
        )


def test_canary_activation_requires_persistent_approval_and_rejects_legacy_controls(
    session: Session,
) -> None:
    base = _activation_input()
    approval = issue_canary_approval(
        session,
        approval_id="approval-80",
        asset="XAUUSD",
        state_scope="daily_close",
        trade_date=NOW.date(),
        run_id=RUN_ID,
        approved_by="review-center",
        approved_role="canary_approver",
        approved_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(hours=1),
    )
    activation = resolve_canary_activation(
        snapshot_asset="XAUUSD",
        snapshot_trade_date=NOW.date(),
        run_id=RUN_ID,
        shadow_input=base,
        approval=approval,
    )
    assert activation.activation_source == "persistent_approval"
    assert activation.activation_identity == approval.approval_id

    with pytest.raises(ValueError, match="persistent canary approval is required"):
        resolve_canary_activation(
            snapshot_asset="XAUUSD",
            snapshot_trade_date=NOW.date(),
            run_id=RUN_ID,
            shadow_input=base,
            approval=None,
        )
    for field, value in (
        ("canary_trade_dates", [NOW.date().isoformat()]),
        ("canary_run_ids", [RUN_ID]),
        ("canary_manual_request", {"request_id": "forged"}),
        ("canary_enabled", True),
    ):
        with pytest.raises(ValueError, match="caller-owned"):
            resolve_canary_activation(
                snapshot_asset="XAUUSD",
                snapshot_trade_date=NOW.date(),
                run_id=RUN_ID,
                shadow_input=_activation_input(**{field: value}),
                approval=approval,
            )


def test_runner_rejects_missing_or_caller_owned_authority_before_registry_or_sidecar(
    session: Session, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.worker import runner

    def unexpected_registry(*args, **kwargs):
        raise AssertionError("approval rejection must happen before terminal/sidecar lookup")

    monkeypatch.setattr(runner, "select_canary_terminal_result_for_run", unexpected_registry)
    snapshot = {"asset": "XAUUSD", "trade_date": NOW.date().isoformat()}
    with pytest.raises(ValueError, match="canary_approval_id"):
        runner._resolve_canary_runner_activation(
            session,
            attempt_session_factory=lambda: Session(session.get_bind()),
            storage_root=tmp_path,
            analysis_snapshot=snapshot,
            run_id=RUN_ID,
            state_shadow_input=_activation_input(),
            canary_approval_id=None,
            now=NOW,
        )
    with pytest.raises(ValueError, match="caller-owned"):
        runner._resolve_canary_runner_activation(
            session,
            attempt_session_factory=lambda: Session(session.get_bind()),
            storage_root=tmp_path,
            analysis_snapshot=snapshot,
            run_id=RUN_ID,
            state_shadow_input=_activation_input(canary_run_ids=[RUN_ID]),
            canary_approval_id="forged-approval",
            now=NOW,
        )


def test_runner_loads_persistent_approval_before_building_activation(tmp_path) -> None:
    from apps.worker import runner

    engine = create_engine("sqlite+pysqlite:///:memory:")
    AnalysisBase.metadata.create_all(engine)
    ensure_execution_tables(engine)
    runner_run_id = "00000000-0000-0000-0000-000000000080"
    with Session(engine) as db:
        approval = issue_canary_approval(
            db,
            approval_id="runner-approval",
            asset="XAUUSD",
            state_scope="daily_close",
            trade_date=NOW.date(),
            run_id=runner_run_id,
            approved_by="review-center",
            approved_role="canary_approver",
            approved_at=NOW - timedelta(minutes=1),
            expires_at=NOW + timedelta(hours=1),
        )
        db.commit()
        recovered, activation, attempt = runner._resolve_canary_runner_activation(
            db,
            attempt_session_factory=lambda: Session(engine),
            storage_root=tmp_path,
            analysis_snapshot={"asset": "XAUUSD", "trade_date": NOW.date().isoformat()},
            run_id=runner_run_id,
            state_shadow_input=_activation_input(),
            canary_approval_id=approval.approval_id,
            now=NOW,
        )
    assert recovered is None
    assert attempt is None
    assert activation is not None
    assert activation.approval_id == approval.approval_id
    assert activation.activation_source == "persistent_approval"


def test_request_requires_nine_projections_and_matching_gate_hash(session: Session) -> None:
    root = _seed_head(session, scope="daily_close")
    request, gate, loop, authority = _request(root)
    assert request.schema_version == "analysis_state_canary_request.v4"
    assert authority.schema_version == "analysis_state_canary_authority.v2"
    with pytest.raises(ValueError, match="schema_version"):
        CanaryAuthorityPayload.model_validate(
            {
                **authority.model_dump(mode="json"),
                "schema_version": "analysis_state_canary_authority.v1",
            }
        )
    with pytest.raises(ValueError, match="schema_version"):
        CanaryMaterializationRequest.model_validate(
            {**request.model_dump(mode="json"), "schema_version": "analysis_state_canary_request.v3"}
        )
    with pytest.raises(ValueError, match="nine canary consumers"):
        CanaryMaterializationRequest.model_validate(
            {**request.model_dump(mode="json"), "consumer_projection_hashes": {"macro": "a" * 64}}
        )
    mismatch = materialize_canary_request(
        session,
        request=request.model_copy(update={"quality_gate_hash": "b" * 64}),
        quality_gate=gate,
        agent_loop=loop,
        task_run_id=RUN_ID,
        authority_payload=authority,
    )
    assert mismatch.status == "failed"
    assert "quality_gate_hash" in mismatch.reason
    with pytest.raises(ValueError, match="task_run_id"):
        materialize_canary_request(
            session,
            request=request,
            quality_gate=gate,
            agent_loop=loop,
            task_run_id="other-run",
            authority_payload=authority,
        )


def test_materializer_revalidates_forged_activation_and_authority_payload(session: Session) -> None:
    root = _seed_head(session, scope="daily_close")
    request, gate, loop, authority = _request(root)
    forged_activation = request.model_copy(update={"activation_identity": "other-run"})
    with pytest.raises(ValueError, match="persistent approval"):
        materialize_canary_request(
            session,
            request=forged_activation,
            quality_gate=gate,
            agent_loop=loop,
            task_run_id=RUN_ID,
            authority_payload=authority,
        )

    mismatched_fact_review = authority.fact_review_output.model_copy(update={"snapshot_id": "other-fact-review"})
    mismatched_authority = CanaryAuthorityPayload.build(
        context_bundle_id=authority.context_bundle_id,
        context_bundle_hash=authority.context_bundle_hash,
        run_id=authority.run_id,
        canonical_state_id=authority.canonical_state_id,
        consumer_projections=authority.consumer_projections,
        quality_gate_inputs=[
            mismatched_fact_review if output.agent_name == "fact_review_agent" else output
            for output in authority.agent_outputs.values()
        ],
        accepted_output_reference=authority.accepted_output_reference,
        accepted_output=authority.accepted_output,
        transition_review=request.review,
    )
    mismatched_request = request.model_copy(
        update={
            "authority_hash": mismatched_authority.authority_hash,
            "quality_gate_hash": compute_canary_quality_gate_hash(
                gate, authority_hash=mismatched_authority.authority_hash
            ),
            "agent_loop_hash": compute_canary_agent_loop_hash(loop, authority_hash=mismatched_authority.authority_hash),
        }
    )
    result = materialize_canary_request(
        session,
        request=mismatched_request,
        quality_gate=gate,
        agent_loop=loop,
        task_run_id=RUN_ID,
        authority_payload=mismatched_authority,
    )
    assert result.status == "failed"
    assert "FactReview snapshot" in result.reason


@pytest.mark.parametrize(
    ("request_kwargs", "expected_status"),
    [
        ({"accepted_typed": False}, "unverifiable"),
        ({"conclusion_update": {"net_bias": "bearish"}}, "conflicting"),
        (
            {"conclusion_update": {"core_thesis": "different accepted thesis"}},
            "partially_consistent",
        ),
    ],
)
def test_non_consistent_transition_never_advances_canonical(
    session: Session, request_kwargs: dict, expected_status: str
) -> None:
    root = _seed_head(session, scope="daily_close")
    request, gate, loop, authority = _request(root, **request_kwargs)

    assert authority.transition_consistency.status == expected_status
    result = materialize_canary_request(
        session,
        request=request,
        quality_gate=gate,
        agent_loop=loop,
        task_run_id=RUN_ID,
        authority_payload=authority,
    )

    assert result.status == "observe_only"
    assert result.materialization_disposition == "manual_review_required"
    assert result.canonical_advanced is False
    head = session.scalar(
        select(AnalysisStateHead).where(
            AnalysisStateHead.asset == "XAUUSD",
            AnalysisStateHead.state_scope == "daily_close",
        )
    )
    assert head.canonical_state_id == root.id


def test_authority_hash_detects_consistency_and_accepted_output_tampering(
    session: Session,
) -> None:
    root = _seed_head(session, scope="daily_close")
    _request_value, _gate_value, _loop_value, authority = _request(root)
    payload = authority.model_dump(mode="json")
    payload["transition_consistency"]["status"] = "conflicting"
    with pytest.raises(ValueError, match="transition_consistency_hash"):
        CanaryAuthorityPayload.model_validate(payload)

    payload = authority.model_dump(mode="json")
    payload["accepted_output"]["summary"] = "tampered accepted output"
    with pytest.raises(ValueError, match="accepted_output_hash"):
        CanaryAuthorityPayload.model_validate(payload)


def test_authority_rejects_agent_map_hash_gate_order_and_artifact_tampering(
    session: Session,
) -> None:
    root = _seed_head(session, scope="daily_close")
    _request_value, _gate_value, _loop_value, authority = _request(root)

    payload = authority.model_dump(mode="json")
    payload["agent_outputs"]["risk_agent"]["summary"] = "tampered risk"
    with pytest.raises(ValueError, match="agent_output_hashes does not match risk_agent"):
        CanaryAuthorityPayload.model_validate(payload)

    payload = authority.model_dump(mode="json")
    payload["agent_outputs"]["risk_agent"], payload["agent_outputs"]["news_agent"] = (
        payload["agent_outputs"]["news_agent"],
        payload["agent_outputs"]["risk_agent"],
    )
    with pytest.raises(ValueError, match="key must match agent_name"):
        CanaryAuthorityPayload.model_validate(payload)

    payload = authority.model_dump(mode="json")
    payload["agent_outputs"].pop("technical_agent")
    with pytest.raises(ValueError, match="exactly the nine canary AgentOutputs"):
        CanaryAuthorityPayload.model_validate(payload)

    payload = authority.model_dump(mode="json")
    payload["quality_gate_input_hashes"] = payload["quality_gate_input_hashes"][:-1]
    with pytest.raises(ValueError, match="exact ordered gate inputs"):
        CanaryAuthorityPayload.model_validate(payload)

    payload = authority.model_dump(mode="json")
    payload["accepted_output_reference"]["artifact_ref"]["final_report_paths"] = ["outputs/reports/tampered.md"]
    with pytest.raises(ValueError, match="accepted_artifact_hash"):
        CanaryAuthorityPayload.model_validate(payload)


def test_primary_accepted_output_is_bound_coordinator_and_fallback_is_independent(
    session: Session,
) -> None:
    root = _seed_head(session, scope="daily_close")
    request, _gate_value, _loop_value, authority = _request(root)
    mismatched_primary = authority.accepted_output.model_copy(update={"summary": "different primary coordinator"})
    payload = authority.model_dump(mode="json")
    payload["accepted_output"] = mismatched_primary.model_dump(mode="json")
    payload["accepted_output_hash"] = content_hash(
        mismatched_primary.model_dump(mode="json", exclude_computed_fields=True),
        exclude_keys=frozenset(),
    )
    payload["transition_consistency"]["accepted_output_hash"] = payload["accepted_output_hash"]
    payload["transition_consistency_hash"] = content_hash(payload["transition_consistency"], exclude_keys=frozenset())
    with pytest.raises(ValueError, match="accepted primary output must equal"):
        CanaryAuthorityPayload.model_validate(payload)

    fallback = authority.accepted_output.model_copy(
        update={
            "agent_name": "fallback_synthesis_agent",
            "summary": "independent accepted fallback",
        }
    )
    fallback_reference = AcceptedOutputReference(
        source="corrective_fallback",
        agent_name=fallback.agent_name,
        snapshot_id=fallback.snapshot_id,
        artifact_ref=AcceptedOutputArtifactRef(final_report_paths=["outputs/reports/XAUUSD/2026-07-26/fallback.md"]),
    )
    fallback_authority = CanaryAuthorityPayload.build(
        context_bundle_id=authority.context_bundle_id,
        context_bundle_hash=authority.context_bundle_hash,
        run_id=authority.run_id,
        canonical_state_id=authority.canonical_state_id,
        consumer_projections=authority.consumer_projections,
        quality_gate_inputs=list(authority.agent_outputs.values()),
        accepted_output_reference=fallback_reference,
        accepted_output=fallback,
        transition_review=request.review,
    )
    assert fallback_authority.accepted_output_hash != fallback_authority.agent_output_hashes["coordinator_agent"]
    assert fallback_authority.accepted_output_reference.source == "corrective_fallback"


def test_savepoint_advances_only_daily_scope_and_rolls_back_cas_conflict(session: Session) -> None:
    intraday = _seed_head(session, scope="intraday")
    daily = _seed_head(session, scope="daily_close")
    request, gate, loop, authority = _request(daily)
    advanced = materialize_canary_request(
        session, request=request, quality_gate=gate, agent_loop=loop, task_run_id=RUN_ID, authority_payload=authority
    )
    assert advanced.status == "canonical_advanced"
    assert advanced.canonical_version == 2
    intraday_head = session.scalar(select(AnalysisStateHead).where(AnalysisStateHead.state_scope == "intraday"))
    assert intraday_head.canonical_state_id == intraday.id

    before_states = session.scalar(select(func.count()).select_from(AnalysisState))
    before_transitions = session.scalar(select(func.count()).select_from(AnalysisTransition))
    stale_request, stale_gate, stale_loop, stale_authority = _request(daily, expected_version=1, run_id="stale-run")
    stale = materialize_canary_request(
        session,
        request=stale_request,
        quality_gate=stale_gate,
        agent_loop=stale_loop,
        task_run_id="stale-run",
        authority_payload=stale_authority,
    )
    assert stale.status == "recompute_required"
    assert stale.legacy_output_preserved is True
    assert session.scalar(select(func.count()).select_from(AnalysisState)) == before_states
    assert session.scalar(select(func.count()).select_from(AnalysisTransition)) == before_transitions


def test_approval_consumption_failure_rolls_back_canonical_advance(session: Session) -> None:
    root = _seed_head(session, scope="daily_close")
    request, gate, loop, authority = _request(root)
    with pytest.raises(CanaryApprovalConsumptionError, match="does not exist"):
        with session.begin_nested():
            result = materialize_canary_request(
                session,
                request=request,
                quality_gate=gate,
                agent_loop=loop,
                task_run_id=RUN_ID,
                authority_payload=authority,
            )
            assert result.status == "canonical_advanced"
            consume_canary_approval(
                session,
                approval_id=request.approval_id,
                expected_approval_hash=request.approval_hash,
                run_id=RUN_ID,
                consumed_at=NOW,
            )
    session.expire_all()
    head = session.scalar(
        select(AnalysisStateHead).where(
            AnalysisStateHead.asset == "XAUUSD",
            AnalysisStateHead.state_scope == "daily_close",
        )
    )
    assert head.canonical_state_id == root.id


def test_second_conflict_is_terminal_and_keeps_one_hop_supersession() -> None:
    first = CanaryMaterializationResult(
        status="recompute_required",
        asset="XAUUSD",
        trade_date=NOW.date(),
        run_id=RUN_ID,
        state_scope="daily_close",
        approval_id="approval-recompute",
        approval_hash="f" * 64,
        activation_source="persistent_approval",
        activation_identity="approval-recompute",
        context_bundle_id="bundle-stale",
        context_bundle_hash="a" * 64,
        requested_canonical_state_id="state-stale",
        expected_head_version=1,
        recompute_required=True,
        latest_canonical_state_id="state-fresh",
        latest_head_version=2,
    )
    assert first.schema_version == "analysis_state_canary_result.v4"
    with pytest.raises(ValueError, match="schema_version"):
        CanaryMaterializationResult.model_validate(
            {**first.model_dump(mode="json"), "schema_version": "analysis_state_canary_result.v3"}
        )
    second = first.model_copy(
        update={
            "context_bundle_id": "bundle-fresh",
            "context_bundle_hash": "b" * 64,
            "expected_head_version": 2,
            "latest_head_version": 3,
        }
    )
    terminal = mark_canary_recompute_result(second, superseded=first, trace={"fresh_bundle": True})
    assert terminal.status == "failed"
    assert terminal.recompute_required is False
    assert terminal.recompute_attempt_count == 1
    assert terminal.superseded_context_bundle_id == "bundle-stale"
    assert terminal.reason == "canonical_head_compare_and_swap_conflict_after_recompute"


def test_exact_context_bundle_selector_revalidates_complete_identity(tmp_path) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    TaskBase.metadata.create_all(engine)
    AnalysisBase.metadata.create_all(engine)
    ensure_execution_tables(engine)
    with Session(engine) as db:
        source_run = TaskRun(name="source", status=TaskStatus.success)
        retry_run = TaskRun(name="retry", status=TaskStatus.running)
        db.add_all([source_run, retry_run])
        db.flush()
        source_step = TaskStep(
            task_run_id=source_run.id,
            name="report_render",
            status=StepStatus.success,
        )
        db.add(source_step)
        root = _seed_head(db, scope="daily_close")
        bundle = assemble_context_bundle(
            run_id=str(source_run.id),
            asset="XAUUSD",
            state_scope="daily_close",
            canonical_state_id=root.id,
            canonical_state=dict(root.payload),
            evidence=[],
            evidence_cursors={},
            cutoff_at=NOW,
            assembled_at=NOW,
            expected_session="daily_close",
        )
        descriptor = write_context_bundle(storage_root=tmp_path, bundle=bundle).registry_artifact
        register_context_bundle_artifact(
            db,
            run_id=str(source_run.id),
            step=source_step,
            descriptor=descriptor,
            storage_root=tmp_path,
        )

        selected = select_exact_context_bundle_artifact(
            db,
            bundle_id=bundle.bundle_id,
            content_hash=bundle.content_hash,
            run_id=str(source_run.id),
            asset="XAUUSD",
            state_scope="daily_close",
            base_canonical_state_id=root.id,
            current_run_id=str(retry_run.id),
            storage_root=tmp_path,
        )
        assert selected is not None
        assert selected["metadata"]["canonical_state_id"] == root.id
        for overrides in (
            {"state_scope": "intraday"},
            {"base_canonical_state_id": "wrong-predecessor"},
            {"content_hash": "0" * 64},
            {"run_id": str(uuid.uuid4())},
        ):
            arguments = {
                "bundle_id": bundle.bundle_id,
                "content_hash": bundle.content_hash,
                "run_id": str(source_run.id),
                "asset": "XAUUSD",
                "state_scope": "daily_close",
                "base_canonical_state_id": root.id,
                "current_run_id": str(retry_run.id),
                "storage_root": tmp_path,
                **overrides,
            }
            assert select_exact_context_bundle_artifact(db, **arguments) is None
        with pytest.raises(ValueError, match="different run"):
            select_exact_context_bundle_artifact(
                db,
                bundle_id=bundle.bundle_id,
                content_hash=bundle.content_hash,
                run_id=str(source_run.id),
                asset="XAUUSD",
                state_scope="daily_close",
                base_canonical_state_id=root.id,
                current_run_id=str(source_run.id),
                storage_root=tmp_path,
            )

        path = tmp_path / descriptor["file_path"]
        path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        with pytest.raises(ValueError, match="file hash mismatch"):
            select_exact_context_bundle_artifact(
                db,
                bundle_id=bundle.bundle_id,
                content_hash=bundle.content_hash,
                run_id=str(source_run.id),
                asset="XAUUSD",
                state_scope="daily_close",
                base_canonical_state_id=root.id,
                current_run_id=str(retry_run.id),
                storage_root=tmp_path,
            )


def test_exact_context_bundle_selector_rejects_ambiguous_registry_identity(tmp_path) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    TaskBase.metadata.create_all(engine)
    AnalysisBase.metadata.create_all(engine)
    ensure_execution_tables(engine)
    with Session(engine) as db:
        source_run = TaskRun(name="source", status=TaskStatus.success)
        retry_run = TaskRun(name="retry", status=TaskStatus.running)
        db.add_all([source_run, retry_run])
        db.flush()
        source_step = TaskStep(task_run_id=source_run.id, name="report_render", status=StepStatus.success)
        db.add(source_step)
        root = _seed_head(db, scope="daily_close")
        bundle = assemble_context_bundle(
            run_id=str(source_run.id),
            asset="XAUUSD",
            state_scope="daily_close",
            canonical_state_id=root.id,
            canonical_state=dict(root.payload),
            evidence=[],
            evidence_cursors={},
            cutoff_at=NOW,
            assembled_at=NOW,
            expected_session="daily_close",
        )
        descriptor = write_context_bundle(storage_root=tmp_path, bundle=bundle).registry_artifact
        registered = register_context_bundle_artifact(
            db,
            run_id=str(source_run.id),
            step=source_step,
            descriptor=descriptor,
            storage_root=tmp_path,
        )
        db.add(
            RunArtifact(
                artifact_id=uuid.uuid4(),
                run_id=source_run.id,
                task_id=source_step.id,
                artifact_type=registered.artifact_type,
                file_path=registered.file_path,
                storage_backend=registered.storage_backend,
                sha256=registered.sha256,
                content_type=registered.content_type,
                source_refs_data=list(registered.source_refs_data or []),
                artifact_metadata=dict(registered.artifact_metadata or {}),
            )
        )
        db.flush()

        with pytest.raises(ValueError, match="ambiguous"):
            select_exact_context_bundle_artifact(
                db,
                bundle_id=bundle.bundle_id,
                content_hash=bundle.content_hash,
                run_id=str(source_run.id),
                asset="XAUUSD",
                state_scope="daily_close",
                base_canonical_state_id=root.id,
                current_run_id=str(retry_run.id),
                storage_root=tmp_path,
            )


def test_runner_recompute_executes_full_fresh_attempt_before_second_cas(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.worker import runner

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'recompute.db'}")
    TaskBase.metadata.create_all(engine)
    AnalysisBase.metadata.create_all(engine)
    ensure_execution_tables(engine)
    with Session(engine) as db:
        task = TaskRun(name="premarket-retry", status=TaskStatus.running)
        source_task = TaskRun(name="premarket-concurrent", status=TaskStatus.success)
        db.add_all([task, source_task])
        db.flush()
        task_run_id = str(task.id)
        approval_id = f"approval-{task.id}"
        approval_record = issue_canary_approval(
            db,
            approval_id=approval_id,
            asset="XAUUSD",
            state_scope="daily_close",
            trade_date=NOW.date(),
            run_id=task_run_id,
            approved_by="review-center",
            approved_role="canary_approver",
            approved_at=NOW - timedelta(minutes=1),
            expires_at=NOW + timedelta(days=1),
        )
        report_step = TaskStep(
            task_run_id=task.id,
            name="report_render",
            status=StepStatus.success,
        )
        source_report_step = TaskStep(
            task_run_id=source_task.id,
            name="report_render",
            status=StepStatus.success,
        )
        db.add_all([report_step, source_report_step])
        root = _seed_head(db, scope="daily_close")
        snapshot = AnalysisSnapshot(
            snapshot_id="market-20260726",
            asset="XAUUSD",
            trade_date=NOW.date(),
            run_id=str(task.id),
            snapshot_time=NOW,
            input_snapshot_ids={},
            source_refs=[REF],
            payload={},
            payload_sha256=content_hash({}, exclude_keys=frozenset()),
            artifact_path="outputs/snapshots/canary.json",
        )
        db.add(snapshot)
        db.flush()

        original_bundle = assemble_context_bundle(
            run_id=str(task.id),
            asset="XAUUSD",
            state_scope="daily_close",
            canonical_state_id=root.id,
            canonical_state=dict(root.payload),
            evidence=[],
            evidence_cursors={},
            cutoff_at=NOW,
            assembled_at=NOW,
            expected_session="daily_close",
        )
        original_descriptor = write_context_bundle(
            storage_root=tmp_path,
            bundle=original_bundle,
        ).registry_artifact
        register_context_bundle_artifact(
            db,
            run_id=str(task.id),
            step=report_step,
            descriptor=original_descriptor,
            storage_root=tmp_path,
        )
        source_bundle = assemble_context_bundle(
            run_id=str(source_task.id),
            asset="XAUUSD",
            state_scope="daily_close",
            canonical_state_id=root.id,
            canonical_state=dict(root.payload),
            evidence=[],
            evidence_cursors={},
            cutoff_at=NOW,
            assembled_at=NOW + timedelta(minutes=1),
            expected_session="daily_close",
        )
        source_descriptor = write_context_bundle(
            storage_root=tmp_path,
            bundle=source_bundle,
        ).registry_artifact
        register_context_bundle_artifact(
            db,
            run_id=str(source_task.id),
            step=source_report_step,
            descriptor=source_descriptor,
            storage_root=tmp_path,
        )
        stale_request, stale_gate, stale_loop, stale_authority = _request(
            root, run_id=str(task.id), bundle=original_bundle
        )
        stale_request = stale_request.model_copy(update={"approval_hash": approval_record.approval_hash})
        concurrent_request, concurrent_gate, concurrent_loop, concurrent_authority = _request(
            root,
            run_id=str(source_task.id),
            thesis="concurrent canonical advance",
            bundle=source_bundle,
        )
        concurrent = materialize_canary_request(
            db,
            request=concurrent_request,
            quality_gate=concurrent_gate,
            agent_loop=concurrent_loop,
            task_run_id=str(source_task.id),
            analysis_snapshot_db_id=snapshot.id,
            authority_payload=concurrent_authority,
        )
        assert concurrent.status == "canonical_advanced"
        conflict = materialize_canary_request(
            db,
            request=stale_request,
            quality_gate=stale_gate,
            agent_loop=stale_loop,
            task_run_id=str(task.id),
            analysis_snapshot_db_id=snapshot.id,
            authority_payload=stale_authority,
        )
        assert conflict.status == "recompute_required"
        latest = db.get(AnalysisState, concurrent.canonical_state_id)
        root_id = root.id
        db.commit()
        attempt_factory = sessionmaker(bind=engine, expire_on_commit=False)
        with attempt_factory.begin() as attempt_db:
            attempt0 = create_or_resume_canary_attempt(
                attempt_db,
                run_id=str(task.id),
                approval_id=approval_id,
                approval_hash=approval_record.approval_hash,
                attempt_no=0,
                asset="XAUUSD",
                state_scope="daily_close",
                trade_date=NOW.date(),
                requested_canonical_state_id=root_id,
                expected_head_version=1,
                started_at=NOW,
            )
            attempt0_id = attempt0.attempt_id
        attempt0_outputs = {
            "context_bundle_registry_artifact": original_descriptor,
            "canary_materialization_request": stale_request,
            "canary_authority_payload": stale_authority,
            "agents": dict(stale_authority.agent_outputs),
            "post_coordinator_quality_gate_decision": stale_gate,
            "agent_loop_decision": stale_loop,
            "canary_attempt_number": 0,
            "canary_attempt_id": attempt0_id,
        }
        runner._persist_canary_attempt_audit(
            db,
            attempt_session_factory=attempt_factory,
            storage_root=tmp_path,
            analysis_snapshot={
                "asset": "XAUUSD",
                "trade_date": NOW.date().isoformat(),
                "snapshot_id": snapshot.snapshot_id,
                "source_refs": [{"source": "market", **REF}],
                "input_snapshot_ids": {},
            },
            run_id=str(task.id),
            report_step=report_step,
            summaries={"domain_agents": {"status": "success"}},
            outputs=attempt0_outputs,
        )
        db.commit()
        with attempt_factory.begin() as attempt_db:
            authorize_canary_recompute(
                attempt_db,
                attempt_id=attempt0_id,
                updated_at=NOW,
            )
            attempt1 = create_or_resume_canary_attempt(
                attempt_db,
                run_id=str(task.id),
                approval_id=approval_id,
                approval_hash=approval_record.approval_hash,
                attempt_no=1,
                asset="XAUUSD",
                state_scope="daily_close",
                trade_date=NOW.date(),
                requested_canonical_state_id=latest.id,
                expected_head_version=2,
                started_at=NOW + timedelta(hours=2),
            )
            attempt1_id = attempt1.attempt_id
        _, resumed_activation, resumed_attempt = runner._resolve_canary_runner_activation(
            db,
            attempt_session_factory=attempt_factory,
            storage_root=tmp_path,
            analysis_snapshot={"asset": "XAUUSD", "trade_date": NOW.date().isoformat()},
            run_id=str(task.id),
            state_shadow_input={
                **_activation_input(),
                "canonical_state_id": root.id,
                "canonical_state": dict(root.payload),
                "evidence": [],
            },
            canary_approval_id=approval_id,
            now=NOW + timedelta(hours=2),
        )
        assert resumed_activation.canonical_state_id == latest.id
        assert resumed_attempt["attempt_id"] == attempt1_id
        assert resumed_attempt["attempt_no"] == 1
        assert resumed_attempt["shadow_input"]["canonical_state_id"] == latest.id
        calls: list[dict] = []

        def full_fresh_attempt(**kwargs):
            refreshed = kwargs["state_shadow_input"]
            calls.append(refreshed)
            assert refreshed["canonical_state_id"] == latest.id
            assert refreshed["expected_head_version"] == 2
            assert refreshed["previous_context_bundle_base_canonical_state_id"] == root.id
            assert refreshed["previous_context_bundle_artifact"]["metadata"]["bundle_id"] == source_bundle.bundle_id
            assert "previous_semantic_hashes" not in refreshed
            assert "freshness_sla_seconds" not in refreshed
            fresh_bundle = assemble_context_bundle(
                run_id=str(task.id),
                asset="XAUUSD",
                state_scope="daily_close",
                canonical_state_id=latest.id,
                canonical_state=dict(latest.payload),
                evidence=[],
                evidence_cursors={},
                cutoff_at=NOW,
                assembled_at=NOW + timedelta(hours=2),
                expected_session="daily_close",
            )
            fresh_descriptor = write_context_bundle(
                storage_root=tmp_path,
                bundle=fresh_bundle,
            ).registry_artifact
            fresh_request, fresh_gate, fresh_loop, fresh_authority = _request(
                latest,
                expected_version=2,
                run_id=str(task.id),
                next_as_of=NOW + timedelta(hours=2),
                thesis="fresh full attempt",
                bundle=fresh_bundle,
            )
            fresh_request = fresh_request.model_copy(update={"approval_hash": approval_record.approval_hash})
            return {}, {
                "context_bundle_registry_artifact": fresh_descriptor,
                "canary_materialization_request": fresh_request,
                "post_coordinator_quality_gate_decision": fresh_gate,
                    "agent_loop_decision": fresh_loop,
                    "canary_authority_payload": fresh_authority,
                    "agents": dict(fresh_authority.agent_outputs),
                    "canary_attempt_number": 1,
                "canary_attempt_id": kwargs["attempt_id"],
            }

        monkeypatch.setattr(runner, "_run_canary_sidecar_attempt", full_fresh_attempt)
        register_bundle = runner._register_context_bundle_artifact

        def register_bundle_checkpoint(*args, **kwargs):
            row = register_bundle(*args, **kwargs)
            db.commit()
            return row

        monkeypatch.setattr(
            runner,
            "_register_context_bundle_artifact",
            register_bundle_checkpoint,
        )
        result = runner._consume_canary_recompute_once(
            db,
            conflict_result=conflict,
            analysis_snapshot={"asset": "XAUUSD", "trade_date": NOW.date().isoformat()},
            run_id=str(task.id),
            storage_root=tmp_path,
            created_at=NOW + timedelta(hours=2),
            state_shadow_input={
                **_activation_input(),
                "canonical_state_id": root.id,
                "canonical_state": dict(root.payload),
                "evidence": [],
            },
            state_delta_analyzer=None,
            canary_activation=CanaryActivation(
                asset="XAUUSD",
                trade_date=NOW.date(),
                run_id=str(task.id),
                state_scope="daily_close",
                canonical_state_id=root.id,
                expected_head_version=1,
                approval_id=f"approval-{task.id}",
                approval_hash=approval_record.approval_hash,
                activation_identity=f"approval-{task.id}",
            ),
            report_step=report_step,
            snapshot_db_id=snapshot.id,
            attempt_session_factory=attempt_factory,
            superseded_attempt_id=attempt0_id,
        )

        assert len(calls) == 1
        assert result.status == "canonical_advanced"
        assert result.canonical_version == 3
        assert result.recompute_attempt_count == 1
        assert len(result.recompute_trace["fresh_consumer_projection_hashes"]) == 9
        rows = db.scalars(select(RunArtifact).where(RunArtifact.run_id == task.id)).all()
        assert len(rows) == 4
        audit_rows = [
            row
            for row in rows
            if (row.artifact_metadata or {}).get("execution_mode") == "analysis_state_canary_sidecar"
        ]
        assert len(audit_rows) == 2
        fresh_audit_row = next(
            row for row in audit_rows if json.loads(Path(row.file_path).read_text(encoding="utf-8"))["attempt"] == 1
        )
        audit_payload = json.loads(Path(fresh_audit_row.file_path).read_text(encoding="utf-8"))
        assert audit_payload["official_output_isolated"] is True
        assert len(audit_payload["authority_payload"]["consumer_projections"]) == 9
        assert audit_payload["fact_review_output"]["agent_name"] == "fact_review_agent"
        assert result.recompute_trace["fresh_attempt_audit"]["sha256"] == fresh_audit_row.sha256
        assert result.attempt_audit_sha256 == fresh_audit_row.sha256
        assert result.attempt_audit_path == fresh_audit_row.file_path
        failed_attempt_id, audit_bound_failure = runner._failed_terminal_from_durable_attempt(
            attempt_factory,
            run_id=str(task.id),
            storage_root=tmp_path,
            reason="simulated_failure_after_attempt_1_audit",
        )
        assert failed_attempt_id == attempt1_id
        assert audit_bound_failure.status == "failed"
        assert audit_bound_failure.recompute_attempt_count == 1
        assert audit_bound_failure.context_bundle_id == result.context_bundle_id
        assert audit_bound_failure.authority_hash == result.authority_hash
        assert (
            select_canary_terminal_result_for_run(
                db,
                run_id=str(task.id),
                storage_root=tmp_path,
            )
            is None
        )
        selected = select_context_bundle_artifact_for_run(
            db,
            run_id=str(task.id),
            storage_root=tmp_path,
        )
        assert selected["metadata"]["artifact_role"] == "canary_recompute"
        assert selected["metadata"]["supersedes_bundle_id"] == original_bundle.bundle_id
        terminal = runner._persist_canary_terminal_result(
            db,
            storage_root=tmp_path,
            run_id=str(task.id),
            report_step=report_step,
            result=result,
        )
        assert terminal["status"] == "canonical_advanced"
        consume_canary_approval(
            db,
            approval_id=approval_id,
            expected_approval_hash=approval_record.approval_hash,
            run_id=task_run_id,
            consumed_at=NOW + timedelta(hours=2),
        )
        db.commit()

    with Session(engine) as restarted:
        recovered = select_canary_terminal_result_for_run(
            restarted,
            run_id=task_run_id,
            storage_root=tmp_path,
        )
        assert recovered is not None
        assert recovered.model_dump(mode="json") == result.model_dump(mode="json")
        replay_result, replay_activation, replay_attempt = runner._resolve_canary_runner_activation(
            restarted,
            attempt_session_factory=attempt_factory,
            storage_root=tmp_path,
            analysis_snapshot={"asset": "XAUUSD", "trade_date": NOW.date().isoformat()},
            run_id=task_run_id,
            state_shadow_input={
                **_activation_input(),
                "canonical_state_id": result.canonical_state_id,
            },
            canary_approval_id=approval_id,
            now=NOW + timedelta(hours=3),
        )
        assert replay_activation is None
        assert replay_attempt is None
        assert replay_result == recovered
        with attempt_factory.begin() as tamper_db:
            checkpoint = tamper_db.scalar(
                select(CanaryAttempt).where(
                    CanaryAttempt.run_id == task_run_id,
                    CanaryAttempt.attempt_no == 1,
                )
            )
            original_context_bundle_id = checkpoint.context_bundle_id
            checkpoint.context_bundle_id = "tampered-bundle"
        with pytest.raises(ValueError, match="identity mismatch: context_bundle_id"):
            runner._resolve_canary_runner_activation(
                restarted,
                attempt_session_factory=attempt_factory,
                storage_root=tmp_path,
                analysis_snapshot={"asset": "XAUUSD", "trade_date": NOW.date().isoformat()},
                run_id=task_run_id,
                state_shadow_input=_activation_input(),
                canary_approval_id=approval_id,
                now=NOW + timedelta(hours=3),
            )
        with attempt_factory.begin() as tamper_db:
            checkpoint = tamper_db.scalar(
                select(CanaryAttempt).where(
                    CanaryAttempt.run_id == task_run_id,
                    CanaryAttempt.attempt_no == 1,
                )
            )
            checkpoint.context_bundle_id = original_context_bundle_id
            original_terminal_path = checkpoint.terminal_artifact_path
            checkpoint.terminal_artifact_path = str(tmp_path / "wrong-terminal.json")
        with pytest.raises(ValueError, match="artifact binding"):
            runner._resolve_canary_runner_activation(
                restarted,
                attempt_session_factory=attempt_factory,
                storage_root=tmp_path,
                analysis_snapshot={"asset": "XAUUSD", "trade_date": NOW.date().isoformat()},
                run_id=task_run_id,
                state_shadow_input=_activation_input(),
                canary_approval_id=approval_id,
                now=NOW + timedelta(hours=3),
            )
        with attempt_factory.begin() as restore_db:
            checkpoint = restore_db.scalar(
                select(CanaryAttempt).where(
                    CanaryAttempt.run_id == task_run_id,
                    CanaryAttempt.attempt_no == 1,
                )
            )
            checkpoint.terminal_artifact_path = original_terminal_path
        head = restarted.scalar(
            select(AnalysisStateHead).where(
                AnalysisStateHead.asset == "XAUUSD",
                AnalysisStateHead.state_scope == "daily_close",
            )
        )
        assert head.version == 3


def test_durable_started_does_not_commit_outer_runner_sentinel(tmp_path) -> None:
    from apps.worker import runner

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'started.db'}")
    TaskBase.metadata.create_all(engine)
    AnalysisBase.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with Session(engine) as setup:
        task = TaskRun(name="sentinel", status=TaskStatus.running, trade_date=NOW.date().isoformat())
        setup.add(task)
        setup.commit()
        task_id = task.id
    activation = CanaryActivation(
        asset="XAUUSD",
        trade_date=NOW.date(),
        run_id=str(task_id),
        state_scope="daily_close",
        canonical_state_id="00000000-0000-0000-0000-000000000001",
        expected_head_version=1,
        approval_id="approval-sentinel",
        approval_hash="a" * 64,
        activation_identity="approval-sentinel",
    )
    with Session(engine) as outer:
        task = outer.get(TaskRun, task_id)
        task.error_summary = "must remain uncommitted"
        attempt_id = runner._durably_start_canary_attempt(
            factory,
            activation=activation,
            attempt_no=0,
            started_at=NOW,
        )
        assert (
            runner._failed_terminal_from_durable_attempt(
                factory,
                run_id=str(task_id),
                storage_root=tmp_path,
                reason="simulated_failure_before_audit",
            )
            is None
        )
        assert not list((tmp_path / "outputs" / "analysis_memory_canary").glob("**/terminal-results/*.json"))
        assert (
            runner._durably_start_canary_attempt(
                factory,
                activation=activation,
                attempt_no=0,
                started_at=NOW + timedelta(minutes=1),
            )
            == attempt_id
        )
        with Session(engine) as observer:
            attempt = observer.get(CanaryAttempt, attempt_id)
            observed_task = observer.get(TaskRun, task_id)
            assert attempt is not None
            assert attempt.status == "started"
            assert observed_task.error_summary is None
        outer.rollback()


def test_verified_audit_checkpoint_rehydrates_without_sidecar_rerun(tmp_path) -> None:
    from apps.worker import runner

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'audit-recovery.db'}")
    TaskBase.metadata.create_all(engine)
    AnalysisBase.metadata.create_all(engine)
    ensure_execution_tables(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with Session(engine) as db:
        task = TaskRun(name="audit-recovery", status=TaskStatus.running)
        db.add(task)
        db.flush()
        report_step = TaskStep(
            task_run_id=task.id,
            name="report_render",
            status=StepStatus.success,
        )
        db.add(report_step)
        root = _seed_head(db, scope="daily_close")
        approval = issue_canary_approval(
            db,
            approval_id=f"approval-{task.id}",
            asset="XAUUSD",
            state_scope="daily_close",
            trade_date=NOW.date(),
            run_id=str(task.id),
            approved_by="review-center",
            approved_role="canary_approver",
            approved_at=NOW - timedelta(minutes=1),
            expires_at=NOW + timedelta(days=1),
        )
        bundle = assemble_context_bundle(
            run_id=str(task.id),
            asset="XAUUSD",
            state_scope="daily_close",
            canonical_state_id=root.id,
            canonical_state=dict(root.payload),
            evidence=[],
            evidence_cursors={},
            cutoff_at=NOW,
            assembled_at=NOW,
            expected_session="daily_close",
        )
        descriptor = write_context_bundle(storage_root=tmp_path, bundle=bundle).registry_artifact
        request, gate, loop, authority = _request(root, run_id=str(task.id), bundle=bundle)
        request = request.model_copy(update={"approval_hash": approval.approval_hash})
        activation = CanaryActivation(
            asset="XAUUSD",
            trade_date=NOW.date(),
            run_id=str(task.id),
            state_scope="daily_close",
            canonical_state_id=root.id,
            expected_head_version=1,
            approval_id=approval.approval_id,
            approval_hash=approval.approval_hash,
            activation_identity=approval.approval_id,
        )
        db.commit()
        attempt_id = runner._durably_start_canary_attempt(
            factory,
            activation=activation,
            attempt_no=0,
            started_at=NOW,
        )
        outputs = {
            "context_bundle_registry_artifact": descriptor,
            "canary_materialization_request": request,
            "canary_authority_payload": authority,
            "agents": dict(authority.agent_outputs),
            "post_coordinator_quality_gate_decision": gate,
            "agent_loop_decision": loop,
            "canary_attempt_number": 0,
            "canary_attempt_id": attempt_id,
        }
        runner._persist_canary_attempt_audit(
            db,
            attempt_session_factory=factory,
            storage_root=tmp_path,
            analysis_snapshot={
                "asset": "XAUUSD",
                "trade_date": NOW.date().isoformat(),
                "snapshot_id": "audit-recovery-snapshot",
                "source_refs": [{"source": "market", **REF}],
                "input_snapshot_ids": {},
            },
            run_id=str(task.id),
            report_step=report_step,
            summaries={"domain_agents": {"status": "success"}},
            outputs=outputs,
        )
        audit_path = outputs["canary_attempt_audit"]["file_path"]
        assert f"attempt-0/{attempt_id}/" in audit_path
        persisted_audit = json.loads(Path(audit_path).read_text(encoding="utf-8"))
        assert persisted_audit["schema_version"] == "analysis_state_canary_attempt.v2"
        old_payload = {**persisted_audit, "schema_version": "analysis_state_canary_attempt.v1"}
        old_content = (
            json.dumps(
                old_payload,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
        old_digest = hashlib.sha256(old_content).hexdigest()
        old_attempt_id = "old-schema-attempt"
        old_path = (
            tmp_path
            / "outputs"
            / "analysis_memory_canary"
            / NOW.date().isoformat()
            / str(task.id)
            / "attempt-0"
            / old_attempt_id
            / f"{old_digest}.json"
        )
        old_path.parent.mkdir(parents=True, exist_ok=True)
        old_path.write_bytes(old_content)
        with pytest.raises(ValueError, match="schema_version is unsupported"):
            runner._recover_canary_attempt_audit(
                SimpleNamespace(
                    trade_date=NOW.date(),
                    run_id=str(task.id),
                    attempt_no=0,
                    attempt_id=old_attempt_id,
                    audit_artifact_path=str(old_path),
                    audit_artifact_sha256=old_digest,
                ),
                storage_root=tmp_path,
            )
        tampered_payload = json.loads(json.dumps(persisted_audit))
        tampered_payload["consumer_outputs"]["risk_agent"]["summary"] = "tampered recovered risk output"
        tampered_content = (
            json.dumps(
                tampered_payload,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
        tampered_digest = hashlib.sha256(tampered_content).hexdigest()
        tampered_attempt_id = "tampered-output-attempt"
        tampered_path = (
            tmp_path
            / "outputs"
            / "analysis_memory_canary"
            / NOW.date().isoformat()
            / str(task.id)
            / "attempt-0"
            / tampered_attempt_id
            / f"{tampered_digest}.json"
        )
        tampered_path.parent.mkdir(parents=True, exist_ok=True)
        tampered_path.write_bytes(tampered_content)
        with pytest.raises(ValueError, match="consumer output is mismatched: risk_agent"):
            runner._recover_canary_attempt_audit(
                SimpleNamespace(
                    trade_date=NOW.date(),
                    run_id=str(task.id),
                    attempt_no=0,
                    attempt_id=tampered_attempt_id,
                    audit_artifact_path=str(tampered_path),
                    audit_artifact_sha256=tampered_digest,
                    approval_id=approval.approval_id,
                    approval_hash=approval.approval_hash,
                    context_bundle_id=request.context_bundle_id,
                    context_bundle_hash=request.context_bundle_hash,
                    authority_hash=request.authority_hash,
                ),
                storage_root=tmp_path,
            )
        db.rollback()  # crash before audit RunArtifact / terminal transaction commit

        recovered_result, recovered_activation, recovery = runner._resolve_canary_runner_activation(
            db,
            attempt_session_factory=factory,
            storage_root=tmp_path,
            analysis_snapshot={"asset": "XAUUSD", "trade_date": NOW.date().isoformat()},
            run_id=str(task.id),
            state_shadow_input={**_activation_input(), "canonical_state_id": root.id},
            canary_approval_id=approval.approval_id,
            now=NOW,
        )
        assert recovered_result is None
        assert recovered_activation is not None
        assert recovery["attempt_id"] == attempt_id
        assert recovery["outputs"]["canary_attempt_audit_recovered"] is True
        assert recovery["outputs"]["canary_materialization_request"] == request
