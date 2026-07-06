from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

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

    if _has_p0_source_gap(health) and (
        _has_strong_conclusion(outputs=outputs, overview=overview, max_confidence=max_confidence)
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

    if _mixed_without_driver_decomposition(outputs=outputs, overview=overview):
        findings.append(
            QualityGateFinding(
                code="mixed_without_driver_decomposition",
                severity="manual_review",
                message="Mixed conclusion must include bullish/bearish driver decomposition.",
            )
        )

    if _has_invalid_conditions(outputs):
        findings.append(
            QualityGateFinding(
                code="invalid_conditions_present",
                severity="retry",
                message="Agent output includes invalid_conditions; refresh or rerun before stronger publication.",
                evidence={"invalid_conditions": _invalid_conditions(outputs)},
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

    action = _decision_action(findings)
    return QualityGateDecision(
        action=action,
        review_status="blocked" if action is QualityGateAction.BLOCK_PUBLISH else ("pass" if action is QualityGateAction.PASS else "needs_review"),
        publish_allowed=action is not QualityGateAction.BLOCK_PUBLISH,
        retry_recommended=action is QualityGateAction.RETRY,
        fallback_recommended=action is QualityGateAction.FALLBACK,
        manual_review_required=action in {QualityGateAction.MANUAL_REVIEW, QualityGateAction.FALLBACK},
        findings=findings,
        fallback_actions=_dedupe(fallback_actions),
        source_ref_count=len(source_refs),
        evidence_item_count=len(evidence_items),
        max_confidence=max_confidence,
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


def _mixed_without_driver_decomposition(*, outputs: list[AgentOutput], overview: dict[str, Any]) -> bool:
    if _overview_mixed_without_decomposition(overview):
        return True
    for output in outputs:
        if output.bias is not AgentBias.MIXED:
            continue
        payload = output.input_payload if isinstance(output.input_payload, dict) else {}
        if not _has_driver_lists(payload):
            return True
    return False


def _overview_mixed_without_decomposition(overview: dict[str, Any]) -> bool:
    if str(overview.get("net_bias") or overview.get("bias") or "").lower() != "mixed":
        return False
    conflict = overview.get("driver_conflict") if isinstance(overview.get("driver_conflict"), dict) else {}
    return not _has_driver_lists(conflict)


def _has_driver_lists(value: dict[str, Any]) -> bool:
    bullish = value.get("bullish_drivers")
    bearish = value.get("bearish_drivers")
    return isinstance(bullish, list) and bool(bullish) and isinstance(bearish, list) and bool(bearish)


def _has_invalid_conditions(outputs: list[AgentOutput]) -> bool:
    return bool(_invalid_conditions(outputs))


def _invalid_conditions(outputs: list[AgentOutput]) -> list[str]:
    return _dedupe(str(item) for output in outputs for item in output.invalid_conditions if str(item).strip())


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
