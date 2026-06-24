from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError

from apps.analysis.agents.schemas import AgentBias, AgentOutput, AgentStatus, DataCategory

_AGENT_NAME = "risk_agent"
_MODULE = "risk"
_VERSION = "1.0"
_WATCHLIST = [
    "macro/options bias alignment",
    "unavailable modules",
    "prior agent status",
    "invalid conditions",
    "risk invalidation triggers",
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


def analyze_risk(
    snapshot: dict[str, Any],
    *,
    macro_output: AgentOutput | dict[str, Any] | None,
    options_output: AgentOutput | dict[str, Any] | None,
    created_at: datetime | None = None,
) -> AgentOutput:
    """Combine already-loaded snapshot metadata and prior AgentOutput objects into read-only risk notes."""

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
            risk_points=["风险输入必须是已加载的快照字典。"],
            watchlist=list(_WATCHLIST),
            invalid_conditions=["非字典输入被拒绝；文件/路径读取不在范围内。"],
            summary="风险输入不可用；未生成只读风险结论。",
            source_refs=[],
            status=AgentStatus.UNAVAILABLE,
            created_at=created_at,
            data_category=DataCategory.SYSTEM_INFERENCE,
        )

    snapshot_id = str(snapshot.get("snapshot_id") or "unknown")
    macro = _coerce_output(macro_output)
    options = _coerce_output(options_output)

    input_snapshot_ids = _input_snapshot_ids(snapshot, macro, options)
    source_refs = _source_refs(snapshot, macro, options)
    key_findings: list[str] = []
    risk_points: list[str] = []
    invalid_conditions: list[str] = []
    status = AgentStatus.SUCCESS

    if macro is None:
        status = AgentStatus.PARTIAL
        risk_points.append("Macro prior agent output is missing; macro risk cannot be cross-checked.")
        invalid_conditions.append("macro_output missing or invalid; no macro conclusion was invented.")
    else:
        key_findings.append(
            f"Macro prior bias is {macro.bias.value} with status {macro.status.value} and confidence {macro.confidence:.2f}."
        )
        if macro.status is not AgentStatus.SUCCESS:
            status = AgentStatus.PARTIAL
            risk_points.append(f"Macro prior agent status is {macro.status.value}; risk view is provisional.")
        _extend_prefixed(risk_points, "Macro prior risk: ", macro.risk_points)
        _extend_prefixed(invalid_conditions, "Macro prior invalid condition: ", macro.invalid_conditions)

    if options is None:
        status = AgentStatus.PARTIAL
        risk_points.append("Options prior agent output is missing; options risk cannot be cross-checked.")
        invalid_conditions.append("options_output missing or invalid; no options conclusion was invented.")
    else:
        key_findings.append(
            f"Options prior bias is {options.bias.value} with status {options.status.value} and confidence {options.confidence:.2f}."
        )
        if options.status is not AgentStatus.SUCCESS:
            status = AgentStatus.PARTIAL
            risk_points.append(f"Options prior agent status is {options.status.value}; risk view is provisional.")
        _extend_prefixed(risk_points, "Options prior risk: ", options.risk_points)
        _extend_prefixed(invalid_conditions, "Options prior invalid condition: ", options.invalid_conditions)

    unavailable_modules = _unavailable_modules(snapshot)
    if unavailable_modules:
        status = AgentStatus.PARTIAL
        joined = ", ".join(unavailable_modules)
        risk_points.append(f"Snapshot unavailable modules limit risk validation: {joined}.")
        invalid_conditions.append(f"Unavailable modules must stay explicit in risk view: {joined}.")

    both_priors_unavailable = _is_unavailable_prior(macro) and _is_unavailable_prior(options)
    bias = _combined_bias(macro, options, risk_points)
    if macro is None and options is None:
        bias = AgentBias.UNAVAILABLE
        status = AgentStatus.UNAVAILABLE if not unavailable_modules else AgentStatus.PARTIAL
    elif both_priors_unavailable:
        bias = AgentBias.UNAVAILABLE
        status = AgentStatus.UNAVAILABLE

    confidence = _confidence(macro, options, status, unavailable_modules, risk_points, invalid_conditions)
    if not key_findings and bias is AgentBias.UNAVAILABLE:
        key_findings = []
    elif not key_findings:
        key_findings.append("Risk view has insufficient prior agent findings for directional conviction.")

    return AgentOutput(
        version=_VERSION,
        agent_name=_AGENT_NAME,
        module=_MODULE,
        snapshot_id=snapshot_id,
        input_snapshot_ids=input_snapshot_ids,
        bias=bias,
        confidence=confidence,
        key_findings=key_findings,
        risk_points=risk_points,
        watchlist=list(_WATCHLIST),
        invalid_conditions=invalid_conditions,
        summary=_summary(bias, status, confidence),
        source_refs=source_refs,
        status=status,
        created_at=created_at,
        data_category=DataCategory.SYSTEM_INFERENCE,
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


def _is_unavailable_prior(output: AgentOutput | None) -> bool:
    if output is None:
        return True
    return output.status in {AgentStatus.UNAVAILABLE, AgentStatus.FAILED} or output.bias is AgentBias.UNAVAILABLE


def _input_snapshot_ids(
    snapshot: dict[str, Any], macro: AgentOutput | None, options: AgentOutput | None
) -> dict[str, Any]:
    value = snapshot.get("input_snapshot_ids")
    ids = dict(value) if isinstance(value, dict) else {}
    snapshot_id = snapshot.get("snapshot_id")
    if snapshot_id is not None:
        ids.setdefault("analysis_snapshot", snapshot_id)
    for output in (macro, options):
        if output is None:
            continue
        ids.update(dict(output.input_snapshot_ids))
        ids.setdefault(output.module, output.snapshot_id)
    return ids


def _source_refs(snapshot: dict[str, Any], macro: AgentOutput | None, options: AgentOutput | None) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    snapshot_refs = snapshot.get("source_refs")
    if isinstance(snapshot_refs, list):
        refs.extend(dict(item) for item in snapshot_refs if isinstance(item, dict))
    for output in (macro, options):
        if output is None:
            continue
        refs.extend(dict(item) for item in output.source_refs if isinstance(item, dict))
    return refs


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


def _extend_prefixed(target: list[str], prefix: str, notes: list[str]) -> None:
    for note in notes:
        if note:
            target.append(prefix + str(note))


def _combined_bias(macro: AgentOutput | None, options: AgentOutput | None, risk_points: list[str]) -> AgentBias:
    if macro is None and options is None:
        return AgentBias.UNAVAILABLE
    if macro is None:
        return _risk_aware_bias(options.bias if options is not None else AgentBias.UNAVAILABLE)
    if options is None:
        return _risk_aware_bias(macro.bias)
    if macro.bias in _DIRECTIONAL_BIASES and options.bias in _DIRECTIONAL_BIASES and macro.bias != options.bias:
        risk_points.append(
            f"Macro/options bias conflict: macro is {macro.bias.value} while options is {options.bias.value}."
        )
        return AgentBias.MIXED
    if macro.bias == options.bias:
        return _risk_aware_bias(macro.bias)
    if AgentBias.UNAVAILABLE in {macro.bias, options.bias}:
        return _risk_aware_bias(options.bias if macro.bias is AgentBias.UNAVAILABLE else macro.bias)
    return AgentBias.MIXED


def _risk_aware_bias(bias: AgentBias) -> AgentBias:
    if bias in _DIRECTIONAL_BIASES:
        return bias
    if bias is AgentBias.NEUTRAL:
        return AgentBias.NEUTRAL
    if bias is AgentBias.MIXED:
        return AgentBias.MIXED
    return AgentBias.UNAVAILABLE


def _confidence(
    macro: AgentOutput | None,
    options: AgentOutput | None,
    status: AgentStatus,
    unavailable_modules: list[str],
    risk_points: list[str],
    invalid_conditions: list[str],
) -> float:
    available = [output for output in (macro, options) if output is not None]
    if not available:
        return 0.12 if unavailable_modules else 0.0
    if all(_is_unavailable_prior(output) for output in (macro, options)):
        return 0.0
    confidence = sum(output.confidence for output in available) / len(available)
    if len(available) < 2:
        confidence -= 0.25
    if status is AgentStatus.PARTIAL:
        confidence -= 0.10
    confidence -= min(0.06 * len(unavailable_modules), 0.18)
    confidence -= min(0.01 * (len(risk_points) + len(invalid_conditions)), 0.12)
    upper = 0.78 if status is AgentStatus.PARTIAL else 0.9
    return _clamp(confidence, 0.0, upper)


def _summary(bias: AgentBias, status: AgentStatus, confidence: float) -> str:
    if status is AgentStatus.UNAVAILABLE:
        return f"风险只读视图不可用；确信度 {confidence:.2f}。"
    if status is AgentStatus.PARTIAL:
        return f"风险只读视图 {bias.value}（输入不完整）；确信度 {confidence:.2f}。"
    return f"风险只读视图 {bias.value}；确信度 {confidence:.2f}。"


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, round(value, 2)))
