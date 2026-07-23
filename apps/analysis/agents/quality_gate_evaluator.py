from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from apps.analysis.agents.schemas import AgentBias, AgentOutput


class QualityGateAction(StrEnum):
    PASS = "pass"
    RETRY = "retry"
    FALLBACK = "fallback"
    MANUAL_REVIEW = "manual_review"
    BLOCK_PUBLISH = "block_publish"


class QualityGateFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    severity: str
    message: str
    evidence: dict[str, Any] = Field(default_factory=dict)


class QualityGateDecision(BaseModel):
    """Read-only publish gate decision for AgentLoop / ReviewGate flows."""

    model_config = ConfigDict(extra="forbid")

    action: QualityGateAction
    review_status: str
    publish_allowed: bool
    retry_recommended: bool = False
    fallback_recommended: bool = False
    manual_review_required: bool = False
    findings: list[QualityGateFinding] = Field(default_factory=list)
    fallback_actions: list[str] = Field(default_factory=list)
    source_ref_count: int = 0
    evidence_item_count: int = 0
    max_confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def enforce_publish_contract(self) -> "QualityGateDecision":
        self.publish_allowed = self.action is QualityGateAction.PASS
        return self


_ACTION_RANK = {
    QualityGateAction.PASS: 0,
    QualityGateAction.RETRY: 1,
    QualityGateAction.FALLBACK: 2,
    QualityGateAction.MANUAL_REVIEW: 3,
    QualityGateAction.BLOCK_PUBLISH: 4,
}


def evaluate_quality_gate(
    *,
    agent_outputs: list[AgentOutput | dict[str, Any]] | None = None,
    gold_macro_overview: dict[str, Any] | None = None,
    source_health: dict[str, Any] | None = None,
) -> QualityGateDecision:
    """Evaluate whether an analysis artifact can be published.

    The gate is intentionally read-only: it consumes persisted AgentOutput-like
    objects and overview/source-health read models, then returns a deterministic
    decision for ReviewGate / AgentLoop orchestration.
    """

    outputs = [_coerce_agent_output(item) for item in agent_outputs or []]
    outputs = [item for item in outputs if item is not None]
    overview = dict(gold_macro_overview or {})
    health = dict(source_health or overview.get("source_health") or {})

    source_refs = _collect_source_refs(outputs=outputs, overview=overview)
    evidence_items = _collect_evidence_items(outputs=outputs, overview=overview)
    max_confidence = _max_confidence(outputs=outputs, overview=overview)
    findings: list[QualityGateFinding] = []
    fallback_actions: list[str] = []

    context = overview.get("gold_analysis_context")
    if isinstance(context, dict) and str(context.get("status") or "") not in {"", "ready"}:
        findings.append(
            QualityGateFinding(
                code="gold_analysis_context_degraded",
                severity="manual_review",
                message="统一黄金分析上下文缺失或过期；综合输出保持 observe/needs_review。",
                evidence={
                    "status": context.get("status"),
                    "baseline_kind": context.get("baseline_kind"),
                    "freshness": context.get("freshness") or {},
                },
            )
        )

    if _has_p0_source_gap(health) and (
        health.get("can_build_gold_macro_overview") is False
        or _has_strong_conclusion(outputs=outputs, overview=overview, max_confidence=max_confidence)
        or _source_health_blocks_strong_conclusion(health)
    ):
        findings.append(
            QualityGateFinding(
                code="p0_gap_strong_conclusion",
                severity="blocker",
                message="P0 source gap conflicts with a strong or high-confidence conclusion.",
                evidence={
                    "p0_missing": list(health.get("p0_missing") or []),
                    "overall_status": health.get("overall_status"),
                    "max_confidence": max_confidence,
                },
            )
        )

    if not source_refs:
        findings.append(
            QualityGateFinding(
                code="source_refs_missing",
                severity="blocker",
                message="Publishable analysis must retain source_refs for source trace.",
            )
        )

    if max_confidence >= 0.75 and not evidence_items:
        findings.append(
            QualityGateFinding(
                code="high_confidence_without_evidence_items",
                severity="manual_review",
                message="High-confidence conclusion has no structured evidence_items for quality review.",
                evidence={"max_confidence": max_confidence},
            )
        )

    coordinator = _output_by_name(outputs, "coordinator_agent")
    if coordinator is not None and not coordinator.source_refs:
        findings.append(
            QualityGateFinding(
                code="coordinator_source_refs_missing",
                severity="blocker",
                message="Coordinator output must retain its own source_refs before publication.",
            )
        )
    if coordinator is not None and coordinator.confidence >= 0.75 and not coordinator.evidence_items:
        findings.append(
            QualityGateFinding(
                code="coordinator_high_confidence_without_evidence_items",
                severity="manual_review",
                message="High-confidence Coordinator output has no structured evidence_items.",
                evidence={"confidence": coordinator.confidence},
            )
        )

    coordinator_risk_conflict = _coordinator_risk_conflict(outputs)
    if coordinator_risk_conflict:
        findings.append(
            QualityGateFinding(
                code="coordinator_risk_conflict",
                severity="manual_review",
                message="Coordinator directional conclusion conflicts with the Risk Agent output.",
                evidence=coordinator_risk_conflict,
            )
        )

    if _mixed_without_driver_decomposition(outputs=outputs, overview=overview):
        findings.append(
            QualityGateFinding(
                code="mixed_without_driver_decomposition",
                severity="manual_review",
                message="Mixed conclusion must include bullish/bearish driver decomposition.",
            )
        )

    if _fact_review_needs_review(outputs=outputs, overview=overview):
        findings.append(
            QualityGateFinding(
                code="fact_review_needs_review",
                severity="manual_review",
                message="Fact review marked the artifact as needs_review; strong publication must stop.",
                evidence={"fact_review_status": overview.get("fact_review_status")},
            )
        )

    claim_status = _claim_review_status(outputs=outputs, overview=overview)
    if claim_status == "contradicted":
        findings.append(
            QualityGateFinding(
                code="contradicted_claim",
                severity="blocker",
                message="Contradicted claim cannot be published without a corrected fallback output.",
            )
        )
    elif claim_status == "unsupported":
        findings.append(
            QualityGateFinding(
                code="unsupported_claim",
                severity="fallback",
                message="Unsupported claim requires fallback reanalysis or independent source check.",
            )
        )
        fallback_actions.append("fallback_reanalyze")

    if _critical_agent_low_confidence(outputs):
        findings.append(
            QualityGateFinding(
                code="critical_agent_low_confidence",
                severity="fallback",
                message="Critical Gold v3 agent confidence is below the fallback threshold.",
                evidence={"threshold": 0.60},
            )
        )
        fallback_actions.append("fallback_reanalyze")

    if _parse_or_required_field_quality_gap(outputs=outputs, overview=overview):
        findings.append(
            QualityGateFinding(
                code="parse_or_required_field_quality_gap",
                severity="fallback",
                message="Parse-suspect or missing required fields require fallback reparse.",
            )
        )
        fallback_actions.append("fallback_reparse")

    active_blockers = _active_blockers(outputs)
    if active_blockers:
        findings.append(
            QualityGateFinding(
                code="active_blockers_present",
                severity="blocker",
                message="Agent output declares current active blockers; publication must stop.",
                evidence={"active_blockers": active_blockers},
            )
        )

    blocking_data_gaps = _blocking_data_gaps(outputs)
    if blocking_data_gaps:
        findings.append(
            QualityGateFinding(
                code="p0_data_gaps_present",
                severity="blocker",
                message="Agent output declares current P0/blocker data gaps; publication must stop.",
                evidence={"data_gaps": blocking_data_gaps},
            )
        )

    review_triggers = _manual_review_triggers(outputs)
    if review_triggers:
        findings.append(
            QualityGateFinding(
                code="review_triggers_present",
                severity="manual_review",
                message="Agent output declares current review triggers.",
                evidence={"review_triggers": review_triggers},
            )
        )

    if _single_source_important_conclusion(outputs=outputs, overview=overview, max_confidence=max_confidence):
        findings.append(
            QualityGateFinding(
                code="single_source_important_conclusion",
                severity="fallback",
                message="Important directional conclusion depends on single-source evidence.",
                evidence={"max_confidence": max_confidence},
            )
        )
        fallback_actions.append("cross_check_with_independent_source")
        fallback_actions.append("downgrade_to_single_source_context_until_confirmed")

    if (
        _has_external_market_odds(outputs=outputs, overview=overview)
        and _has_strong_conclusion(outputs=outputs, overview=overview, max_confidence=max_confidence)
        and not _has_independent_market_confirmation(outputs=outputs, overview=overview)
    ):
        findings.append(
            QualityGateFinding(
                code="external_market_odds_only_strong_conclusion",
                severity="blocker",
                message="External single-source market odds cannot independently support a strong directional conclusion.",
                evidence={
                    "source_kind": "jin10_external_market_odds",
                    "max_confidence": max_confidence,
                    "independent_market_confirmation": False,
                },
            )
        )

    action = _decision_action(findings)
    return QualityGateDecision(
        action=action,
        review_status="blocked" if action is QualityGateAction.BLOCK_PUBLISH else ("pass" if action is QualityGateAction.PASS else "needs_review"),
        publish_allowed=action is QualityGateAction.PASS,
        retry_recommended=action is QualityGateAction.RETRY,
        fallback_recommended=action is QualityGateAction.FALLBACK,
        manual_review_required=action in {QualityGateAction.MANUAL_REVIEW, QualityGateAction.FALLBACK},
        findings=findings,
        fallback_actions=_dedupe(fallback_actions),
        source_ref_count=len(source_refs),
        evidence_item_count=len(evidence_items),
        max_confidence=max_confidence,
    )


def preserve_unresolved_pre_gate(
    *,
    pre_coordinator_decision: QualityGateDecision,
    post_coordinator_decision: QualityGateDecision,
) -> QualityGateDecision:
    """Carry unresolved domain-gate failures into the final post gate.

    Domain fallbacks are observation-only until an independent validator is
    wired, so adding a Coordinator output cannot by itself erase an earlier
    publication failure.
    """

    if pre_coordinator_decision.action is QualityGateAction.PASS:
        return post_coordinator_decision
    action = max(
        (pre_coordinator_decision.action, post_coordinator_decision.action),
        key=_ACTION_RANK.__getitem__,
    )
    findings: list[QualityGateFinding] = []
    seen: set[tuple[str, str]] = set()
    for finding in [*pre_coordinator_decision.findings, *post_coordinator_decision.findings]:
        key = (finding.code, finding.message)
        if key in seen:
            continue
        seen.add(key)
        findings.append(finding)
    return QualityGateDecision(
        action=action,
        review_status=(
            "blocked"
            if action is QualityGateAction.BLOCK_PUBLISH
            else ("pass" if action is QualityGateAction.PASS else "needs_review")
        ),
        publish_allowed=action is QualityGateAction.PASS,
        retry_recommended=action is QualityGateAction.RETRY,
        fallback_recommended=action is QualityGateAction.FALLBACK,
        manual_review_required=action in {QualityGateAction.MANUAL_REVIEW, QualityGateAction.FALLBACK},
        findings=findings,
        fallback_actions=_dedupe(
            [
                *pre_coordinator_decision.fallback_actions,
                *post_coordinator_decision.fallback_actions,
            ]
        ),
        source_ref_count=max(
            pre_coordinator_decision.source_ref_count,
            post_coordinator_decision.source_ref_count,
        ),
        evidence_item_count=max(
            pre_coordinator_decision.evidence_item_count,
            post_coordinator_decision.evidence_item_count,
        ),
        max_confidence=max(
            pre_coordinator_decision.max_confidence,
            post_coordinator_decision.max_confidence,
        ),
    )


def _coerce_agent_output(value: AgentOutput | dict[str, Any]) -> AgentOutput | None:
    if isinstance(value, AgentOutput):
        return value
    if isinstance(value, dict):
        try:
            return AgentOutput.model_validate(value)
        except Exception:
            return None
    return None


def _collect_source_refs(*, outputs: list[AgentOutput], overview: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    refs.extend(dict(item) for item in overview.get("source_refs") or [] if isinstance(item, dict))
    for row in overview.get("theme_rankings") or []:
        if isinstance(row, dict):
            refs.extend(dict(item) for item in row.get("source_refs") or [] if isinstance(item, dict))
    for output in outputs:
        refs.extend(dict(item) for item in output.source_refs if isinstance(item, dict))
    return _dedupe_dicts(refs)


def _collect_evidence_items(*, outputs: list[AgentOutput], overview: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    items.extend(dict(item) for item in overview.get("evidence_items") or [] if isinstance(item, dict))
    for output in outputs:
        items.extend(dict(item) for item in output.evidence_items if isinstance(item, dict))
    return items


def _max_confidence(*, outputs: list[AgentOutput], overview: dict[str, Any]) -> float:
    values = [output.confidence for output in outputs]
    for key in ("confidence", "confidence_score"):
        value = overview.get(key)
        if isinstance(value, int | float):
            values.append(float(value) if key == "confidence" else float(value) / 100.0)
    return _clamp(max(values or [0.0]))


def _output_by_name(outputs: list[AgentOutput], agent_name: str) -> AgentOutput | None:
    return next((output for output in outputs if output.agent_name == agent_name), None)


def _coordinator_risk_conflict(outputs: list[AgentOutput]) -> dict[str, str]:
    coordinator = _output_by_name(outputs, "coordinator_agent")
    risk = _output_by_name(outputs, "risk_agent")
    if coordinator is None or risk is None:
        return {}
    directional = {AgentBias.BULLISH, AgentBias.BEARISH}
    if coordinator.bias not in directional or risk.bias not in directional:
        return {}
    if risk.bias is coordinator.bias:
        return {}
    return {
        "coordinator_bias": coordinator.bias.value,
        "risk_bias": risk.bias.value,
    }


def _has_p0_source_gap(source_health: dict[str, Any]) -> bool:
    if source_health.get("can_build_gold_macro_overview") is False:
        return True
    return bool(source_health.get("p0_missing"))


def _source_health_blocks_strong_conclusion(source_health: dict[str, Any]) -> bool:
    reasons = " ".join(str(item) for item in source_health.get("blocking_reasons") or []).lower()
    return "strong goldmacrooverview conclusion" in reasons or "strong conclusion" in reasons


def _has_strong_conclusion(*, outputs: list[AgentOutput], overview: dict[str, Any], max_confidence: float) -> bool:
    strong_terms = ("strong", "breakout", "high_conviction", "强", "突破", "确定")
    overview_text = " ".join(
        str(overview.get(key) or "")
        for key in ("phase", "net_bias", "one_line_conclusion", "priority_regime")
    ).lower()
    if any(term in overview_text for term in strong_terms):
        return True
    if str(overview.get("net_bias") or "") in {"strong_bullish", "strong_bearish"}:
        return True
    return any(output.bias in {AgentBias.BULLISH, AgentBias.BEARISH} and output.confidence >= 0.75 for output in outputs) or max_confidence >= 0.82


def _has_external_market_odds(*, outputs: list[AgentOutput], overview: dict[str, Any]) -> bool:
    if _contains_external_market_odds(overview):
        return True
    return any(
        _contains_external_market_odds(output.input_payload)
        or _contains_external_market_odds(output.evidence_items)
        or _contains_external_market_odds(output.source_refs)
        for output in outputs
    )


def _contains_external_market_odds(value: Any) -> bool:
    if isinstance(value, dict):
        if value.get("source_kind") == "jin10_external_market_odds" or value.get("observation_type") == "external_market_odds":
            return True
        return any(_contains_external_market_odds(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_external_market_odds(item) for item in value)
    return False


def _has_independent_market_confirmation(*, outputs: list[AgentOutput], overview: dict[str, Any]) -> bool:
    if any(
        overview.get(key)
        for key in (
            "market_derived_odds",
            "price_context",
            "rates_context",
            "official_event_confirmation",
            "confirmed_market_evidence",
        )
    ):
        return True
    for output in outputs:
        category = output.data_category.value if output.data_category is not None else ""
        if category not in {"confirmed_data", "system_inference"}:
            continue
        if output.agent_name in {"news_agent", "jin10_report_analysis_agent"}:
            continue
        if output.status.value in {"success", "partial"} and (output.source_refs or output.evidence_items):
            return True
    return False


def _mixed_without_driver_decomposition(*, outputs: list[AgentOutput], overview: dict[str, Any]) -> bool:
    # This gate protects the publishable artifact.  Intermediate agents can be
    # mixed while the final overview resolves that conflict into a directional
    # conclusion with its own driver decomposition.
    _ = outputs
    return _overview_mixed_without_decomposition(overview)


def _overview_mixed_without_decomposition(overview: dict[str, Any]) -> bool:
    if str(overview.get("net_bias") or overview.get("bias") or "").lower() != "mixed":
        return False
    conflict = overview.get("driver_conflict") if isinstance(overview.get("driver_conflict"), dict) else {}
    return not _has_driver_lists(conflict)


def _has_driver_lists(value: dict[str, Any]) -> bool:
    bullish = value.get("bullish_drivers")
    bearish = value.get("bearish_drivers")
    return isinstance(bullish, list) and bool(bullish) and isinstance(bearish, list) and bool(bearish)


def _active_blockers(outputs: list[AgentOutput]) -> list[str]:
    return _dedupe(str(item) for output in outputs for item in output.active_blockers if str(item).strip())


def _blocking_data_gaps(outputs: list[AgentOutput]) -> list[dict[str, str]]:
    gaps: list[dict[str, str]] = []
    for output in outputs:
        for gap in output.data_gaps:
            if gap.severity not in {"p0", "blocker"}:
                continue
            gaps.append(
                {
                    "agent_name": output.agent_name,
                    "code": gap.code,
                    "message": gap.message,
                    "severity": gap.severity,
                }
            )
    return gaps


def _manual_review_triggers(outputs: list[AgentOutput]) -> list[str]:
    claim_status_triggers = {"unsupported_claim", "contradicted_claim"}
    return _dedupe(
        str(item)
        for output in outputs
        for item in output.review_triggers
        if str(item).strip().lower() not in claim_status_triggers
    )


def _fact_review_needs_review(*, outputs: list[AgentOutput], overview: dict[str, Any]) -> bool:
    statuses = [str(overview.get("fact_review_status") or "").lower()]
    review_gate = overview.get("review_gate")
    if isinstance(review_gate, dict):
        statuses.append(str(review_gate.get("fact_review_status") or "").lower())
    for output in outputs:
        payload = output.input_payload if isinstance(output.input_payload, dict) else {}
        statuses.append(str(payload.get("fact_review_status") or "").lower())
        statuses.extend(str(item).lower() for item in output.data_quality)
    return any(status in {"needs_review", "fact_review:needs_review"} for status in statuses)


def _claim_review_status(*, outputs: list[AgentOutput], overview: dict[str, Any]) -> str | None:
    statuses: list[str] = []
    for key in ("claim_review_status", "claim_status", "fact_review_status"):
        value = overview.get(key)
        if value:
            statuses.append(str(value).lower())
    for output in outputs:
        payload = output.input_payload if isinstance(output.input_payload, dict) else {}
        for key in ("claim_review_status", "claim_status", "fact_review_status"):
            value = payload.get(key)
            if value:
                statuses.append(str(value).lower())
        statuses.extend(str(item).strip().lower() for item in output.active_blockers)
        statuses.extend(str(item).strip().lower() for item in output.review_triggers)
        statuses.extend(
            str(item).strip().lower()
            for item in output.invalidation_conditions
            if str(item).strip().lower() in {"unsupported_claim", "contradicted_claim"}
        )
    if any(status in {"contradicted", "contradicted_claim"} for status in statuses):
        return "contradicted"
    if any(status in {"unsupported", "unsupported_claim"} for status in statuses):
        return "unsupported"
    return None


def _critical_agent_low_confidence(outputs: list[AgentOutput]) -> bool:
    critical_agents = {
        "source_health_agent",
        "event_attribution_agent",
        "transmission_chain_agent",
        "driver_decomposition_agent",
        "mainline_ranking_agent",
        "gold_macro_overview_agent",
        "review_gate_agent",
    }
    return any(output.agent_name in critical_agents and output.confidence < 0.60 for output in outputs)


def _parse_or_required_field_quality_gap(*, outputs: list[AgentOutput], overview: dict[str, Any]) -> bool:
    quality_tags: list[str] = []
    data_quality = overview.get("data_quality")
    if isinstance(data_quality, dict):
        quality_tags.extend(str(value).lower() for value in data_quality.values() if value)
    else:
        quality_tags.extend(str(item).lower() for item in data_quality or [] if isinstance(item, str))
    for output in outputs:
        quality_tags.extend(str(item).lower() for item in output.data_quality)
        payload = output.input_payload if isinstance(output.input_payload, dict) else {}
        payload_quality = payload.get("data_quality")
        if isinstance(payload_quality, dict):
            quality_tags.extend(str(value).lower() for value in payload_quality.values() if value)
        else:
            quality_tags.extend(str(item).lower() for item in payload_quality or [] if isinstance(item, str))
    return any(tag in {"parse_suspect", "missing_required_fields"} for tag in quality_tags)


def _single_source_important_conclusion(*, outputs: list[AgentOutput], overview: dict[str, Any], max_confidence: float) -> bool:
    if max_confidence < 0.70 and not _has_strong_conclusion(outputs=outputs, overview=overview, max_confidence=max_confidence):
        return False
    statuses: list[str] = []
    data_quality = overview.get("data_quality")
    if isinstance(data_quality, dict):
        statuses.extend(str(item).lower() for item in data_quality.values() if item)
    else:
        statuses.extend(str(item).lower() for item in data_quality or [] if isinstance(item, str))
    for ref in _collect_source_refs(outputs=outputs, overview=overview):
        for key in ("verification_status", "status", "source_tier"):
            value = ref.get(key)
            if value:
                statuses.append(str(value).lower())
    for output in outputs:
        statuses.extend(str(item).lower() for item in output.data_quality)
        for item in output.evidence_items:
            status = item.get("verification_status") or item.get("source_tier") or item.get("status")
            if status:
                statuses.append(str(status).lower())
    return any("single_source" in item or item == "single" for item in statuses)


def _decision_action(findings: list[QualityGateFinding]) -> QualityGateAction:
    action = QualityGateAction.PASS
    for finding in findings:
        severity = finding.severity
        if severity == "blocker":
            candidate = QualityGateAction.BLOCK_PUBLISH
        elif severity == "manual_review":
            candidate = QualityGateAction.MANUAL_REVIEW
        elif severity == "fallback":
            candidate = QualityGateAction.FALLBACK
        elif severity == "retry":
            candidate = QualityGateAction.RETRY
        else:
            candidate = QualityGateAction.PASS
        if _ACTION_RANK[candidate] > _ACTION_RANK[action]:
            action = candidate
    return action


def _dedupe(items: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = str(item).strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _dedupe_dicts(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        key = repr(sorted(item.items()))
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, round(float(value), 4)))
