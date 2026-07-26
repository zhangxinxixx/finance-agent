from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from apps.analysis.figure_facts import FigureFact
from apps.worker.db_persistence import persist_review_items
from apps.worker.composite_state_shadow import (
    build_state_delta_setup_failure_review_item,
    execute_composite_state_shadow,
    finalize_composite_state_shadow,
    prepare_composite_state_shadow,
    resolve_analysis_context_mode,
)
from database.models.analysis import AnalysisBase
from database.queries.review import get_review_item


NOW = datetime(2026, 7, 22, 8, tzinfo=UTC)
REF = {"snapshot_id": "market-2"}


def _state() -> dict:
    return {
        "asset": "XAUUSD",
        "as_of": NOW,
        "market_stage": "direction_decision",
        "core_thesis": "等待突破",
        "net_bias": "mixed_bullish",
        "dominant_drivers": [],
        "key_levels": [{"price": 4000, "role": "support"}],
        "scenario_states": [],
        "unresolved_items": [],
        "invalidation_conditions": [],
        "evidence_cursors": {},
        "input_snapshot_ids": {"market": "market-1"},
        "source_refs": [{"snapshot_id": "market-1"}],
    }


def _evidence(*, provider_metadata: bool = False) -> dict:
    # Minimal typed payload conforming to the published #76 EvidenceDelta contract
    # (validated key_level_event) so the v3 bundle can evaluate and retain it.
    payload = {
        "evidence_type": "key_level_event",
        "asset": "XAUUSD",
        "source_quality": "validated",
        "level_id": "support-4000",
        "level_role": "support",
        "level_value": 4000,
        "observed_value": 4050,
        "event": "confirmed_break",
        "confirmation_status": "confirmed",
    }

    if provider_metadata:
        # Transport metadata must be stripped by the assembler so it never
        # influences bundle identity or content hash.
        payload.update({"provider": "jojocode", "conversation_id": "thread-1"})
    return {
        "source": "market",
        "evidence_id": "market-2",
        "business_time": NOW + timedelta(minutes=1),
        "ingested_at": NOW + timedelta(minutes=2),
        "session": "asia",
        "payload": payload,
        "source_ref": REF,
    }


def _macro_evidence(*, current: float, source_quality: str = "validated") -> dict:
    return {
        "source": "macro",
        "evidence_id": f"dxy-{current}",
        "business_time": NOW + timedelta(minutes=1),
        "ingested_at": NOW + timedelta(minutes=2),
        "payload": {
            "evidence_type": "macro_metric",
            "asset": "XAUUSD",
            "source_quality": source_quality,
            "metric": "dxy",
            "current_value": current,
            "previous_value": 100.0,
            "unit": "index",
        },
        "source_ref": REF,
    }


def _shadow_input(*, evidence: list[dict] | None = None) -> dict:
    return {
        "state_scope": "daily_close",
        "canonical_state_id": "state-66",
        "canonical_state": _state(),
        "evidence": list(evidence or []),
        "evidence_cursors": {},
        "cutoff_at": NOW + timedelta(minutes=5),
        "assembled_at": NOW + timedelta(minutes=6),
        "expected_session": "asia",
    }


def _candidate(bundle) -> dict:
    return {
        "previous_state_id": bundle.canonical_state_id,
        "summary": "价格突破后强化",
        "changes": [
            {
                "target": "core_thesis",
                "action": "strengthen",
                "reason": "价格确认",
                "evidence_refs": [REF],
            },
            {
                "target": "as_of",
                "action": "strengthen",
                "reason": "新证据时间",
                "evidence_refs": [REF],
            },
        ],
        "state_patch": {
            "core_thesis": "突破确认",
            "as_of": NOW + timedelta(hours=1),
        },
        "evidence_refs": [REF],
    }


def test_no_delta_skips_shadow_analyzer_and_never_allows_canonical_write(tmp_path) -> None:
    runtime = prepare_composite_state_shadow(
        storage_root=tmp_path,
        run_id="run-69",
        created_at=NOW,
        shadow_input=_shadow_input(),
    )

    def unexpected(_bundle):
        raise AssertionError("no-delta path must not call the analyzer")

    trace = execute_composite_state_shadow(runtime=runtime, analyzer=unexpected)
    final = finalize_composite_state_shadow(
        trace,
        legacy_coordinator=SimpleNamespace(summary="legacy"),
        agent_loop_decision=SimpleNamespace(publish_allowed=True),
        consumer_names=["coordinator_agent"],
    )

    assert trace["status"] == "no_material_delta"
    assert trace["model_invocation"] == "skipped"
    assert final["production_canonical_write_allowed"] is False


def test_provider_metadata_removal_rebuilds_same_bundle_and_recovers_artifact(tmp_path) -> None:
    first = prepare_composite_state_shadow(
        storage_root=tmp_path,
        run_id="run-69",
        created_at=NOW,
        shadow_input=_shadow_input(evidence=[_evidence(provider_metadata=True)]),
    )
    replay = prepare_composite_state_shadow(
        storage_root=tmp_path,
        run_id="run-69",
        created_at=NOW + timedelta(hours=1),
        shadow_input=_shadow_input(evidence=[_evidence(provider_metadata=False)]),
    )

    assert replay.bundle.bundle_id == first.bundle.bundle_id
    assert replay.bundle.content_hash == first.bundle.content_hash
    assert first.artifact.written is True
    assert replay.artifact.written is False


def test_shadow_candidate_is_reviewed_and_all_consumers_share_bundle(tmp_path) -> None:
    runtime = prepare_composite_state_shadow(
        storage_root=tmp_path,
        run_id="run-69",
        created_at=NOW,
        shadow_input=_shadow_input(evidence=[_evidence()]),
    )
    trace = execute_composite_state_shadow(runtime=runtime, analyzer=_candidate)
    final = finalize_composite_state_shadow(
        trace,
        legacy_coordinator=SimpleNamespace(summary="legacy thesis"),
        agent_loop_decision=SimpleNamespace(publish_allowed=False),
        consumer_names=["macro_liquidity_agent", "fact_review_agent", "coordinator_agent"],
    )

    assert trace["status"] == "candidate_accepted_shadow_only"
    assert trace["shadow_review_status"] == "accepted"
    assert trace["schema_version"] == "composite_state_shadow.v3"
    assert trace["state_scope"] == "daily_close"
    assert "/daily_close/" in trace["bundle_path"]
    assert trace["transition_diff"][0]["action"] == "strengthen"
    assert set(final["bundle_consumers"].values()) == {runtime.bundle.bundle_id}
    assert final["quality_distribution"] == {
        "legacy": "needs_review",
        "shadow": "accepted",
    }


def test_shadow_analyzer_failure_is_contained_as_needs_review(tmp_path) -> None:
    runtime = prepare_composite_state_shadow(
        storage_root=tmp_path,
        run_id="run-69",
        created_at=NOW,
        shadow_input=_shadow_input(evidence=[_evidence()]),
    )

    def broken(_bundle):
        raise RuntimeError("provider unavailable")

    trace = execute_composite_state_shadow(runtime=runtime, analyzer=broken)

    assert trace["status"] == "candidate_rejected"
    assert trace["shadow_review_status"] == "needs_review"
    assert trace["reason"].startswith("RuntimeError:")


@pytest.mark.parametrize(
    ("evidence", "expected_action", "expected_calls"),
    [
        ([], "no_op", 0),
        ([_macro_evidence(current=100.3)], "update_context_only", 0),
        ([_evidence()], "run_transition_analysis", 1),
        ([_macro_evidence(current=101.0, source_quality="unverified")], "manual_review", 0),
    ],
)
def test_evidence_delta_action_is_the_only_analyzer_gate(
    tmp_path, evidence, expected_action, expected_calls
) -> None:
    runtime = prepare_composite_state_shadow(
        storage_root=tmp_path,
        run_id="run-decision-gate",
        created_at=NOW,
        shadow_input=_shadow_input(evidence=evidence),
    )
    calls = 0

    def analyzer(bundle):
        nonlocal calls
        calls += 1
        return _candidate(bundle)

    trace = execute_composite_state_shadow(runtime=runtime, analyzer=analyzer)

    assert runtime.evidence_delta_decision.recommended_action.value == expected_action
    assert trace["evidence_delta_action"] == expected_action
    assert calls == expected_calls
    if expected_action == "manual_review":
        review = trace["review_items"][0]
        assert review["review_id"] == f"evidence_delta:{trace['evidence_delta_decision_id']}"
        assert review["run_id"] == "run-decision-gate"
        assert review["source_module"] == "state_delta_shadow"
        assert review["source_step_id"] == "evidence_delta_decision"
        assert review["status"] == "pending"


def test_duplicate_evidence_skips_analyzer_from_recovered_semantic_hash(tmp_path) -> None:
    evidence = _macro_evidence(current=100.3)
    first = prepare_composite_state_shadow(
        storage_root=tmp_path,
        run_id="run-before-duplicate",
        created_at=NOW,
        shadow_input=_shadow_input(evidence=[evidence]),
    )
    replay_input = _shadow_input(evidence=[evidence])
    replay_input["previous_semantic_hashes"] = dict(
        first.evidence_delta_decision.semantic_hashes
    )
    replay = prepare_composite_state_shadow(
        storage_root=tmp_path,
        run_id="run-duplicate",
        created_at=NOW,
        shadow_input=replay_input,
    )
    calls = 0

    def analyzer(_bundle):
        nonlocal calls
        calls += 1
        raise AssertionError("duplicate evidence must not invoke analyzer")

    trace = execute_composite_state_shadow(runtime=replay, analyzer=analyzer)

    assert replay.evidence_delta_decision.recommended_action.value == "no_op"
    assert trace["status"] == "no_material_delta"
    assert calls == 0


def test_accepted_figure_fact_enters_facts_and_evidence_delta_decision(tmp_path) -> None:
    fact = FigureFact.build(
        figure_id="fig-accepted",
        report_id="225145",
        page_no=1,
        bbox=[0, 0, 10, 10],
        asset="XAUUSD",
        observations=["关键支撑 4000"],
        numeric_values=[],
        derived_claims=[],
        interpretation_limits=[],
        source_ref={
            "report_id": "225145",
            "figure_id": "fig-accepted",
            "page_no": 1,
            "bbox": [0, 0, 10, 10],
        },
        quality_status="accepted",
        image_content_hash="b" * 64,
        created_by_run_id="run-figure",
    )
    shadow_input = _shadow_input()
    shadow_input["figure_facts"] = [fact]

    runtime = prepare_composite_state_shadow(
        storage_root=tmp_path,
        run_id="run-accepted-figure",
        created_at=NOW,
        shadow_input=shadow_input,
    )

    facts_block = next(block for block in runtime.bundle.blocks if block.name == "facts")
    assert facts_block.payload[0]["figure_fact_id"] == fact.figure_fact_id
    assert [item.evidence_type for item in runtime.evidence_delta_decision.evaluated_items] == [
        "figure_fact"
    ]
    assert runtime.evidence_delta_decision.recommended_action.value == "update_context_only"


def test_explicit_prior_bundle_recovers_delta_and_selection_state(tmp_path) -> None:
    first_input = _shadow_input(evidence=[_macro_evidence(current=100.3)])
    first_input.update(
        {
            "freshness_sla_seconds": {"macro": 123},
            "default_freshness_sla_seconds": 456,
        }
    )
    first = prepare_composite_state_shadow(
        storage_root=tmp_path,
        run_id="run-prior",
        created_at=NOW,
        shadow_input=first_input,
    )
    next_input = _shadow_input(evidence=[_macro_evidence(current=100.3)])
    next_input["previous_bundle_path"] = first.artifact.storage_relative_path

    replay = prepare_composite_state_shadow(
        storage_root=tmp_path,
        run_id="run-replay",
        created_at=NOW + timedelta(hours=1),
        shadow_input=next_input,
    )

    assert replay.bundle.freshness_sla_seconds == {"macro": 123}
    assert replay.bundle.default_freshness_sla_seconds == 456
    assert replay.evidence_delta_decision.recommended_action.value == "no_op"
    assert replay.bundle.deferred_queue == first.bundle.deferred_queue
    assert replay.bundle.processed_above_frontier == first.bundle.processed_above_frontier


@pytest.mark.parametrize("field, value", [("asset", "EURUSD"), ("state_scope", "intraday")])
def test_prior_bundle_identity_mismatch_fails_closed(tmp_path, field, value) -> None:
    first = prepare_composite_state_shadow(
        storage_root=tmp_path,
        run_id="run-prior",
        created_at=NOW,
        shadow_input=_shadow_input(evidence=[_macro_evidence(current=100.3)]),
    )
    replay_input = _shadow_input(evidence=[_macro_evidence(current=100.3)])
    replay_input["previous_bundle_path"] = first.artifact.storage_relative_path
    if field == "asset":
        replay_input["canonical_state"] = {**_state(), "asset": value}
    else:
        replay_input[field] = value

    with pytest.raises(ValueError, match="previous context bundle identity|daily_close"):
        prepare_composite_state_shadow(
            storage_root=tmp_path,
            run_id="run-replay",
            created_at=NOW,
            shadow_input=replay_input,
        )


def test_prior_bundle_hash_and_ambiguous_recovery_fail_closed(tmp_path) -> None:
    first = prepare_composite_state_shadow(
        storage_root=tmp_path,
        run_id="run-prior",
        created_at=NOW,
        shadow_input=_shadow_input(evidence=[_macro_evidence(current=100.3)]),
    )
    artifact = tmp_path / first.artifact.storage_relative_path
    artifact.write_text(artifact.read_text(encoding="utf-8").replace("XAUUSD", "XAUUSZ", 1), encoding="utf-8")
    replay_input = _shadow_input(evidence=[_macro_evidence(current=100.3)])
    replay_input["previous_bundle_path"] = first.artifact.storage_relative_path
    with pytest.raises(Exception, match="context bundle"):
        prepare_composite_state_shadow(
            storage_root=tmp_path,
            run_id="run-replay",
            created_at=NOW,
            shadow_input=replay_input,
        )

    replay_input.pop("previous_bundle_path")
    replay_input["previous_semantic_hashes"] = {}
    replay_input["previous_bundle_path"] = first.artifact.storage_relative_path
    with pytest.raises(ValueError, match="cannot be combined"):
        prepare_composite_state_shadow(
            storage_root=tmp_path,
            run_id="run-ambiguous",
            created_at=NOW,
            shadow_input=replay_input,
        )


def test_manual_review_trace_persists_through_worker_boundary(tmp_path) -> None:
    runtime = prepare_composite_state_shadow(
        storage_root=tmp_path,
        run_id="run-review-persistence",
        created_at=NOW,
        shadow_input=_shadow_input(
            evidence=[_macro_evidence(current=101.0, source_quality="unverified")]
        ),
    )
    review = execute_composite_state_shadow(runtime=runtime, analyzer=None)["review_items"][0]
    engine = create_engine(f"sqlite:///{tmp_path / 'review-items.db'}")
    AnalysisBase.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        persist_review_items(db, [review])
        persisted = get_review_item(db, review["review_id"])
        assert persisted is not None
        assert persisted.run_id == "run-review-persistence"
        assert persisted.source_module == "state_delta_shadow"
        assert persisted.source_step_id == "evidence_delta_decision"
        assert persisted.status == "pending"
        assert persisted.evidence_refs == review["evidence_refs"]
    finally:
        db.close()


def test_setup_failure_review_item_is_stable_and_persistable(tmp_path) -> None:
    review = build_state_delta_setup_failure_review_item(
        run_id="run-setup-failure",
        failure_kind="ValueError",
    )
    replay = build_state_delta_setup_failure_review_item(
        run_id="run-setup-failure",
        failure_kind="ValueError",
    )

    assert replay["review_id"] == review["review_id"]
    assert review["source_step_id"] == "state_delta_shadow_setup"
    assert review["evidence_refs"] == []

    engine = create_engine(f"sqlite:///{tmp_path / 'setup-review-items.db'}")
    AnalysisBase.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        persist_review_items(db, [review])
        persisted = get_review_item(db, review["review_id"])
        assert persisted is not None
        assert persisted.run_id == "run-setup-failure"
        assert persisted.source_step_id == "state_delta_shadow_setup"
    finally:
        db.close()
        engine.dispose()


def test_unaccepted_figure_fact_cannot_create_material_delta(tmp_path) -> None:
    fact = FigureFact.build(
        figure_id="fig-1",
        report_id="225144",
        page_no=1,
        bbox=[0, 0, 10, 10],
        asset="XAUUSD",
        observations=["候选观察"],
        numeric_values=[],
        derived_claims=[],
        interpretation_limits=["awaiting review"],
        source_ref={
            "report_id": "225144",
            "figure_id": "fig-1",
            "page_no": 1,
            "bbox": [0, 0, 10, 10],
        },
        quality_status="needs_review",
        image_content_hash="a" * 64,
        created_by_run_id="run-70",
    )
    shadow_input = _shadow_input()
    shadow_input["figure_facts"] = [fact]
    runtime = prepare_composite_state_shadow(
        storage_root=tmp_path,
        run_id="run-69",
        created_at=NOW,
        shadow_input=shadow_input,
    )

    assert runtime.no_material_delta is True


def test_context_mode_validation(monkeypatch) -> None:
    monkeypatch.delenv("FINANCE_AGENT_ANALYSIS_CONTEXT_MODE", raising=False)
    assert resolve_analysis_context_mode() == "legacy_full_context"
    with pytest.raises(ValueError, match="unsupported"):
        resolve_analysis_context_mode("invalid")


def test_shadow_requires_explicit_scope_and_rejects_legacy_cross_scope(tmp_path) -> None:
    missing = _shadow_input()
    missing.pop("state_scope")
    with pytest.raises(ValueError, match="state_scope is required"):
        prepare_composite_state_shadow(
            storage_root=tmp_path,
            run_id="run-missing-scope",
            created_at=NOW,
            shadow_input=missing,
        )

    cross_scope = _shadow_input()
    cross_scope["state_scope"] = "intraday"
    with pytest.raises(ValueError, match="only valid for daily_close"):
        prepare_composite_state_shadow(
            storage_root=tmp_path,
            run_id="run-cross-scope",
            created_at=NOW,
            shadow_input=cross_scope,
        )
