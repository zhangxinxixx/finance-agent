from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError

from apps.analysis.agents.schemas import AgentBias, AgentOutput, AgentStatus, DataCategory
from apps.analysis.confidence import compute_confidence_kernel

_AGENT_NAME = "coordinator_agent"
_MODULE = "coordinator"
_VERSION = "1.0"
_WATCHLIST = [
    "宏观方向",
    "CME 期权关键价位",
    "风险上限",
    "技术面可用性",
    "新闻可用性",
    "持仓可用性",
    "市场赔率可用性",
]
_DIRECTIONAL_BIASES = {AgentBias.BULLISH, AgentBias.BEARISH}
_BIAS_ALIASES = {
    "supportive": AgentBias.BULLISH,
    "constructive": AgentBias.BULLISH,
    "upside": AgentBias.BULLISH,
    "bullish": AgentBias.BULLISH,
    "resistance": AgentBias.BEARISH,
    "pressure": AgentBias.BEARISH,
    "downside": AgentBias.BEARISH,
    "bearish": AgentBias.BEARISH,
    "balanced": AgentBias.NEUTRAL,
    "range": AgentBias.NEUTRAL,
    "neutral": AgentBias.NEUTRAL,
    "mixed": AgentBias.MIXED,
    "missing": AgentBias.UNAVAILABLE,
    "failed": AgentBias.UNAVAILABLE,
    "unavailable": AgentBias.UNAVAILABLE,
}


def coordinate_agent_outputs(
    snapshot: dict[str, Any],
    *,
    macro_output: AgentOutput | dict[str, Any] | None,
    options_output: AgentOutput | dict[str, Any] | None,
    risk_output: AgentOutput | dict[str, Any] | None,
    technical_output: AgentOutput | dict[str, Any] | None = None,
    positioning_output: AgentOutput | dict[str, Any] | None = None,
    news_output: AgentOutput | dict[str, Any] | None = None,
    market_odds_output: AgentOutput | dict[str, Any] | None = None,
    created_at: datetime | None = None,
) -> AgentOutput:
    """Coordinate already-computed pseudo-agent outputs into one read-only AgentOutput."""

    created_at = created_at or datetime.now(timezone.utc)
    if not isinstance(snapshot, dict):
        return AgentOutput(
            version=_VERSION,
            agent_name=_AGENT_NAME,
            module=_MODULE,
            snapshot_id="unknown",
            input_snapshot_ids={},
            bias=AgentBias.UNAVAILABLE,
            confidence=0.0,
            key_findings=[],
            risk_points=["Coordinator 输入必须是已加载的快照字典。"],
            watchlist=list(_WATCHLIST),
            invalid_conditions=["非字典输入被拒绝；文件/路径读取不在范围内。"],
            summary="Coordinator 输入不可用；未生成只读综合结论。",
            source_refs=[],
            status=AgentStatus.UNAVAILABLE,
            created_at=created_at,
            data_category=DataCategory.SYSTEM_INFERENCE,
        )

    snapshot_id = str(snapshot.get("snapshot_id") or "unknown")
    macro = _coerce_output(macro_output)
    options = _coerce_output(options_output)
    risk = _coerce_output(risk_output)
    technical = _coerce_output(technical_output)
    positioning = _coerce_output(positioning_output)
    news = _coerce_output(news_output)
    market_odds = _coerce_output(market_odds_output)
    prior_outputs = [output for output in (macro, options, risk, technical, positioning, news, market_odds) if output is not None]

    input_snapshot_ids = _input_snapshot_ids(snapshot, prior_outputs)
    source_refs = _source_refs(snapshot, prior_outputs)
    unavailable_modules = _unavailable_modules(snapshot)

    key_findings: list[str] = []
    risk_points: list[str] = []
    invalid_conditions: list[str] = []
    status = AgentStatus.SUCCESS

    status = _add_prior_notes("宏观", macro, key_findings, risk_points, invalid_conditions, status)
    status = _add_prior_notes("期权", options, key_findings, risk_points, invalid_conditions, status)
    status = _add_prior_notes("风险", risk, key_findings, risk_points, invalid_conditions, status)
    status = _add_prior_notes("技术面", technical, key_findings, risk_points, invalid_conditions, status)
    status = _add_prior_notes("持仓", positioning, key_findings, risk_points, invalid_conditions, status)
    status = _add_prior_notes("新闻", news, key_findings, risk_points, invalid_conditions, status)
    # Market odds is optional for backward compat -- only report if present
    if market_odds is not None:
        status = _add_prior_notes("市场赔率", market_odds, key_findings, risk_points, invalid_conditions, status)
    elif snapshot.get("market_odds"):
        risk_points.append("市场赔率数据存在于快照中但 agent 输出缺失；协调员观点不完整。")
        invalid_conditions.append("market_odds_output 缺失；快照有数据但无 agent 分析。")
        status = AgentStatus.PARTIAL if status is AgentStatus.SUCCESS else status

    # ── Market odds conflict check with macro/options direction ──────
    if market_odds is not None and market_odds.bias in _DIRECTIONAL_BIASES:
        if macro is not None and macro.bias in _DIRECTIONAL_BIASES and macro.bias != market_odds.bias:
            risk_points.append(
                f"宏观/市场赔率方向冲突：宏观 {macro.bias.value}，市场赔率 {market_odds.bias.value}。"
            )
            invalid_conditions.append(
                f"宏观/市场赔率偏向冲突 — {macro.bias.value} vs {market_odds.bias.value}；建议交叉验证。"
            )
        if options is not None and options.bias in _DIRECTIONAL_BIASES and options.bias != market_odds.bias:
            risk_points.append(
                f"期权/市场赔率方向冲突：期权 {options.bias.value}，市场赔率 {market_odds.bias.value}。"
            )

    bias = _combined_bias(macro, options, risk, risk_points)
    if macro is not None and options is not None:
        if macro.bias in _DIRECTIONAL_BIASES and options.bias in _DIRECTIONAL_BIASES and macro.bias != options.bias:
            status = AgentStatus.PARTIAL
            invalid_conditions.append(
                f"宏观/期权方向冲突：宏观 {macro.bias.value}，期权 {options.bias.value}。"
            )

    if unavailable_modules:
        status = AgentStatus.PARTIAL
        joined = ", ".join(unavailable_modules)
        risk_points.append(f"不可用模块限制协调员确信度：{joined}。")
        invalid_conditions.append(f"不可用模块在协调员输出中显式保留：{joined}。")
        if _contains_any(unavailable_modules, {"technical"}):
            risk_points.append("技术模块不可用；无法生成精确交易执行计划。")
        if _contains_any(unavailable_modules, {"news", "positioning"}):
            risk_points.append("新闻/持仓不可用；协调员确信度降低。")
        if _contains_any(unavailable_modules, {"market_odds"}):
            risk_points.append("市场赔率不可用；无 CME/Polymarket 概率交叉验证。")

    if not prior_outputs:
        status = AgentStatus.UNAVAILABLE
        bias = AgentBias.UNAVAILABLE
    elif all(_is_unavailable_prior(output) for output in prior_outputs):
        status = AgentStatus.UNAVAILABLE
        bias = AgentBias.UNAVAILABLE

    confidence = _confidence(prior_outputs, status, unavailable_modules, risk_points, invalid_conditions)
    confidence_kernel = compute_confidence_kernel(
        market_state=snapshot,
        evidence_items=_confidence_evidence_items(snapshot, prior_outputs),
        agent_outputs=prior_outputs,
    )
    if risk is not None:
        confidence = min(confidence, _risk_cap(risk))
        if risk.bias in {AgentBias.MIXED, AgentBias.NEUTRAL, AgentBias.UNAVAILABLE} and bias in _DIRECTIONAL_BIASES:
            risk_points.append(f"风险前置为 {risk.bias.value}；协调员方向调整为混合。")
            bias = AgentBias.MIXED
            status = AgentStatus.PARTIAL
            confidence = min(confidence, 0.55)

    if status is AgentStatus.UNAVAILABLE:
        key_findings = []
        confidence = 0.0
    elif not key_findings:
        key_findings.append("协调员收到前置输出但方向性发现不足。")

    return AgentOutput(
        version=_VERSION,
        agent_name=_AGENT_NAME,
        module=_MODULE,
        snapshot_id=snapshot_id,
        input_snapshot_ids=input_snapshot_ids,
        bias=bias,
        confidence=_clamp(confidence, 0.0, 1.0),
        key_findings=key_findings,
        risk_points=risk_points,
        watchlist=list(_WATCHLIST),
        invalid_conditions=invalid_conditions,
        summary=_summary(bias, status, _clamp(confidence, 0.0, 1.0)),
        source_refs=source_refs,
        status=status,
        created_at=created_at,
        data_category=DataCategory.SYSTEM_INFERENCE,
        input_payload={"confidence_kernel": confidence_kernel.model_dump(mode="json")},
    )


def _coerce_output(value: AgentOutput | dict[str, Any] | None) -> AgentOutput | None:
    if isinstance(value, AgentOutput):
        return value
    if isinstance(value, dict):
        normalized = dict(value)
        normalized["bias"] = _normalize_bias_value(normalized.get("bias"))
        try:
            return AgentOutput.model_validate(normalized)
        except ValidationError:
            return None
    return None


def _normalize_bias_value(value: Any) -> str:
    if isinstance(value, AgentBias):
        return value.value
    if isinstance(value, str):
        return _BIAS_ALIASES.get(value.strip().lower(), AgentBias.UNAVAILABLE).value
    return AgentBias.UNAVAILABLE.value


def _input_snapshot_ids(snapshot: dict[str, Any], outputs: list[AgentOutput]) -> dict[str, Any]:
    value = snapshot.get("input_snapshot_ids")
    ids = dict(value) if isinstance(value, dict) else {}
    snapshot_id = snapshot.get("snapshot_id")
    if snapshot_id is not None:
        ids.setdefault("analysis_snapshot", snapshot_id)
    for output in outputs:
        ids.update(dict(output.input_snapshot_ids))
        ids.setdefault(output.module, output.snapshot_id)
    return ids


def _source_refs(snapshot: dict[str, Any], outputs: list[AgentOutput]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    snapshot_refs = snapshot.get("source_refs")
    if isinstance(snapshot_refs, list):
        refs.extend(dict(item) for item in snapshot_refs if isinstance(item, dict))
    for output in outputs:
        refs.extend(dict(item) for item in output.source_refs if isinstance(item, dict))
    return _dedupe_refs(refs)


def _confidence_evidence_items(snapshot: dict[str, Any], outputs: list[AgentOutput]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for ref in _source_refs(snapshot, outputs):
        item = dict(ref)
        item.setdefault("source_type", item.get("source") or item.get("type") or "structured")
        item.setdefault("status", item.get("verification_status") or item.get("status") or "confirmed")
        items.append(item)
    return items


def _dedupe_refs(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ref in refs:
        key = json.dumps(ref, ensure_ascii=False, sort_keys=True, default=str)
        if key not in seen:
            seen.add(key)
            deduped.append(ref)
    return deduped


def _unavailable_modules(snapshot: dict[str, Any]) -> list[str]:
    candidates = []
    metadata = snapshot.get("metadata")
    if isinstance(metadata, dict):
        candidates.extend(_as_list(metadata.get("unavailable_modules")))
    candidates.extend(_as_list(snapshot.get("unavailable_modules")))
    modules: list[str] = []
    for item in candidates:
        text = str(item).strip()
        if text and text not in modules:
            modules.append(text)
    return modules


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _add_prior_notes(
    label: str,
    output: AgentOutput | None,
    key_findings: list[str],
    risk_points: list[str],
    invalid_conditions: list[str],
    status: AgentStatus,
) -> AgentStatus:
    if output is None:
        risk_points.append(f"{label} 前置 agent 输出缺失；协调员返回不完整视图。")
        invalid_conditions.append(f"{label.lower()}_output 缺失或无效；未生成结论。")
        return AgentStatus.PARTIAL if status is AgentStatus.SUCCESS else status

    key_findings.append(
        f"{label} 前置偏向为 {output.bias.value}，状态 {output.status.value}，确信度 {output.confidence:.2f}。"
    )
    _extend_prefixed(key_findings, f"{label} 前置发现：", output.key_findings[:3])
    _extend_prefixed(risk_points, f"{label} 前置风险：", output.risk_points[:3])
    _extend_prefixed(invalid_conditions, f"{label} 前置失效条件：", output.invalid_conditions[:3])
    if output.status is not AgentStatus.SUCCESS:
        risk_points.append(f"{label} 前置 agent 状态为 {output.status.value}；协调员观点为临时性。")
        return AgentStatus.PARTIAL
    return status


def _extend_prefixed(target: list[str], prefix: str, notes: list[str]) -> None:
    for note in notes:
        if note:
            target.append(prefix + str(note))


def _combined_bias(macro: AgentOutput | None, options: AgentOutput | None, risk: AgentOutput | None, risk_points: list[str]) -> AgentBias:
    if risk is not None and risk.bias in {AgentBias.MIXED, AgentBias.NEUTRAL, AgentBias.UNAVAILABLE}:
        return risk.bias
    if risk is not None and risk.bias in _DIRECTIONAL_BIASES:
        return risk.bias
    if macro is not None and options is not None:
        if macro.bias in _DIRECTIONAL_BIASES and options.bias in _DIRECTIONAL_BIASES and macro.bias != options.bias:
            risk_points.append(f"宏观/期权偏向冲突：宏观 {macro.bias.value}，期权 {options.bias.value}。")
            return AgentBias.MIXED
        if macro.bias == options.bias:
            return _directional_or_soft_bias(macro.bias)
        if AgentBias.UNAVAILABLE in {macro.bias, options.bias}:
            return _directional_or_soft_bias(options.bias if macro.bias is AgentBias.UNAVAILABLE else macro.bias)
        return AgentBias.MIXED
    for output in (macro, options):
        if output is not None:
            return _directional_or_soft_bias(output.bias)
    return AgentBias.UNAVAILABLE


def _directional_or_soft_bias(bias: AgentBias) -> AgentBias:
    if bias in _DIRECTIONAL_BIASES:
        return bias
    if bias is AgentBias.NEUTRAL:
        return AgentBias.NEUTRAL
    if bias is AgentBias.MIXED:
        return AgentBias.MIXED
    return AgentBias.UNAVAILABLE


def _is_unavailable_prior(output: AgentOutput) -> bool:
    return output.status in {AgentStatus.UNAVAILABLE, AgentStatus.FAILED} or output.bias is AgentBias.UNAVAILABLE


def _risk_cap(risk: AgentOutput) -> float:
    if risk.status is AgentStatus.UNAVAILABLE or risk.bias is AgentBias.UNAVAILABLE:
        return 0.25
    if risk.status is AgentStatus.PARTIAL or risk.bias in {AgentBias.MIXED, AgentBias.NEUTRAL}:
        return 0.55
    return min(0.85, risk.confidence + 0.10)


def _confidence(
    outputs: list[AgentOutput],
    status: AgentStatus,
    unavailable_modules: list[str],
    risk_points: list[str],
    invalid_conditions: list[str],
) -> float:
    if not outputs:
        return 0.0
    if all(_is_unavailable_prior(output) for output in outputs):
        return 0.0
    confidence = sum(output.confidence for output in outputs) / len(outputs)
    if len(outputs) < 5:
        confidence -= 0.10 * (5 - len(outputs))
    if status is AgentStatus.PARTIAL:
        confidence -= 0.10
    confidence -= min(0.07 * len(unavailable_modules), 0.21)
    confidence -= min(0.01 * (len(risk_points) + len(invalid_conditions)), 0.14)
    upper = 0.68 if status is AgentStatus.PARTIAL else 0.9
    if any("conflict" in note.lower() or "冲突" in note for note in risk_points + invalid_conditions):
        upper = min(upper, 0.55)
    return _clamp(confidence, 0.0, upper)


def _contains_any(values: list[str], needles: set[str]) -> bool:
    lowered = {value.lower() for value in values}
    return any(needle in lowered for needle in needles)


def _summary(bias: AgentBias, status: AgentStatus, confidence: float) -> str:
    if status is AgentStatus.UNAVAILABLE:
        return f"协调员只读视图不可用；确信度 {confidence:.2f}。"
    if status is AgentStatus.PARTIAL:
        return f"协调员只读视图为 {bias.value}（输入不完整）；确信度 {confidence:.2f}。"
    return f"协调员只读视图为 {bias.value}；确信度 {confidence:.2f}。"


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, round(value, 2)))
