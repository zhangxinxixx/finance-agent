"""Strategy-only replay projection; no account or market-path metrics live here."""

from __future__ import annotations

from collections.abc import Iterable

from .metrics import (
    adjacent_change_metric,
    blocked_to_directional_metric,
    independent_cases,
    ordered_cases,
    sample_kind_counts,
    stratum_counts,
)
from .schemas import ReplayCase, ReplayReport


def evaluate_strategy_replay(cases: Iterable[ReplayCase]) -> ReplayReport:
    ordered = ordered_cases(cases)
    if not ordered:
        raise ValueError("strategy replay requires at least one case")
    identity = ordered[0].identity
    if any(case.identity != identity for case in ordered):
        raise ValueError("strategy replay cases must share an identity")
    samples = independent_cases(ordered)
    def changed(a: ReplayCase, b: ReplayCase) -> bool:
        return (a.result.strategy_status, a.result.strategy_direction) != (
            b.result.strategy_status,
            b.result.strategy_direction,
        )
    metrics = (
        adjacent_change_metric(samples, name="strategy_churn_rate", changed=changed),
        adjacent_change_metric(
            samples,
            name="unsupported_strategy_change_rate",
            changed=lambda a, b: changed(a, b) and not b.result.strategy_change_supported,
        ),
        blocked_to_directional_metric(samples),
    )
    return ReplayReport("strategy", identity, len(ordered), len(samples), stratum_counts(samples), sample_kind_counts(samples), metrics)
