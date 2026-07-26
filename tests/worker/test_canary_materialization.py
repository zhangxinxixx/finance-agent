from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from apps.analysis.agents.quality_gate import AcceptedOutputReference, AgentLoopDecision
from apps.analysis.agents.quality_gate_evaluator import QualityGateAction, QualityGateDecision
from apps.analysis.context_bundle import assemble_context_bundle, project_context_bundle
from apps.analysis.agents.schemas import AgentBias, AgentOutput, AgentStatus
from apps.analysis.state import (
    ANALYSIS_STATE_MACHINE_VERSION,
    AnalysisStateDocumentV11,
    AnalysisTransitionDocumentV11,
    StateChange,
    StateMaterializationAuthority,
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
)
from apps.worker.canary_materialization import (
    CANARY_CONSUMERS,
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
from database.models.analysis_state import AnalysisState, AnalysisStateHead, AnalysisTransition
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
        ),
    )


def _authority_payload(*, root: AnalysisState, run_id: str, bundle=None) -> CanaryAuthorityPayload:
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
    projections = {
        consumer: project_context_bundle(bundle, consumer=consumer)
        for consumer in CANARY_CONSUMERS
    }
    fact_projection = projections["fact_review"]
    fact_review = AgentOutput(
        version="v1",
        agent_name="fact_review_agent",
        module="tests",
        snapshot_id="fact-review-80",
        input_snapshot_ids={
            "context_bundle_id": bundle.bundle_id,
            "context_bundle_hash": bundle.content_hash,
            "context_bundle_run_id": run_id,
            "context_bundle_projection_hash": fact_projection.projection_hash,
            "canonical_state_id": root.id,
            "state_scope": "daily_close",
        },
        input_payload={
            "context_bundle_consumer": "fact_review",
            "context_bundle_projection": fact_projection.model_dump(mode="json"),
        },
        bias=AgentBias.NEUTRAL,
        confidence=0.5,
        key_findings=[],
        risk_points=[],
        watchlist=[],
        summary="reviewed",
        source_refs=[REF],
        status=AgentStatus.SUCCESS,
        created_at=NOW,
    )
    return CanaryAuthorityPayload.build(
        context_bundle_id=bundle.bundle_id,
        context_bundle_hash=bundle.content_hash,
        run_id=run_id,
        canonical_state_id=root.id,
        consumer_projections=projections,
        fact_review_output=fact_review,
    )


def _request(
    root: AnalysisState,
    *,
    expected_version: int = 1,
    run_id: str = RUN_ID,
    next_as_of: datetime = NOW + timedelta(hours=1),
    thesis: str = "daily close breakout confirmed",
    bundle=None,
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
                target="as_of",
                action=TransitionAction.STRENGTHEN,
                reason="new evidence time",
                evidence_refs=[REF],
            ),
        ],
        state_patch={"core_thesis": thesis, "as_of": next_as_of},
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
    )
    gate, loop = _gate(), _loop()
    authority = _authority_payload(root=root, run_id=run_id, bundle=bundle)
    request = CanaryMaterializationRequest(
        asset="XAUUSD",
        trade_date=NOW.date(),
        run_id=run_id,
        state_scope="daily_close",
        canonical_state_id=root.id,
        expected_head_version=expected_version,
        activation_source="exact_run_id",
        activation_identity=run_id,
        context_bundle_id=authority.context_bundle_id,
        context_bundle_hash=authority.context_bundle_hash,
        consumer_projection_hashes={
            name: projection.projection_hash
            for name, projection in authority.consumer_projections.items()
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


def test_canary_activation_requires_auditable_exact_control() -> None:
    base = _activation_input()
    assert resolve_canary_activation(
        snapshot_asset="XAUUSD", snapshot_trade_date=NOW.date(), run_id=RUN_ID, shadow_input=base
    ) is None

    by_date = resolve_canary_activation(
        snapshot_asset="XAUUSD",
        snapshot_trade_date=NOW.date(),
        run_id=RUN_ID,
        shadow_input=_activation_input(canary_trade_dates=[NOW.date().isoformat()]),
    )
    assert (by_date.activation_source, by_date.activation_identity) == ("exact_trade_date", NOW.date().isoformat())

    by_run = resolve_canary_activation(
        snapshot_asset="XAUUSD",
        snapshot_trade_date=NOW.date(),
        run_id=RUN_ID,
        shadow_input=_activation_input(canary_run_ids=[RUN_ID]),
    )
    assert (by_run.activation_source, by_run.activation_identity) == ("exact_run_id", RUN_ID)

    manual = resolve_canary_activation(
        snapshot_asset="XAUUSD",
        snapshot_trade_date=NOW.date(),
        run_id=RUN_ID,
        shadow_input=_activation_input(
            canary_manual_request={
                "request_id": "approval-80",
                "asset": "XAUUSD",
                "state_scope": "daily_close",
                "run_id": RUN_ID,
            }
        ),
    )
    assert (manual.activation_source, manual.activation_identity) == ("manual_request", "manual:approval-80")

    with pytest.raises(ValueError, match="canary_enabled"):
        resolve_canary_activation(
            snapshot_asset="XAUUSD",
            snapshot_trade_date=NOW.date(),
            run_id=RUN_ID,
            shadow_input=_activation_input(canary_enabled=True),
        )
    with pytest.raises(ValueError, match="asset=XAUUSD"):
        resolve_canary_activation(
            snapshot_asset="EURUSD",
            snapshot_trade_date=NOW.date(),
            run_id=RUN_ID,
            shadow_input={**_activation_input(canary_run_ids=[RUN_ID]), "asset": "EURUSD"},
        )


def test_request_requires_nine_projections_and_matching_gate_hash(session: Session) -> None:
    root = _seed_head(session, scope="daily_close")
    request, gate, loop, authority = _request(root)
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
            session, request=request, quality_gate=gate, agent_loop=loop, task_run_id="other-run", authority_payload=authority
        )


def test_materializer_revalidates_forged_activation_and_authority_payload(session: Session) -> None:
    root = _seed_head(session, scope="daily_close")
    request, gate, loop, authority = _request(root)
    forged_activation = request.model_copy(update={"activation_identity": "other-run"})
    with pytest.raises(ValueError, match="exact_run_id"):
        materialize_canary_request(
            session,
            request=forged_activation,
            quality_gate=gate,
            agent_loop=loop,
            task_run_id=RUN_ID,
            authority_payload=authority,
        )

    mismatched_fact_review = authority.fact_review_output.model_copy(
        update={"snapshot_id": "other-fact-review"}
    )
    mismatched_authority = CanaryAuthorityPayload.build(
        context_bundle_id=authority.context_bundle_id,
        context_bundle_hash=authority.context_bundle_hash,
        run_id=authority.run_id,
        canonical_state_id=authority.canonical_state_id,
        consumer_projections=authority.consumer_projections,
        fact_review_output=mismatched_fact_review,
    )
    mismatched_request = request.model_copy(
        update={
            "authority_hash": mismatched_authority.authority_hash,
            "quality_gate_hash": compute_canary_quality_gate_hash(
                gate, authority_hash=mismatched_authority.authority_hash
            ),
            "agent_loop_hash": compute_canary_agent_loop_hash(
                loop, authority_hash=mismatched_authority.authority_hash
            ),
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


def test_second_conflict_is_terminal_and_keeps_one_hop_supersession() -> None:
    first = CanaryMaterializationResult(
        status="recompute_required",
        asset="XAUUSD",
        trade_date=NOW.date(),
        run_id=RUN_ID,
        state_scope="daily_close",
        activation_source="exact_run_id",
        activation_identity=RUN_ID,
        context_bundle_id="bundle-stale",
        context_bundle_hash="a" * 64,
        requested_canonical_state_id="state-stale",
        expected_head_version=1,
        recompute_required=True,
        latest_canonical_state_id="state-fresh",
        latest_head_version=2,
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


def test_runner_recompute_executes_full_fresh_attempt_before_second_cas(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.worker import runner

    engine = create_engine("sqlite+pysqlite:///:memory:")
    TaskBase.metadata.create_all(engine)
    AnalysisBase.metadata.create_all(engine)
    ensure_execution_tables(engine)
    with Session(engine) as db:
        task = TaskRun(name="premarket", status=TaskStatus.running)
        db.add(task)
        db.flush()
        task_run_id = str(task.id)
        report_step = TaskStep(
            task_run_id=task.id,
            name="report_render",
            status=StepStatus.success,
        )
        db.add(report_step)
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
        stale_request, stale_gate, stale_loop, stale_authority = _request(
            root, run_id=str(task.id), bundle=original_bundle
        )
        concurrent_request, concurrent_gate, concurrent_loop, concurrent_authority = _request(
            root,
            run_id=str(task.id),
            thesis="concurrent canonical advance",
            bundle=original_bundle,
        )
        concurrent = materialize_canary_request(
            db,
            request=concurrent_request,
            quality_gate=concurrent_gate,
            agent_loop=concurrent_loop,
            task_run_id=str(task.id),
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
        calls: list[dict] = []

        def full_fresh_attempt(**kwargs):
            refreshed = kwargs["state_shadow_input"]
            calls.append(refreshed)
            assert refreshed["canonical_state_id"] == latest.id
            assert refreshed["expected_head_version"] == 2
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
            return {}, {
                "context_bundle_registry_artifact": fresh_descriptor,
                "canary_materialization_request": fresh_request,
                "post_coordinator_quality_gate_decision": fresh_gate,
                "agent_loop_decision": fresh_loop,
                "canary_authority_payload": fresh_authority,
                "canary_attempt_number": 1,
            }

        monkeypatch.setattr(runner, "_run_canary_sidecar_attempt", full_fresh_attempt)
        result = runner._consume_canary_recompute_once(
            db,
            conflict_result=conflict,
            analysis_snapshot={"asset": "XAUUSD", "trade_date": NOW.date().isoformat()},
            run_id=str(task.id),
            storage_root=tmp_path,
            created_at=NOW + timedelta(hours=2),
            state_shadow_input={
                **_activation_input(canary_run_ids=[str(task.id)]),
                "canonical_state_id": root.id,
                "canonical_state": dict(root.payload),
                "evidence": [],
            },
            state_delta_analyzer=None,
            report_step=report_step,
            snapshot_db_id=snapshot.id,
        )

        assert len(calls) == 1
        assert result.status == "canonical_advanced"
        assert result.canonical_version == 3
        assert result.recompute_attempt_count == 1
        assert len(result.recompute_trace["fresh_consumer_projection_hashes"]) == 9
        rows = db.scalars(select(RunArtifact).where(RunArtifact.run_id == task.id)).all()
        assert len(rows) == 3
        audit_rows = [
            row
            for row in rows
            if (row.artifact_metadata or {}).get("execution_mode")
            == "analysis_state_canary_sidecar"
        ]
        assert len(audit_rows) == 1
        audit_payload = json.loads(Path(audit_rows[0].file_path).read_text(encoding="utf-8"))
        assert audit_payload["official_output_isolated"] is True
        assert len(audit_payload["authority_payload"]["consumer_projections"]) == 9
        assert audit_payload["fact_review_output"]["agent_name"] == "fact_review_agent"
        assert result.recompute_trace["fresh_attempt_audit"]["sha256"] == audit_rows[0].sha256
        assert result.attempt_audit_sha256 == audit_rows[0].sha256
        assert result.attempt_audit_path == audit_rows[0].file_path
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
        db.commit()

    with Session(engine) as restarted:
        recovered = select_canary_terminal_result_for_run(
            restarted,
            run_id=task_run_id,
            storage_root=tmp_path,
        )
        assert recovered is not None
        assert recovered.model_dump(mode="json") == result.model_dump(mode="json")
        head = restarted.scalar(
            select(AnalysisStateHead).where(
                AnalysisStateHead.asset == "XAUUSD",
                AnalysisStateHead.state_scope == "daily_close",
            )
        )
        assert head.version == 3
