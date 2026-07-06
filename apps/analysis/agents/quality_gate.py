from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from apps.analysis.agents.schemas import AgentBias, AgentOutput, AgentStatus
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


class AgentLoopFallbackExecution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attempted: bool
    task_results: list[dict[str, Any]] = Field(default_factory=list)
    fallback_agent_outputs: dict[str, AgentOutput] = Field(default_factory=dict)
    fallback_quality_gate_decision: QualityGateDecision | None = None


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


def execute_agent_loop_fallback_tasks(
    *,
    agent_outputs: list[AgentOutput],
    primary_quality_gate_decision: QualityGateDecision,
    gold_macro_overview: dict[str, Any] | None = None,
    source_health: dict[str, Any] | None = None,
    created_at: datetime | None = None,
) -> AgentLoopFallbackExecution:
    """Run deterministic fallback tasks for the C4 AgentLoop.

    The first executable fallback is conservative synthesis: it preserves
    source/evidence refs, downgrades bias to neutral, caps confidence, and marks
    the result as a fallback so downstream reports can render no-strong-
    conclusion output without silently overwriting the primary output.
    """

    tasks = _fallback_tasks(primary_quality_gate_decision)
    if not tasks:
        return AgentLoopFallbackExecution(attempted=False)

    primary = _preferred_primary_output(agent_outputs)
    fallback = _conservative_fallback_output(
        primary=primary,
        tasks=tasks,
        created_at=created_at or datetime.now(timezone.utc),
    )
    overview = dict(gold_macro_overview or {})
    overview["net_bias"] = "neutral"
    overview["source_refs"] = fallback.source_refs
    fallback_quality_gate_decision = evaluate_quality_gate(
        agent_outputs=[fallback],
        gold_macro_overview=overview,
        source_health=source_health,
    )
    task_results = [
        {
            "task_type": task.task_type,
            "reason": task.reason,
            "status": "queued_not_implemented",
            "fallback_output_agent": None,
            "fallback_of": f"{primary.agent_name}:{primary.snapshot_id}",
            "note": "Dedicated fallback task execution is not wired; conservative synthesis was used instead.",
        }
        for task in tasks
        if task.task_type != "fallback_conservative_synthesis"
    ]
    task_results.append(
        {
            "task_type": "fallback_conservative_synthesis",
            "reason": "conservative_fallback_after_quality_gate",
            "status": "success",
            "fallback_output_agent": fallback.agent_name,
            "fallback_of": f"{primary.agent_name}:{primary.snapshot_id}",
        }
    )
    return AgentLoopFallbackExecution(
        attempted=True,
        task_results=task_results,
        fallback_agent_outputs={fallback.agent_name: fallback},
        fallback_quality_gate_decision=fallback_quality_gate_decision,
    )


def _preferred_primary_output(agent_outputs: list[AgentOutput]) -> AgentOutput:
    for agent_name in ("coordinator_agent", "gold_macro_overview_agent", "cme_options_agent"):
        for output in agent_outputs:
            if output.agent_name == agent_name:
                return output
    if not agent_outputs:
        raise ValueError("fallback execution requires at least one primary agent output")
    return agent_outputs[-1]


def _conservative_fallback_output(
    *,
    primary: AgentOutput,
    tasks: list[AgentLoopFallbackTask],
    created_at: datetime,
) -> AgentOutput:
    source_refs = [dict(ref) for ref in primary.source_refs if isinstance(ref, dict)]
    evidence_items = [dict(item) for item in primary.evidence_items if isinstance(item, dict)]
    confidence = min(float(primary.confidence), 0.55)
    task_types = [task.task_type for task in tasks]
    return AgentOutput(
        version=primary.version,
        agent_name="fallback_synthesis_agent",
        module="agent_loop_fallback",
        snapshot_id=f"{primary.snapshot_id}:fallback",
        input_snapshot_ids={
            **dict(primary.input_snapshot_ids),
            "fallback_of": primary.snapshot_id,
            "fallback_tasks": task_types,
        },
        bias=AgentBias.NEUTRAL,
        confidence=confidence,
        key_findings=[
            "Fallback conservative synthesis generated; no strong directional conclusion is allowed.",
            f"Fallback source: {primary.agent_name}.",
        ],
        risk_points=[
            "No strong conclusion: primary output is unavailable for publication; keep the report in observe/wait mode.",
            *list(primary.risk_points),
        ],
        watchlist=[
            "Review primary vs fallback output before restoring any strong conclusion.",
            *list(primary.watchlist),
        ],
        invalid_conditions=[],
        summary="No strong conclusion: fallback conservative synthesis is in effect.",
        source_refs=source_refs,
        status=AgentStatus.PARTIAL,
        created_at=created_at,
        evidence_refs=[dict(ref) for ref in primary.evidence_refs if isinstance(ref, dict)],
        evidence_items=evidence_items,
        data_quality=[*list(primary.data_quality), "fallback_synthesis", "no_strong_conclusion"],
        input_payload={
            "fallback_of": {
                "agent_name": primary.agent_name,
                "snapshot_id": primary.snapshot_id,
            },
            "fallback_tasks": [task.model_dump(mode="json") for task in tasks],
            "primary_quality": {
                "confidence": primary.confidence,
                "bias": primary.bias.value,
                "status": primary.status.value,
            },
        },
    )
