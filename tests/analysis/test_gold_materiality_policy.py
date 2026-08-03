from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from apps.analysis.gold_policy.materiality_policy import (
    GoldMaterialityDecision,
    evaluate_gold_materiality,
)


def _decision(**changes):
    payload = {
        "factor": "real_yield",
        "move_magnitude": Decimal("0.03"),
        "direction_sign": 1,
        "quality_status": "accepted",
        "alignment_status": "aligned",
        "freshness_status": "fresh",
    }
    payload.update(changes)
    return evaluate_gold_materiality(**payload)


@pytest.mark.parametrize(
    ("raw_ratio", "bucket", "normalized"),
    (
        (Decimal("0"), "noise", Decimal("0")),
        (Decimal("0.499999999"), "noise", Decimal("0")),
        (Decimal("0.5"), "small", Decimal("0")),
        (Decimal("0.999999999"), "small", Decimal("0")),
        (Decimal("1"), "material", Decimal("1")),
        (Decimal("1.999999999"), "material", Decimal("1.999999999")),
        (Decimal("2"), "large", Decimal("2")),
        (Decimal("5"), "large", Decimal("2")),
    ),
)
def test_bucket_boundaries_and_normalization_cap(
    raw_ratio: Decimal,
    bucket: str,
    normalized: Decimal,
) -> None:
    decision = _decision(move_magnitude=Decimal("0.03") * raw_ratio)

    assert decision.raw_ratio == raw_ratio
    assert decision.bucket == bucket
    assert decision.normalized_move == normalized


@pytest.mark.parametrize(
    ("factor", "threshold", "weight"),
    (
        ("real_yield", Decimal("0.03"), Decimal("0.40")),
        ("broad_dollar", Decimal("0.20"), Decimal("0.35")),
        ("breakeven", Decimal("0.03"), Decimal("0.25")),
        ("oil", Decimal("0.50"), Decimal("0.15")),
        ("event_reaction", Decimal("0.20"), Decimal("0.40")),
        ("xauusd_return", Decimal("0.10"), Decimal("0")),
    ),
)
def test_factor_thresholds_and_weights_are_serialized(
    factor: str,
    threshold: Decimal,
    weight: Decimal,
) -> None:
    decision = _decision(factor=factor, move_magnitude=threshold)
    payload = decision.model_dump(mode="json")

    assert decision.threshold == threshold
    assert decision.factor_weight == weight
    assert decision.normalization_cap == Decimal("2")
    assert payload["policy_version"] == "gold_materiality_policy.v1"
    assert payload["threshold"] == str(threshold)
    assert payload["factor_weight"] == str(weight)
    assert payload["normalization_cap"] == "2"


@pytest.mark.parametrize(
    ("quality", "alignment", "expected"),
    (
        ("accepted", "aligned", Decimal("1")),
        ("observe", "aligned", Decimal("0.5")),
        ("accepted", "unknown", Decimal("0.5")),
        ("observe", "unknown", Decimal("0.5")),
        ("blocked", "aligned", Decimal("0")),
        ("accepted", "misaligned", Decimal("0")),
        ("blocked", "misaligned", Decimal("0")),
    ),
)
def test_quality_and_alignment_collapse_to_one_guardrail_weight(
    quality: str,
    alignment: str,
    expected: Decimal,
) -> None:
    decision = _decision(quality_status=quality, alignment_status=alignment)

    assert decision.quality_weight == expected
    assert decision.contribution == (Decimal("0.40000000") * expected)


@pytest.mark.parametrize(
    ("freshness", "expected_weight", "expected_contribution"),
    (
        ("fresh", Decimal("1"), Decimal("0.40000000")),
        ("stale", Decimal("0.5"), Decimal("0.20000000")),
        ("missing", Decimal("0"), Decimal("0E-8")),
    ),
)
def test_freshness_weight_scales_contribution(
    freshness: str,
    expected_weight: Decimal,
    expected_contribution: Decimal,
) -> None:
    decision = _decision(freshness_status=freshness)

    assert decision.freshness_weight == expected_weight
    assert decision.contribution == expected_contribution


def test_contribution_uses_sign_all_weights_and_eight_decimal_quantization() -> None:
    decision = _decision(
        move_magnitude=Decimal("0.03703703673"),
        direction_sign=-1,
        quality_status="observe",
        freshness_status="stale",
    )

    assert decision.raw_ratio == Decimal("1.234567891")
    assert decision.normalized_move == Decimal("1.234567891")
    assert decision.contribution == Decimal("-0.12345679")
    assert decision.contribution.as_tuple().exponent == -8


def test_noise_small_and_xauusd_return_cannot_contribute() -> None:
    noise = _decision(move_magnitude=Decimal("0.014"))
    small = _decision(move_magnitude=Decimal("0.02"))
    xauusd = _decision(
        factor="xauusd_return",
        move_magnitude=Decimal("0.25"),
    )

    assert (noise.bucket, noise.contribution) == ("noise", Decimal("0E-8"))
    assert (small.bucket, small.contribution) == ("small", Decimal("0E-8"))
    assert (xauusd.bucket, xauusd.normalized_move) == ("large", Decimal("2"))
    assert xauusd.factor_weight == Decimal("0")
    assert xauusd.contribution == Decimal("0E-8")


def test_model_rejects_injected_contribution_and_policy_constants() -> None:
    decision = _decision()
    payload = decision.model_dump(mode="python")

    with pytest.raises(ValidationError, match="contribution does not match"):
        GoldMaterialityDecision.model_validate(
            {**payload, "contribution": Decimal("0.99")}
        )
    with pytest.raises(ValidationError, match="threshold does not match"):
        GoldMaterialityDecision.model_validate(
            {**payload, "threshold": Decimal("0.04")}
        )


def test_contract_is_frozen_extra_forbid_and_decimal_only() -> None:
    decision = _decision()

    with pytest.raises(ValidationError, match="frozen"):
        decision.contribution = Decimal("0")
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        GoldMaterialityDecision.model_validate(
            {**decision.model_dump(mode="python"), "invented": True}
        )
    with pytest.raises(TypeError, match="must be a Decimal"):
        _decision(move_magnitude=0.03)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("factor", "invented", "unsupported materiality factor"),
        ("direction_sign", 0, "direction_sign must be -1 or 1"),
        ("quality_status", "invented", "unsupported quality_status"),
        ("alignment_status", "invented", "unsupported alignment_status"),
        ("freshness_status", "invented", "unsupported freshness_status"),
    ),
)
def test_untrusted_enum_inputs_fail_with_structured_errors(
    field: str,
    value,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        _decision(**{field: value})


def test_same_decimal_input_is_byte_stable_across_100_runs() -> None:
    decisions = [
        _decision(
            factor="broad_dollar",
            move_magnitude=Decimal("0.333333333333333333"),
            direction_sign=-1,
            quality_status="observe",
            alignment_status="unknown",
            freshness_status="stale",
        )
        for _ in range(100)
    ]
    expected = decisions[0].model_dump_json()

    assert all(decision == decisions[0] for decision in decisions)
    assert {decision.model_dump_json() for decision in decisions} == {expected}
