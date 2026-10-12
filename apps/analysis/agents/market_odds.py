"""Market odds agent — read-only analysis of market-odds probabilities.

Consumes only the ``market_odds`` section of an already-loaded analysis
snapshot. No network calls, no DB reads, no file I/O, no LLM inference.

Returns a deterministic AgentOutput with bias derived from:
  - CME-implied price target probabilities
  - Aggregate signal across all market-odds events
  - Divergence/reliability scores as confidence modifiers

Placeholder sources (Polymarket, Bloomberg, internal model) are noted
as unavailable but do not block output generation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from apps.analysis.agents.schemas import AgentBias, AgentOutput, AgentStatus, DataCategory

_AGENT_NAME = "market_odds_agent"
_MODULE = "market_odds"
_VERSION = "1.0"


def analyze_market_odds(
    snapshot: dict[str, Any], *, created_at: datetime | None = None
) -> AgentOutput:
    """Analyze the market_odds section of an already-loaded analysis snapshot.

    The agent is purely deterministic and read-only:
      - Reads ``snapshot["market_odds"]``
      - Iterates over events to derive bias, confidence, risk points
      - Returns a structured AgentOutput

    Unavailable or partial market_odds does NOT crash — it returns
    an unavailable output with explicit invalid_conditions.
    """
    created_at = created_at or datetime.now(timezone.utc)
    if not isinstance(snapshot, dict):
        return _unavailable("Market odds input must be an already-loaded snapshot dictionary.", created_at)

    snapshot_id = str(snapshot.get("snapshot_id") or "unknown")
    input_snapshot_ids = _input_snapshot_ids(snapshot)
    source_refs = _market_odds_source_refs(snapshot)

    mo = snapshot.get("market_odds")

    # ── Not available at all ─────────────────────────────────────────
    if not isinstance(mo, dict) or mo.get("status") == "unavailable":
        reason = (
            "market_odds section is missing"
            if not isinstance(mo, dict)
            else f"market_odds status is {mo.get('status')!r}"
        )
        return AgentOutput(
            version=_VERSION,
            agent_name=_AGENT_NAME,
            module=_MODULE,
            snapshot_id=snapshot_id,
            input_snapshot_ids=input_snapshot_ids,
            bias=AgentBias.UNAVAILABLE,
            confidence=0.0,
            key_findings=[],
            risk_points=["市场赔率数据不可用。"],
            watchlist=_build_watchlist(mo),
            invalid_conditions=[reason],
            summary="市场赔率只读视图不可用；无 CME/Polymarket 概率数据。",
            source_refs=source_refs,
            status=AgentStatus.UNAVAILABLE,
            created_at=created_at,
            data_category=DataCategory.SYSTEM_INFERENCE,
        )

    # ── Parse events ────────────────────────────────────────────────
    events_raw = mo.get("events")
    events: list[dict[str, Any]] = events_raw if isinstance(events_raw, list) else []
    agg_signal = str(mo.get("aggregate_signal", "unavailable"))
    mo_status = str(mo.get("status", "unavailable"))

    key_findings: list[str] = []
    risk_points: list[str] = []
    invalid_conditions: list[str] = []
    status = AgentStatus.SUCCESS

    # ── Event-level analysis ────────────────────────────────────────
    available_events = [e for e in events if isinstance(e, dict) and e.get("status") == "available"]
    unavailable_events = [e for e in events if isinstance(e, dict) and e.get("status") != "available"]

    for event in available_events:
        event_id = event.get("event_id", "unknown")
        event_name = event.get("event_name", event_id)
        prob = event.get("final_probability")
        signal = event.get("signal_label", "unavailable")
        reliability = event.get("reliability_score", 0.0)
        divergence = event.get("divergence_score", 0.0)
        interpretation = event.get("interpretation", "")

        if prob is not None and isinstance(prob, (int, float)):
            key_findings.append(
                f"Market odds event '{event_name}': {prob:.0%} probability, "
                f"signal={signal}, reliability={reliability:.2f}, divergence={divergence:.2f}."
            )
            if prob > 0.6 and signal == "bullish":
                key_findings.append(f"Elevated bullish market probability for {event_name} — potential upside catalyst.")
            elif prob > 0.6 and signal == "bearish":
                risk_points.append(f"Elevated bearish market probability for {event_name} — potential downside risk.")
        else:
            invalid_conditions.append(f"Event '{event_id}' has no valid final_probability.")

        if reliability < 0.3:
            risk_points.append(f"Low reliability ({reliability:.2f}) for event '{event_name}' — treat with caution.")
        if divergence > 0.5:
            risk_points.append(f"High source divergence ({divergence:.2f}) for event '{event_name}' — conflicting signals.")

        if interpretation:
            key_findings.append(interpretation[:200])

    # ── Missing sources ─────────────────────────────────────────────
    missing_sources = _detect_missing_sources(events)
    if missing_sources:
        invalid_conditions.append(
            f"Unavailable probability sources: {', '.join(missing_sources)}."
        )
        risk_points.append(
            f"Market odds are based on CME only — {', '.join(missing_sources)} data missing, reducing reliability."
        )

    # ── Placeholder events noted ────────────────────────────────────
    for event in unavailable_events:
        event_name = event.get("event_name", event.get("event_id", "unknown"))
        invalid_conditions.append(
            f"Market odds event '{event_name}' is unavailable — source data not yet integrated."
        )

    # ── Aggregate bias determination ────────────────────────────────
    if not available_events:
        bias = AgentBias.UNAVAILABLE
        key_findings.append("No available market-odds events; all sources are unavailable or placeholder.")
    elif agg_signal == "bullish":
        bias = AgentBias.BULLISH
    elif agg_signal == "bearish":
        bias = AgentBias.BEARISH
    elif agg_signal == "neutral":
        bias = AgentBias.NEUTRAL
    else:
        bias = AgentBias.UNAVAILABLE

    # ── Confidence calculation ──────────────────────────────────────
    confidence = _calculate_confidence(events, mo_status, bias)

    # ── Partial status when sources are incomplete ──────────────────
    if mo_status == "partial":
        status = AgentStatus.PARTIAL
        risk_points.append("Market odds are partial — only CME-implied probabilities are available.")
    elif mo_status == "unavailable":
        status = AgentStatus.UNAVAILABLE

    if not key_findings:
        key_findings.append("Market odds module is available but no significant findings.")

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
        watchlist=_build_watchlist(mo),
        invalid_conditions=invalid_conditions,
        summary=_summary(bias, mo_status, _clamp(confidence, 0.0, 1.0)),
        source_refs=source_refs,
        status=status,
        created_at=created_at,
        data_category=DataCategory.SYSTEM_INFERENCE,
    )


# ── Helpers ────────────────────────────────────────────────────────────


def _input_snapshot_ids(snapshot: dict[str, Any]) -> dict[str, Any]:
    value = snapshot.get("input_snapshot_ids")
    ids = dict(value) if isinstance(value, dict) else {}
    snapshot_id = snapshot.get("snapshot_id")
    if snapshot_id is not None:
        ids.setdefault("analysis_snapshot", snapshot_id)
    return ids


def _market_odds_source_refs(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for candidate in (
        snapshot.get("source_refs"),
        snapshot.get("market_odds", {}).get("source_refs"),
    ):
        if isinstance(candidate, list):
            refs.extend(dict(item) for item in candidate if isinstance(item, dict))
    return refs


def _build_watchlist(mo: dict[str, Any] | None) -> list[str]:
    """Build watchlist from market odds events."""
    watchlist = [
        "CME-implied gold target probabilities",
        "Fed rate path odds (placeholder)",
        "Polymarket gold events (placeholder)",
    ]
    if isinstance(mo, dict):
        events_raw = mo.get("events")
        if isinstance(events_raw, list):
            for event in events_raw:
                if isinstance(event, dict) and event.get("event_id"):
                    watchlist.append(f"Market odds: {event['event_id']}")
    return watchlist


def _detect_missing_sources(events: list[dict[str, Any]]) -> list[str]:
    """Check which probability sources are entirely missing."""
    missing: set[str] = set()
    source_labels = {
        "polymarket": "Polymarket",
        "bloomberg": "Bloomberg",
        "internal_model": "Internal model",
    }
    for event in events:
        probs = event.get("probabilities")
        if isinstance(probs, dict):
            for key, label in source_labels.items():
                source = probs.get(key)
                if isinstance(source, dict) and source.get("probability") is None:
                    missing.add(label)
    return sorted(missing)


def _calculate_confidence(
    events: list[dict[str, Any]], mo_status: str, bias: AgentBias
) -> float:
    """Calculate agent confidence from market odds data quality."""
    if not events:
        return 0.0
    if bias is AgentBias.UNAVAILABLE:
        return 0.0

    available = [e for e in events if isinstance(e, dict) and e.get("status") == "available"]
    if not available:
        return 0.0

    # Base: average reliability of available events
    reliabilities = [
        e.get("reliability_score", 0.0) for e in available
        if isinstance(e.get("reliability_score"), (int, float))
    ]
    confidence = sum(reliabilities) / len(reliabilities) if reliabilities else 0.3

    # Penalty for missing sources
    missing = _detect_missing_sources(events)
    confidence -= 0.08 * len(missing)

    # Penalty for partial status
    if mo_status == "partial":
        confidence -= 0.10

    # Penalty for high divergence
    high_div_count = sum(
        1 for e in available
        if isinstance(e.get("divergence_score"), (int, float)) and float(e["divergence_score"]) > 0.5
    )
    confidence -= 0.05 * high_div_count

    # Cap: market odds is supplementary, not primary
    return _clamp(confidence, 0.0, 0.65)


def _unavailable(reason: str, created_at: datetime) -> AgentOutput:
    return AgentOutput(
        version=_VERSION,
        agent_name=_AGENT_NAME,
        module=_MODULE,
        snapshot_id="unknown",
        input_snapshot_ids={},
        bias=AgentBias.UNAVAILABLE,
        confidence=0.0,
        key_findings=[],
        risk_points=[reason],
        watchlist=[],
        invalid_conditions=[reason],
        summary=f"Market odds unavailable: {reason}",
        source_refs=[],
        status=AgentStatus.UNAVAILABLE,
        created_at=created_at,
        data_category=DataCategory.SYSTEM_INFERENCE,
    )


def _summary(bias: AgentBias, mo_status: str, confidence: float) -> str:
    sig = f"市场赔率只读视图 {bias.value}"
    if mo_status == "partial":
        sig += " (partial)"
    sig += f"; confidence {confidence:.2f}."
    return sig


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, round(value, 2)))
