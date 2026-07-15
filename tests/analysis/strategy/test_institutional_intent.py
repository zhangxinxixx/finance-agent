from __future__ import annotations

from copy import deepcopy

from apps.analysis.strategy.institutional_intent import (
    SCHEMA_VERSION,
    SUPPORTED_LABELS,
    build_institutional_intent_hypotheses,
)


def _cue(cue_id: str, domain: str, supports: list[str], *, contradicts: list[str] | None = None) -> dict[str, object]:
    return {
        "cue_id": cue_id,
        "domain": domain,
        "supports": supports,
        "contradicts": contradicts or [],
        "detail": f"{domain} evidence",
        "source_ref": f"source:{cue_id}",
    }


def test_builds_supported_hypotheses_as_non_facts_with_two_independent_cues() -> None:
    evidence = {
        "cues": [
            _cue("gamma", "gamma", ["volatility_buying", "liquidity_sweep"]),
            _cue("price", "price_event", ["new_positioning", "liquidity_sweep", "covering"]),
            _cue("oi", "options_oi", ["new_positioning", "hedging"]),
            _cue("tail", "options_wall", ["hedging"]),
            _cue("close", "options_oi_change", ["covering"]),
            _cue("iv", "volatility", ["volatility_buying", "volatility_selling"]),
            _cue("regime", "gamma_regime", ["volatility_selling"]),
        ]
    }

    result = build_institutional_intent_hypotheses({}, evidence=evidence)

    assert result["schema_version"] == SCHEMA_VERSION
    assert result["status"] == "hypothesis"
    labels = {item["label"] for item in result["hypotheses"]}
    assert labels == set(SUPPORTED_LABELS)
    for item in result["hypotheses"]:
        assert item["status"] == "hypothesis"
        assert item["is_fact"] is False
        assert 0.0 <= item["confidence"] <= 1.0
        assert len({ref["domain"] for ref in item["evidence_refs"]}) >= 2
        assert item["evidence_refs"] == item["evidence"]


def test_derived_gamma_price_and_oi_cues_support_positioning_without_claiming_fact() -> None:
    strategy = {
        "market_state": {
            "gamma_regime": "negative_gamma",
            "latest_price_event": {"event_type": "accepted_break", "confirmed": True, "direction": "above"},
        }
    }
    options = {"oi_summary": {"total": {"delta": 120}, "call": {"delta": 70}, "put": {"delta": 50}}}

    result = build_institutional_intent_hypotheses(strategy, options)

    by_label = {item["label"]: item for item in result["hypotheses"]}
    assert "new_positioning" in by_label
    assert "volatility_buying" in by_label  # gamma plus a confirmed break forms two cues
    assert by_label["new_positioning"]["is_fact"] is False
    assert {ref["domain"] for ref in by_label["new_positioning"]["evidence_refs"]} == {"options_oi", "price_event"}


def test_insufficient_or_single_domain_evidence_is_unavailable() -> None:
    one_cue = build_institutional_intent_hypotheses(
        {}, evidence={"cues": [_cue("only", "gamma", ["new_positioning", "hedging"])]}
    )
    same_domain = build_institutional_intent_hypotheses(
        {},
        evidence={
            "cues": [
                _cue("a", "options_oi", ["new_positioning"]),
                _cue("b", "options_oi", ["new_positioning"]),
            ]
        },
    )

    for result in (one_cue, same_domain):
        assert result["status"] == "unavailable"
        assert result["hypotheses"] == []
        assert result["reasons"] == ["insufficient_independent_cues"]
        assert result["evidence_refs"] == []


def test_contradictory_cue_lowers_confidence_and_is_retained_as_counter_evidence() -> None:
    clean = build_institutional_intent_hypotheses(
        {}, evidence={"cues": [_cue("gamma", "gamma", ["volatility_buying"]), _cue("event", "price_event", ["volatility_buying"])]}
    )
    conflicted = build_institutional_intent_hypotheses(
        {},
        evidence={
            "cues": [
                _cue("gamma", "gamma", ["volatility_buying"], contradicts=["volatility_selling"]),
                _cue("event", "price_event", ["volatility_buying"]),
                _cue("counter", "options_oi", [], contradicts=["volatility_buying"]),
            ]
        },
    )
    clean_item = next(item for item in clean["hypotheses"] if item["label"] == "volatility_buying")
    conflicted_item = next(item for item in conflicted["hypotheses"] if item["label"] == "volatility_buying")

    assert conflicted_item["confidence"] < clean_item["confidence"]
    assert any(ref["cue_id"] == "counter" for ref in conflicted_item["counter_evidence"])
    assert any(ref["cue_id"] == "counter" for ref in conflicted["counter_evidence"])


def test_output_is_deterministic_and_inputs_are_not_mutated() -> None:
    strategy = {"market_state": {"gamma_regime": "negative_gamma"}}
    options = {"oi_summary": {"total": {"delta": 3}}}
    evidence = {"cues": [_cue("z", "price_event", ["liquidity_sweep"]), _cue("a", "gamma", ["liquidity_sweep"])]}
    before = deepcopy((strategy, options, evidence))

    first = build_institutional_intent_hypotheses(strategy, options, evidence)
    second = build_institutional_intent_hypotheses(
        strategy,
        options,
        {"cues": list(reversed(evidence["cues"]))},
    )

    assert first == second
    assert first["intent_id"].startswith("intent-")
    assert (strategy, options, evidence) == before


def test_unsupported_labels_and_untrusted_direction_are_ignored() -> None:
    result = build_institutional_intent_hypotheses(
        {"market_state": {"latest_price_event": {"event_type": "touch", "direction": "above"}}},
        evidence={
            "cues": [
                _cue("a", "price_event", ["certain_institutional_buying"]),
                _cue("b", "price_event_2", ["certain_institutional_buying"]),
            ]
        },
    )

    assert result["status"] == "unavailable"
    assert all(item["label"] in SUPPORTED_LABELS for item in result["hypotheses"])
