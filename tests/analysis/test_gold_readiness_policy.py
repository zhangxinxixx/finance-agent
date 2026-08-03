from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from apps.analysis.gold_policy.feature_snapshot import build_feature_snapshot
from apps.analysis.gold_policy.readiness_policy import evaluate_gold_readiness
from apps.analysis.gold_policy.schemas import FeatureSnapshotV2, FeatureSnapshotV2Input


_FIXTURE = (
    Path(__file__).parents[1]
    / "fixtures"
    / "gold_policy"
    / "real10y_v2_cases.json"
)
_CUTOFF = "2025-01-17T21:00:00Z"


def _payload() -> dict:
    fixture = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    payload = deepcopy(fixture["base_payload"])
    aligned = next(case for case in fixture["cases"] if case["id"] == "aligned")
    for field_name, changes in aligned["patch"].items():
        payload[field_name].update(changes)
    for field_name, value in payload.items():
        if isinstance(value, dict) and "source_refs" in value:
            for reference in value["source_refs"]:
                reference["retrieved_at"] = _CUTOFF
    return payload


def _decision(payload: dict | None = None):
    input_snapshot = FeatureSnapshotV2Input.model_validate(payload or _payload())
    built = build_feature_snapshot(input_snapshot)
    assert isinstance(built, FeatureSnapshotV2)
    return evaluate_gold_readiness(
        input_snapshot,
        real10y_estimated=built.real10y_estimated,
    )


def _missing(payload: dict, field_name: str) -> None:
    payload[field_name].update(
        value=None,
        freshness_status="missing",
        quality_status="blocked",
        alignment_status="unknown",
    )


def test_complete_snapshot_has_ready_domains_and_normal_no_event_semantics() -> None:
    decision = _decision()

    assert decision.policy_version == "gold_readiness_policy.v1"
    assert (
        decision.analysis_readiness,
        decision.strategy_readiness,
        decision.options_readiness,
        decision.event_attribution_readiness,
    ) == ("ready", "ready", "ready", "ready")
    assert decision.missing_required_inputs == ()
    assert decision.missing_confirmatory_inputs == ()
    assert decision.prohibited_outputs == ()
    assert decision.reason_codes == ("NO_MATERIAL_OFFICIAL_EVENT",)


@pytest.mark.parametrize(
    ("field_name", "expected_missing"),
    (
        ("xauusd_spot", ("XAUUSD",)),
        ("us10y", ("US10Y", "REAL10Y_ESTIMATED")),
        ("t10yie", ("T10YIE", "REAL10Y_ESTIMATED")),
        ("broad_dollar", ("BROAD_DOLLAR",)),
    ),
)
def test_missing_raw_core_blocks_analysis_and_strategy(
    field_name: str,
    expected_missing: tuple[str, ...],
) -> None:
    payload = _payload()
    _missing(payload, field_name)
    decision = _decision(payload)

    assert decision.analysis_readiness == "blocked"
    assert decision.strategy_readiness == "blocked"
    assert decision.missing_required_inputs == expected_missing
    assert decision.prohibited_outputs[:2] == (
        "DIRECTIONAL_ANALYSIS",
        "DIRECTIONAL_STRATEGY",
    )


def test_unavailable_estimated_real10y_is_a_required_core_failure() -> None:
    payload = _payload()
    payload["t10yie"]["as_of"] = "2025-01-16T21:00:00Z"
    decision = _decision(payload)

    assert decision.missing_required_inputs == ("REAL10Y_ESTIMATED",)
    assert decision.analysis_readiness == "blocked"
    assert "REQUIRED_INPUT_UNUSABLE:REAL10Y_ESTIMATED" in decision.reason_codes


def test_core_cutoff_or_source_lineage_violation_blocks_directional_outputs() -> None:
    payload = _payload()
    payload["broad_dollar"]["source_refs"][0]["retrieved_at"] = (
        "2025-01-17T21:00:01Z"
    )
    decision = _decision(payload)

    assert decision.missing_required_inputs == ("BROAD_DOLLAR",)
    assert decision.analysis_readiness == "blocked"
    assert decision.prohibited_outputs[:2] == (
        "DIRECTIONAL_ANALYSIS",
        "DIRECTIONAL_STRATEGY",
    )


@pytest.mark.parametrize(
    ("field_name", "label"),
    (
        ("us02y", "US02Y"),
        ("us30y", "US30Y"),
        ("gc_futures", "GC"),
        ("wti", "WTI"),
        ("brent", "BRENT"),
        ("etf_flow", "ETF"),
        ("cot", "COT"),
    ),
)
def test_missing_confirmatory_input_observes_but_never_blocks_analysis(
    field_name: str,
    label: str,
) -> None:
    payload = _payload()
    _missing(payload, field_name)
    decision = _decision(payload)

    assert decision.analysis_readiness == "observe"
    assert decision.strategy_readiness == "observe"
    assert decision.missing_required_inputs == ()
    assert decision.missing_confirmatory_inputs == (label,)
    assert "DIRECTIONAL_ANALYSIS" not in decision.prohibited_outputs
    assert "TRIGGERED_STRATEGY" in decision.prohibited_outputs


def test_missing_options_blocks_only_options_and_caps_strategy_at_observe() -> None:
    payload = _payload()
    _missing(payload, "cme_options_regime")
    decision = _decision(payload)

    assert decision.analysis_readiness == "ready"
    assert decision.options_readiness == "blocked"
    assert decision.strategy_readiness == "observe"
    assert decision.prohibited_outputs == (
        "OPTIONS_CONFIRMATION",
        "TRIGGERED_STRATEGY",
    )


def test_confirmed_structured_event_is_ready() -> None:
    payload = _payload()
    payload["official_events"]["events"] = [
        {
            "event_id": "fomc-2025-01-17",
            "title": "FOMC statement",
            "occurred_at": "2025-01-17T20:00:00Z",
            "reaction_window_end": "2025-01-17T20:30:00Z",
            "reaction_summary": "XAUUSD rose in the bounded reaction window.",
            "reaction_asset": "XAUUSD",
            "reaction_return_pct": 0.4,
            "reaction_status": "confirmed",
            "source_refs": [
                {
                    "source": "federal_reserve",
                    "reference": "official://fomc/2025-01-17",
                    "retrieved_at": _CUTOFF,
                }
            ],
            "reaction_source_refs": [
                {
                    "source": "xauusd_candles",
                    "reference": "market://xauusd/fomc-2025-01-17/30m",
                    "retrieved_at": _CUTOFF,
                }
            ],
        }
    ]
    decision = _decision(payload)

    assert decision.event_attribution_readiness == "ready"
    assert decision.reason_codes[-1] == "OFFICIAL_EVENT_REACTION_CONFIRMED"
    assert "CONFIRMED_EVENT_ATTRIBUTION" not in decision.prohibited_outputs


@pytest.mark.parametrize(
    "reaction_window_end",
    ("2025-01-17T21:00:01Z", "2025-01-17T19:59:59Z"),
)
def test_invalid_reaction_window_blocks_event_attribution(
    reaction_window_end: str,
) -> None:
    payload = _payload()
    payload["official_events"]["events"] = [
        {
            "event_id": "fomc-2025-01-17",
            "title": "FOMC statement",
            "occurred_at": "2025-01-17T20:00:00Z",
            "reaction_window_end": reaction_window_end,
            "reaction_summary": "XAUUSD reaction window",
            "reaction_asset": "XAUUSD",
            "reaction_return_pct": 0.4,
            "reaction_status": "confirmed",
            "source_refs": [
                {
                    "source": "federal_reserve",
                    "reference": "official://fomc/2025-01-17",
                    "retrieved_at": _CUTOFF,
                }
            ],
            "reaction_source_refs": [
                {
                    "source": "xauusd_candles",
                    "reference": "market://xauusd/fomc-2025-01-17/30m",
                    "retrieved_at": _CUTOFF,
                }
            ],
        }
    ]
    decision = _decision(payload)

    assert decision.event_attribution_readiness == "blocked"
    assert decision.prohibited_outputs == ("CONFIRMED_EVENT_ATTRIBUTION",)
    assert decision.reason_codes[-1] == "OFFICIAL_EVENT_SNAPSHOT_UNUSABLE"


@pytest.mark.parametrize(
    ("axis", "value"),
    (
        ("freshness_status", "stale"),
        ("quality_status", "observe"),
        ("alignment_status", "unknown"),
    ),
)
def test_degraded_empty_event_snapshot_is_observe_not_no_material_event(
    axis: str,
    value: str,
) -> None:
    payload = _payload()
    payload["official_events"][axis] = value
    decision = _decision(payload)

    assert decision.event_attribution_readiness == "observe"
    assert decision.prohibited_outputs == ("CONFIRMED_EVENT_ATTRIBUTION",)
    assert decision.reason_codes[-1] == "OFFICIAL_EVENT_SNAPSHOT_DEGRADED"
    assert "NO_MATERIAL_OFFICIAL_EVENT" not in decision.reason_codes


def test_unconfirmed_event_is_observe_and_cannot_claim_confirmed_attribution() -> None:
    payload = _payload()
    payload["official_events"]["events"] = [
        {
            "event_id": "fomc-2025-01-17",
            "title": "FOMC statement",
            "occurred_at": "2025-01-17T20:00:00Z",
            "reaction_status": "unconfirmed",
            "source_refs": [
                {
                    "source": "federal_reserve",
                    "reference": "official://fomc/2025-01-17",
                    "retrieved_at": _CUTOFF,
                }
            ],
        }
    ]
    decision = _decision(payload)

    assert decision.event_attribution_readiness == "observe"
    assert decision.prohibited_outputs == ("CONFIRMED_EVENT_ATTRIBUTION",)
    assert decision.reason_codes[-1] == "OFFICIAL_EVENT_REACTION_UNCONFIRMED"


def test_missing_or_malformed_event_snapshot_blocks_event_domain_only() -> None:
    payload = _payload()
    payload["official_events"].update(
        freshness_status="missing",
        quality_status="blocked",
        alignment_status="misaligned",
    )
    decision = _decision(payload)

    assert decision.event_attribution_readiness == "blocked"
    assert decision.analysis_readiness == "ready"
    assert decision.strategy_readiness == "ready"
    assert decision.options_readiness == "ready"
    assert decision.prohibited_outputs == ("CONFIRMED_EVENT_ATTRIBUTION",)


def test_decision_is_frozen_and_stably_ordered_across_repeated_runs() -> None:
    payload = _payload()
    _missing(payload, "broad_dollar")
    _missing(payload, "us02y")
    _missing(payload, "etf_flow")
    _missing(payload, "cme_options_regime")
    input_snapshot = FeatureSnapshotV2Input.model_validate(payload)
    built = build_feature_snapshot(input_snapshot)
    assert isinstance(built, FeatureSnapshotV2)
    decisions = [
        evaluate_gold_readiness(
            input_snapshot,
            real10y_estimated=built.real10y_estimated,
        )
        for _ in range(100)
    ]
    assert all(decision == decisions[0] for decision in decisions)
    assert decisions[0].missing_required_inputs == ("BROAD_DOLLAR",)
    assert decisions[0].missing_confirmatory_inputs == ("US02Y", "ETF")
    assert decisions[0].prohibited_outputs == (
        "DIRECTIONAL_ANALYSIS",
        "DIRECTIONAL_STRATEGY",
        "OPTIONS_CONFIRMATION",
        "TRIGGERED_STRATEGY",
    )
    with pytest.raises(ValidationError):
        decisions[0].analysis_readiness = "ready"  # type: ignore[misc]
