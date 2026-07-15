from __future__ import annotations

from copy import deepcopy

from apps.analysis.strategy.recompute import RECOMPUTE_SCHEMA_VERSION, evaluate_strategy_recompute


def _strategy(*, strategy_id: str = "live-a", version: str = "live_strategy.rules.v2") -> dict:
    return {
        "schema_version": "live_strategy.v1",
        "status": "available",
        "strategy_id": strategy_id,
        "baseline_strategy_id": "baseline-a",
        "strategy_version": version,
        "asset": "XAUUSD",
        "strategy_status": "WATCHING",
        "updated_at": "2026-07-18T09:00:00+00:00",
        "live_market": {"status": "available", "price": 2360.0},
        "data_quality": {"canonical_candle": {"status": "available"}},
        "market_state": {"nearest_level": {"value": 2360.0}},
        "setups": [{"direction": "long", "stop_reference": 2348.0}],
        "event_overlay": {"status": "unavailable", "recompute_candidate": False},
    }


def _eligible_candidate(previous: dict) -> dict:
    candidate = deepcopy(previous)
    candidate.update({"strategy_id": "live-b", "updated_at": "2026-07-18T09:05:00+00:00"})
    candidate["market_state"]["nearest_level"]["value"] = 2362.0
    candidate["event_overlay"] = {
        "schema_version": "live_strategy.event_overlay.v1",
        "status": "eligible",
        "event_id": "fed-2026-07-18",
        "event_type": "fomc_statement",
        "observed_at": "2026-07-18T09:01:00+00:00",
        "recompute_candidate": True,
        "evidence": [{"kind": "release", "id": "fed-2026-07-18"}],
        "source_refs": [{"source_ref": "fed://release"}, {"source_ref": "cme://reaction"}],
    }
    return candidate


def test_same_without_overlay_is_blocked() -> None:
    previous = _strategy()
    result = evaluate_strategy_recompute(previous, deepcopy(previous))

    assert result["schema_version"] == RECOMPUTE_SCHEMA_VERSION
    assert result["accepted"] is False
    assert "candidate_event_overlay_required" not in result["reason_codes"]
    assert "event_recompute_candidate_required" in result["reason_codes"]
    assert "decision_diff_unchanged" in result["reason_codes"]
    assert result["decision_changed"] is False


def test_eligible_event_without_decision_change_is_not_executed() -> None:
    previous = _strategy()
    candidate = deepcopy(previous)
    candidate["event_overlay"] = {
        "status": "eligible",
        "recompute_candidate": True,
        "event_id": "event-1",
        "evidence": [{"id": "evidence-1"}],
    }

    result = evaluate_strategy_recompute(previous, candidate)

    assert result["accepted"] is False
    assert "decision_diff_unchanged" in result["reason_codes"]
    assert result["diff"]["changed"] is True
    assert result["decision_diff"]["changed"] is False


def test_eligible_changed_strategy_is_accepted_with_evidence_and_ref() -> None:
    previous = _strategy()
    result = evaluate_strategy_recompute(previous, _eligible_candidate(previous))

    assert result["accepted"] is True
    assert result["reason_codes"] == ["accepted:material_event_decision_changed"]
    assert result["decision_changed"] is True
    assert result["event_evidence"] == [{"kind": "release", "id": "fed-2026-07-18"}]
    assert result["event_overlay_ref"]["event_id"] == "fed-2026-07-18"
    assert result["diff"]["changed"] is True
    assert result["decision_diff"]["changed"] is True


def test_stale_or_suspended_data_blocks_candidate() -> None:
    previous = _strategy()
    candidate = _eligible_candidate(previous)
    candidate["live_market"]["status"] = "stale"
    candidate["data_quality"]["canonical_candle"]["status"] = "stale"
    candidate["strategy_status"] = "SUSPENDED_DATA"

    result = evaluate_strategy_recompute(previous, candidate)

    assert result["accepted"] is False
    assert "candidate_canonical_market_unavailable" in result["reason_codes"]
    assert "candidate_canonical_data_unavailable" in result["reason_codes"]
    assert "candidate_strategy_suspended_data" in result["reason_codes"]


def test_invalid_identity_and_missing_fields_are_explicitly_blocked() -> None:
    previous = _strategy()
    candidate = _eligible_candidate(previous)
    candidate.pop("strategy_id")
    candidate.pop("strategy_version")
    candidate["schema_version"] = "other.v1"
    candidate.pop("data_quality")
    candidate.pop("live_market")

    result = evaluate_strategy_recompute(previous, candidate)

    assert result["accepted"] is False
    assert "candidate_schema_version_required" in result["reason_codes"]
    assert "candidate_strategy_id_required" in result["reason_codes"]
    assert "candidate_strategy_version_required" in result["reason_codes"]
    assert "candidate_canonical_market_unavailable" in result["reason_codes"]
    assert "candidate_canonical_data_unavailable" in result["reason_codes"]


def test_recompute_id_is_stable_and_input_is_not_mutated() -> None:
    previous = _strategy()
    candidate = _eligible_candidate(previous)
    before = deepcopy(candidate)

    first = evaluate_strategy_recompute(previous, candidate)
    second = evaluate_strategy_recompute(previous, candidate)

    assert first["recompute_id"] == second["recompute_id"]
    assert candidate == before
