"""Analysis-only replay projection; it never invokes a provider or policy."""

from __future__ import annotations

from collections.abc import Iterable

from .metrics import (
    adjacent_change_metric,
    coverage_metric,
    driver_rank_stability,
    independent_cases,
    ordered_cases,
    same_input_reproducibility,
    sample_kind_counts,
    stage_churn_metric,
    stratum_counts,
)
from .schemas import ReplayCase, ReplayReport


def evaluate_analysis_replay(cases: Iterable[ReplayCase]) -> ReplayReport:
    ordered = ordered_cases(cases)
    if not ordered:
        raise ValueError("analysis replay requires at least one case")
    identity = ordered[0].identity
    if any(case.identity != identity for case in ordered):
        raise ValueError("analysis replay cases must share an identity")
    samples = independent_cases(ordered)
    metrics = (
        same_input_reproducibility(ordered),
        adjacent_change_metric(
            samples,
            name="state_flip_rate",
            changed=lambda a, b: {a.result.state_direction, b.result.state_direction} == {"bullish", "bearish"},
        ),
        adjacent_change_metric(
            samples,
            name="unsupported_state_flip_rate",
            changed=lambda a, b: {a.result.state_direction, b.result.state_direction} == {"bullish", "bearish"}
            and not b.result.transition_supported,
        ),
        stage_churn_metric(samples),
        driver_rank_stability(samples),
        coverage_metric(samples, name="attribution_coverage", predicate=lambda case: case.result.attribution_supported),
        coverage_metric(samples, name="attribution_unconfirmed_rate", predicate=lambda case: case.result.attribution_status == "unconfirmed"),
    )
    return ReplayReport("analysis", identity, len(ordered), len(samples), stratum_counts(samples), sample_kind_counts(samples), metrics)
