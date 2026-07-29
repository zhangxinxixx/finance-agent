"""Fail-closed comparison of two replay datasets and their metric reports."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Iterable

from .analysis_replay import evaluate_analysis_replay
from .strategy_replay import evaluate_strategy_replay
from .schemas import ReplayCase, ReplayReport


@dataclass(frozen=True)
class MetricChange:
    name: str
    baseline_value: float | None
    candidate_value: float | None


@dataclass(frozen=True)
class VersionComparison:
    baseline_identity: object
    candidate_identity: object
    analysis_changes: tuple[MetricChange, ...]
    strategy_changes: tuple[MetricChange, ...]
    promotion_verdict: str


def _verify_compatible(baseline: tuple[ReplayCase, ...], candidate: tuple[ReplayCase, ...]) -> None:
    baseline_inputs = {case.case_id: case.input_fingerprint for case in baseline}
    candidate_inputs = {case.case_id: case.input_fingerprint for case in candidate}
    if baseline_inputs != candidate_inputs:
        raise ValueError("incompatible replay datasets: case IDs or input fingerprints differ")


def _changes(baseline: ReplayReport, candidate: ReplayReport) -> tuple[MetricChange, ...]:
    left = {metric.name: metric.value for metric in baseline.metrics}
    right = {metric.name: metric.value for metric in candidate.metrics}
    if left.keys() != right.keys():
        raise ValueError("incompatible replay reports: metric definitions differ")
    return tuple(MetricChange(name, left[name], right[name]) for name in sorted(left) if left[name] != right[name])


def compare_versions(baseline: Iterable[ReplayCase], candidate: Iterable[ReplayCase]) -> VersionComparison:
    base_cases, candidate_cases = tuple(baseline), tuple(candidate)
    _verify_compatible(base_cases, candidate_cases)
    base_analysis, candidate_analysis = evaluate_analysis_replay(base_cases), evaluate_analysis_replay(candidate_cases)
    base_strategy, candidate_strategy = evaluate_strategy_replay(base_cases), evaluate_strategy_replay(candidate_cases)
    analysis_changes = _changes(base_analysis, candidate_analysis)
    strategy_changes = _changes(base_strategy, candidate_strategy)
    if base_analysis.sample_count < 20:
        verdict = "insufficient_sample"
    elif analysis_changes or strategy_changes:
        verdict = "metrics_changed"
    else:
        verdict = "no_metric_change"
    return VersionComparison(
        base_analysis.identity,
        candidate_analysis.identity,
        analysis_changes,
        strategy_changes,
        verdict,
    )
