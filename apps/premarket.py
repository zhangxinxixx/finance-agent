"""Shared premarket step ordering and canonical contract helpers."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol, TypeVar

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

PipelineGroup = Literal["macro", "cme", "news", "other"]
StepStage = Literal["collect", "parse", "ingest", "feature", "output", "summary"]
StepType = Literal["collector", "parser", "ingestor", "feature", "renderer", "summary"]
BlockedScope = Literal["macro", "cme", "news", "none"]


@dataclass(frozen=True, slots=True)
class PremarketStepContract:
    """Pure read model for one canonical premarket step."""

    name: str
    order: int
    pipeline_group: PipelineGroup
    stage: StepStage
    type: StepType
    upstream_dependencies: tuple[str, ...] = ()
    blocked_scope: BlockedScope = "none"

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-friendly representation."""
        return {
            "name": self.name,
            "order": self.order,
            "pipeline_group": self.pipeline_group,
            "stage": self.stage,
            "type": self.type,
            "upstream_dependencies": list(self.upstream_dependencies),
            "blocked_scope": self.blocked_scope,
        }


_PREMARKET_STEP_CONTRACT_SPECS: dict[str, PremarketStepContract] = {
    "macro_collect": PremarketStepContract(
        name="macro_collect",
        order=0,
        pipeline_group="macro",
        stage="collect",
        type="collector",
        blocked_scope="macro",
    ),
    "macro_feature": PremarketStepContract(
        name="macro_feature",
        order=1,
        pipeline_group="macro",
        stage="feature",
        type="feature",
        upstream_dependencies=("macro_collect",),
        blocked_scope="macro",
    ),
    "cme_download": PremarketStepContract(
        name="cme_download",
        order=2,
        pipeline_group="cme",
        stage="collect",
        type="collector",
        blocked_scope="cme",
    ),
    "cme_parse": PremarketStepContract(
        name="cme_parse",
        order=3,
        pipeline_group="cme",
        stage="parse",
        type="parser",
        upstream_dependencies=("cme_download",),
        blocked_scope="cme",
    ),
    "cme_ingest": PremarketStepContract(
        name="cme_ingest",
        order=4,
        pipeline_group="cme",
        stage="ingest",
        type="ingestor",
        upstream_dependencies=("cme_parse",),
        blocked_scope="cme",
    ),
    "option_wall": PremarketStepContract(
        name="option_wall",
        order=5,
        pipeline_group="cme",
        stage="feature",
        type="feature",
        upstream_dependencies=("cme_ingest",),
        blocked_scope="cme",
    ),
    "report_render": PremarketStepContract(
        name="report_render",
        order=6,
        pipeline_group="macro",
        stage="output",
        type="renderer",
        upstream_dependencies=("macro_feature",),
        blocked_scope="macro",
    ),
    "news_collect": PremarketStepContract(
        name="news_collect",
        order=7,
        pipeline_group="news",
        stage="collect",
        type="collector",
        blocked_scope="news",
    ),
    "news_feature": PremarketStepContract(
        name="news_feature",
        order=8,
        pipeline_group="news",
        stage="feature",
        type="feature",
        upstream_dependencies=("news_collect",),
        blocked_scope="news",
    ),
    "news_brief": PremarketStepContract(
        name="news_brief",
        order=9,
        pipeline_group="news",
        stage="output",
        type="renderer",
        upstream_dependencies=("news_feature",),
        blocked_scope="news",
    ),
    "strategy_card": PremarketStepContract(
        name="strategy_card",
        order=10,
        pipeline_group="other",
        stage="summary",
        type="summary",
        upstream_dependencies=("report_render", "option_wall", "news_brief"),
        blocked_scope="none",
    ),
}

PREMARKET_STEP_CONTRACTS: tuple[PremarketStepContract, ...] = tuple(
    _PREMARKET_STEP_CONTRACT_SPECS[name] for name in PREMARKET_STEP_ORDER
)
_PREMARKET_STEP_CONTRACT_BY_NAME = {
    contract.name: contract for contract in PREMARKET_STEP_CONTRACTS
}


class _StepLike(Protocol):
    name: str
    id: object


TStep = TypeVar("TStep", bound=_StepLike)


def sort_premarket_steps(steps: Sequence[TStep]) -> list[TStep]:
    """Return task steps in canonical premarket execution order."""
    return sorted(steps, key=_premarket_step_sort_key)


def get_premarket_step_contract(step_name: str) -> PremarketStepContract | None:
    """Return the canonical read-only contract for one premarket step."""
    return _PREMARKET_STEP_CONTRACT_BY_NAME.get(step_name)


def get_premarket_step_contracts() -> tuple[PremarketStepContract, ...]:
    """Return the canonical premarket step contracts in execution order."""
    return PREMARKET_STEP_CONTRACTS


def get_premarket_pipeline_contract() -> dict[str, object]:
    """Return the canonical premarket DAG contract as a JSON-friendly payload."""
    steps = [contract.to_dict() for contract in PREMARKET_STEP_CONTRACTS]
    pipeline_groups: dict[str, list[str]] = {"macro": [], "cme": [], "news": [], "other": []}
    for contract in PREMARKET_STEP_CONTRACTS:
        pipeline_groups[contract.pipeline_group].append(contract.name)

    return {
        "step_order": list(PREMARKET_STEP_ORDER),
        "steps": steps,
        "pipeline_groups": pipeline_groups,
    }


def _premarket_step_sort_key(step: _StepLike) -> tuple[int, str, str]:
    """Stable sort key that keeps unknown steps at the end."""
    return (
        _PREMARKET_STEP_INDEX.get(step.name, len(PREMARKET_STEP_ORDER)),
        step.name,
        str(step.id),
    )
