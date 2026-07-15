from __future__ import annotations

from copy import deepcopy

import pytest

from apps.analysis.strategy.recompute_execution import (
    RECOMPUTE_EXECUTION_SCHEMA_VERSION,
    execute_strategy_recompute,
)


def _strategy(*, strategy_id: str = "live-a") -> dict:
    return {
        "schema_version": "live_strategy.v1",
        "status": "available",
        "strategy_id": strategy_id,
        "baseline_strategy_id": "baseline-a",
        "strategy_version": "live_strategy.rules.v2",
        "asset": "XAUUSD",
        "strategy_status": "WATCHING",
        "updated_at": "2026-07-18T09:00:00+00:00",
        "live_market": {"status": "available", "price": 2360.0},
        "data_quality": {"canonical_candle": {"status": "available"}},
        "market_state": {
            "nearest_level": {"value": 2360.0},
            "gamma_regime": "negative_gamma",
            "latest_price_event": {"event_type": "accepted_break"},
        },
        "setups": [{"direction": "long", "stop_reference": 2348.0}],
        "event_overlay": {"status": "unavailable", "recompute_candidate": False},
    }


def _candidate(previous: dict) -> dict:
    candidate = deepcopy(previous)
    candidate["strategy_id"] = "live-b"
    candidate["updated_at"] = "2026-07-18T09:05:00+00:00"
    candidate["market_state"]["nearest_level"]["value"] = 2362.0
    candidate["event_overlay"] = {
        "schema_version": "live_strategy.event_overlay.v1",
        "status": "eligible",
        "event_id": "fed-2026-07-18",
        "event_type": "fomc_statement",
        "observed_at": "2026-07-18T09:01:00+00:00",
        "recompute_candidate": True,
        "evidence": [{"kind": "release", "id": "fed-2026-07-18"}],
        "source_refs": [{"source_ref": "fed://release"}],
    }
    return candidate


def test_accepted_path_builds_intent_and_refs() -> None:
    previous = _strategy()
    candidate = _candidate(previous)
    result = execute_strategy_recompute(
        previous,
        candidate,
        options_decision={"gamma_summary": {"regime": "negative_gamma"}},
        evidence={
            "cues": [
                {
                    "domain": "event",
                    "cue_id": "event:fed",
                    "supports": ["volatility_buying"],
                }
            ]
        },
    )

    assert result["schema_version"] == RECOMPUTE_EXECUTION_SCHEMA_VERSION
    assert result["status"] == "accepted"
    assert result["recompute"]["accepted"] is True
    assert result["institutional_intent"]["schema_version"] == "live_strategy.institutional_intent.v1"
    assert result["institutional_intent"]["status"] == "hypothesis"
    assert result["institutional_intent"]["hypotheses"]
    assert result["from_ref"] == {"strategy_id": "live-a", "strategy_version": "live_strategy.rules.v2"}
    assert result["to_ref"]["strategy_id"] == "live-b"
    assert result["execution_id"].startswith("execution-")
    assert all(item["is_fact"] is False for item in result["institutional_intent"]["hypotheses"])


def test_blocked_path_has_no_hypotheses() -> None:
    previous = _strategy()
    result = execute_strategy_recompute(previous, deepcopy(previous))

    assert result["status"] == "blocked"
    assert result["recompute"]["accepted"] is False
    assert result["institutional_intent"]["status"] == "unavailable"
    assert result["institutional_intent"]["hypotheses"] == []
    assert result["institutional_intent"]["reasons"] == ["recompute_blocked"]


@pytest.mark.parametrize(
    ("args", "message"),
    [
        ((None, {}), "previous"),
        (({}, None), "candidate"),
        (({}, {}, []), "options_decision"),
        (({}, {}, None, []), "evidence"),
    ],
)
def test_type_validation(args: tuple[object, ...], message: str) -> None:
    with pytest.raises(TypeError, match=message):
        execute_strategy_recompute(*args)  # type: ignore[arg-type]


def test_execution_id_is_stable_and_inputs_are_unchanged() -> None:
    previous = _strategy()
    candidate = _candidate(previous)
    options = {"gamma_summary": {"regime": "negative_gamma"}}
    evidence = {"cues": [{"domain": "event", "cue_id": "event:fed", "supports": ["volatility_buying"]}]}
    previous_before = deepcopy(previous)
    candidate_before = deepcopy(candidate)
    options_before = deepcopy(options)
    evidence_before = deepcopy(evidence)

    first = execute_strategy_recompute(previous, candidate, options, evidence)
    second = execute_strategy_recompute(previous, candidate, options, evidence)

    assert first["execution_id"] == second["execution_id"]
    assert previous == previous_before
    assert candidate == candidate_before
    assert options == options_before
    assert evidence == evidence_before
