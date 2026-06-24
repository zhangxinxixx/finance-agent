from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from apps.analysis.agents.schemas import AgentBias, AgentOutput, AgentStatus
from apps.analysis.strategy.schemas import StrategyCardOutput

_VERSION = "1.0"
_FORBIDDEN_EXECUTION_WORDS = re.compile(
    r"\b(buy|sell|enter|stop.loss|take.profit|target\s*\d|tp\d|sl\d|long\s*entry|short\s*entry)\b",
    re.IGNORECASE,
)


def build_strategy_card(
    *,
    snapshot: dict[str, Any],
    coordinator_output: AgentOutput,
    risk_output: AgentOutput | None = None,
    created_at: datetime | None = None,
) -> StrategyCardOutput:
    """Build a research-only strategy card from coordinator (and optional risk) outputs.

    This is a deterministic, read-only post-processor. It does not call an LLM,
    does not hit the network, and does not read raw/parsed data files.
    """

    created_at = created_at or datetime.now(timezone.utc)

    # ── primary research view ──────────────────────────────────────────
    bias = coordinator_output.bias
    confidence = coordinator_output.confidence

    # ── merge risk_points / invalid_conditions ─────────────────────────
    risk_points = list(coordinator_output.risk_points)
    invalid_conditions = list(coordinator_output.invalid_conditions)

    if risk_output is not None:
        risk_points.extend(risk_output.risk_points)
        invalid_conditions.extend(risk_output.invalid_conditions)

    # ── key levels *only* from existing output text — no price invention
    key_levels_from_options = _extract_option_levels(coordinator_output)
    # sanitize extracted levels too — no executable language
    key_levels_from_options = [_strip_execution(level) for level in key_levels_from_options]

    # ── mark incomplete when technical/news/positioning unavailable ───
    unavailable_modules = _unavailable_modules(snapshot)
    _append_incomplete_markers(
        unavailable_modules, risk_points, invalid_conditions
    )

    # ── scenario summary ───────────────────────────────────────────────
    scenario_summary = _scenario_summary(
        bias,
        confidence,
        coordinator_output.status,
        risk_points,
        invalid_conditions,
    )

    # ── watchlist ──────────────────────────────────────────────────────
    watchlist = list(coordinator_output.watchlist)
    if risk_output is not None:
        for item in risk_output.watchlist:
            if item not in watchlist:
                watchlist.append(item)

    # ── source_refs (snapshot + coordinator + risk) ────────────────────
    source_refs = _merge_source_refs(snapshot, coordinator_output, risk_output)

    # ── evidence_refs (coordinator + risk) ─────────────────────────────
    evidence_refs = list(coordinator_output.evidence_refs)
    if risk_output is not None:
        evidence_refs.extend(risk_output.evidence_refs)

    # ── data_quality (coordinator + risk) ──────────────────────────────
    data_quality = list(coordinator_output.data_quality)
    if risk_output is not None:
        for tag in risk_output.data_quality:
            if tag not in data_quality:
                data_quality.append(tag)

    # ── data_category_summary from source_refs ────────────────────────
    data_category_summary = _compute_data_category_summary(source_refs)

    # ── input_snapshot_ids ─────────────────────────────────────────────
    input_snapshot_ids = _lineage_ids(snapshot, coordinator_output, risk_output)

    # ── asset / trade_date / run_id ────────────────────────────────────
    asset = _extract_symbol(snapshot)
    trade_date = _extract_as_of(snapshot, created_at)
    run_id = str(snapshot.get("run_id") or snapshot.get("snapshot_id") or "unknown")
    market_regime = _extract_market_regime(snapshot)

    # ── final sanitisation: never emit executable trade instructions ───
    risk_points = [_strip_execution(text) for text in risk_points]
    invalid_conditions = [_strip_execution(text) for text in invalid_conditions]
    scenario_summary = _strip_execution(scenario_summary)

    return StrategyCardOutput(
        version=_VERSION,
        asset=asset,
        trade_date=trade_date,
        run_id=run_id,
        bias=bias,
        confidence=confidence,
        scenario_summary=scenario_summary,
        key_levels_from_options=key_levels_from_options,
        risk_points=risk_points,
        invalid_conditions=invalid_conditions,
        watchlist=watchlist,
        source_refs=source_refs,
        input_snapshot_ids=input_snapshot_ids,
        created_at=created_at,
        is_trade_instruction=False,
        market_regime=market_regime,
        evidence_refs=evidence_refs,
        data_quality=data_quality,
        data_category_summary=data_category_summary,
    )


# ═══════════════════════════════════════════════════════════════════════
# helpers
# ═══════════════════════════════════════════════════════════════════════


def _extract_option_levels(coordinator: AgentOutput) -> list[str]:
    """Pull option-level snippets from coordinator text — never invent prices."""
    levels: list[str] = []
    candidates = coordinator.key_findings + [coordinator.summary]
    for line in candidates:
        lowered = line.lower()
        if "options prior finding:" in lowered:
            text = line.split(":", 1)[-1].strip()
            if text and text not in levels:
                levels.append(text)
    return levels


def _unavailable_modules(snapshot: dict[str, Any]) -> list[str]:
    modules: list[str] = []
    for key in ("metadata",):
        metadata = snapshot.get(key)
        if isinstance(metadata, dict):
            for item in _as_list(metadata.get("unavailable_modules")):
                text = str(item).strip()
                if text and text not in modules:
                    modules.append(text)
    for item in _as_list(snapshot.get("unavailable_modules")):
        text = str(item).strip()
        if text and text not in modules:
            modules.append(text)
    return modules


def _append_incomplete_markers(
    unavailable: list[str],
    risk_points: list[str],
    invalid_conditions: list[str],
) -> None:
    if not unavailable:
        return
    joined = ", ".join(unavailable)
    has_technical = any("technical" in m.lower() for m in unavailable)
    has_news_positioning = any(
        tag in m.lower() for m in unavailable
        for tag in ("news", "positioning")
    )

    risk_points.append(
        f"Strategy card is incomplete: {joined} unavailable. "
        "Directional view is provisional; no precise levels or timing should be inferred."
    )
    invalid_conditions.append(
        f"Strategy card validity is conditional on resolution of: {joined}."
    )
    if has_technical:
        risk_points.append(
            "Without technical data, no precise execution plan can be derived "
            "from this research card."
        )
    if has_news_positioning:
        risk_points.append(
            "Missing news/positioning inputs reduce conviction; "
            "monitor upcoming events before acting on directional view."
        )


def _scenario_summary(
    bias: AgentBias,
    confidence: float,
    status: AgentStatus,
    risk_points: list[str],
    invalid_conditions: list[str],
) -> str:
    if bias is AgentBias.UNAVAILABLE or status is AgentStatus.UNAVAILABLE:
        return (
            f"Research view is unavailable (confidence {confidence:.2f}). "
            "No directional conclusion can be drawn from current inputs."
        )

    base = (
        f"Coordinator research view is {bias.value} "
        f"(confidence {confidence:.2f}, status {status.value})."
    )

    if status is AgentStatus.PARTIAL:
        base += " View is partial due to missing or conflicting inputs."

    # append the first risk point as context if relevant
    for rp in risk_points:
        if "unavailable" in rp.lower() or "missing" in rp.lower():
            base += f" {rp}"
            break

    # append first invalidation condition
    for ic in invalid_conditions:
        if "conflict" in ic.lower() or "invalid" in ic.lower():
            base += f" {ic}"
            break

    return base


def _merge_source_refs(
    snapshot: dict[str, Any],
    coordinator: AgentOutput,
    risk: AgentOutput | None,
) -> list[dict[str, Any]]:
    import json as _json

    refs: list[dict[str, Any]] = []
    snapshot_refs = snapshot.get("source_refs")
    if isinstance(snapshot_refs, list):
        refs.extend(dict(item) for item in snapshot_refs if isinstance(item, dict))
    refs.extend(dict(item) for item in coordinator.source_refs if isinstance(item, dict))
    if risk is not None:
        refs.extend(dict(item) for item in risk.source_refs if isinstance(item, dict))

    # infer data_category for each ref
    for ref in refs:
        if "data_category" in ref:
            continue
        ref["data_category"] = _infer_data_category(ref)

    # deduplicate
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ref in refs:
        key = _json.dumps(ref, ensure_ascii=False, sort_keys=True, default=str)
        if key not in seen:
            seen.add(key)
            deduped.append(ref)
    return deduped


def _infer_data_category(ref: dict[str, Any]) -> str:
    """Infer data_category from source name patterns."""
    source = str(ref.get("source") or ref.get("name") or "").lower()
    if any(prefix in source for prefix in ("jin10", "jin10_", "llm", "gpt", "claude")):
        return "external_opinion"
    if any(prefix in source for prefix in ("cme", "fred", "cftc", "cot")):
        return "confirmed_data"
    return "system_inference"


def _compute_data_category_summary(source_refs: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute a summary of data_category counts from source_refs."""
    counts: dict[str, int] = {}
    for ref in source_refs:
        cat = str(ref.get("data_category") or "unknown")
        counts[cat] = counts.get(cat, 0) + 1
    total = sum(counts.values())
    return {
        "confirmed_data": counts.get("confirmed_data", 0),
        "external_opinion": counts.get("external_opinion", 0),
        "system_inference": counts.get("system_inference", 0),
        "total": total,
    }


def _lineage_ids(
    snapshot: dict[str, Any],
    coordinator: AgentOutput,
    risk: AgentOutput | None,
) -> dict[str, Any]:
    ids: dict[str, Any] = {}

    # inherit from snapshot
    snapshot_ids = snapshot.get("input_snapshot_ids")
    if isinstance(snapshot_ids, dict):
        ids.update(snapshot_ids)

    # ensure baseline keys
    snapshot_id = snapshot.get("snapshot_id")
    if snapshot_id is not None:
        ids["analysis_snapshot"] = str(snapshot_id)

    # merge coordinator lineage
    ids.update(dict(coordinator.input_snapshot_ids))
    ids["coordinator"] = coordinator.snapshot_id
    # ensure snapshot's own snapshot_id always wins as analysis_snapshot
    if snapshot_id is not None:
        ids["analysis_snapshot"] = str(snapshot_id)

    # merge risk lineage
    if risk is not None:
        ids.update(dict(risk.input_snapshot_ids))
        ids.setdefault("risk", risk.snapshot_id)

    return ids


def _extract_symbol(snapshot: dict[str, Any]) -> str:
    metadata = snapshot.get("metadata")
    if isinstance(metadata, dict):
        symbol = metadata.get("symbol")
        if isinstance(symbol, str) and symbol.strip():
            return symbol.strip()
    return "XAUUSD"


def _extract_as_of(snapshot: dict[str, Any], fallback: datetime) -> str:
    # Prefer the explicit trade_date on the snapshot (source of truth)
    trade_date = snapshot.get("trade_date")
    if isinstance(trade_date, str) and trade_date.strip():
        return trade_date.strip()
    # Fallback: metadata.as_of (legacy path)
    as_of = None
    metadata = snapshot.get("metadata")
    if isinstance(metadata, dict):
        as_of = metadata.get("as_of")
        if isinstance(as_of, str) and as_of.strip():
            return as_of.strip()
    return fallback.strftime("%Y-%m-%d")


def _extract_market_regime(snapshot: dict[str, Any]) -> str:
    for key in ("market_regime", "market_phase"):
        value = snapshot.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    metadata = snapshot.get("metadata")
    if isinstance(metadata, dict):
        for key in ("market_regime", "market_phase"):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

    macro = snapshot.get("macro")
    if isinstance(macro, dict):
        for key in ("market_regime", "market_phase"):
            value = macro.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        if macro.get("status") == "available":
            data = macro.get("data")
            if isinstance(data, dict):
                indicators = data.get("indicators")
                if isinstance(indicators, dict):
                    from apps.analysis.macro.regime import classify_macro_regime

                    phase = classify_macro_regime(indicators).get("market_phase")
                    if isinstance(phase, str) and phase.strip():
                        return phase.strip()

    return "unavailable"


def _strip_execution(text: str) -> str:
    """Replace any executable trading language with a research-only stance."""
    return _FORBIDDEN_EXECUTION_WORDS.sub("[research view only — not executable]", text)


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []
