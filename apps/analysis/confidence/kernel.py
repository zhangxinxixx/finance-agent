from __future__ import annotations

from typing import Any

from apps.analysis.agents.schemas import AgentBias, AgentOutput, AgentStatus
from apps.analysis.confidence.schemas import ConfidenceKernel

_DIRECTIONAL = {AgentBias.BULLISH.value, AgentBias.BEARISH.value}
_CRITICAL_MODULES = ("macro", "options", "technical")


def compute_confidence_kernel(
    *,
    market_state: dict[str, Any],
    evidence_items: list[dict[str, Any]],
    agent_outputs: list[AgentOutput | dict[str, Any]] | None = None,
) -> ConfidenceKernel:
    """Compute a deterministic confidence breakdown from market state and evidence."""

    state = dict(market_state) if isinstance(market_state, dict) else {}
    evidence = [dict(item) for item in evidence_items if isinstance(item, dict)]
    outputs = [_coerce_output(item) for item in agent_outputs or []]
    outputs = [item for item in outputs if item is not None]

    caps: list[str] = []
    reasons: list[str] = []

    data_confidence = _data_confidence(state, caps, reasons)
    freshness_confidence = _freshness_confidence(state, evidence, outputs, caps, reasons)
    evidence_confidence = _evidence_confidence(evidence, outputs, reasons)
    cross_source_confidence = _cross_source_confidence(evidence, outputs, caps, reasons)
    conflict_penalty = round(max(0.0, 1.0 - cross_source_confidence), 2)
    model_dependency_penalty = _model_dependency_penalty(evidence, outputs, reasons)
    regime_confidence = _regime_confidence(state)

    components = [data_confidence, freshness_confidence, evidence_confidence, cross_source_confidence]
    if regime_confidence is not None:
        components.append(regime_confidence)
    overall = sum(components) / len(components)
    overall -= conflict_penalty * 0.20
    overall -= model_dependency_penalty * 0.15
    overall = _apply_caps(overall, caps)

    return ConfidenceKernel(
        data_confidence=_clamp(data_confidence),
        freshness_confidence=_clamp(freshness_confidence),
        evidence_confidence=_clamp(evidence_confidence),
        cross_source_confidence=_clamp(cross_source_confidence),
        conflict_penalty=_clamp(conflict_penalty),
        model_dependency_penalty=_clamp(model_dependency_penalty),
        regime_confidence=_clamp(regime_confidence) if regime_confidence is not None else None,
        overall=_clamp(overall),
        caps=caps,
        reasons=reasons,
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


def _data_confidence(state: dict[str, Any], caps: list[str], reasons: list[str]) -> float:
    missing: list[str] = []
    for module in _CRITICAL_MODULES:
        section = state.get(module)
        if not isinstance(section, dict) or str(section.get("status") or "unavailable") != "available":
            missing.append(module)
    unavailable = _unavailable_modules(state)
    for module in unavailable:
        if module not in missing:
            missing.append(module)

    score = 1.0 - min(0.16 * len(missing), 0.55)
    if "technical" in missing:
        _add_unique(caps, "technical_unavailable")
        reasons.append("technical data unavailable caps high-confidence research.")
    for module in missing:
        reasons.append(f"{module} data unavailable or incomplete.")
    return score


def _freshness_confidence(
    state: dict[str, Any],
    evidence: list[dict[str, Any]],
    outputs: list[AgentOutput],
    caps: list[str],
    reasons: list[str],
) -> float:
    stale_count = 0
    tags = [str(item).lower() for item in _as_list(state.get("data_quality"))]
    stale_count += sum(1 for item in tags if "stale" in item)
    stale_count += sum(1 for item in evidence if str(item.get("freshness") or "").lower() == "stale")
    stale_count += sum(1 for output in outputs for tag in output.data_quality if "stale" in str(tag).lower())
    if stale_count:
        _add_unique(caps, "stale_inputs")
        reasons.append("stale inputs lower freshness confidence.")
    return 1.0 - min(0.18 * stale_count, 0.55)


def _evidence_confidence(evidence: list[dict[str, Any]], outputs: list[AgentOutput], reasons: list[str]) -> float:
    scores: list[float] = []
    for item in evidence:
        source_type = str(item.get("source_type") or item.get("source") or "").lower()
        status = str(item.get("status") or item.get("verification_status") or "").lower()
        if "official" in source_type or status in {"official_confirmed", "confirmed"}:
            scores.append(0.92)
        elif "structured" in source_type or "multi" in status:
            scores.append(0.78)
        elif "candidate" in source_type or "single" in status:
            scores.append(0.58)
        else:
            scores.append(0.45)
    scores.extend(output.confidence for output in outputs if output.status is AgentStatus.SUCCESS)
    if not scores:
        reasons.append("no evidence items or agent outputs provided.")
        return 0.0
    return sum(scores) / len(scores)


def _cross_source_confidence(
    evidence: list[dict[str, Any]],
    outputs: list[AgentOutput],
    caps: list[str],
    reasons: list[str],
) -> float:
    directions_by_module: dict[str, str] = {}
    directions: list[str] = []
    for output in outputs:
        bias = output.bias.value
        if bias in _DIRECTIONAL:
            directions.append(bias)
            directions_by_module[output.module] = bias
    for item in evidence:
        bias = _normalize_bias(item.get("bias") or item.get("direction"))
        if bias in _DIRECTIONAL:
            directions.append(bias)

    if (
        directions_by_module.get("macro") in _DIRECTIONAL
        and directions_by_module.get("options") in _DIRECTIONAL
        and directions_by_module["macro"] != directions_by_module["options"]
    ):
        _add_unique(caps, "macro_options_conflict")
        reasons.append("macro/options directional conflict caps confidence.")
        return 0.50

    unique = set(directions)
    if len(unique) > 1:
        _add_unique(caps, "cross_source_conflict")
        reasons.append("cross-source directional conflict lowers confidence.")
        return 0.58
    if not directions:
        return 0.50
    return 0.88 if len(directions) >= 2 else 0.72


def _model_dependency_penalty(evidence: list[dict[str, Any]], outputs: list[AgentOutput], reasons: list[str]) -> float:
    dependent = 0
    dependent += sum(
        1
        for item in evidence
        if str(item.get("source_type") or "").lower() in {"llm", "model", "external_opinion", "inference"}
    )
    dependent += sum(1 for output in outputs if output.llm_model or output.llm_provider)
    if not dependent:
        return 0.0
    reasons.append("model-dependent evidence reduces confidence until externally confirmed.")
    return min(0.12 * dependent, 0.36)


def _regime_confidence(state: dict[str, Any]) -> float | None:
    value = state.get("regime_confidence")
    if isinstance(value, int | float):
        return float(value)
    regime = state.get("regime")
    if isinstance(regime, dict) and isinstance(regime.get("confidence"), int | float):
        return float(regime["confidence"])
    return None


def _apply_caps(value: float, caps: list[str]) -> float:
    capped = value
    if "macro_options_conflict" in caps:
        capped = min(capped, 0.55)
    if "cross_source_conflict" in caps:
        capped = min(capped, 0.62)
    if "technical_unavailable" in caps:
        capped = min(capped, 0.65)
    if "stale_inputs" in caps:
        capped = min(capped, 0.70)
    return capped


def _unavailable_modules(state: dict[str, Any]) -> list[str]:
    modules: list[str] = []
    metadata = state.get("metadata")
    if isinstance(metadata, dict):
        modules.extend(str(item).lower() for item in _as_list(metadata.get("unavailable_modules")))
    modules.extend(str(item).lower() for item in _as_list(state.get("unavailable_modules")))
    return [item for item in modules if item]


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _normalize_bias(value: Any) -> str:
    if isinstance(value, AgentBias):
        return value.value
    text = str(value or "").strip().lower()
    if text in {"supportive", "constructive", "upside", "bullish"}:
        return AgentBias.BULLISH.value
    if text in {"pressure", "resistance", "downside", "bearish"}:
        return AgentBias.BEARISH.value
    return text


def _add_unique(target: list[str], value: str) -> None:
    if value not in target:
        target.append(value)


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, round(float(value), 2)))
