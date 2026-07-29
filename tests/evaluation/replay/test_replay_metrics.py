from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from apps.evaluation.replay.analysis_replay import evaluate_analysis_replay
from apps.evaluation.replay.report import build_replay_reports
from apps.evaluation.replay.schemas import ReplayCase, ReplayIdentity, ReplayResult
from apps.evaluation.replay.version_compare import compare_versions


FIXTURE = Path(__file__).parents[2] / "fixtures" / "evaluation" / "replay" / "five_day_boundary_cases.json"


def load_cases() -> tuple[ReplayCase, ...]:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    identity = ReplayIdentity(**payload["identity"])
    return tuple(
        ReplayCase(
            case_id=item["case_id"],
            sequence=item["sequence"],
            stratum=item["stratum"],
            input_fingerprint=item["input_fingerprint"],
            identity=identity,
            result=ReplayResult(
                **{key: tuple(value) if key in {"driver_ranking", "source_ids"} else value for key, value in item["result"].items()}
            ),
        )
        for item in payload["cases"]
    )


def metric_values(report) -> dict[str, float | None]:
    return {metric.name: metric.value for metric in report.metrics}


def test_five_day_boundaries_are_separate_and_replay_is_byte_stable() -> None:
    cases = load_cases()
    first_analysis, first_strategy = build_replay_reports(cases)
    second_analysis, second_strategy = build_replay_reports(cases)

    assert first_analysis.canonical_json() == second_analysis.canonical_json()
    assert first_strategy.canonical_json() == second_strategy.canonical_json()
    assert (first_analysis.execution_count, first_analysis.sample_count) == (6, 5)
    assert dict(first_analysis.sample_kind_counts)["no_op"] == 1
    assert dict(first_analysis.sample_kind_counts)["ordinary"] == 1
    assert dict(first_analysis.sample_kind_counts)["hard_invalidation"] == 1
    assert dict(first_analysis.sample_kind_counts)["blocked"] == 2
    assert metric_values(first_analysis)["same_input_reproducibility"] == 1.0
    blocked_metric = next(metric for metric in first_strategy.metrics if metric.name == "blocked_to_directional_violations")
    assert (blocked_metric.numerator, blocked_metric.denominator) == (1, 2)


def test_version_compare_exposes_changed_metrics_and_keeps_small_sample_verdict() -> None:
    baseline = load_cases()
    candidate_identity = replace(baseline[0].identity, model_version="model.freeze.2")
    candidate = tuple(replace(case, identity=candidate_identity) for case in baseline)
    changed_result = replace(candidate[3].result, strategy_direction="none", strategy_status="OBSERVE")
    candidate = candidate[:3] + (replace(candidate[3], result=changed_result),) + candidate[4:]

    comparison = compare_versions(baseline, candidate)

    assert comparison.promotion_verdict == "insufficient_sample"
    assert {change.name for change in comparison.strategy_changes} >= {"strategy_churn_rate"}


def test_support_flags_drive_flip_and_strategy_metrics_and_stage_churn_is_aba_only() -> None:
    source = load_cases()[1]
    first = replace(
        source,
        case_id="first",
        sequence=0,
        input_fingerprint="first",
        result=replace(
            source.result,
            analysis_stage="A",
            state_direction="bullish",
            strategy_status="OBSERVE",
            strategy_direction="none",
        ),
    )
    second = replace(
        first,
        case_id="second",
        sequence=1,
        input_fingerprint="second",
        result=replace(
            first.result,
            analysis_stage="B",
            state_direction="bearish",
            transition_supported=False,
            strategy_status="SHORT_WATCH",
            strategy_direction="short",
            strategy_change_supported=False,
        ),
    )
    third = replace(
        second,
        case_id="third",
        sequence=2,
        input_fingerprint="third",
        result=replace(
            second.result,
            analysis_stage="A",
            state_direction="bullish",
            transition_supported=True,
            strategy_status="OBSERVE",
            strategy_direction="none",
            strategy_change_supported=True,
        ),
    )

    analysis, strategy = build_replay_reports((first, second, third))

    assert metric_values(analysis)["state_flip_rate"] == 1.0
    assert metric_values(analysis)["unsupported_state_flip_rate"] == 0.5
    assert metric_values(analysis)["stage_churn_rate"] == 1.0
    assert metric_values(strategy)["strategy_churn_rate"] == 1.0
    assert metric_values(strategy)["unsupported_strategy_change_rate"] == 0.5


def test_twenty_compatible_samples_with_no_changes_have_no_metric_change_verdict() -> None:
    source = load_cases()[1]
    baseline = tuple(
        replace(source, case_id=f"sample-{index}", sequence=index, input_fingerprint=f"input-{index}")
        for index in range(20)
    )
    candidate_identity = replace(source.identity, model_version="model.freeze.2")
    candidate = tuple(replace(case, identity=candidate_identity) for case in baseline)

    comparison = compare_versions(baseline, candidate)

    assert comparison.promotion_verdict == "no_metric_change"
    assert comparison.analysis_changes == ()
    assert comparison.strategy_changes == ()


def test_twenty_reruns_of_one_input_remain_insufficient_sample() -> None:
    source = load_cases()[1]
    baseline = tuple(
        replace(source, case_id=f"rerun-{index}", sequence=index, input_fingerprint="same-input") for index in range(20)
    )
    candidate_identity = replace(source.identity, model_version="model.freeze.2")
    candidate = tuple(replace(case, identity=candidate_identity) for case in baseline)

    analysis = evaluate_analysis_replay(baseline)
    comparison = compare_versions(baseline, candidate)

    assert (analysis.execution_count, analysis.sample_count) == (20, 1)
    assert comparison.promotion_verdict == "insufficient_sample"


@pytest.mark.parametrize("status", ["unconfirmed", "unavailable"])
def test_unsupported_attribution_status_cannot_claim_support(status: str) -> None:
    result = load_cases()[1].result

    with pytest.raises(ValueError, match="cannot be supported"):
        replace(result, attribution_status=status, attribution_supported=True)


def test_incompatible_case_sets_fail_closed() -> None:
    baseline = load_cases()
    incompatible = tuple(replace(case, input_fingerprint="different") if case.case_id == "D2-ordinary" else case for case in baseline)

    with pytest.raises(ValueError, match="incompatible replay datasets"):
        compare_versions(baseline, incompatible)


def test_identity_mismatch_within_one_evaluation_fails_closed() -> None:
    cases = load_cases()
    mismatch = replace(cases[1], identity=replace(cases[1].identity, provider_id="other"))

    with pytest.raises(ValueError, match="share an identity"):
        evaluate_analysis_replay((cases[0], mismatch))
