"""Shared premarket step ordering helpers."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, TypeVar

PREMARKET_STEP_ORDER: tuple[str, ...] = (
    "macro_collect",
    "macro_feature",
    "cme_download",
    "cme_parse",
    "cme_ingest",
    "option_wall",
    "report_render",
    "news_collect",
    "news_feature",
    "news_brief",
    "strategy_card",
)

_PREMARKET_STEP_INDEX = {name: idx for idx, name in enumerate(PREMARKET_STEP_ORDER)}


class _StepLike(Protocol):
    name: str
    id: object


TStep = TypeVar("TStep", bound=_StepLike)


def sort_premarket_steps(steps: Sequence[TStep]) -> list[TStep]:
    """Return task steps in canonical premarket execution order."""
    return sorted(steps, key=_premarket_step_sort_key)


def _premarket_step_sort_key(step: _StepLike) -> tuple[int, str, str]:
    """Stable sort key that keeps unknown steps at the end."""
    return (
        _PREMARKET_STEP_INDEX.get(step.name, len(PREMARKET_STEP_ORDER)),
        step.name,
        str(step.id),
    )
