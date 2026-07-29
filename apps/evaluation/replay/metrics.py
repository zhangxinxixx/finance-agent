"""Pure metrics for frozen replay results."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Iterable

from .schemas import Metric, ReplayCase


def ordered_cases(cases: Iterable[ReplayCase]) -> tuple[ReplayCase, ...]:
    ordered = tuple(sorted(cases, key=lambda case: (case.sequence, case.case_id)))
    if len({case.case_id for case in ordered}) != len(ordered):
        raise ValueError("replay case_id values must be unique")
    return ordered


def independent_cases(cases: Iterable[ReplayCase]) -> tuple[ReplayCase, ...]:
    """Choose the earliest execution as the deterministic representative per input."""
    representatives: list[ReplayCase] = []
    seen: set[str] = set()
    for case in ordered_cases(cases):
        if case.input_fingerprint not in seen:
            representatives.append(case)
            seen.add(case.input_fingerprint)
    return tuple(representatives)


def stratum_counts(cases: Iterable[ReplayCase]) -> tuple[tuple[str, int], ...]:
    counts: Counter[str] = Counter()
    for case in cases:
        counts[case.stratum] += 1
    return tuple(sorted(counts.items()))


def sample_kind_counts(cases: Iterable[ReplayCase]) -> tuple[tuple[str, int], ...]:
    counts: Counter[str] = Counter()
    for case in cases:
        counts["blocked" if case.result.is_blocked else case.result.evidence_delta_kind] += 1
    return tuple(sorted(counts.items()))


def same_input_reproducibility(cases: Iterable[ReplayCase]) -> Metric:
    groups: dict[str, list[ReplayCase]] = defaultdict(list)
    for case in cases:
        groups[case.input_fingerprint].append(case)
    matches = comparisons = 0
    for group in groups.values():
        first = group[0].result
        for case in group[1:]:
            comparisons += 1
            matches += case.result == first
    return Metric("same_input_reproducibility", matches, comparisons)


def adjacent_change_metric(
    cases: Iterable[ReplayCase], *, name: str, changed: Callable[[ReplayCase, ReplayCase], bool]
) -> Metric:
    ordered = ordered_cases(cases)
    return Metric(name, sum(changed(previous, current) for previous, current in zip(ordered, ordered[1:])), max(0, len(ordered) - 1))


def stage_churn_metric(cases: Iterable[ReplayCase]) -> Metric:
    ordered = ordered_cases(cases)
    windows = tuple(zip(ordered, ordered[1:], ordered[2:]))
    churns = sum(
        first.result.analysis_stage == third.result.analysis_stage
        and first.result.analysis_stage != second.result.analysis_stage
        for first, second, third in windows
    )
    return Metric("stage_churn_rate", churns, len(windows))


def blocked_to_directional_metric(cases: Iterable[ReplayCase]) -> Metric:
    blocked = tuple(case for case in cases if case.result.is_blocked)
    return Metric(
        "blocked_to_directional_violations",
        sum(case.result.is_directional_strategy for case in blocked),
        len(blocked),
    )


def driver_rank_stability(cases: Iterable[ReplayCase]) -> Metric:
    def stable(previous: ReplayCase, current: ReplayCase) -> bool:
        return previous.result.driver_ranking == current.result.driver_ranking

    changed = adjacent_change_metric(cases, name="driver_rank_stability", changed=lambda a, b: not stable(a, b))
    return Metric(changed.name, changed.denominator - changed.numerator, changed.denominator)


def coverage_metric(cases: Iterable[ReplayCase], *, name: str, predicate: Callable[[ReplayCase], bool]) -> Metric:
    values = tuple(cases)
    return Metric(name, sum(predicate(case) for case in values), len(values))
