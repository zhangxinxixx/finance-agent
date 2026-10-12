"""P4-07: Market odds snapshot schema and builder.

Defines the market-odds feature layer as a pure filesystem JSON schema
with no DB tables, no network collectors, and no fake probabilities.

Data sources (MVP):
  - CME-first: an OI wall is kept as structure.  A probability is produced
    only when a dated option observation has F/K/IV/T and source lineage; it
    then uses the Black-76 terminal risk-neutral ``N(d2)`` calculation.
  - FedWatch/Polymarket/Bloomberg: generic unavailable statuses until a
    collector supplies an actual observation.

The distinction between an option delta, an OI wall, a terminal
risk-neutral probability, and a touch probability is intentional.  This
module never turns OI or a delta into a gold directional vote.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
import math
from typing import Any
from urllib.parse import urlparse


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
    """One observed market-odds event or structural observation."""

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

    No network calls, no DB reads, and no LLM inference are performed here.
    OI-only inputs remain structural.  The CME event builder is deliberately
    fail-closed when the actual expiry, source lineage, or any of F/K/IV/T is
    absent.
    """

    generated_at = datetime.now(timezone.utc).isoformat()
    snapshot_id = f"{asset}:{trade_date}:{run_id}:market_odds"

    events: list[MarketOddsEvent] = []

    # ── 1. CME-derived gold price target probabilities ────────────────
    if options_snapshot and isinstance(options_snapshot, dict):
        cme_events = _derive_cme_price_target_odds(options_snapshot, asset, trade_date)
        events.extend(cme_events)

    # Keep collection state visible without inventing a dated rate event or
    # a price target.  These are source statuses, not market events.
    events.extend(_generic_unavailable_events())

    # ── Determine aggregate signal ─────────────────────────────────────
    available_events = [e for e in events if e.status == "available"]
    partial_events = [e for e in events if e.status == "partial"]
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
    elif partial_events:
        # Structural observations exist, but none can support a probability.
        aggregate_signal = "unavailable"
        avg_conf = 0.0
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
            {
                "source": "cme_options",
                "method": "oi_structure_or_black76_nd2",
                "probability_semantics": (
                    "terminal risk-neutral probability in futures coordinates; "
                    "not real-world and not touch probability"
                ),
            },
            {
                "source": "fed_funds_futures",
                "status": "unavailable",
                "reason": "official collector not configured",
            },
            {
                "source": "polymarket",
                "status": "unavailable",
                "reason": "collector not configured",
            },
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
    """Derive CME option structure and, when justified, terminal probabilities.

    Strategy (priority order):
      1. Per-expiry strike-level data.  OI selects a structural wall; only
         complete F/K/IV/T plus a real expiry and source lineage can add an
         ``N(d2)`` terminal risk-neutral probability.
      2. Structured walls in the options snapshot.  These remain structural
         observations and never become probabilities.
      3. Return no CME events when no usable structure exists.
    """
    # ── Try primary: per_expiry strike-level data ────────────────────
    per_expiry = options.get("per_expiry") or {}
    if per_expiry and isinstance(per_expiry, dict):
        events = _derive_from_per_expiry(
            per_expiry, asset, trade_date, options=options,
        )
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
        events.append(
            _build_structural_wall_event(
                target=resistance_target,
                direction="above",
                asset=asset,
                trade_date=trade_date,
                walls=call_walls,
                options=options,
            )
        )

    support_target = _extract_top_wall_strike(put_walls)
    if support_target and support_target > 0:
        events.append(
            _build_structural_wall_event(
                target=support_target,
                direction="below",
                asset=asset,
                trade_date=trade_date,
                walls=put_walls,
                options=options,
            )
        )

    return events


def _derive_from_per_expiry(
    per_expiry: dict[str, Any],
    asset: str,
    trade_date: str,
    *,
    options: dict[str, Any] | None = None,
) -> list[MarketOddsEvent]:
    """Derive structural walls and fail-closed priced events by expiry."""
    events: list[MarketOddsEvent] = []

    for expiry_key in sorted(per_expiry.keys()):
        exp_data = per_expiry.get(expiry_key)
        if not isinstance(exp_data, dict):
            continue

        strikes = exp_data.get("strikes") or []
        if not isinstance(strikes, list) or not strikes:
            continue

        forward = _extract_forward_price(exp_data, options or {}, expiry_key)

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
                exp_data=exp_data,
                options=options or {},
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
                exp_data=exp_data,
                options=options or {},
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
    exp_data: dict[str, Any] | None = None,
    options: dict[str, Any] | None = None,
) -> MarketOddsEvent | None:
    """Build a price event without treating delta as a probability.

    The historical helper name is retained for callers, but its calculation
    is now deliberately fail-closed.  A supplied delta can describe the
    option surface; it cannot produce an exact terminal or touch probability.
    A probability is emitted only when Black-76 has F/K/IV/T, a real future
    expiry date, and a non-placeholder source reference.
    """
    if direction not in ("above", "below"):
        return None

    exp_data = exp_data or {}
    options = options or {}

    # OI selects the event threshold, so pricing must come from that exact
    # strike.  A nearby strike's IV/delta cannot be silently substituted.
    nearest = _find_exact_strike(strikes, target)
    if nearest is None:
        nearest = {"strike": target}

    target_strike = _as_positive_number(nearest.get("strike")) or float(target)
    expiry_date = _resolve_expiry_date(expiry, exp_data)
    as_of = _resolve_as_of_date(trade_date, exp_data, options)
    T = _extract_time_to_expiry(exp_data, expiry_date, as_of)
    F = _as_positive_number(forward)
    K = target_strike if target_strike > 0 else None
    iv = _extract_implied_volatility(nearest, direction)
    source_refs = _collect_valid_source_refs(nearest, exp_data, options)
    source_ref = _source_ref_text(source_refs[0]) if source_refs else None

    missing: list[str] = []
    if F is None:
        missing.append("F")
    if K is None:
        missing.append("K")
    if iv is None:
        missing.append("IV")
    if T is None:
        missing.append("T")
    if expiry_date is None:
        missing.append("actual_expiry_date")
    elif as_of is None:
        missing.append("as_of_date")
    elif expiry_date <= as_of:
        missing.append("future_expiry")
    if not source_refs:
        missing.append("source_lineage")

    probability: float | None = None
    if not missing:
        probability = _black76_terminal_probability(
            F=float(F),
            K=float(K),
            implied_vol=float(iv),
            T=float(T),
            direction=direction,
        )
        if probability is None:
            missing.append("valid_black76_inputs")

    selected_delta = nearest.get(
        "call_delta" if direction == "above" else "put_delta"
    )
    source_notes = (
        "Black-76 N(d2) terminal risk-neutral probability in futures coordinates; "
        "not a real-world probability and not a touch probability. "
        "It is informational and does not create a gold directional signal."
    )
    event_id_expiry = _expiry_id_token(expiry, expiry_date)
    if missing:
        reason = "Unavailable: " + ", ".join(dict.fromkeys(missing)) + "."
        if selected_delta is not None:
            reason += " Option delta alone is insufficient for a precise probability."
        return MarketOddsEvent(
            event_id=f"gold_{direction}_{int(target)}_{event_id_expiry}",
            event_name=f"Gold {direction} ${int(target)} ({expiry_date or expiry})",
            event_type="price_target",
            symbol=asset,
            target_value=target,
            target_unit="USD",
            horizon_end=expiry_date.isoformat() if expiry_date else "",
            probabilities={
                "cme_options": ProbabilitySource(
                    source="cme_options",
                    probability=None,
                    confidence=0.0,
                    last_updated=_last_updated(nearest, exp_data, trade_date),
                    source_ref=source_ref,
                    notes=reason,
                ),
                "polymarket": _unavailable_prob("Polymarket collector not configured."),
                "bloomberg": _unavailable_prob("Bloomberg source not configured."),
                "internal_model": _unavailable_prob("Internal model not configured."),
            },
            final_probability=None,
            confidence=0.0,
            reliability_score=0.0,
            divergence_score=0.0,
            signal_label="unavailable",
            interpretation=reason,
            source_refs=source_refs,
            status="unavailable",
        )

    confidence = 0.75
    if abs(target_strike - target) > 25:
        confidence -= 0.1
    probability = round(float(probability), 4)
    return MarketOddsEvent(
        event_id=f"gold_{direction}_{int(target)}_{event_id_expiry}",
        event_name=f"Gold {direction} ${int(target)} ({expiry_date.isoformat()})",
        event_type="price_target",
        symbol=asset,
        target_value=target,
        target_unit="USD",
        horizon_end=expiry_date.isoformat(),
        probabilities={
            "cme_options": ProbabilitySource(
                source="cme_options",
                probability=probability,
                confidence=round(confidence, 2),
                last_updated=_last_updated(nearest, exp_data, trade_date),
                source_ref=source_ref,
                notes=source_notes,
            ),
            "polymarket": _unavailable_prob("Polymarket collector not configured."),
            "bloomberg": _unavailable_prob("Bloomberg source not configured."),
            "internal_model": _unavailable_prob("Internal model not configured."),
        },
        final_probability=probability,
        confidence=round(confidence, 2),
        reliability_score=round(confidence, 2),
        divergence_score=0.0,
        # A terminal risk-neutral probability is not a real-world gold vote.
        signal_label="neutral",
        interpretation=(
            f"Black-76 N(d2) terminal risk-neutral probability is {probability:.0%} "
            f"for Gold {direction} ${int(target)} by {expiry_date.isoformat()} in futures coordinates; "
            "not a real-world probability, not a touch probability, and not a gold directional signal."
        ),
        source_refs=source_refs,
        status="available",
    )


# ── Helpers ───────────────────────────────────────────────────────────────


def _find_exact_strike(
    strikes: list[dict[str, Any]],
    target: float,
) -> dict[str, Any] | None:
    """Find the row whose strike is exactly the structural target."""
    for row in strikes:
        if not isinstance(row, dict):
            continue
        strike = _as_positive_number(row.get("strike"))
        if strike is not None and strike == float(target):
            return row
    return None


def _expiry_id_token(expiry: Any, expiry_date: date | None) -> str:
    """Create a stable, readable expiry component for event IDs."""
    text = expiry_date.isoformat() if expiry_date else str(expiry).strip()
    token = "".join(char if char.isalnum() else "-" for char in text)
    return token.strip("-") or "unknown-expiry"


def _as_positive_number(value: Any) -> float | None:
    """Return a finite positive number, otherwise ``None``."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0:
        return None
    return number


def _parse_date(value: Any) -> date | None:
    """Parse an ISO date/datetime without guessing a missing day."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        if "T" in text or " " in text:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        return date.fromisoformat(text)
    except ValueError:
        return None


def _resolve_expiry_date(expiry: Any, exp_data: dict[str, Any]) -> date | None:
    """Resolve an explicitly supplied expiry date; never estimate a month."""
    if exp_data.get("expiry_estimated") or exp_data.get("estimated_expiry") or "estimat" in str(exp_data.get("expiry_source", "")).lower():
        return None
    candidates: list[Any] = [
        exp_data.get("expiry_date"),
        exp_data.get("expiration_date"),
        exp_data.get("expiration"),
        exp_data.get("actual_expiry_date"),
        exp_data.get("expiry"),
        expiry,
    ]
    contract = exp_data.get("contract")
    if isinstance(contract, dict):
        candidates.extend(
            [
                contract.get("expiry_date"),
                contract.get("expiration_date"),
                contract.get("expiration"),
            ]
        )
    for candidate in candidates:
        parsed = _parse_date(candidate)
        if parsed is not None:
            return parsed
    return None


def _resolve_as_of_date(
    trade_date: str,
    exp_data: dict[str, Any],
    options: dict[str, Any],
) -> date | None:
    """Resolve the observation date used to validate an expiry."""
    for candidate in (
        trade_date,
        exp_data.get("as_of"),
        exp_data.get("as_of_date"),
        exp_data.get("trade_date"),
        options.get("as_of"),
        options.get("as_of_date"),
        options.get("trade_date"),
    ):
        parsed = _parse_date(candidate)
        if parsed is not None:
            return parsed
    return None


def _extract_time_to_expiry(
    exp_data: dict[str, Any],
    expiry_date: date | None,
    as_of: date | None,
) -> float | None:
    """Read an explicit Black-76 T; do not infer missing time."""
    for key in (
        "time_to_expiry_years",
        "time_to_expiry",
        "year_fraction",
        "T",
        "t",
    ):
        value = _as_positive_number(exp_data.get(key))
        if value is not None:
            if expiry_date is None or as_of is None:
                return None
            # Day precision permits intraday conventions, not a different tenor.
            if abs(value - (expiry_date - as_of).days / 365.0) > 1.0 / 365.0:
                return None
            return value
    return None


def _extract_forward_price(
    exp_data: dict[str, Any],
    options: dict[str, Any],
    expiry_key: str,
) -> float | None:
    """Read the per-expiry futures forward without falling back to spot."""
    for container in (exp_data,):
        for key in ("forward_price", "futures_price", "f_value", "forward", "F"):
            value = _as_positive_number(container.get(key))
            if value is not None:
                return value

    for parent in (options, options.get("parameters")):
        if not isinstance(parent, dict):
            continue
        for map_key in ("forward_by_expiry", "model_f"):
            values = parent.get(map_key)
            if not isinstance(values, dict):
                continue
            item = values.get(expiry_key)
            if item is None:
                expiry_date = _resolve_expiry_date(expiry_key, exp_data)
                if expiry_date is not None:
                    item = values.get(expiry_date.isoformat())
            if isinstance(item, dict):
                for key in ("forward_price", "futures_price", "f_value", "forward", "F"):
                    value = _as_positive_number(item.get(key))
                    if value is not None:
                        return value
            else:
                value = _as_positive_number(item)
                if value is not None:
                    return value
    return None


def _extract_implied_volatility(
    strike: dict[str, Any],
    direction: str,
) -> float | None:
    """Read a decimal IV from the selected call/put row."""
    side = "call" if direction == "above" else "put"
    containers: list[dict[str, Any]] = [strike]
    nested = strike.get(side)
    if isinstance(nested, dict):
        containers.insert(0, nested)
    keys = (
        f"{side}_iv",
        f"{side}_implied_volatility",
        f"{side}_implied_vol",
        "iv",
        "implied_volatility",
        "implied_vol",
        "sigma",
    )
    for container in containers:
        for key in keys:
            value = _normalise_iv(container.get(key), unit=container.get("iv_unit", "decimal"))
            if value is not None:
                return value
    return None


def _normalise_iv(value: Any, *, unit: str = "decimal") -> float | None:
    """Accept decimal IV and an explicit percentage representation."""
    try:
        sigma = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(sigma) or sigma <= 0:
        return None
    if unit in {"percent", "%"}:
        sigma /= 100.0
    elif unit != "decimal":
        return None
    if sigma > 5.0:
        return None
    return sigma


def _is_valid_source_ref(value: Any) -> bool:
    if isinstance(value, str):
        text = value.strip().lower()
        if not text or any(
            marker in text
            for marker in ("placeholder", "unavailable", "not configured", "not applicable")
        ):
            return False
        return text.startswith(("cme://", "cme:", "cme_options:", "raw/", "snapshot:", "ingest:"))
    if not isinstance(value, dict):
        return False
    if any(str(value.get(key, "")).lower() in {"unavailable", "failed", "error", "stale", "blocked"} for key in ("status", "quality_status", "freshness_status")):
        return False
    identity = " ".join(
        str(value.get(key, "")).strip().lower()
        for key in ("source", "provider", "collector", "dataset")
    )
    known_cme = any(token in identity for token in ("cme", "cmegroup"))
    for key in ("snapshot_id", "input_snapshot_id", "ingest_id"):
        candidate = value.get(key)
        if isinstance(candidate, str) and _is_valid_source_ref(f"snapshot:{candidate}"):
            return True
    for key in ("raw_path", "raw_file"):
        candidate = value.get(key)
        if not isinstance(candidate, str) or not candidate.strip():
            continue
        if known_cme or candidate.lower().startswith("raw/"):
            return _is_valid_source_ref(f"raw/{candidate.lstrip('/')}")
    for key in ("url", "source_url"):
        candidate = value.get(key)
        if not isinstance(candidate, str):
            continue
        hostname = (urlparse(candidate.strip()).hostname or "").lower()
        # A URL alone is not lineage.  Only the official CME host is accepted
        # here, and it still needs a source identity in the record.
        if known_cme and (hostname == "cmegroup.com" or hostname.endswith(".cmegroup.com")):
            return _is_valid_source_ref(candidate.replace("https://", "cme://", 1))
    for key in ("source_ref", "ref", "uri"):
        candidate = value.get(key)
        if isinstance(candidate, str) and _is_valid_source_ref(candidate):
            return True
    return False


def _collect_valid_source_refs(
    strike: dict[str, Any],
    exp_data: dict[str, Any],
    options: dict[str, Any],
) -> list[dict[str, Any]]:
    """Collect actual lineage records for the selected observation."""
    refs: list[dict[str, Any]] = []

    def add(value: Any, *, key: str = "source_ref") -> None:
        values = value if isinstance(value, list) else [value]
        for item in values:
            if isinstance(item, dict):
                if _is_valid_source_ref(item):
                    normalized = dict(item)
                else:
                    continue
            elif _is_valid_source_ref(
                f"snapshot:{item}" if key == "snapshot_id" else item
            ):
                normalized = {key: str(item)}
            else:
                continue
            if normalized not in refs:
                refs.append(normalized)

    for container in (strike, exp_data, options):
        if not isinstance(container, dict):
            continue
        for key in ("source_ref", "source_refs", "raw_ref", "raw_refs"):
            if key in container:
                add(container.get(key), key="source_ref")
        for key in ("data_source_url", "source_url", "url"):
            if key in container:
                add(container.get(key), key="url")
        data_source = container.get("data_source")
        if isinstance(data_source, dict):
            add(data_source, key="source_ref")
    input_ids = options.get("input_snapshot_ids")
    if isinstance(input_ids, dict):
        for value in input_ids.values():
            add(value, key="snapshot_id")
    return refs


def _source_ref_text(ref: dict[str, Any]) -> str | None:
    for key in (
        "source_ref",
        "raw_path",
        "raw_file",
        "url",
        "source_url",
        "snapshot_id",
        "input_snapshot_id",
        "ingest_id",
        "ref",
        "uri",
    ):
        value = ref.get(key)
        if value is not None and str(value).strip():
            return str(value)
    return None


def _last_updated(
    strike: dict[str, Any],
    exp_data: dict[str, Any],
    fallback: str,
) -> str | None:
    for container in (strike, exp_data):
        for key in ("last_updated", "retrieved_at", "observed_at", "as_of", "trade_date"):
            value = container.get(key)
            if value is not None and str(value).strip():
                return str(value)
    return fallback or None


def _black76_terminal_probability(
    *,
    F: float,
    K: float,
    implied_vol: float,
    T: float,
    direction: str,
) -> float | None:
    """Return Black-76 ``N(d2)`` terminal probability for a futures event."""
    if direction not in ("above", "below"):
        return None
    if not all(math.isfinite(value) for value in (F, K, implied_vol, T)):
        return None
    if F <= 0 or K <= 0 or implied_vol <= 0 or T <= 0:
        return None
    denominator = implied_vol * math.sqrt(T)
    if denominator <= 0:
        return None
    d2 = (math.log(F / K) - 0.5 * implied_vol * implied_vol * T) / denominator
    cdf_d2 = 0.5 * (1.0 + math.erf(d2 / math.sqrt(2.0)))
    probability = cdf_d2 if direction == "above" else 1.0 - cdf_d2
    return min(max(probability, 0.0), 1.0)


def _build_structural_wall_event(
    *,
    target: float,
    direction: str,
    asset: str,
    trade_date: str,
    walls: list[dict[str, Any]],
    options: dict[str, Any],
) -> MarketOddsEvent:
    """Keep an OI wall visible without turning concentration into odds."""
    refs = _collect_valid_source_refs({}, {}, options)
    source_ref = _source_ref_text(refs[0]) if refs else None
    side = "call" if direction == "above" else "put"
    return MarketOddsEvent(
        event_id=f"gold_{side}_oi_wall_{int(target)}",
        event_name=f"Gold {side} open-interest wall ${int(target)}",
        event_type="price_structure",
        asset_class="commodity",
        symbol=asset,
        target_value=target,
        target_unit="USD",
        probabilities={
            "cme_options": ProbabilitySource(
                source="cme_options",
                probability=None,
                confidence=0.0,
                last_updated=trade_date or None,
                source_ref=source_ref,
                notes=(
                    "Open interest wall is structural only; it cannot produce "
                    "a terminal or touch probability."
                ),
            ),
            "polymarket": _unavailable_prob("Polymarket collector not configured."),
            "bloomberg": _unavailable_prob("Bloomberg source not configured."),
            "internal_model": _unavailable_prob("Internal model not configured."),
        },
        signal_label="unavailable",
        interpretation=(
            f"Observed {side} open-interest wall at ${int(target)} from {len(walls)} wall rows; "
            "structural context only, no probability or gold directional vote."
        ),
        source_refs=refs,
        status="partial",
    )


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
    """Deprecated compatibility helper; OI concentration is not a probability."""
    return None


def _generic_unavailable_events() -> list[MarketOddsEvent]:
    """Return source statuses without inventing dates, targets, or outcomes."""
    return [
        _placeholder_event(
            event_id="fed_rate",
            event_name="Fed rate probability data",
            event_type="rate_cut",
            source_note="Official FedWatch/fed-funds-futures collector is not configured.",
        ),
        _placeholder_event(
            event_id="polymarket_price_target",
            event_name="Polymarket price-target data",
            event_type="price_target",
            source_note="Polymarket collector is not configured.",
        ),
    ]


def _placeholder_event(
    event_id: str,
    event_name: str,
    event_type: str = "price_target",
    target_value: float | None = None,
    source_note: str = "",
) -> MarketOddsEvent:
    """Create a generic unavailable source status.

    ``target_value`` remains a compatibility argument, but the builder never
    supplies it.  New source statuses must not contain a guessed date or
    target.
    """
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
        interpretation=f"Unavailable: {source_note}",
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
