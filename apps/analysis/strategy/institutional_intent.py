"""Deterministic institutional-intent hypotheses for ``live_strategy.v1``.

This module is deliberately a read-only interpretation layer.  It does not
assert that a dealer or another institution actually took a position: every
row is explicitly marked as a hypothesis and keeps the cues that led to it.
The rules only combine already-built strategy/options/event mappings; they do
not fetch data, mutate an input, or write an artifact.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from copy import deepcopy
from typing import Any


SCHEMA_VERSION = "live_strategy.institutional_intent.v1"
SUPPORTED_LABELS: tuple[str, ...] = (
    "new_positioning",
    "covering",
    "hedging",
    "volatility_buying",
    "volatility_selling",
    "liquidity_sweep",
)

_LABEL_SET = frozenset(SUPPORTED_LABELS)
_EVENTS_WITH_DIRECTION = frozenset({"accepted_break", "reclaim", "retest", "failed_break", "intrabar_breach"})
_CONFIRMED_EVENTS = frozenset({"accepted_break", "reclaim", "retest", "failed_break"})


def build_institutional_intent_hypotheses(
    live_strategy: Mapping[str, Any] | None,
    options_decision: Mapping[str, Any] | None = None,
    evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build bounded, deterministic hypotheses from existing read models.

    A hypothesis needs two *different cue domains* (for example ``gamma``
    and ``price_event``).  This deliberately prevents one price move or one
    OI field from being promoted to an institutional claim.  ``evidence`` is
    an optional extension point for pre-computed cues and is never treated as
    an authoritative fact by itself.
    """

    strategy = dict(live_strategy) if isinstance(live_strategy, Mapping) else {}
    options = dict(options_decision) if isinstance(options_decision, Mapping) else {}
    extra = deepcopy(dict(evidence)) if isinstance(evidence, Mapping) else {}
    cues = _derived_cues(strategy, options) + _explicit_cues(extra)
    cues = _dedupe_cues(cues)

    hypotheses: list[dict[str, Any]] = []
    for label in SUPPORTED_LABELS:
        supporting = [cue for cue in cues if label in cue["supports"]]
        counter = [cue for cue in cues if label in cue["contradicts"]]
        # Two cues from one domain are not independent confirmation.
        domains = {cue["domain"] for cue in supporting}
        if len(domains) < 2:
            continue
        support_refs = [_cue_ref(cue) for cue in supporting]
        counter_refs = [_cue_ref(cue) for cue in counter]
        hypotheses.append(
            {
                "label": label,
                "status": "hypothesis",
                "is_fact": False,
                "confidence": _confidence(len(supporting), len(domains), len(counter)),
                "evidence": support_refs,
                "evidence_refs": support_refs,
                "counter_evidence": counter_refs,
            }
        )

    hypotheses.sort(key=lambda item: (-float(item["confidence"]), item["label"]))
    status = "hypothesis" if hypotheses else "unavailable"
    top_level_evidence = _unique_refs(
        ref for item in hypotheses for ref in item["evidence_refs"]
    )
    top_level_counter = _unique_refs(
        ref for item in hypotheses for ref in item["counter_evidence"]
    )
    reasons = [] if hypotheses else ["insufficient_independent_cues"]
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "hypotheses": hypotheses,
        "evidence_refs": top_level_evidence,
        "counter_evidence": top_level_counter,
        "reasons": reasons,
    }
    payload["intent_id"] = f"intent-{_digest(payload)}"
    return payload


def _derived_cues(strategy: Mapping[str, Any], options: Mapping[str, Any]) -> list[dict[str, Any]]:
    cues: list[dict[str, Any]] = []
    market_state = strategy.get("market_state") if isinstance(strategy.get("market_state"), Mapping) else {}
    gamma = _text(market_state.get("gamma_regime"))
    if gamma in {None, "unavailable", "unknown", "none"}:
        gamma = _text(_nested(options, "gamma_summary", "regime"))
    if gamma and gamma not in {"unavailable", "unknown", "none"}:
        supports: set[str] = set()
        contradicts: set[str] = set()
        if gamma == "negative_gamma":
            supports.update({"volatility_buying", "liquidity_sweep"})
            contradicts.add("volatility_selling")
        elif gamma == "positive_gamma":
            supports.add("volatility_selling")
            contradicts.update({"volatility_buying", "liquidity_sweep"})
        elif gamma == "flip_zone":
            supports.add("hedging")
            contradicts.update({"volatility_buying", "volatility_selling"})
        if supports or contradicts:
            cues.append(_cue("gamma", f"gamma:{gamma}", f"gamma regime={gamma}", supports, contradicts))

    event = market_state.get("latest_price_event")
    if isinstance(event, Mapping):
        event_type = _text(event.get("event_type"))
        if event_type in _EVENTS_WITH_DIRECTION:
            confirmed = event.get("confirmed") is True or event_type in _CONFIRMED_EVENTS
            supports: set[str] = set()
            contradicts: set[str] = set()
            if event_type in {"accepted_break", "reclaim", "retest"} and confirmed:
                supports.add("new_positioning")
                supports.add("volatility_buying")
                contradicts.add("covering")
            elif event_type == "failed_break":
                supports.update({"covering", "liquidity_sweep"})
                contradicts.add("new_positioning")
            elif event_type == "intrabar_breach":
                supports.add("liquidity_sweep")
            elif event_type in {"touch", "approach"}:
                supports.add("volatility_selling")
            if supports or contradicts:
                detail = f"confirmed price event={event_type}" if confirmed else f"price event={event_type}"
                cues.append(_cue("price_event", f"price_event:{event_type}", detail, supports, contradicts, event))

    oi = options.get("oi_summary")
    if isinstance(oi, Mapping):
        total = oi.get("total") if isinstance(oi.get("total"), Mapping) else {}
        call = oi.get("call") if isinstance(oi.get("call"), Mapping) else {}
        put = oi.get("put") if isinstance(oi.get("put"), Mapping) else {}
        total_delta = _number(total.get("delta"))
        call_delta = _number(call.get("delta"))
        put_delta = _number(put.get("delta"))
        if any(value is not None for value in (total_delta, call_delta, put_delta)):
            positive = [name for name, value in (("total", total_delta), ("call", call_delta), ("put", put_delta)) if value is not None and value > 0]
            negative = [name for name, value in (("total", total_delta), ("call", call_delta), ("put", put_delta)) if value is not None and value < 0]
            supports: set[str] = set()
            contradicts: set[str] = set()
            if positive:
                supports.add("new_positioning")
                contradicts.add("covering")
            if negative:
                supports.add("covering")
                contradicts.add("new_positioning")
            if put_delta is not None and put_delta > 0:
                supports.add("hedging")
            if supports or contradicts:
                detail = f"options OI delta positive={positive or []} negative={negative or []}"
                cues.append(_cue("options_oi", "options_oi:delta", detail, supports, contradicts, oi))

    for item in _as_mappings(_nested(options, "wall_changes", "items")):
        trend = _text(item.get("trend"))
        role = _text(item.get("role") or item.get("side")) or "wall"
        if trend not in {"strengthening", "weakening"}:
            continue
        supports: set[str] = set()
        contradicts: set[str] = set()
        if trend == "strengthening" and any(word in role.lower() for word in ("tail", "support", "put", "protection")):
            supports.add("hedging")
            contradicts.add("liquidity_sweep")
        elif trend == "weakening":
            supports.add("liquidity_sweep")
            contradicts.add("hedging")
        if supports or contradicts:
            cue_id = f"wall:{role}:{trend}:{item.get('strike', '')}"
            cues.append(_cue("options_wall", cue_id, f"{role} wall {trend}", supports, contradicts, item))

    # Explicit volatility/read-through fields are accepted only when named;
    # a raw IV number is not enough to claim buying or selling.
    volatility = options.get("volatility_signal") or options.get("volatility_regime")
    if isinstance(volatility, str):
        value = volatility.lower()
        supports = {"volatility_buying"} if value in {"buying", "expanding", "high", "long_vol"} else {"volatility_selling"} if value in {"selling", "compressing", "low", "short_vol"} else set()
        contradicts = {"volatility_selling"} if "volatility_buying" in supports else {"volatility_buying"} if supports else set()
        if supports:
            cues.append(_cue("volatility", f"volatility:{value}", f"explicit volatility signal={value}", supports, contradicts))
    return cues


def _explicit_cues(evidence: Mapping[str, Any]) -> list[dict[str, Any]]:
    values: list[Any] = []
    for key in ("cues", "signals", "evidence"):
        candidate = evidence.get(key)
        if isinstance(candidate, Sequence) and not isinstance(candidate, (str, bytes, bytearray)):
            values.extend(candidate)
    result: list[dict[str, Any]] = []
    for index, raw in enumerate(values):
        if not isinstance(raw, Mapping):
            continue
        supports = _labels(raw.get("supports") or raw.get("labels") or raw.get("label"))
        contradicts = _labels(raw.get("contradicts") or raw.get("counter_labels"))
        if not supports and not contradicts:
            continue
        domain = _text(raw.get("domain") or raw.get("kind") or raw.get("type")) or "explicit"
        cue_id = _text(raw.get("cue_id") or raw.get("id")) or f"explicit:{domain}:{index}"
        detail = _text(raw.get("detail") or raw.get("description") or raw.get("value")) or cue_id
        result.append(_cue(domain, cue_id, detail, supports, contradicts, raw))
    return result


def _cue(domain: str, cue_id: str, detail: str, supports: set[str], contradicts: set[str], raw: Mapping[str, Any] | None = None) -> dict[str, Any]:
    raw_ref = raw.get("source_ref") if isinstance(raw, Mapping) else None
    if raw_ref is None and isinstance(raw, Mapping):
        raw_ref = raw.get("ref") or raw.get("source")
    return {
        "domain": _text(domain) or "unknown",
        "cue_id": str(cue_id),
        "detail": str(detail),
        "supports": sorted(_LABEL_SET.intersection(supports)),
        "contradicts": sorted(_LABEL_SET.intersection(contradicts)),
        "source_ref": _text(raw_ref),
    }


def _cue_ref(cue: Mapping[str, Any]) -> dict[str, Any]:
    result = {
        "cue_id": cue["cue_id"],
        "domain": cue["domain"],
        "detail": cue["detail"],
    }
    if cue.get("source_ref"):
        result["source_ref"] = cue["source_ref"]
    return result


def _dedupe_cues(cues: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for cue in cues:
        item = dict(cue)
        key = str(item.get("cue_id"))
        unique.setdefault(key, item)
    return [unique[key] for key in sorted(unique)]


def _confidence(support_count: int, domain_count: int, counter_count: int) -> float:
    value = 0.35 + min(support_count, 4) * 0.10 + min(domain_count, 3) * 0.08 - min(counter_count, 4) * 0.10
    return round(min(max(value, 0.0), 1.0), 3)


def _labels(value: Any) -> set[str]:
    values: list[Any]
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        values = list(value)
    else:
        values = []
    aliases = {
        "new-positioning": "new_positioning",
        "new positioning": "new_positioning",
        "volatility-buying": "volatility_buying",
        "volatility-selling": "volatility_selling",
        "liquidity-sweep": "liquidity_sweep",
    }
    normalized = {aliases.get(str(item).strip().lower(), str(item).strip().lower()) for item in values if item not in (None, "")}
    return normalized & _LABEL_SET


def _as_mappings(value: Any) -> list[Mapping[str, Any]]:
    return [item for item in value or [] if isinstance(item, Mapping)] if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)) else []


def _nested(payload: Mapping[str, Any], *keys: str) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _number(value: Any) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None


def _unique_refs(items: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        ref = dict(item)
        key = _canonical_json(ref)
        if key not in seen:
            seen.add(key)
            result.append(ref)
    return result


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


__all__ = ["SCHEMA_VERSION", "SUPPORTED_LABELS", "build_institutional_intent_hypotheses"]
