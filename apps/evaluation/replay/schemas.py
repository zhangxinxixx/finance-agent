"""Immutable inputs and outputs for deterministic analysis/strategy replay."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass


def _required(value: str, field: str) -> str:
    if not value.strip():
        raise ValueError(f"{field} must not be empty")
    return value


def canonical_json(value: object) -> str:
    """Return the stable JSON representation used for replay comparisons."""
    return json.dumps(asdict(value), ensure_ascii=True, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class ReplayIdentity:
    policy_version: str
    model_version: str
    provider_id: str
    run_mode: str

    def __post_init__(self) -> None:
        for field in ("policy_version", "model_version", "provider_id", "run_mode"):
            _required(getattr(self, field), field)


@dataclass(frozen=True)
class ReplayResult:
    """Frozen structured result, deliberately excluding prose and market outcomes."""

    analysis_conclusion: str
    state_direction: str
    analysis_stage: str
    driver_ranking: tuple[str, ...]
    attribution_status: str
    attribution_supported: bool
    transition_supported: bool
    strategy_status: str
    strategy_direction: str
    strategy_change_supported: bool
    evidence_delta_kind: str
    source_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        for field in (
            "analysis_conclusion",
            "state_direction",
            "analysis_stage",
            "attribution_status",
            "strategy_status",
            "strategy_direction",
            "evidence_delta_kind",
        ):
            _required(getattr(self, field), field)
        if not self.source_ids or any(not item.strip() for item in self.source_ids):
            raise ValueError("source_ids must contain non-empty source identities")
        if len(set(self.source_ids)) != len(self.source_ids):
            raise ValueError("source_ids must be unique")
        if len(set(self.driver_ranking)) != len(self.driver_ranking):
            raise ValueError("driver_ranking must be unique")
        if self.state_direction not in {"bullish", "bearish", "mixed", "neutral", "blocked"}:
            raise ValueError("state_direction must be bullish/bearish/mixed/neutral/blocked")
        if self.attribution_status in {"unconfirmed", "unavailable"} and self.attribution_supported:
            raise ValueError("unconfirmed or unavailable attribution cannot be supported")

    @property
    def is_blocked(self) -> bool:
        return self.analysis_conclusion == "blocked"

    @property
    def is_directional_strategy(self) -> bool:
        return self.strategy_direction in {"long", "short"}


@dataclass(frozen=True)
class ReplayCase:
    case_id: str
    sequence: int
    stratum: str
    input_fingerprint: str
    identity: ReplayIdentity
    result: ReplayResult

    def __post_init__(self) -> None:
        _required(self.case_id, "case_id")
        _required(self.stratum, "stratum")
        _required(self.input_fingerprint, "input_fingerprint")
        if self.sequence < 0:
            raise ValueError("sequence must be non-negative")


@dataclass(frozen=True)
class Metric:
    name: str
    numerator: int
    denominator: int

    def __post_init__(self) -> None:
        _required(self.name, "name")
        if self.numerator < 0 or self.denominator < 0 or self.numerator > self.denominator:
            raise ValueError("metric counts must satisfy 0 <= numerator <= denominator")

    @property
    def value(self) -> float | None:
        return None if self.denominator == 0 else self.numerator / self.denominator


@dataclass(frozen=True)
class ReplayReport:
    report_kind: str
    identity: ReplayIdentity
    execution_count: int
    sample_count: int
    stratum_counts: tuple[tuple[str, int], ...]
    sample_kind_counts: tuple[tuple[str, int], ...]
    metrics: tuple[Metric, ...]

    def __post_init__(self) -> None:
        _required(self.report_kind, "report_kind")
        if self.execution_count < self.sample_count:
            raise ValueError("execution_count must be at least sample_count")
        if self.sample_count < 0 or sum(count for _, count in self.stratum_counts) != self.sample_count:
            raise ValueError("stratum_counts must total sample_count")
        if sum(count for _, count in self.sample_kind_counts) != self.sample_count:
            raise ValueError("sample_kind_counts must total sample_count")
        if len({name for name, _ in self.stratum_counts}) != len(self.stratum_counts):
            raise ValueError("stratum names must be unique")
        if len({name for name, _ in self.sample_kind_counts}) != len(self.sample_kind_counts):
            raise ValueError("sample kind names must be unique")
        if len({metric.name for metric in self.metrics}) != len(self.metrics):
            raise ValueError("metric names must be unique")

    def canonical_json(self) -> str:
        return canonical_json(self)
