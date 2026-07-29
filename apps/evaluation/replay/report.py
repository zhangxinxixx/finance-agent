"""Convenience construction for the two deliberately separate replay reports."""

from __future__ import annotations

from collections.abc import Iterable

from .analysis_replay import evaluate_analysis_replay
from .schemas import ReplayCase, ReplayReport
from .strategy_replay import evaluate_strategy_replay


def build_replay_reports(cases: Iterable[ReplayCase]) -> tuple[ReplayReport, ReplayReport]:
    frozen_cases = tuple(cases)
    return evaluate_analysis_replay(frozen_cases), evaluate_strategy_replay(frozen_cases)
