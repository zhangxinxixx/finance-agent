from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from apps.analysis.figure_facts import FigureFact
from apps.worker.composite_state_shadow import (
    execute_composite_state_shadow,
    finalize_composite_state_shadow,
    prepare_composite_state_shadow,
    resolve_analysis_context_mode,
)


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
    assert trace["schema_version"] == "composite_state_shadow.v2"
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
