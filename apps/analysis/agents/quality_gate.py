from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from apps.analysis.agents.schemas import AgentOutput
from apps.api.services.quality_gate_service import QualityGateAction, QualityGateDecision, evaluate_quality_gate


class AgentLoopFallbackTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_type: str
    reason: str
    source: str = "agent_quality_gate"


class AgentLoopDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: str
    review_status: str
    publish_allowed: bool
    reasons: list[str] = Field(default_factory=list)
    fallback_tasks: list[AgentLoopFallbackTask] = Field(default_factory=list)
    accepted_outputs: dict[str, Any] = Field(default_factory=dict)
    fallback_of: list[str] = Field(default_factory=list)
    fallback_trace: dict[str, Any] = Field(default_factory=dict)
    no_strong_conclusion: bool = False
    strategy_card_override: dict[str, Any] = Field(default_factory=dict)
    primary_quality_gate_decision: dict[str, Any] = Field(default_factory=dict)
    fallback_quality_gate_decision: dict[str, Any] | None = None


def evaluate_agent_quality_gate(
    *,
    agent_outputs: list[AgentOutput | dict[str, Any]] | None = None,
    gold_macro_overview: dict[str, Any] | None = None,
    source_health: dict[str, Any] | None = None,
    primary_quality_gate_decision: QualityGateDecision | dict[str, Any] | None = None,
    fallback_outputs: dict[str, Any] | None = None,
    fallback_quality_gate_decision: QualityGateDecision | dict[str, Any] | None = None,
    review_items: list[dict[str, Any]] | None = None,
) -> AgentLoopDecision:
    primary = _quality_gate_decision(
        primary_quality_gate_decision,
        agent_outputs=agent_outputs,
        gold_macro_overview=gold_macro_overview,
        source_health=source_health,
    )
    fallback = _quality_gate_decision_or_none(fallback_quality_gate_decision)
    reasons = _decision_reasons(primary)
    fallback_tasks = _fallback_tasks(primary)
    fallback_of = _fallback_of(agent_outputs)

    if fallback_outputs:
        if fallback is not None and fallback.action is QualityGateAction.PASS:
            return AgentLoopDecision(
                decision="passed",
                review_status="pass",
                publish_allowed=True,
                reasons=[*reasons, "fallback_output_accepted"],
                fallback_tasks=fallback_tasks,
                accepted_outputs=dict(fallback_outputs),
                fallback_of=fallback_of,
                fallback_trace={
                    "fallback_used": True,
                    "accepted_output": "fallback",
                    "reason": reasons,
                    "review_items": list(review_items or []),
                },
                primary_quality_gate_decision=primary.model_dump(mode="json"),
                fallback_quality_gate_decision=fallback.model_dump(mode="json"),
            )
        return AgentLoopDecision(
            decision="blocked" if fallback is not None and fallback.action is QualityGateAction.BLOCK_PUBLISH else "needs_review",
            review_status="blocked" if fallback is not None and fallback.action is QualityGateAction.BLOCK_PUBLISH else "needs_review",
            publish_allowed=False,
            reasons=[*reasons, "fallback_output_rejected"],
            fallback_tasks=fallback_tasks or [AgentLoopFallbackTask(task_type="fallback_conservative_synthesis", reason="fallback_failed")],
            accepted_outputs={},
            fallback_of=fallback_of,
            fallback_trace={
                "fallback_used": True,
                "accepted_output": None,
                "reason": reasons,
                "review_items": list(review_items or []),
            },
            no_strong_conclusion=True,
            strategy_card_override={
                "bias": "neutral",
                "action": "observe_wait",
                "reason": "fallback_failed_or_needs_review",
            },
            primary_quality_gate_decision=primary.model_dump(mode="json"),
            fallback_quality_gate_decision=fallback.model_dump(mode="json") if fallback is not None else None,
        )

    decision = _agent_loop_decision(primary)
    return AgentLoopDecision(
        decision=decision,
        review_status=primary.review_status,
        publish_allowed=primary.publish_allowed and decision != "blocked",
        reasons=reasons,
        fallback_tasks=fallback_tasks,
        accepted_outputs={},
        fallback_of=fallback_of,
        fallback_trace={
            "fallback_used": False,
            "accepted_output": "primary" if decision == "passed" else None,
            "reason": reasons,
            "review_items": list(review_items or []),
        },
        no_strong_conclusion=decision in {"blocked", "needs_review"} and primary.action is not QualityGateAction.PASS,
        strategy_card_override=_strategy_override(decision),
        primary_quality_gate_decision=primary.model_dump(mode="json"),
    )


def _quality_gate_decision(
    value: QualityGateDecision | dict[str, Any] | None,
    *,
    agent_outputs: list[AgentOutput | dict[str, Any]] | None,
    gold_macro_overview: dict[str, Any] | None,
    source_health: dict[str, Any] | None,
) -> QualityGateDecision:
    if isinstance(value, QualityGateDecision):
        return value
    if isinstance(value, dict):
        return QualityGateDecision.model_validate(value)
    return evaluate_quality_gate(
        agent_outputs=agent_outputs,
        gold_macro_overview=gold_macro_overview,
        source_health=source_health,
    )


def _quality_gate_decision_or_none(value: QualityGateDecision | dict[str, Any] | None) -> QualityGateDecision | None:
    if value is None:
        return None
    if isinstance(value, QualityGateDecision):
        return value
    return QualityGateDecision.model_validate(value)


def _agent_loop_decision(decision: QualityGateDecision) -> str:
    if decision.action is QualityGateAction.PASS:
        return "passed"
    if decision.action in {QualityGateAction.FALLBACK, QualityGateAction.RETRY}:
        return "fallback_required"
    if decision.action is QualityGateAction.BLOCK_PUBLISH:
        return "blocked"
    return "needs_review"


def _decision_reasons(decision: QualityGateDecision) -> list[str]:
    return [finding.code for finding in decision.findings]


def _fallback_tasks(decision: QualityGateDecision) -> list[AgentLoopFallbackTask]:
    tasks: list[AgentLoopFallbackTask] = []
    for action in decision.fallback_actions:
        tasks.append(AgentLoopFallbackTask(task_type=str(action), reason="quality_gate_finding"))
    if decision.retry_recommended and not tasks:
        tasks.append(AgentLoopFallbackTask(task_type="fallback_reanalyze", reason="retry_recommended"))
    if decision.fallback_recommended and not tasks:
        tasks.append(AgentLoopFallbackTask(task_type="fallback_cross_check", reason="fallback_recommended"))
    return tasks


def _fallback_of(outputs: list[AgentOutput | dict[str, Any]] | None) -> list[str]:
    refs: list[str] = []
    for output in outputs or []:
        if isinstance(output, AgentOutput):
            refs.append(f"{output.agent_name}:{output.snapshot_id}")
        elif isinstance(output, dict):
            agent = str(output.get("agent_name") or output.get("module") or "agent")
            snapshot = str(output.get("snapshot_id") or "unknown")
            refs.append(f"{agent}:{snapshot}")
    return refs


def _strategy_override(decision: str) -> dict[str, Any]:
    if decision in {"blocked", "needs_review"}:
        return {"bias": "neutral", "action": "observe_wait", "reason": decision}
    return {}
