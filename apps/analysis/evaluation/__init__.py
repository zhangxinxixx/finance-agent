"""Pure, append-only strategy outcome evaluation primitives for Issue #59."""

from .outcomes import OutcomeEvaluation, evaluate_strategy_outcome
from .replay import ReplayCoverageError, build_replay_snapshot, run_shadow_replay
from .strategy_snapshot import EvaluationSetup, StrategySnapshot, build_strategy_snapshot

__all__ = [
    "OutcomeEvaluation",
    "EvaluationSetup",
    "StrategySnapshot",
    "build_strategy_snapshot",
    "evaluate_strategy_outcome",
    "ReplayCoverageError",
    "build_replay_snapshot",
    "run_shadow_replay",
]
