from __future__ import annotations

from datetime import datetime, time, timezone
from typing import Any

from apps.analysis.agents.schemas import AgentBias, AgentOutput, AgentStatus
from apps.analysis.confidence import ConfidenceKernel
from apps.decision.feasibility import evaluate_feasibility
from apps.decision.schemas import StrategyDecision


def build_strategy_decision(
    *,
    market_state: dict[str, Any],
    evidence_items: list[dict[str, Any]],
    confidence_kernel: ConfidenceKernel,
    agent_outputs: list[AgentOutput | dict[str, Any]],
    created_at: datetime | None = None,
) -> StrategyDecision:
    state = dict(market_state) if isinstance(market_state, dict) else {}
    evidence = [dict(item) for item in evidence_items if isinstance(item, dict)]
    outputs = [_coerce_output(item) for item in agent_outputs]
    outputs = [item for item in outputs if item is not None]
    created_at = created_at or _created_at_from_state(state)

    bias = _decision_bias(market_state=state, confidence_kernel=confidence_kernel, evidence_items=evidence, outputs=outputs)
    status = AgentStatus.UNAVAILABLE if bias is AgentBias.UNAVAILABLE else AgentStatus.SUCCESS
    feasibility_label, feasibility_score, feasibility_reasons = evaluate_feasibility(
        confidence_kernel=confidence_kernel,
        bias=bias,
        market_state=state,
        evidence_items=evidence,
    )
    if feasibility_label == "not_actionable":
        status = AgentStatus.UNAVAILABLE

    snapshot_id = str(state.get("snapshot_id") or "unknown")
    return StrategyDecision(
        asset=str(state.get("asset") or state.get("symbol") or "XAUUSD"),
        trade_date=str(state.get("trade_date") or state.get("as_of") or _date_from_snapshot(snapshot_id)),
        run_id=str(state.get("run_id") or snapshot_id),
        snapshot_id=snapshot_id,
        bias=bias,
        status=status,
        confidence=confidence_kernel.overall,
        confidence_kernel=confidence_kernel,
        feasibility_label=feasibility_label,
        feasibility_score=feasibility_score,
        feasibility_reasons=feasibility_reasons,
        regime_context=_regime_context(state),
        time_horizon=str(state.get("time_horizon")) if state.get("time_horizon") else None,
        required_confirmations=_required_confirmations(confidence_kernel, evidence),
        invalidation_conditions=_invalidation_conditions(confidence_kernel),
        risk_points=list(feasibility_reasons),
        source_refs=_source_refs(state, evidence, outputs),
        evidence_items=evidence,
        created_at=created_at,
        is_trade_instruction=False,
    )


def _coerce_output(value: AgentOutput | dict[str, Any]) -> AgentOutput | None:
    if isinstance(value, AgentOutput):
        return value
    if isinstance(value, dict):
        try:
            return AgentOutput.model_validate(value)
        except Exception:
            return None
    return None


def _decision_bias(
    *,
    market_state: dict[str, Any],
    confidence_kernel: ConfidenceKernel,
    evidence_items: list[dict[str, Any]],
    outputs: list[AgentOutput],
) -> AgentBias:
    if confidence_kernel.overall < 0.35:
        return AgentBias.UNAVAILABLE
    if not evidence_items and not outputs and confidence_kernel.data_confidence <= 0.55:
        return AgentBias.UNAVAILABLE
    state_bias = _normalize_bias(market_state.get("bias") or market_state.get("direction"))
    if state_bias in {AgentBias.BULLISH, AgentBias.BEARISH, AgentBias.NEUTRAL, AgentBias.MIXED}:
        return state_bias
    output_biases = [output.bias for output in outputs if output.bias in {AgentBias.BULLISH, AgentBias.BEARISH}]
    if output_biases:
        if len(set(output_biases)) > 1:
            return AgentBias.MIXED
        return output_biases[0]
    evidence_biases = {_normalize_bias(item.get("bias") or item.get("direction")) for item in evidence_items}
    evidence_biases.discard(None)
    if len(evidence_biases) == 1:
        return next(iter(evidence_biases))  # type: ignore[return-value]
    if len(evidence_biases) > 1:
        return AgentBias.MIXED
    return AgentBias.NEUTRAL if confidence_kernel.overall >= 0.50 else AgentBias.UNAVAILABLE


def _normalize_bias(value: Any) -> AgentBias | None:
    text = str(value or "").lower()
    if text in {"bullish", "supportive", "constructive", "upside"}:
        return AgentBias.BULLISH
    if text in {"bearish", "pressure", "resistance", "downside"}:
        return AgentBias.BEARISH
    if text in {"neutral", "balanced", "range"}:
        return AgentBias.NEUTRAL
    if text == "mixed":
        return AgentBias.MIXED
    return None


def _required_confirmations(kernel: ConfidenceKernel, evidence_items: list[dict[str, Any]]) -> list[str]:
    confirmations = [f"resolve confidence cap: {cap}" for cap in kernel.caps]
    for item in evidence_items:
        value = item.get("required_confirmation") or item.get("confirmation")
        if value:
            confirmations.append(str(value))
    if not confirmations:
        confirmations.append("confirm source freshness and cross-source alignment before increasing conviction.")
    return _dedupe(confirmations)


def _invalidation_conditions(kernel: ConfidenceKernel) -> list[str]:
    conditions = [f"confidence invalid if {cap} persists." for cap in kernel.caps]
    if not conditions:
        conditions.append("decision invalid if confidence kernel falls below research threshold.")
    return conditions


def _source_refs(
    state: dict[str, Any],
    evidence_items: list[dict[str, Any]],
    outputs: list[AgentOutput],
) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    refs.extend(dict(item) for item in state.get("source_refs") or [] if isinstance(item, dict))
    for item in evidence_items:
        refs.extend(dict(ref) for ref in item.get("source_refs") or [] if isinstance(ref, dict))
    for output in outputs:
        refs.extend(dict(ref) for ref in output.source_refs if isinstance(ref, dict))
    return _dedupe_dicts(refs)


def _regime_context(state: dict[str, Any]) -> str | None:
    regime = state.get("regime")
    if isinstance(regime, dict):
        return str(regime.get("phase") or regime.get("label") or "") or None
    return str(regime) if regime else None


def _date_from_snapshot(snapshot_id: str) -> str:
    for part in snapshot_id.split(":"):
        if len(part) == 10 and part[4] == "-" and part[7] == "-":
            return part
    return "unknown"


def _created_at_from_state(state: dict[str, Any]) -> datetime:
    value = state.get("created_at") or state.get("as_of") or state.get("trade_date")
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    trade_date = str(state.get("trade_date") or _date_from_snapshot(str(state.get("snapshot_id") or "")))
    try:
        date_value = datetime.strptime(trade_date, "%Y-%m-%d").date()
        return datetime.combine(date_value, time.min, tzinfo=timezone.utc)
    except ValueError:
        return datetime(1970, 1, 1, tzinfo=timezone.utc)


def _dedupe(items: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = item.strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _dedupe_dicts(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        key = repr(sorted(item.items()))
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result
