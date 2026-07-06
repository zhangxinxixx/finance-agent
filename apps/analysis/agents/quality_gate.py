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
    snapshot: dict[str, Any] | None = None,
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
    created_at = created_at or datetime.now(timezone.utc)
    fallback_agent_outputs: dict[str, AgentOutput] = {}
    task_results: list[dict[str, Any]] = []
    for task in tasks:
        result, output = _execute_dedicated_fallback_task(
            task=task,
            agent_outputs=agent_outputs,
            snapshot=snapshot,
            created_at=created_at,
        )
        task_results.append(result)
        if output is not None:
            fallback_agent_outputs[output.agent_name] = output

    fallback = _conservative_fallback_output(
        primary=primary,
        tasks=tasks,
        created_at=created_at,
    )
    fallback_agent_outputs[fallback.agent_name] = fallback
    overview = dict(gold_macro_overview or {})
    overview["net_bias"] = "neutral"
    overview["source_refs"] = fallback.source_refs
    fallback_quality_gate_decision = evaluate_quality_gate(
        agent_outputs=[fallback],
        gold_macro_overview=overview,
        source_health=source_health,
    )
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
        fallback_agent_outputs=fallback_agent_outputs,
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


def _execute_dedicated_fallback_task(
    *,
    task: AgentLoopFallbackTask,
    agent_outputs: list[AgentOutput],
    snapshot: dict[str, Any] | None,
    created_at: datetime,
) -> tuple[dict[str, Any], AgentOutput | None]:
    if task.task_type == "fallback_reparse":
        output = _cme_options_reparse_output(agent_outputs=agent_outputs, snapshot=snapshot, created_at=created_at)
        if output is None:
            output = _jin10_vlm_reparse_output(agent_outputs=agent_outputs, created_at=created_at)
        if output is None:
            output = _jin10_report_reparse_output(agent_outputs=agent_outputs, created_at=created_at)
        if output is not None:
            return (
                {
                    "task_type": task.task_type,
                    "reason": task.reason,
                    "status": "success",
                    "fallback_output_agent": output.agent_name,
                    "fallback_of": str(output.input_payload.get("fallback_of", {}).get("snapshot_id") or "unknown"),
                },
                output,
            )
    if task.task_type in {"fallback_cross_check", "cross_check_with_independent_source"}:
        output = _fallback_cross_check_output(agent_outputs=agent_outputs, task=task, created_at=created_at)
        return _successful_fallback_task_result(task=task, output=output), output
    if task.task_type in {"fallback_reanalyze", "downgrade_to_single_source_context_until_confirmed"}:
        output = _fallback_reanalysis_output(agent_outputs=agent_outputs, task=task, created_at=created_at)
        return _successful_fallback_task_result(task=task, output=output), output
    return (
        {
            "task_type": task.task_type,
            "reason": task.reason,
            "status": "queued_not_implemented",
            "fallback_output_agent": None,
            "fallback_of": _fallback_target_ref(agent_outputs),
            "note": "Dedicated fallback task execution is not wired; conservative synthesis was used instead.",
        },
        None,
    )


def _successful_fallback_task_result(*, task: AgentLoopFallbackTask, output: AgentOutput) -> dict[str, Any]:
    fallback_of = output.input_payload.get("fallback_of", {}) if output.input_payload else {}
    return {
        "task_type": task.task_type,
        "reason": task.reason,
        "status": "success",
        "fallback_output_agent": output.agent_name,
        "fallback_of": f"{fallback_of.get('agent_name', 'agent')}:{fallback_of.get('snapshot_id', 'unknown')}",
    }


def _cme_options_reparse_output(
    *,
    agent_outputs: list[AgentOutput],
    snapshot: dict[str, Any] | None,
    created_at: datetime,
) -> AgentOutput | None:
    if not isinstance(snapshot, dict):
        return None
    if not isinstance(snapshot.get("options"), dict):
        return None
    primary = next((output for output in agent_outputs if output.agent_name == "cme_options_agent"), None)
    if primary is None:
        return None
    from apps.analysis.agents.cme_options import analyze_cme_options

    reparsed = analyze_cme_options(snapshot, created_at=created_at)
    return reparsed.model_copy(
        update={
            "agent_name": "cme_options_reparse_agent",
            "module": "agent_loop_fallback_reparse",
            "snapshot_id": f"{reparsed.snapshot_id}:fallback_reparse",
            "data_quality": [*list(reparsed.data_quality), "fallback_reparse"],
            "input_payload": {
                **dict(reparsed.input_payload or {}),
                "fallback_task": "fallback_reparse",
                "fallback_of": {
                    "agent_name": primary.agent_name,
                    "snapshot_id": primary.snapshot_id,
                },
            },
        }
    )


def _fallback_cross_check_output(
    *,
    agent_outputs: list[AgentOutput],
    task: AgentLoopFallbackTask,
    created_at: datetime,
) -> AgentOutput:
    primary = _preferred_primary_output(agent_outputs)
    source_refs = _combined_source_refs(agent_outputs)
    evidence_items = _combined_evidence_items(agent_outputs)
    source_keys = _independent_source_keys(source_refs)
    independent_source_count = len(source_keys)
    confidence = 0.60 if independent_source_count >= 2 else 0.50
    status = AgentStatus.SUCCESS if independent_source_count >= 2 else AgentStatus.PARTIAL
    source_note = (
        "Independent source cross-check found multiple source references."
        if independent_source_count >= 2
        else "Independent source cross-check did not find enough independent source references."
    )
    return AgentOutput(
        version=primary.version,
        agent_name="fallback_cross_check_agent",
        module="agent_loop_fallback_cross_check",
        snapshot_id=f"{primary.snapshot_id}:fallback_cross_check",
        input_snapshot_ids={
            **dict(primary.input_snapshot_ids),
            "fallback_of": primary.snapshot_id,
            "fallback_task": task.task_type,
        },
        bias=AgentBias.MIXED if independent_source_count >= 2 else AgentBias.NEUTRAL,
        confidence=confidence,
        key_findings=[
            source_note,
            f"Checked {len(agent_outputs)} agent outputs with {len(source_refs)} source refs and {len(evidence_items)} evidence items.",
        ],
        risk_points=[
            "Cross-check output is deterministic and read-only; it does not replace domain reanalysis.",
            *list(primary.risk_points),
        ],
        watchlist=[
            "Require human or external-source confirmation before restoring a strong directional conclusion.",
            *list(primary.watchlist),
        ],
        invalid_conditions=[],
        summary=source_note,
        source_refs=source_refs,
        status=status,
        created_at=created_at,
        evidence_refs=_combined_evidence_refs(agent_outputs),
        evidence_items=evidence_items,
        data_quality=[*_dedupe_strings(primary.data_quality), "fallback_cross_check"],
        input_payload={
            "fallback_task": task.task_type,
            "fallback_of": {
                "agent_name": primary.agent_name,
                "snapshot_id": primary.snapshot_id,
            },
            "checked_agents": [output.agent_name for output in agent_outputs],
            "source_ref_count": len(source_refs),
            "evidence_item_count": len(evidence_items),
            "independent_source_count": independent_source_count,
            "independent_source_keys": source_keys,
        },
    )


def _fallback_reanalysis_output(
    *,
    agent_outputs: list[AgentOutput],
    task: AgentLoopFallbackTask,
    created_at: datetime,
) -> AgentOutput:
    primary = _preferred_primary_output(agent_outputs)
    source_refs = _combined_source_refs(agent_outputs)
    evidence_items = _combined_evidence_items(agent_outputs)
    source_keys = _independent_source_keys(source_refs)
    is_single_source_downgrade = task.task_type == "downgrade_to_single_source_context_until_confirmed"
    agent_name = "single_source_downgrade_agent" if is_single_source_downgrade else "fallback_reanalysis_agent"
    module = "agent_loop_single_source_downgrade" if is_single_source_downgrade else "agent_loop_fallback_reanalysis"
    quality_tag = "single_source_downgrade" if is_single_source_downgrade else "fallback_reanalysis"
    summary = (
        "Single-source context downgraded; no strong directional conclusion is allowed until independently confirmed."
        if is_single_source_downgrade
        else "Deterministic fallback reanalysis generated; no strong directional conclusion is allowed."
    )
    return AgentOutput(
        version=primary.version,
        agent_name=agent_name,
        module=module,
        snapshot_id=f"{primary.snapshot_id}:{quality_tag}",
        input_snapshot_ids={
            **dict(primary.input_snapshot_ids),
            "fallback_of": primary.snapshot_id,
            "fallback_task": task.task_type,
        },
        bias=AgentBias.NEUTRAL,
        confidence=min(float(primary.confidence), 0.50),
        key_findings=[
            summary,
            f"Reanalysis preserved {len(source_refs)} source refs and {len(evidence_items)} evidence items for audit.",
        ],
        risk_points=[
            "No strong conclusion: fallback reanalysis is conservative until the primary issue is resolved.",
            *list(primary.risk_points),
        ],
        watchlist=[
            "Confirm the primary finding with an independent source before publishing a directional conclusion.",
            *list(primary.watchlist),
        ],
        invalid_conditions=[],
        summary=summary,
        source_refs=source_refs,
        status=AgentStatus.PARTIAL,
        created_at=created_at,
        evidence_refs=_combined_evidence_refs(agent_outputs),
        evidence_items=evidence_items,
        data_quality=[*_dedupe_strings(primary.data_quality), quality_tag, "no_strong_conclusion"],
        input_payload={
            "fallback_task": task.task_type,
            "fallback_of": {
                "agent_name": primary.agent_name,
                "snapshot_id": primary.snapshot_id,
            },
            "checked_agents": [output.agent_name for output in agent_outputs],
            "source_ref_count": len(source_refs),
            "evidence_item_count": len(evidence_items),
            "independent_source_count": len(source_keys),
            "independent_source_keys": source_keys,
        },
    )


def _jin10_vlm_reparse_output(
    *,
    agent_outputs: list[AgentOutput],
    created_at: datetime,
) -> AgentOutput | None:
    primary = next((output for output in agent_outputs if output.agent_name == "jin10_report_analysis_agent"), None)
    if primary is None:
        return None
    input_payload = primary.input_payload if isinstance(primary.input_payload, dict) else {}
    reparse_input = input_payload.get("vlm_reparse_input")
    if not isinstance(reparse_input, dict):
        return None
    image_entries = [dict(item) for item in reparse_input.get("image_entries") or [] if isinstance(item, dict)]
    if not image_entries:
        return None

    from apps.parsers.jin10.report_image_parser import parse_report_images

    artifacts = parse_report_images(
        article_id=str(reparse_input.get("article_id") or "unknown"),
        title=str(reparse_input.get("title") or "Jin10 report"),
        published_at=str(reparse_input.get("published_at") or "") or None,
        image_entries=image_entries,
        report_type=str(reparse_input.get("report_type") or "") or None,
    )
    parse_status = dict(artifacts.get("parse_status") or {})
    warnings = [str(item) for item in parse_status.get("warnings") or [] if str(item).strip()]
    vision_status = str(parse_status.get("vision_markdown_status") or "")
    status = AgentStatus.SUCCESS if vision_status == "success" else AgentStatus.PARTIAL
    source_refs = [dict(ref) for ref in primary.source_refs if isinstance(ref, dict)]
    evidence_refs = [
        *[dict(ref) for ref in primary.evidence_refs if isinstance(ref, dict)],
        *[
            {
                "artifact_path": str(item.get("path") or ""),
                "asset_type": item.get("asset_type") or "image",
                "seq": item.get("seq"),
                "sha256": item.get("sha256"),
            }
            for item in image_entries
            if str(item.get("path") or "").strip()
        ],
    ]
    evidence_items = _dedupe_dicts(
        [
            *[dict(item) for item in primary.evidence_items if isinstance(item, dict)],
            {
                "factor": "jin10_vlm_reparse",
                "direction": "parser_quality",
                "confidence": 0.52 if status is AgentStatus.PARTIAL else 0.60,
                "source_tier": "external_opinion",
                "verification_status": "vlm_reparse_executed",
                "pages_total": parse_status.get("pages_total"),
                "figures_total": parse_status.get("figures_total"),
            },
        ]
    )
    return AgentOutput(
        version=primary.version,
        agent_name="jin10_vlm_reparse_agent",
        module="agent_loop_fallback_jin10_vlm_reparse",
        snapshot_id=f"{primary.snapshot_id}:fallback_vlm_reparse",
        input_snapshot_ids={
            **dict(primary.input_snapshot_ids),
            "fallback_of": primary.snapshot_id,
            "fallback_task": "fallback_reparse",
        },
        bias=AgentBias.NEUTRAL,
        confidence=0.52 if status is AgentStatus.PARTIAL else 0.60,
        key_findings=[
            "Jin10 VLM parser fallback reparse executed from archived image inputs.",
            f"VLM status: {vision_status or 'unavailable'}; pages={parse_status.get('pages_total') or 0}; figures={parse_status.get('figures_total') or 0}.",
        ],
        risk_points=[
            *([f"VLM reparse warning: {warning}" for warning in warnings[:5]]),
            *list(primary.risk_points),
        ],
        watchlist=[
            "Review VLM parser status before restoring a strong directional conclusion.",
            *list(primary.watchlist),
        ],
        invalid_conditions=[],
        summary="Jin10 VLM parser fallback reparse executed; use parser status as quality evidence.",
        source_refs=source_refs,
        status=status,
        created_at=created_at,
        evidence_refs=evidence_refs,
        evidence_items=evidence_items,
        data_quality=[*_dedupe_strings(primary.data_quality), "fallback_reparse", "jin10_vlm_reparse"],
        input_payload={
            "fallback_task": "fallback_reparse",
            "fallback_of": {
                "agent_name": primary.agent_name,
                "snapshot_id": primary.snapshot_id,
            },
            "vlm_reparse_input": reparse_input,
            "parse_status": parse_status,
            "page_images": artifacts.get("page_images"),
            "figures": artifacts.get("figures"),
            "vision_markdown": artifacts.get("vision_markdown"),
            "vision_layout": artifacts.get("vision_layout"),
            "source_ref_count": len(source_refs),
            "evidence_item_count": len(evidence_items),
        },
    )


def _jin10_report_reparse_output(
    *,
    agent_outputs: list[AgentOutput],
    created_at: datetime,
) -> AgentOutput | None:
    primary = next((output for output in agent_outputs if output.agent_name == "jin10_report_analysis_agent"), None)
    if primary is None:
        return None
    input_payload = primary.input_payload if isinstance(primary.input_payload, dict) else {}
    raw_report = input_payload.get("raw_report")
    daily_report = input_payload.get("daily_report")
    if not isinstance(raw_report, dict) or not isinstance(daily_report, dict):
        return None

    from apps.analysis.jin10.agent_analysis import build_jin10_agent_analysis_report

    reparsed = build_jin10_agent_analysis_report(raw_report, daily_report).to_dict()
    source_refs = _dedupe_dicts(
        [
            *[dict(ref) for ref in reparsed.get("source_refs") or [] if isinstance(ref, dict)],
            *[dict(ref) for ref in primary.source_refs if isinstance(ref, dict)],
        ]
    )
    unresolved = [str(item).strip() for item in reparsed.get("unresolved_items") or [] if str(item).strip()]
    key_variables = [item for item in reparsed.get("key_variables") or [] if isinstance(item, dict)]
    key_levels = [item for item in reparsed.get("key_levels") or [] if isinstance(item, dict)]
    logic_chain = [str(item).strip() for item in reparsed.get("logic_chain") or [] if str(item).strip()]
    evidence_items = _dedupe_dicts(
        [
            *[dict(item) for item in primary.evidence_items if isinstance(item, dict)],
            {
                "factor": "jin10_report_reparse",
                "direction": str(reparsed.get("market_stage", {}).get("label") or "neutral"),
                "confidence": 0.58,
                "source_tier": "external_opinion",
                "verification_status": "archived_input_reparse",
            },
            *[
                {
                    "factor": "jin10_key_level",
                    "direction": str(level.get("role") or level.get("label") or "level"),
                    "strength": 0.5,
                    "confidence": 0.55,
                    "source_tier": "external_opinion",
                    "value": level.get("value") or level.get("level"),
                }
                for level in key_levels[:6]
            ],
        ]
    )
    status = AgentStatus.PARTIAL if unresolved else AgentStatus.SUCCESS
    return AgentOutput(
        version=primary.version,
        agent_name="jin10_report_reparse_agent",
        module="agent_loop_fallback_jin10_reparse",
        snapshot_id=f"{primary.snapshot_id}:fallback_reparse",
        input_snapshot_ids={
            **dict(primary.input_snapshot_ids),
            "fallback_of": primary.snapshot_id,
            "fallback_task": "fallback_reparse",
        },
        bias=_jin10_reparse_bias(reparsed, primary.bias),
        confidence=min(float(primary.confidence), 0.58),
        key_findings=_dedupe_strings(
            [
                "Jin10 archived report inputs were deterministically reparsed.",
                f"Market stage: {str(reparsed.get('market_stage', {}).get('label') or 'unavailable')}.",
                *logic_chain[:3],
            ]
        ),
        risk_points=[
            *[str(item).strip() for item in reparsed.get("risk_points") or [] if str(item).strip()],
            *list(primary.risk_points),
        ],
        watchlist=[
            *[
                str(item.get("name") or item.get("label") or "").strip()
                for item in key_variables
                if str(item.get("name") or item.get("label") or "").strip()
            ][:8],
            *list(primary.watchlist),
        ],
        invalid_conditions=unresolved,
        summary=str(reparsed.get("one_line_conclusion") or reparsed.get("final_summary") or primary.summary),
        source_refs=source_refs,
        status=status,
        created_at=created_at,
        evidence_refs=[
            *[dict(ref) for ref in primary.evidence_refs if isinstance(ref, dict)],
            *[
                {"artifact_path": path}
                for path in reparsed.get("source_artifact_refs") or []
                if str(path).strip()
            ],
        ],
        evidence_items=evidence_items,
        data_quality=[*_dedupe_strings(primary.data_quality), "fallback_reparse", "jin10_archived_input_reparse"],
        input_payload={
            "fallback_task": "fallback_reparse",
            "fallback_of": {
                "agent_name": primary.agent_name,
                "snapshot_id": primary.snapshot_id,
            },
            "raw_report": raw_report,
            "daily_report": daily_report,
            "report_json": reparsed,
            "source_ref_count": len(source_refs),
            "evidence_item_count": len(evidence_items),
            "unresolved_item_count": len(unresolved),
        },
    )


def _jin10_reparse_bias(reparsed: dict[str, Any], fallback: AgentBias) -> AgentBias:
    text = " ".join(
        [
            str(reparsed.get("one_line_conclusion") or ""),
            str(reparsed.get("final_summary") or ""),
            str((reparsed.get("market_stage") or {}).get("label") or ""),
        ]
    )
    positive = sum(word in text for word in ("反弹", "修复", "上行", "顺风", "突破", "看涨", "多头"))
    negative = sum(word in text for word in ("承压", "压制", "下行", "失守", "看跌", "空头"))
    if positive and negative:
        return AgentBias.MIXED
    if positive:
        return AgentBias.BULLISH
    if negative:
        return AgentBias.BEARISH
    return fallback if fallback in {AgentBias.BULLISH, AgentBias.BEARISH, AgentBias.MIXED} else AgentBias.NEUTRAL


def _fallback_target_ref(agent_outputs: list[AgentOutput]) -> str:
    target = next((output for output in agent_outputs if output.agent_name == "cme_options_agent"), None)
    if target is None:
        target = _preferred_primary_output(agent_outputs)
    return f"{target.agent_name}:{target.snapshot_id}"


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


def _combined_source_refs(agent_outputs: list[AgentOutput]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for output in agent_outputs:
        refs.extend(dict(ref) for ref in output.source_refs if isinstance(ref, dict))
    return _dedupe_dicts(refs)


def _combined_evidence_refs(agent_outputs: list[AgentOutput]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for output in agent_outputs:
        refs.extend(dict(ref) for ref in output.evidence_refs if isinstance(ref, dict))
    return _dedupe_dicts(refs)


def _combined_evidence_items(agent_outputs: list[AgentOutput]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for output in agent_outputs:
        items.extend(dict(item) for item in output.evidence_items if isinstance(item, dict))
    return _dedupe_dicts(items)


def _dedupe_dicts(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for value in values:
        marker = repr(sorted(value.items()))
        if marker in seen:
            continue
        seen.add(marker)
        deduped.append(value)
    return deduped


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _independent_source_keys(source_refs: list[dict[str, Any]]) -> list[str]:
    keys = {_source_ref_key(ref) for ref in source_refs}
    return sorted(key for key in keys if key)


def _source_ref_key(ref: dict[str, Any]) -> str:
    source = str(ref.get("source") or ref.get("provider") or ref.get("dataset") or "").strip()
    for field in ("source_ref", "ref_id", "artifact_ref", "url", "path", "symbol", "id"):
        value = str(ref.get(field) or "").strip()
        if value:
            return f"{source}:{value}" if source else value
    if source:
        return source
    return repr(sorted(ref.items()))
