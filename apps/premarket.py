"""Shared premarket step ordering and canonical contract helpers."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Mapping, Protocol, TypeVar

if TYPE_CHECKING:
    from database.models.task import TaskStep

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
PremarketStepDecision = Literal["ready", "degraded_allowed", "blocked"]


@dataclass(frozen=True, slots=True)
class PremarketStepContract:
    """Pure read model for one canonical premarket step."""

    name: str
    order: int
    pipeline_group: PipelineGroup
    stage: StepStage
    type: StepType
    upstream_dependencies: tuple[str, ...] = ()
    required_sources: tuple[str, ...] = ()
    fallback_policy: str = "none"
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
            "required_sources": list(self.required_sources),
            "fallback_policy": self.fallback_policy,
            "blocked_scope": self.blocked_scope,
        }


@dataclass(frozen=True, slots=True)
class PremarketStepReadinessResult:
    """Pure readiness evaluation result for one premarket step."""

    decision: PremarketStepDecision
    required_sources: tuple[str, ...]
    degraded_sources: tuple[str, ...]
    blocked_sources: tuple[str, ...]
    gating_reason: str


_PREMARKET_STEP_CONTRACT_SPECS: dict[str, PremarketStepContract] = {
    "macro_collect": PremarketStepContract(
        name="macro_collect",
        order=0,
        pipeline_group="macro",
        stage="collect",
        type="collector",
        required_sources=("fred", "fed", "treasury", "dxy"),
        fallback_policy="openbb_macro_or_stale_allowed",
        blocked_scope="macro",
    ),
    "macro_feature": PremarketStepContract(
        name="macro_feature",
        order=1,
        pipeline_group="macro",
        stage="feature",
        type="feature",
        upstream_dependencies=("macro_collect",),
        required_sources=("fred", "fed", "treasury", "dxy"),
        fallback_policy="stale_allowed_1d",
        blocked_scope="macro",
    ),
    "cme_download": PremarketStepContract(
        name="cme_download",
        order=2,
        pipeline_group="cme",
        stage="collect",
        type="collector",
        required_sources=("cme_daily_bulletin",),
        fallback_policy="block_if_unavailable",
        blocked_scope="cme",
    ),
    "cme_parse": PremarketStepContract(
        name="cme_parse",
        order=3,
        pipeline_group="cme",
        stage="parse",
        type="parser",
        upstream_dependencies=("cme_download",),
        required_sources=("cme_daily_bulletin",),
        fallback_policy="block_if_unavailable",
        blocked_scope="cme",
    ),
    "cme_ingest": PremarketStepContract(
        name="cme_ingest",
        order=4,
        pipeline_group="cme",
        stage="ingest",
        type="ingestor",
        upstream_dependencies=("cme_parse",),
        required_sources=("cme_daily_bulletin",),
        fallback_policy="block_if_unavailable",
        blocked_scope="cme",
    ),
    "option_wall": PremarketStepContract(
        name="option_wall",
        order=5,
        pipeline_group="cme",
        stage="feature",
        type="feature",
        upstream_dependencies=("cme_ingest",),
        required_sources=("cme_options",),
        fallback_policy="stale_allowed_1d",
        blocked_scope="cme",
    ),
    "report_render": PremarketStepContract(
        name="report_render",
        order=6,
        pipeline_group="macro",
        stage="output",
        type="renderer",
        upstream_dependencies=("macro_feature",),
        required_sources=("fred", "fed", "treasury", "dxy"),
        fallback_policy="degraded_allowed",
        blocked_scope="macro",
    ),
    "news_collect": PremarketStepContract(
        name="news_collect",
        order=7,
        pipeline_group="news",
        stage="collect",
        type="collector",
        required_sources=("jin10_news", "jin10_flash", "jin10_mcp_calendar"),
        fallback_policy="degraded_allowed",
        blocked_scope="news",
    ),
    "news_feature": PremarketStepContract(
        name="news_feature",
        order=8,
        pipeline_group="news",
        stage="feature",
        type="feature",
        upstream_dependencies=("news_collect",),
        required_sources=("jin10_news",),
        fallback_policy="degraded_allowed",
        blocked_scope="news",
    ),
    "news_brief": PremarketStepContract(
        name="news_brief",
        order=9,
        pipeline_group="news",
        stage="output",
        type="renderer",
        upstream_dependencies=("news_feature",),
        required_sources=("jin10_news",),
        fallback_policy="degraded_allowed",
        blocked_scope="news",
    ),
    "strategy_card": PremarketStepContract(
        name="strategy_card",
        order=10,
        pipeline_group="other",
        stage="summary",
        type="summary",
        upstream_dependencies=("report_render", "option_wall", "news_brief"),
        required_sources=(),
        fallback_policy="depends_on_upstream_status",
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


def materialize_premarket_task_steps(
    task_run_id: uuid.UUID | str,
    *,
    status: str = "pending",
) -> list["TaskStep"]:
    """Materialize canonical premarket DAG nodes into pending TaskStep rows.

    This keeps the execution blueprint explicit and queryable even when the
    actual runtime execution path is delegated to worker/Dagster flows.
    """

    from database.models.task import StepStatus, TaskStep

    run_uuid = task_run_id if isinstance(task_run_id, uuid.UUID) else uuid.UUID(str(task_run_id))
    step_status = StepStatus(status)
    return [
        TaskStep(
            task_run_id=run_uuid,
            name=contract.name,
            stage=contract.stage,
            task_kind=contract.type,
            status=step_status,
            step_order=contract.order,
        )
        for contract in PREMARKET_STEP_CONTRACTS
    ]


def evaluate_premarket_step_readiness(
    contract: PremarketStepContract,
    source_status_index: Mapping[str, Mapping[str, object]],
) -> PremarketStepReadinessResult:
    """Evaluate whether a premarket step can run from current source status."""
    required_sources = tuple(contract.required_sources)
    if not required_sources:
        return PremarketStepReadinessResult(
            decision="ready",
            required_sources=required_sources,
            degraded_sources=(),
            blocked_sources=(),
            gating_reason="ready",
        )

    degraded_sources: list[str] = []
    blocked_sources: list[str] = []
    gating_reason = "ready"

    for source_key in required_sources:
        source_status = source_status_index.get(source_key)
        if source_status is None:
            blocked_sources.append(source_key)
            if gating_reason == "ready":
                gating_reason = "missing_source_status"
            continue

        readiness_state = _normalize_readiness_state(source_status.get("readiness_state"))
        if readiness_state == "blocked":
            blocked_sources.append(source_key)
            if gating_reason in {"ready", "missing_source_status"}:
                gating_reason = "required_source_blocked"
            continue
        if readiness_state == "not_configured":
            blocked_sources.append(source_key)
            if gating_reason in {"ready", "missing_source_status"}:
                gating_reason = "required_source_not_configured"
            continue
        if readiness_state == "degraded":
            degraded_sources.append(source_key)

    if blocked_sources:
        return PremarketStepReadinessResult(
            decision="blocked",
            required_sources=required_sources,
            degraded_sources=tuple(degraded_sources),
            blocked_sources=tuple(blocked_sources),
            gating_reason=gating_reason,
        )

    if degraded_sources:
        if contract.fallback_policy in {
            "degraded_allowed",
            "stale_allowed_1d",
            "openbb_macro_or_stale_allowed",
        }:
            return PremarketStepReadinessResult(
                decision="degraded_allowed",
                required_sources=required_sources,
                degraded_sources=tuple(degraded_sources),
                blocked_sources=(),
                gating_reason="required_source_degraded_allowed",
            )
        return PremarketStepReadinessResult(
            decision="blocked",
            required_sources=required_sources,
            degraded_sources=tuple(degraded_sources),
            blocked_sources=tuple(degraded_sources),
            gating_reason="required_source_degraded_blocked",
        )

    return PremarketStepReadinessResult(
        decision="ready",
        required_sources=required_sources,
        degraded_sources=(),
        blocked_sources=(),
        gating_reason="ready",
    )


def _premarket_step_sort_key(step: _StepLike) -> tuple[int, str, str]:
    """Stable sort key that keeps unknown steps at the end."""
    return (
        _PREMARKET_STEP_INDEX.get(step.name, len(PREMARKET_STEP_ORDER)),
        step.name,
        str(step.id),
    )


def _normalize_readiness_state(value: object) -> str:
    return str(value or "").strip().lower()
