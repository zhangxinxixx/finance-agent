from __future__ import annotations

from typing import Any

from apps.analysis.agents.schemas import AgentBias
from apps.analysis.confidence import ConfidenceKernel
from apps.decision.schemas import FeasibilityLabel


def evaluate_feasibility(
    *,
    confidence_kernel: ConfidenceKernel,
    bias: AgentBias,
    market_state: dict[str, Any],
    evidence_items: list[dict[str, Any]],
) -> tuple[FeasibilityLabel, float, list[str]]:
    reasons: list[str] = []
    score = confidence_kernel.overall
    caps = set(confidence_kernel.caps)

    if bias is AgentBias.UNAVAILABLE or confidence_kernel.overall < 0.35:
        reasons.append("confidence too low or no directional conclusion.")
        return "not_actionable", _clamp(min(score, 0.30)), reasons

    if "technical_unavailable" in caps:
        reasons.append("technical data unavailable; decision remains research-only.")
    if "macro_options_conflict" in caps or "cross_source_conflict" in caps:
        reasons.append("cross-source conflict prevents high-conviction research.")
    if "stale_inputs" in caps:
        reasons.append("stale inputs require refresh before stronger feasibility.")

    missing = _unavailable_modules(market_state)
    if missing:
        reasons.append(f"missing modules: {', '.join(missing)}.")
        score = min(score, 0.62)

    if reasons:
        return "research_only", _clamp(min(score, 0.65)), reasons

    if confidence_kernel.overall >= 0.80 and len(evidence_items) >= 2:
        reasons.append("confirmed evidence and confidence support high-conviction research.")
        return "high_conviction_research", _clamp(score), reasons

    reasons.append("usable research view with explicit confirmations still required.")
    return "watchlist_candidate", _clamp(min(score, 0.78)), reasons


def _unavailable_modules(market_state: dict[str, Any]) -> list[str]:
    modules: list[str] = []
    for key in ("macro", "options", "technical"):
        section = market_state.get(key)
        if isinstance(section, dict) and section.get("status") == "unavailable":
            modules.append(key)
    metadata = market_state.get("metadata")
    if isinstance(metadata, dict):
        modules.extend(str(item) for item in metadata.get("unavailable_modules") or [])
    return sorted(set(item for item in modules if item))


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, round(float(value), 2)))
