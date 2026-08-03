from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from apps.analysis.gold_policy.analysis_policy import (
    GoldAnalysisDecisionV2,
    evaluate_gold_analysis_policy,
)
from apps.analysis.gold_policy.feature_snapshot import build_feature_snapshot


_ROOT = Path(__file__).parents[2]
_CASES = _ROOT / "tests/fixtures/gold_policy/analysis_v2/cases.json"
_V1_PREVIOUS = _ROOT / "tests/fixtures/gold_policy/feature_snapshot_v1_bullish_2025-01-17.json"
_V1_CURRENT = _ROOT / "tests/fixtures/gold_policy/feature_snapshot_v1_bearish_2025-01-21.json"


def _fixture() -> dict:
    return json.loads(_CASES.read_text(encoding="utf-8"))


def _set_times(payload: dict, as_of: str) -> None:
    payload["as_of"] = as_of
    for value in payload.values():
        if not isinstance(value, dict):
            continue
        if "as_of" in value:
            value["as_of"] = as_of
        for ref in value.get("source_refs", []):
            ref["retrieved_at"] = as_of


def _pair(case: dict):
    previous_payload = deepcopy(_fixture()["base_payload"])
    _set_times(previous_payload, "2025-01-17T21:00:00Z")
    current_payload = deepcopy(previous_payload)
    _set_times(current_payload, "2025-01-21T21:00:00Z")
    deltas = {key: Decimal(value) for key, value in case.get("deltas", {}).items()}
    breakeven_delta = deltas.get("breakeven", Decimal("0"))
    real10y_delta = deltas.get("real10y_estimated", Decimal("0"))
    current_payload["t10yie"]["value"] = float(
        Decimal(str(previous_payload["t10yie"]["value"])) + breakeven_delta
    )
    current_payload["us10y"]["value"] = float(
        Decimal(str(previous_payload["us10y"]["value"])) + breakeven_delta + real10y_delta
    )
    current_estimated = Decimal(str(current_payload["us10y"]["value"])) - Decimal(
        str(current_payload["t10yie"]["value"])
    )
    current_payload["real10y_direct"]["value"] = float(
        current_estimated + deltas.get("real10y_direct", Decimal("0"))
    )
    current_payload["broad_dollar"]["value"] = float(
        Decimal(str(previous_payload["broad_dollar"]["value"]))
        + deltas.get("broad_dollar", Decimal("0"))
    )
    current_payload["xauusd_spot"]["value"] = float(
        Decimal(str(previous_payload["xauusd_spot"]["value"]))
        + deltas.get("xauusd_spot", Decimal("0"))
    )
    for field in case.get("missing_confirmatory", []):
        current_payload[field].update(
            value=None,
            freshness_status="missing",
            quality_status="blocked",
            alignment_status="unknown",
        )
    for field, changes in case.get("factor_statuses", {}).items():
        current_payload[field].update(changes)
    return build_feature_snapshot(current_payload), build_feature_snapshot(previous_payload)


def _decision(case_id: str):
    case = next(item for item in _fixture()["cases"] if item["id"] == case_id)
    current, previous = _pair(case)
    return case, evaluate_gold_analysis_policy(current, previous)


def _details(decision) -> dict[str, dict]:
    return {item.factor: item.model_dump(mode="json") for item in decision.factor_contributions}


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(Decimal(_fixture()["output_quantum"]), rounding=ROUND_HALF_EVEN)


def test_xauusd_alone_is_not_a_macro_direction_contribution() -> None:
    case, decision = _decision("xauusd_only_up")
    assert decision.policy_version == "gold_analysis_policy.v2"
    assert decision.materiality_policy_version == "gold_analysis_materiality.v1"
    assert decision.direction == case["expected"]["direction"]
    assert decision.direction_tilt == case["expected"]["direction_tilt"]
    assert Decimal(str(decision.net_contribution)) == Decimal("0.0")
    assert "xauusd_price_state" not in _details(decision)


@pytest.mark.parametrize("factor", ("real10y_estimated", "broad_dollar", "breakeven"))
@pytest.mark.parametrize("boundary", _fixture()["boundary_cases"], ids=lambda item: item["bucket"] + "-" + item["raw_ratio"])
def test_materiality_boundaries_and_contributions_are_recomputable(factor: str, boundary: dict) -> None:
    config = _fixture()["factors"][factor]
    case = {"deltas": {factor: str(Decimal(config["materiality_threshold"]) * Decimal(boundary["raw_ratio"]))}}
    current, previous = _pair(case)
    decision = evaluate_gold_analysis_policy(current, previous)
    detail = _details(decision)[factor]
    assert decision.policy_version == "gold_analysis_policy.v2"
    assert detail["materiality_bucket"] == boundary["bucket"]
    assert Decimal(str(detail["materiality_threshold"])) == Decimal(config["materiality_threshold"])
    assert Decimal(str(detail["raw_ratio"])) == Decimal(boundary["raw_ratio"])
    assert Decimal(str(detail["normalized_move"])) == Decimal(boundary["normalized_move"])
    recomputed = _quantize(
        Decimal(detail["direction_sign"])
        * Decimal(str(detail["normalized_move"]))
        * Decimal(str(detail["factor_weight"]))
        * Decimal(str(detail["quality_weight"]))
        * Decimal(str(detail["freshness_weight"]))
    )
    assert Decimal(str(detail["contribution"])) == recomputed


def test_material_support_and_counter_are_preserved_and_net_sets_tilt() -> None:
    case, decision = _decision("material_conflict_net_bullish")
    expected = case["expected"]
    assert decision.direction == expected["direction"] == "mixed"
    assert decision.direction_tilt == expected["direction_tilt"] == "bullish"
    assert Decimal(str(decision.bullish_contribution)) == Decimal(expected["bullish_contribution"])
    assert Decimal(str(decision.bearish_contribution)) == Decimal(expected["bearish_contribution"])
    assert Decimal(str(decision.net_contribution)) == Decimal(expected["net_contribution"])
    assert {item.direction_sign for item in decision.factor_contributions if item.contribution} == {-1, 1}


def test_material_counter_does_not_force_mixed_when_net_clears_threshold() -> None:
    current, previous = _pair(
        {"deltas": {"real10y_estimated": "-0.06", "breakeven": "-0.03"}}
    )
    decision = evaluate_gold_analysis_policy(current, previous)

    assert decision.bullish_contribution == Decimal("0.80000000")
    assert decision.bearish_contribution == Decimal("0.25000000")
    assert decision.net_contribution == Decimal("0.55000000")
    assert decision.direction == "bullish"
    assert decision.direction_tilt == "bullish"


def test_observe_factor_keeps_half_weighted_material_contribution() -> None:
    current, previous = _pair(
        {
            "deltas": {"broad_dollar": "-0.40"},
            "factor_statuses": {"broad_dollar": {"quality_status": "observe"}},
        }
    )
    decision = evaluate_gold_analysis_policy(current, previous)
    dollar = _details(decision)["broad_dollar"]

    assert decision.quality_status == "observe"
    assert Decimal(str(dollar["quality_weight"])) == Decimal("0.5")
    assert Decimal(str(dollar["contribution"])) == Decimal("0.35000000")
    assert decision.direction == "bullish"


def test_confidence_is_recomputable_and_confirmatory_gap_reduces_coverage() -> None:
    case, decision = _decision("confirmatory_gap_observe")
    assert decision.quality_status == case["expected"]["quality_status"] == "observe"
    assert 0 < decision.evidence_coverage_ratio < 1
    assert 0 <= decision.conflict_share_ratio <= 1
    readiness_weight = Decimal(_fixture()["confidence"]["readiness_weights"]["observe"])
    expected = _quantize(
        min(abs(Decimal(str(decision.net_contribution))), Decimal("1.0"))
        * (Decimal("1") - Decimal(str(decision.conflict_share_ratio)))
        * Decimal(str(decision.evidence_coverage_ratio))
        * readiness_weight
    )
    assert Decimal(str(decision.confidence)) == expected


def test_dfii10_is_cross_check_only_and_output_is_stable_100_times() -> None:
    direct_case, direct = _decision("dfii10_direct_only")
    stable_case, stable = _decision("deterministic_material_bearish")
    assert direct.direction == direct_case["expected"]["direction"] == "neutral"
    assert Decimal(str(direct.net_contribution)) == Decimal("0.0")
    assert "real10y_direct" not in _details(direct)
    current, previous = _pair(stable_case)
    expected_bytes = json.dumps(stable.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    expected_hash = hashlib.sha256(expected_bytes.encode()).hexdigest()
    for _ in range(100):
        repeated = evaluate_gold_analysis_policy(current, previous)
        payload = json.dumps(repeated.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        assert payload == expected_bytes
        assert hashlib.sha256(payload.encode()).hexdigest() == expected_hash

    stable_payload = stable.model_dump(
        mode="python", exclude_computed_fields=True
    )
    validated = GoldAnalysisDecisionV2.model_validate(stable_payload)
    assert validated == stable
    with pytest.raises(ValidationError):
        GoldAnalysisDecisionV2.model_validate(
            {
                **stable_payload,
                "net_contribution": stable.net_contribution + Decimal("0.01"),
            }
        )
    with pytest.raises(ValidationError):
        GoldAnalysisDecisionV2.model_validate(
            {
                **stable_payload,
                "evidence_coverage_ratio": stable.evidence_coverage_ratio
                - Decimal("0.01"),
            }
        )
    with pytest.raises(ValidationError):
        GoldAnalysisDecisionV2.model_validate(
            {**stable_payload, "payload_hash": "0" * 64}
        )
    with pytest.raises(ValidationError):
        GoldAnalysisDecisionV2.model_validate(
            {**stable_payload, "decision_id": "caller-supplied"}
        )


def test_v1_dispatch_and_frozen_representative_hash_remain_unchanged() -> None:
    previous = build_feature_snapshot(json.loads(_V1_PREVIOUS.read_text(encoding="utf-8")))
    current = build_feature_snapshot(json.loads(_V1_CURRENT.read_text(encoding="utf-8")))
    decision = evaluate_gold_analysis_policy(current, previous)
    payload = json.dumps(decision.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert decision.policy_version == "gold_analysis_policy.v1"
    assert hashlib.sha256(payload.encode("utf-8")).hexdigest() == "21560ed78f38b2d9cb482c02878de5c3261e30f16e64710fcd2580d340663831"
