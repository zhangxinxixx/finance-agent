"""P4-07: Market odds snapshot schema and builder.

Defines the market-odds feature layer as a pure filesystem JSON schema
with no DB tables, no network collectors, and no fake probabilities.

Data sources (MVP):
  - CME-first: probability estimates derived from existing options delta /
    forward price positioning (no external API calls).
  - Polymarket: placeholder (unavailable until collector exists).
  - Bloomberg/reference: placeholder (unavailable, source_tier=reference).
  - Internal model: placeholder (unavailable, deferred to P4-08 agent).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ── Core schema types ────────────────────────────────────────────────────


@dataclass(frozen=True)
class ProbabilitySource:
    """A single probability estimate from one data source."""

    source: str  # "cme_options" | "polymarket" | "bloomberg" | "internal_model"
    probability: float | None  # 0.0 ~ 1.0 or None if unavailable
    confidence: float | None  # quality of this estimate
    last_updated: str | None
    source_ref: str | None  # URL, snapshot_id, or provenance ref
    notes: str = ""


@dataclass(frozen=True)
class MarketOddsEvent:
    """One market-odds event (e.g., 'Gold > 3000 by Jun 2026')."""

    event_id: str
    event_name: str
    event_type: str = "price_target"  # price_target | rate_cut | rate_hike | range
    asset_class: str = "commodity"
    symbol: str = "XAUUSD"
    target_value: float | None = None
    target_unit: str = "USD"
    horizon_start: str = ""  # ISO date
    horizon_end: str = ""  # ISO date
    probabilities: dict[str, ProbabilitySource] = field(default_factory=dict)
    probability_change_1d: float | None = None
    probability_change_1w: float | None = None
    final_probability: float | None = None
    confidence: float = 0.0
    reliability_score: float = 0.0  # 0~1, quality of data sources
    divergence_score: float = 0.0  # 0~1, how much sources disagree
    signal_label: str = "neutral"  # bullish | bearish | neutral | unavailable
    interpretation: str = ""
    source_refs: list[dict[str, Any]] = field(default_factory=list)
    input_snapshot_ids: dict[str, str] = field(default_factory=dict)
    status: str = "unavailable"  # available | partial | unavailable


@dataclass(frozen=True)
class MarketOddsSnapshot:
    """A filesystem JSON snapshot of market-odds events.

    This is the feature-layer output: one JSON file per snapshot.
    No DB tables, no network calls, no LLM inference.
    """

    snapshot_id: str
    asset: str = "XAUUSD"
    trade_date: str = ""
    run_id: str = ""
    generated_at: str = ""
    version: str = "1.0.0"

    events: list[MarketOddsEvent] = field(default_factory=list)
    aggregate_signal: str = "unavailable"  # aggregate across all events
    aggregate_confidence: float = 0.0

    status: str = "unavailable"  # available | partial | unavailable
    source_refs: list[dict[str, Any]] = field(default_factory=list)
    input_snapshot_ids: dict[str, str] = field(default_factory=dict)


# ── Public builder ────────────────────────────────────────────────────────


def build_market_odds_snapshot(
    *,
    asset: str = "XAUUSD",
    trade_date: str = "",
    run_id: str = "",
    options_snapshot: dict[str, Any] | None = None,
    macro_snapshot: dict[str, Any] | None = None,
) -> MarketOddsSnapshot:
    """Build a market-odds snapshot from existing CME options data.

    MVP data sources:
      1. CME options → gold price target probabilities from delta-strike grid.
      2. Fed rate probabilities → placeholder (requires CME FedWatch collector).
      3. Polymarket → placeholder.
      4. Bloomberg → placeholder.

    No network calls, no DB reads, no LLM inference.
    All placeholders are explicitly marked ``unavailable`` with notes.
    """
    from datetime import datetime, timezone

    generated_at = datetime.now(timezone.utc).isoformat()
    snapshot_id = f"{asset}:{trade_date}:{run_id}:market_odds"

    events: list[MarketOddsEvent] = []

    # ── 1. CME-derived gold price target probabilities ────────────────
    if options_snapshot and isinstance(options_snapshot, dict):
        cme_events = _derive_cme_price_target_odds(options_snapshot, asset, trade_date)
        events.extend(cme_events)

    # ── 2. Fed rate odds → placeholder ───────────────────────────────
    events.append(_placeholder_event(
        event_id="fed_rate_jun_2026",
        event_name="Fed Rate Cut by Jun 2026 FOMC",
        event_type="rate_cut",
        source_note="CME FedWatch collector not yet implemented (planned).",
    ))

    # ── 3. Polymarket → placeholder ──────────────────────────────────
    events.append(_placeholder_event(
        event_id="gold_above_3000_polymarket",
        event_name="Gold > $3000 by Dec 2026 (Polymarket)",
        event_type="price_target",
        target_value=3000,
        source_note="Polymarket collector not yet implemented.",
    ))

    # ── Determine aggregate signal ─────────────────────────────────────
    available_events = [e for e in events if e.status == "available"]
    if available_events:
        bullish = sum(1 for e in available_events if e.signal_label == "bullish")
        bearish = sum(1 for e in available_events if e.signal_label == "bearish")
        if bullish > bearish:
            aggregate_signal = "bullish"
        elif bearish > bullish:
            aggregate_signal = "bearish"
        else:
            aggregate_signal = "neutral"
        avg_conf = sum(e.confidence for e in available_events) / len(available_events)
        status = "partial"
    else:
        aggregate_signal = "unavailable"
        avg_conf = 0.0
        status = "unavailable"

    return MarketOddsSnapshot(
        snapshot_id=snapshot_id,
        asset=asset,
        trade_date=trade_date,
        run_id=run_id,
        generated_at=generated_at,
        events=events,
        aggregate_signal=aggregate_signal,
        aggregate_confidence=round(avg_conf, 2),
        status=status,
        source_refs=[
            {"source": "cme_options_delta_grid", "method": "probability_from_delta"},
            {"source": "fed_funds_futures", "method": "placeholder"},
            {"source": "polymarket", "method": "placeholder"},
        ],
        input_snapshot_ids={
            "options_snapshot": f"{asset}:{trade_date}:{run_id}",
        },
    )


# ── CME-derived probability helpers ───────────────────────────────────────


def _derive_cme_price_target_odds(
    options: dict[str, Any],
    asset: str,
    trade_date: str,
) -> list[MarketOddsEvent]:
    """Derive gold price target probabilities from CME options.

    Strategy (priority order):
      1. Per-expiry strike-level delta data → touch probability (Black-76).
      2. Structured walls in options snapshot → OI-based fallback.
      3. Return empty list if no usable data.
    """
    # ── Try primary: per_expiry strike-level data with delta ────────
    per_expiry = options.get("per_expiry") or {}
    if per_expiry and isinstance(per_expiry, dict):
        events = _derive_from_per_expiry(per_expiry, asset, trade_date)
        if events:
            return events

    # ── Try fallback: walls data ────────────────────────────────────
    walls = options.get("walls", {}) or {}
    call_walls = walls.get("call_oi_walls", []) or []
    put_walls = walls.get("put_oi_walls", []) or []

    if not call_walls and not put_walls:
        return []

    events: list[MarketOddsEvent] = []

    resistance_target = _extract_top_wall_strike(call_walls)
    if resistance_target and resistance_target > 0:
        prob = _estimate_probability_from_walls(
            resistance_target, call_walls, put_walls, side="call"
        )
        events.append(
            MarketOddsEvent(
                event_id=f"gold_above_{int(resistance_target)}",
                event_name=f"Gold > ${int(resistance_target)}",
                event_type="price_target",
                symbol=asset,
                target_value=resistance_target,
                target_unit="USD",
                horizon_end="",
                probabilities={
                    "cme_options": ProbabilitySource(
                        source="cme_options",
                        probability=round(prob, 4) if prob else None,
                        confidence=0.5 if prob else 0.0,
                        last_updated=trade_date,
                        source_ref=f"cmegroup.com/dailybulletin walls {trade_date}",
                        notes="Estimated from wall OI concentration (delta unavailable).",
                    ),
                    "polymarket": _unavailable_prob("Polymarket collector not yet implemented."),
                    "bloomberg": _unavailable_prob("Bloomberg source not configured."),
                    "internal_model": _unavailable_prob("Internal model deferred to P4-08."),
                },
                final_probability=round(prob, 4) if prob else None,
                confidence=0.5 if prob else 0.0,
                reliability_score=0.4 if prob else 0.0,
                divergence_score=0.0,
                signal_label="bullish" if prob and prob > 0.5 else (
                    "bearish" if prob and prob < 0.3 else "neutral"
                ),
                interpretation=_interpret_probability(prob, "bullish", int(resistance_target)),
                status="available" if prob else "unavailable",
            ),
        )

    support_target = _extract_top_wall_strike(put_walls)
    if support_target and support_target > 0:
        prob = _estimate_probability_from_walls(
            support_target, call_walls, put_walls, side="put"
        )
        events.append(
            MarketOddsEvent(
                event_id=f"gold_below_{int(support_target)}",
                event_name=f"Gold < ${int(support_target)}",
                event_type="price_target",
                symbol=asset,
                target_value=support_target,
                target_unit="USD",
                horizon_end="",
                probabilities={
                    "cme_options": ProbabilitySource(
                        source="cme_options",
                        probability=round(prob, 4) if prob else None,
                        confidence=0.5 if prob else 0.0,
                        last_updated=trade_date,
                        source_ref=f"cmegroup.com/dailybulletin walls {trade_date}",
                        notes="Estimated from wall OI concentration (delta unavailable).",
                    ),
                    "polymarket": _unavailable_prob("Polymarket collector not yet implemented."),
                    "bloomberg": _unavailable_prob("Bloomberg source not configured."),
                    "internal_model": _unavailable_prob("Internal model deferred to P4-08."),
                },
                final_probability=round(prob, 4) if prob else None,
                confidence=0.5 if prob else 0.0,
                reliability_score=0.4 if prob else 0.0,
                divergence_score=0.0,
                signal_label="bearish" if prob and prob > 0.5 else (
                    "bullish" if prob and prob < 0.3 else "neutral"
                ),
                interpretation=_interpret_probability(prob, "bearish", int(support_target)),
                status="available" if prob else "unavailable",
            ),
        )

    return events


def _derive_from_per_expiry(
    per_expiry: dict[str, Any],
    asset: str,
    trade_date: str,
) -> list[MarketOddsEvent]:
    """Derive delta-backed events from per-expiry strike-level data."""
    events: list[MarketOddsEvent] = []

    for expiry_key in sorted(per_expiry.keys()):
        exp_data = per_expiry.get(expiry_key)
        if not isinstance(exp_data, dict):
            continue

        strikes = exp_data.get("strikes") or []
        if not isinstance(strikes, list) or not strikes:
            continue

        forward = exp_data.get("forward_price")

        # Find resistance (max call OI strike) and support (max put OI strike)
        resistance_target = _find_top_strike(strikes, "call_oi")
        support_target = _find_top_strike(strikes, "put_oi")

        if resistance_target and resistance_target > 0:
            event = _build_delta_backed_event(
                target=resistance_target,
                direction="above",
                asset=asset,
                expiry=expiry_key,
                trade_date=trade_date,
                strikes=strikes,
                forward=forward,
            )
            if event is not None:
                events.append(event)

        if support_target and support_target > 0 and support_target != resistance_target:
            event = _build_delta_backed_event(
                target=support_target,
                direction="below",
                asset=asset,
                expiry=expiry_key,
                trade_date=trade_date,
                strikes=strikes,
                forward=forward,
            )
            if event is not None:
                events.append(event)

    return events


def _build_delta_backed_event(
    *,
    target: float,
    direction: str,
    asset: str,
    expiry: str,
    trade_date: str,
    strikes: list[dict[str, Any]],
    forward: float | None = None,
) -> MarketOddsEvent | None:
    """Build a delta-backed MarketOddsEvent from per-expiry strike data.

    Uses Black-76 delta (call for "above", put for "below") as the
    risk-neutral probability proxy.
    """
    if direction not in ("above", "below"):
        return None

    # Find the nearest strike with usable delta data
    nearest = _find_nearest_strike_with_delta(
        strikes, target, option_type="CALL" if direction == "above" else "PUT"
    )
    if nearest is None:
        return None

    delta_val = nearest.get("call_delta" if direction == "above" else "put_delta")
    iv = nearest.get("iv")
    target_strike = nearest.get("strike", target)

    if delta_val is None:
        return None

    # Touch probability from delta
    try:
        from apps.features.options.probability import compute_touch_probability_from_delta
        touch_prob = compute_touch_probability_from_delta(float(delta_val))
    except ImportError:
        touch_prob = min(float(delta_val) * 2.0, 0.85)

    confidence = 0.6
    if iv and 0.05 <= float(iv) <= 0.60:
        confidence += 0.15
    if abs(target_strike - target) <= 25:
        confidence += 0.1

    if direction == "above":
        signal = "bullish" if touch_prob and touch_prob > 0.5 else (
            "bearish" if touch_prob and touch_prob < 0.3 else "neutral"
        )
    else:
        signal = "bearish" if touch_prob and touch_prob > 0.5 else (
            "bullish" if touch_prob and touch_prob < 0.3 else "neutral"
        )

    event = MarketOddsEvent(
        event_id=f"gold_{direction}_{int(target)}",
        event_name=f"Gold {direction} ${int(target)} ({expiry})",
        event_type="price_target",
        symbol=asset,
        target_value=target,
        target_unit="USD",
        horizon_end=expiry,
        probabilities={
            "cme_options": ProbabilitySource(
                source="cme_options",
                probability=round(touch_prob, 4) if touch_prob else None,
                confidence=round(confidence, 2),
                last_updated=trade_date,
                source_ref=f"cmegroup.com/dailybulletin delta grid {trade_date} {expiry}",
                notes=f"Black-76 {'call' if direction == 'above' else 'put'} delta at strike {int(target_strike)}. IV={iv}",
            ),
            "polymarket": _unavailable_prob("Polymarket collector not yet implemented."),
            "bloomberg": _unavailable_prob("Bloomberg source not configured."),
            "internal_model": _unavailable_prob("Internal model deferred to P4-08."),
        },
        final_probability=round(touch_prob, 4) if touch_prob else None,
        confidence=round(confidence, 2),
        reliability_score=0.6 if touch_prob else 0.0,
        divergence_score=0.0,
        signal_label=signal,
        interpretation=(
            f"Black-76 delta model: {touch_prob:.0%} touch probability for Gold {direction} ${int(target)} "
            f"by {expiry} (nearest strike: {int(target_strike)}, IV: {iv})."
        ) if touch_prob else "Unavailable.",
        status="available" if touch_prob else "unavailable",
    )
    return event


# ── Helpers ───────────────────────────────────────────────────────────────


def _find_nearest_strike_with_delta(
    strikes: list[dict[str, Any]],
    target: float,
    option_type: str = "CALL",
) -> dict[str, Any] | None:
    """Find the strike closest to target that has usable delta data."""
    delta_key = "call_delta" if option_type == "CALL" else "put_delta"
    candidates = [
        s for s in strikes
        if isinstance(s, dict)
        and isinstance(s.get(delta_key), (int, float))
        and s.get(delta_key) is not None
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda s: abs(float(s.get("strike", 0)) - target))


def _find_top_strike(
    strikes: list[dict[str, Any]],
    oi_field: str,
) -> float | None:
    """Get the strike with the highest value for a given OI field."""
    candidates = [
        s for s in strikes
        if isinstance(s, dict) and isinstance(s.get(oi_field), (int, float))
    ]
    if not candidates:
        return None
    best = max(candidates, key=lambda s: float(s.get(oi_field, 0)))
    val = best.get("strike")
    return float(val) if isinstance(val, (int, float)) else None


def _extract_top_wall_strike(walls: list[dict[str, Any]]) -> float | None:
    """Get the strike of the highest-OI wall."""
    if not walls:
        return None
    best = max(walls, key=lambda w: w.get("oi", 0))
    strike = best.get("strike")
    if isinstance(strike, (int, float)):
        return float(strike)
    return None


def _estimate_probability_from_walls(
    target_strike: float,
    call_walls: list[dict[str, Any]],
    put_walls: list[dict[str, Any]],
    side: str = "call",
) -> float | None:
    """Estimate probability from wall OI concentration.

    A simple heuristic: the ratio of target-strike OI to total wall OI
    indicates how much the market is positioned for that level.
    """
    total_oi = sum(w.get("oi", 0) for w in call_walls) + sum(w.get("oi", 0) for w in put_walls)
    if total_oi == 0:
        return None

    if side == "call":
        target_oi = sum(w.get("oi", 0) for w in call_walls if w.get("strike") == target_strike)
    else:
        target_oi = sum(w.get("oi", 0) for w in put_walls if w.get("strike") == target_strike)

    prob = target_oi / total_oi
    return min(max(prob * 3, 0.1), 0.7)


def _placeholder_event(
    event_id: str,
    event_name: str,
    event_type: str = "price_target",
    target_value: float | None = None,
    source_note: str = "",
) -> MarketOddsEvent:
    """Create a placeholder event with unavailable probabilities."""
    return MarketOddsEvent(
        event_id=event_id,
        event_name=event_name,
        event_type=event_type,
        target_value=target_value,
        probabilities={
            "cme_options": _unavailable_prob("Not applicable for this event."),
            "polymarket": _unavailable_prob(source_note),
            "bloomberg": _unavailable_prob("Bloomberg source not configured."),
            "internal_model": _unavailable_prob("Internal model deferred to P4-08."),
        },
        status="unavailable",
        signal_label="unavailable",
        interpretation=f"Placeholder: {source_note}",
    )


def _unavailable_prob(note: str = "") -> ProbabilitySource:
    return ProbabilitySource(
        source="unavailable",
        probability=None,
        confidence=0.0,
        last_updated=None,
        source_ref=None,
        notes=note,
    )


def _interpret_probability(prob: float | None, direction: str, target: int) -> str:
    if prob is None:
        return f"Probability for Gold {direction} ${target} is unavailable."
    if prob > 0.5:
        return f"Market positioning suggests elevated probability ({prob:.0%}) of Gold {direction} ${target}."
    if prob > 0.3:
        return f"Market shows moderate probability ({prob:.0%}) of Gold {direction} ${target}."
    return f"Market assigns low probability ({prob:.0%}) to Gold {direction} ${target}."
