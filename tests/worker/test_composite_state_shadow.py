from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from apps.analysis.figure_facts import FigureFact
from apps.analysis.context_bundle.snapshot_evidence import SNAPSHOT_PASSPORT_METADATA_KEY
from apps.analysis.state import TransitionCandidate
from apps.analysis.state.transition_generator import ScopedTransitionCandidate
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
        ],
        "state_patch": {
            "core_thesis": "突破确认",
        },
        "evidence_refs": [REF],
    }


def _accepted_figure_fact() -> FigureFact:
    return FigureFact.build(
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


def test_same_run_restart_recovers_exact_registered_bundle_descriptor(tmp_path) -> None:
    first = prepare_composite_state_shadow(
        storage_root=tmp_path,
        run_id="run-registry-restart",
        created_at=NOW,
        shadow_input=_shadow_input(evidence=[_evidence()]),
    )
    restart_input = _shadow_input(evidence=[_macro_evidence(current=101.0)])
    restart_input["context_bundle_artifact"] = first.artifact.registry_artifact

    recovered = prepare_composite_state_shadow(
        storage_root=tmp_path,
        run_id="run-registry-restart",
        created_at=NOW + timedelta(hours=1),
        shadow_input=restart_input,
    )

    assert recovered.bundle.bundle_id == first.bundle.bundle_id
    assert recovered.bundle.content_hash == first.bundle.content_hash
    assert recovered.evidence_delta_decision == first.evidence_delta_decision
    assert recovered.artifact.written is False
    assert recovered.artifact.registry_artifact == first.artifact.registry_artifact


def test_same_run_restart_rejects_wrong_run_and_tampered_descriptor(tmp_path) -> None:
    first = prepare_composite_state_shadow(
        storage_root=tmp_path,
        run_id="run-registry-source",
        created_at=NOW,
        shadow_input=_shadow_input(),
    )
    wrong_run_input = _shadow_input()
    wrong_run_input["context_bundle_artifact"] = first.artifact.registry_artifact
    with pytest.raises(ValueError, match="run_id does not match runtime"):
        prepare_composite_state_shadow(
            storage_root=tmp_path,
            run_id="run-registry-other",
            created_at=NOW,
            shadow_input=wrong_run_input,
        )

    tampered = {
        **first.artifact.registry_artifact,
        "metadata": {
            **first.artifact.registry_artifact["metadata"],
            "content_hash": "0" * 64,
        },
    }
    tampered_input = _shadow_input()
    tampered_input["context_bundle_artifact"] = tampered
    with pytest.raises(ValueError, match="identity mismatch: content_hash"):
        prepare_composite_state_shadow(
            storage_root=tmp_path,
            run_id="run-registry-source",
            created_at=NOW,
            shadow_input=tampered_input,
        )


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


def test_review_system_metadata_is_projected_only_from_bundle(tmp_path) -> None:
    runtime = prepare_composite_state_shadow(
        storage_root=tmp_path,
        run_id="run-system-metadata",
        created_at=NOW,
        shadow_input=_shadow_input(evidence=[_evidence()]),
    )
    trace = execute_composite_state_shadow(
        runtime=runtime,
        analyzer=_candidate,
        _return_review=True,
    )
    review = trace["_review_result"]

    assert review.next_state.as_of == runtime.bundle.cutoff_at
    assert review.next_state.evidence_cursors == {
        source: cursor.model_dump(mode="json")
        for source, cursor in runtime.bundle.next_evidence_cursors.items()
    }
    assert review.next_state.input_snapshot_ids == {
        "market": "market-1",
        "context_bundle_id": runtime.bundle.bundle_id,
        "context_bundle_hash": runtime.bundle.content_hash,
        "context_bundle_run_id": runtime.bundle.run_id,
        "canonical_state_id": runtime.bundle.canonical_state_id,
        "evidence_delta_decision_id": runtime.evidence_delta_decision.decision_id,
    }
    assert review.next_state.source_refs == [REF]


def test_review_metadata_retains_bundle_snapshot_passport_without_fabricating_missing_ids(
    tmp_path,
) -> None:
    shadow_input = _shadow_input(evidence=[_evidence()])
    shadow_input["canonical_state"]["input_snapshot_ids"] = {
        "market": "market-snapshot-1",
        "macro": "macro-snapshot-1",
        "options": "options-snapshot-1",
        "events": "events-snapshot-1",
        "reports": "reports-snapshot-1",
        "missing": " ",
    }
    fact = _accepted_figure_fact()
    shadow_input["figure_facts"] = [fact]
    runtime = prepare_composite_state_shadow(
        storage_root=tmp_path,
        run_id="run-snapshot-passport",
        created_at=NOW,
        shadow_input=shadow_input,
    )

    first = execute_composite_state_shadow(
        runtime=runtime,
        analyzer=_candidate,
        _return_review=True,
    )["_review_result"].next_state.input_snapshot_ids
    replay = execute_composite_state_shadow(
        runtime=runtime,
        analyzer=_candidate,
        _return_review=True,
    )["_review_result"].next_state.input_snapshot_ids

    assert {key: first[key] for key in ("market", "macro", "options", "events", "reports")} == {
        "market": "market-snapshot-1",
        "macro": "macro-snapshot-1",
        "options": "options-snapshot-1",
        "events": "events-snapshot-1",
        "reports": "reports-snapshot-1",
    }
    assert first["figure_fact_id_1"] == fact.figure_fact_id
    assert "missing" not in first
    assert "positioning" not in first
    assert first["context_bundle_id"] == runtime.bundle.bundle_id
    assert first["context_bundle_hash"] == runtime.bundle.content_hash
    assert first["context_bundle_run_id"] == runtime.bundle.run_id
    assert first["canonical_state_id"] == runtime.bundle.canonical_state_id
    assert first == replay


def test_review_metadata_overlays_current_bundle_snapshot_passport(
    tmp_path,
) -> None:
    evidence = _evidence()
    evidence["payload"]["metadata"] = {
        SNAPSHOT_PASSPORT_METADATA_KEY: {
            "analysis_snapshot": "XAUUSD:2026-07-22:run-current",
            "analysis_snapshot_db_id": "00000000-0000-0000-0000-000000000022",
            "macro": "macro-current",
            "options": "options-current",
            "options_detail.raw_file_sha256": "raw-current",
        }
    }
    shadow_input = _shadow_input(evidence=[evidence])
    shadow_input["canonical_state"]["input_snapshot_ids"] = {
        "analysis_snapshot": "XAUUSD:2026-07-21:run-previous",
        "macro": "macro-previous",
        "options": "options-previous",
        "predecessor_only": "retained-lineage",
    }
    runtime = prepare_composite_state_shadow(
        storage_root=tmp_path,
        run_id="run-current-snapshot-passport",
        created_at=NOW,
        shadow_input=shadow_input,
    )

    snapshot_ids = execute_composite_state_shadow(
        runtime=runtime,
        analyzer=_candidate,
        _return_review=True,
    )["_review_result"].next_state.input_snapshot_ids

    assert snapshot_ids["analysis_snapshot"] == "XAUUSD:2026-07-22:run-current"
    assert snapshot_ids["analysis_snapshot_db_id"] == "00000000-0000-0000-0000-000000000022"
    assert snapshot_ids["macro"] == "macro-current"
    assert snapshot_ids["options"] == "options-current"
    assert snapshot_ids["options_detail.raw_file_sha256"] == "raw-current"
    assert snapshot_ids["predecessor_only"] == "retained-lineage"
    assert snapshot_ids["context_bundle_id"] == runtime.bundle.bundle_id


def test_review_metadata_rejects_conflicting_current_snapshot_passports(
    tmp_path,
) -> None:
    market = _evidence()
    macro = _macro_evidence(current=101.0)
    market["payload"]["metadata"] = {
        SNAPSHOT_PASSPORT_METADATA_KEY: {"analysis_snapshot": "snapshot-current-a"}
    }
    macro["payload"]["metadata"] = {
        SNAPSHOT_PASSPORT_METADATA_KEY: {"analysis_snapshot": "snapshot-current-b"}
    }
    runtime = prepare_composite_state_shadow(
        storage_root=tmp_path,
        run_id="run-conflicting-snapshot-passport",
        created_at=NOW,
        shadow_input=_shadow_input(evidence=[market, macro]),
    )

    trace = execute_composite_state_shadow(
        runtime=runtime,
        analyzer=_candidate,
        _return_review=True,
    )

    assert trace["status"] == "candidate_rejected"
    assert "conflicting AnalysisSnapshot passports" in trace["reason"]


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
def test_evidence_delta_action_is_the_only_analyzer_gate(tmp_path, evidence, expected_action, expected_calls) -> None:
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
    replay_input["previous_semantic_hashes"] = dict(first.evidence_delta_decision.semantic_hashes)
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
    fact = _accepted_figure_fact()
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
    assert [item.evidence_type for item in runtime.evidence_delta_decision.evaluated_items] == ["figure_fact"]
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


def test_registered_prior_bundle_recovers_delta_and_selection_state(tmp_path) -> None:
    first_input = _shadow_input(evidence=[_macro_evidence(current=100.3)])
    first_input.update(
        {
            "freshness_sla_seconds": {"macro": 123},
            "default_freshness_sla_seconds": 456,
        }
    )
    first = prepare_composite_state_shadow(
        storage_root=tmp_path,
        run_id="run-registered-prior",
        created_at=NOW,
        shadow_input=first_input,
    )
    next_input = _shadow_input(evidence=[_macro_evidence(current=100.3)])
    next_input["previous_context_bundle_artifact"] = first.artifact.registry_artifact

    replay = prepare_composite_state_shadow(
        storage_root=tmp_path,
        run_id="run-registered-replay",
        created_at=NOW + timedelta(hours=1),
        shadow_input=next_input,
    )

    assert replay.bundle.freshness_sla_seconds == {"macro": 123}
    assert replay.bundle.default_freshness_sla_seconds == 456
    assert replay.evidence_delta_decision.recommended_action.value == "no_op"
    assert replay.bundle.deferred_queue == first.bundle.deferred_queue
    assert replay.bundle.processed_above_frontier == first.bundle.processed_above_frontier


def test_predecessor_bundle_recovery_restores_cursor_and_merges_current_evidence(tmp_path) -> None:
    duplicate = _macro_evidence(current=100.3)
    first_input = _shadow_input(evidence=[duplicate])
    first_input.update(
        {
            "freshness_sla_seconds": {"macro": 123},
            "default_freshness_sla_seconds": 456,
        }
    )
    first = prepare_composite_state_shadow(
        storage_root=tmp_path,
        run_id="run-committed-source",
        created_at=NOW,
        shadow_input=first_input,
    )
    current = _macro_evidence(current=101.0)
    retry_input = _shadow_input(evidence=[duplicate, current])
    retry_input["canonical_state_id"] = "state-latest"
    retry_input["previous_context_bundle_artifact"] = first.artifact.registry_artifact
    retry_input["previous_context_bundle_base_canonical_state_id"] = "state-66"
    retry_input.pop("evidence_cursors")

    replay = prepare_composite_state_shadow(
        storage_root=tmp_path,
        run_id="run-cas-retry",
        created_at=NOW + timedelta(hours=1),
        shadow_input=retry_input,
    )

    assert replay.bundle.canonical_state_id == "state-latest"
    assert replay.bundle.evidence_cursors == first.bundle.next_evidence_cursors
    assert replay.bundle.freshness_sla_seconds == {"macro": 123}
    assert replay.bundle.default_freshness_sla_seconds == 456
    delta = next(block for block in replay.bundle.blocks if block.name == "delta_evidence")
    assert [item["evidence_id"] for item in delta.payload] == [current["evidence_id"]]
    assert replay.bundle.next_evidence_cursors["macro"].evidence_id == current["evidence_id"]


def test_predecessor_bundle_recovery_rejects_wrong_base_lineage(tmp_path) -> None:
    first = prepare_composite_state_shadow(
        storage_root=tmp_path,
        run_id="run-committed-source",
        created_at=NOW,
        shadow_input=_shadow_input(evidence=[_macro_evidence(current=100.3)]),
    )
    retry_input = _shadow_input(evidence=[_macro_evidence(current=101.0)])
    retry_input["canonical_state_id"] = "state-latest"
    retry_input["previous_context_bundle_artifact"] = first.artifact.registry_artifact
    retry_input["previous_context_bundle_base_canonical_state_id"] = "wrong-predecessor"
    retry_input.pop("evidence_cursors")

    with pytest.raises(ValueError, match="canonical_state_id"):
        prepare_composite_state_shadow(
            storage_root=tmp_path,
            run_id="run-cas-retry",
            created_at=NOW + timedelta(hours=1),
            shadow_input=retry_input,
        )


def test_registered_recovery_preserves_nonempty_deferred_and_processed_frontier(tmp_path) -> None:
    evidence = [
        {
            "source": "news",
            "evidence_id": f"news-{index}",
            "business_time": NOW + timedelta(minutes=index),
            "ingested_at": NOW + timedelta(minutes=index),
            "session": "asia",
            "payload": {
                "evidence_type": "material_event",
                "asset": "XAUUSD",
                "source_quality": "official",
                "event_id": f"news-{index}",
                "cluster_key": f"cluster:news-{index}",
                "event_type": "test_event",
                "claim": "消息" * 500,
                "materiality_score": 10,
                "risk_level": "low",
                "recompute_eligible": False,
                "confirmation_status": "confirmed",
            },
            "source_ref": {"snapshot_id": f"news-{index}"},
        }
        for index in range(1, 9)
    ]
    first_input = _shadow_input(evidence=evidence)
    first_input.update(
        {
            "cutoff_at": NOW + timedelta(minutes=10),
            "budget_tokens": 1_600,
            "freshness_sla_seconds": {"news": 321},
            "default_freshness_sla_seconds": 654,
        }
    )
    first = prepare_composite_state_shadow(
        storage_root=tmp_path,
        run_id="run-frontier-source",
        created_at=NOW,
        shadow_input=first_input,
    )
    assert first.bundle.deferred_queue
    assert first.bundle.processed_above_frontier["news"]

    retry_input = _shadow_input(evidence=evidence)
    retry_input.update(
        {
            "cutoff_at": NOW + timedelta(minutes=10),
            "budget_tokens": 1_600,
            "previous_context_bundle_artifact": first.artifact.registry_artifact,
        }
    )
    retry_input.pop("evidence_cursors")
    replay = prepare_composite_state_shadow(
        storage_root=tmp_path,
        run_id="run-frontier-retry",
        created_at=NOW + timedelta(hours=1),
        shadow_input=retry_input,
    )

    first_deferred = {item["evidence_id"] for item in first.bundle.deferred_queue}
    replay_accounted = {
        item["evidence_id"] for item in replay.bundle.deferred_queue
    } | set(next(block for block in replay.bundle.blocks if block.name == "delta_evidence").retained_evidence_ids)
    assert first_deferred <= replay_accounted
    assert replay.bundle.freshness_sla_seconds == {"news": 321}
    assert replay.bundle.default_freshness_sla_seconds == 654
    assert any(
        "already_processed_above_frontier" in decision["reasons"]
        for decision in replay.bundle.selection_decisions
    )


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
        shadow_input=_shadow_input(evidence=[_macro_evidence(current=101.0, source_quality="unverified")]),
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
    assert resolve_analysis_context_mode() == "legacy"
    assert resolve_analysis_context_mode("legacy_full_context") == "legacy"
    assert resolve_analysis_context_mode("state_delta_context") == "shadow"
    assert resolve_analysis_context_mode("canary") == "canary"
    assert resolve_analysis_context_mode("state_delta_primary") == "state_delta_primary"
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


def test_canary_rejects_bare_or_stale_scoped_candidate(tmp_path) -> None:
    runtime = prepare_composite_state_shadow(
        storage_root=tmp_path,
        run_id="run-canary-bound",
        created_at=NOW,
        shadow_input=_shadow_input(evidence=[_evidence()]),
    )
    bare = execute_composite_state_shadow(
        runtime=runtime,
        analyzer=_candidate,
        mode="canary",
    )
    assert bare["status"] == "candidate_rejected"

    def stale(bundle):
        return ScopedTransitionCandidate(
            asset="XAUUSD",
            state_scope="daily_close",
            run_id=bundle.run_id,
            canonical_state_id=bundle.canonical_state_id,
            context_bundle_id="stale-bundle",
            context_bundle_hash="a" * 64,
            candidate=TransitionCandidate.model_validate(_candidate(bundle)),
        )

    rejected = execute_composite_state_shadow(runtime=runtime, analyzer=stale, mode="canary")
    assert rejected["status"] == "candidate_rejected"
    assert "Bundle identity" in rejected["reason"]
