"""Pure, append-only strategy outcome evaluation primitives for Issue #59."""

from .outcomes import OutcomeEvaluation, evaluate_strategy_outcome
from .strategy_snapshot import StrategySnapshot, build_strategy_snapshot

__all__ = [
    "OutcomeEvaluation",
    "StrategySnapshot",
    "build_strategy_snapshot",
    "evaluate_strategy_outcome",
]
