from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from apps.analysis.agents.fallback_executor import (
    AgentLoopFallbackExecution,
    AgentLoopFallbackTask,
    build_fallback_tasks as _fallback_tasks,
    execute_agent_loop_fallback_tasks,
    execute_conservative_synthesis_fallback,
)
from apps.analysis.agents.quality_gate_evaluator import QualityGateAction, QualityGateDecision, evaluate_quality_gate
from apps.analysis.agents.schemas import AgentOutput

__all__ = [
    "AcceptedOutputArtifactRef",
    "AcceptedOutputReference",
    "AgentLoopDecision",
    "AgentLoopFallbackExecution",
    "AgentLoopFallbackTask",
    "evaluate_agent_quality_gate",
    "execute_agent_loop_fallback_tasks",
    "execute_conservative_synthesis_fallback",
]


class AcceptedOutputArtifactRef(BaseModel):
    """Concrete rendered artifacts belonging to an already accepted candidate."""

    model_config = ConfigDict(extra="forbid")

    analysis_snapshot: str | None = None
    final_report_paths: list[str] = Field(default_factory=list)
    strategy_card_paths: list[str] = Field(default_factory=list)


class AcceptedOutputReference(BaseModel):
    """The sole authority for the candidate allowed to produce accepted output."""

    model_config = ConfigDict(extra="forbid")

    source: Literal["primary", "corrective_fallback", "none"] = "none"
    agent_name: str | None = None
    snapshot_id: str | None = None
    artifact_ref: AcceptedOutputArtifactRef | None = None

    @model_validator(mode="after")
    def _validate_identity(self) -> "AcceptedOutputReference":
        if self.source == "none":
            if self.agent_name is not None or self.snapshot_id is not None or self.artifact_ref is not None:
                raise ValueError("source='none' cannot carry accepted output identity or artifacts")
        elif not self.agent_name or not self.snapshot_id:
            raise ValueError("accepted output source requires agent_name and snapshot_id")
        return self


class AgentLoopDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: str
    review_status: str
    publish_allowed: bool
    reasons: list[str] = Field(default_factory=list)
    fallback_tasks: list[AgentLoopFallbackTask] = Field(default_factory=list)
    accepted_output: AcceptedOutputReference = Field(default_factory=AcceptedOutputReference)
    fallback_of: list[str] = Field(default_factory=list)
    fallback_trace: dict[str, Any] = Field(default_factory=dict)
    no_strong_conclusion: bool = False
    strategy_card_override: dict[str, Any] = Field(default_factory=dict)
    primary_quality_gate_decision: dict[str, Any] = Field(default_factory=dict)
    fallback_quality_gate_decision: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _validate_accepted_output_authority(self) -> "AgentLoopDecision":
        accepted = self.accepted_output.source != "none"
        if self.publish_allowed != accepted:
            raise ValueError(
                "publish_allowed must be true exactly when accepted_output.source is not 'none'"
            )
        if accepted and self.decision != "passed":
            raise ValueError("accepted output requires decision='passed'")
        legacy_selected = self.fallback_trace.get("accepted_output")
        expected_legacy = {
            "primary": "primary",
            "corrective_fallback": "fallback",
            "none": None,
        }[self.accepted_output.source]
        if "accepted_output" in self.fallback_trace and legacy_selected != expected_legacy:
            raise ValueError("fallback_trace.accepted_output contradicts accepted_output.source")
        return self

    @computed_field(return_type=dict[str, Any])
    @property
    def accepted_outputs(self) -> dict[str, Any]:
        """Compatibility projection; ``accepted_output`` remains the authority."""
        if self.accepted_output.artifact_ref is None:
            return {}
        return self.accepted_output.artifact_ref.model_dump(mode="json", exclude_none=True)


def evaluate_agent_quality_gate(
    *,
    agent_outputs: list[AgentOutput | dict[str, Any]] | None = None,
    gold_macro_overview: dict[str, Any] | None = None,
    source_health: dict[str, Any] | None = None,
    primary_quality_gate_decision: QualityGateDecision | dict[str, Any] | None = None,
    primary_output: AgentOutput | dict[str, Any] | None = None,
    corrective_fallback_output: AgentOutput | dict[str, Any] | None = None,
    fallback_outputs: dict[str, Any] | None = None,
    fallback_quality_gate_decision: QualityGateDecision | dict[str, Any] | None = None,
    corrective_fallback_succeeded: bool = False,
    independent_validator_passed: bool = False,
    unresolved_reason_codes: list[str] | None = None,
    review_items: list[dict[str, Any]] | None = None,
) -> AgentLoopDecision:
    # Legacy planned render paths are deliberately ignored: they are not an
    # accepted candidate or evidence of a rendered artifact.
    _ = fallback_outputs
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

    corrective = _agent_output_or_none(corrective_fallback_output)
    if fallback is not None and _agent_loop_decision(primary) != "passed":
        if (
            corrective is not None
            and fallback.action is QualityGateAction.PASS
            and corrective_fallback_succeeded
            and independent_validator_passed
            and not unresolved_reason_codes
        ):
            return AgentLoopDecision(
                decision="passed",
                review_status="pass",
                publish_allowed=True,
                reasons=[*reasons, "fallback_output_accepted"],
                fallback_tasks=fallback_tasks,
                accepted_output=AcceptedOutputReference(
                    source="corrective_fallback",
                    agent_name=corrective.agent_name,
                    snapshot_id=corrective.snapshot_id,
                ),
                fallback_of=fallback_of,
                fallback_trace={
                    "fallback_used": True,
                    "accepted_output": "fallback",
                    "reason": reasons,
                    "corrective_fallback_succeeded": True,
                    "unresolved_reason_codes": [],
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
            accepted_output=AcceptedOutputReference(),
            fallback_of=fallback_of,
            fallback_trace={
                "fallback_used": True,
                "accepted_output": None,
                "reason": reasons,
                "corrective_fallback_succeeded": corrective_fallback_succeeded,
                "unresolved_reason_codes": list(unresolved_reason_codes or []),
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
    primary_candidate = _agent_output_or_none(primary_output)
    primary_accepted = decision == "passed" and primary_candidate is not None
    effective_decision = "needs_review" if decision == "passed" and not primary_accepted else decision
    return AgentLoopDecision(
        decision=effective_decision,
        review_status="needs_review" if not primary_accepted else primary.review_status,
        publish_allowed=primary.publish_allowed and primary_accepted,
        reasons=[*reasons, *(["accepted_output_missing"] if not primary_accepted else [])],
        fallback_tasks=fallback_tasks,
        accepted_output=(
            AcceptedOutputReference(
                source="primary",
                agent_name=primary_candidate.agent_name,
                snapshot_id=primary_candidate.snapshot_id,
            )
            if primary_accepted and primary_candidate is not None
            else AcceptedOutputReference()
        ),
        fallback_of=fallback_of,
        fallback_trace={
            "fallback_used": False,
            "accepted_output": "primary" if primary_accepted else None,
            "reason": reasons,
            "review_items": list(review_items or []),
        },
        no_strong_conclusion=(effective_decision in {"blocked", "needs_review"} and primary.action is not QualityGateAction.PASS) or not primary_accepted,
        strategy_card_override=_strategy_override("needs_review" if not primary_accepted else effective_decision),
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


def _agent_output_or_none(value: AgentOutput | dict[str, Any] | None) -> AgentOutput | None:
    if isinstance(value, AgentOutput):
        return value
    if isinstance(value, dict):
        return AgentOutput.model_validate(value)
    return None


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
