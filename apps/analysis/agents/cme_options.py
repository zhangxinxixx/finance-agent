from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from apps.analysis.agents.schemas import AgentBias, AgentOutput, AgentStatus, DataCategory

_AGENT_NAME = "cme_options_agent"
_MODULE = "options"
_VERSION = "1.0"
_WATCHLIST = [
    "wall scores",
    "support/resistance",
    "gamma zero",
    "GEX summaries",
    "IV skew",
    "block/PNT flows",
    "expiration summaries",
    "data quality",
    "FINAL/PRELIM source status",
]


def analyze_cme_options(snapshot: dict[str, Any], *, created_at: datetime | None = None) -> AgentOutput:
    """Analyze already-computed CME options snapshot data without mutating inputs or reading files."""

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
            risk_points=["CME 期权输入必须是已加载的快照字典。"],
            watchlist=list(_WATCHLIST),
            invalid_conditions=["非字典输入被拒绝；文件/路径读取不在范围内。"],
            summary="CME options input is unavailable; no read-only conclusion was generated.",
            source_refs=[],
            status=AgentStatus.UNAVAILABLE,
            created_at=created_at,
            data_category=DataCategory.SYSTEM_INFERENCE,
        )

    snapshot_id = str(snapshot.get("snapshot_id") or "unknown")
    input_snapshot_ids = _input_snapshot_ids(snapshot)
    source_refs = _source_refs(snapshot)
    options = snapshot.get("options")

    if not isinstance(options, dict) or options.get("status") != "available":
        reason = "options section is missing" if not isinstance(options, dict) else f"options status is {options.get('status')!r}"
        return AgentOutput(
            version=_VERSION,
            agent_name=_AGENT_NAME,
            module=_MODULE,
            snapshot_id=snapshot_id,
            input_snapshot_ids=input_snapshot_ids,
            bias=AgentBias.UNAVAILABLE,
            confidence=0.0,
            key_findings=[],
            risk_points=["CME 期权输入不可用。"],
            watchlist=list(_WATCHLIST),
            invalid_conditions=[reason],
            summary="CME options input is unavailable; no read-only conclusion was generated.",
            source_refs=source_refs,
            status=AgentStatus.UNAVAILABLE,
            created_at=created_at,
            data_category=DataCategory.SYSTEM_INFERENCE,
        )

    # Unwrap data layer: snapshot.options = {status: "available", data: {...}}
    options = _dict(options.get("data"))

    key_findings: list[str] = []
    risk_points: list[str] = []
    invalid_conditions: list[str] = []
    status = AgentStatus.SUCCESS
    confidence = 0.42

    score = 0.0
    intent = _dict(options.get("intent"))
    intent_score = _to_float(intent.get("score"))
    intent_type = _text(intent.get("type"))
    if intent_type or intent_score is not None:
        finding = f"Options intent {intent_type or 'unknown'}"
        if intent_score is not None:
            finding += f" score {intent_score:.2f}"
            score += intent_score
            confidence += min(abs(intent_score) * 0.12, 0.12)
        key_findings.append(finding + ".")

    wall_scores = _list_of_dicts(options.get("wall_scores"))
    if wall_scores:
        top_wall = wall_scores[0]
        wall_score = _to_float(top_wall.get("wall_score"))
        wall_label = _wall_label(top_wall)
        finding = f"Top wall score highlights {wall_label}"
        strike = _to_float(top_wall.get("strike"))
        if strike is not None:
            finding += f" near {strike:g}"
        else:
            invalid_conditions.append("Top wall score has no numeric strike/level; precise wall price was not invented.")
        if wall_score is not None:
            finding += f" with score {wall_score:.2f}"
            confidence += min(wall_score * 0.10, 0.10)
        key_findings.append(finding + ".")
        score += _direction_from_wall(top_wall) * (wall_score or 0.5)
    else:
        status = AgentStatus.PARTIAL
        confidence -= 0.10
        risk_points.append("Wall scores are missing, so support/resistance conviction is limited.")

    _add_support_resistance(options, key_findings, risk_points, invalid_conditions)
    _add_gex(options, key_findings, risk_points, invalid_conditions)
    expiry_structures = _add_expiry_structure_findings(options, key_findings)
    _add_iv_skew(options, key_findings)
    _add_block_pnt(options, key_findings)
    _add_expiration_summary(options, key_findings)

    if not _has_numeric_price(options):
        status = AgentStatus.PARTIAL
        confidence -= 0.08
        invalid_conditions.append("No reliable price/level fields were available; precise levels were omitted.")

    source_status = _source_status(options)
    if source_status and source_status.upper() != "FINAL":
        status = AgentStatus.PARTIAL
        confidence -= 0.12
        risk_points.append(f"CME options source status is {source_status}; treat conclusions as provisional.")
    elif not source_status:
        status = AgentStatus.PARTIAL
        confidence -= 0.08
        invalid_conditions.append("CME options source status is missing; FINAL/PRELIM certainty is unavailable.")

    prelim_count = _prelim_count(options)
    if prelim_count > 0:
        status = AgentStatus.PARTIAL
        confidence -= 0.08
        risk_points.append(f"Data quality reports {prelim_count:g} PRELIM-derived option rows/signals.")

    warnings = _data_quality_warnings(options)
    if warnings:
        status = AgentStatus.PARTIAL
        confidence -= min(0.02 * len(warnings), 0.10)
        risk_points.extend(f"Data quality warning: {warning}" for warning in warnings[:4])

    # ── P4-06: multi-day calibration findings ─────────────────────
    _add_calibration_findings(options, key_findings, risk_points)

    if not key_findings:
        status = AgentStatus.PARTIAL
        key_findings.append("CME options data is present but directional signals are insufficient.")

    score += _structure_score(expiry_structures)
    confidence += _structure_confidence_bonus(expiry_structures)
    bias = _bias_from_score(score)
    bullish_drivers, bearish_drivers = _directional_drivers(options)
    confidence = _clamp(confidence + min(abs(score) * 0.05, 0.12), 0.0, 0.78 if status is AgentStatus.PARTIAL else 0.90)

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
        summary=_summary(bias, status, confidence, options, expiry_structures),
        source_refs=source_refs,
        status=status,
        created_at=created_at,
        data_category=DataCategory.SYSTEM_INFERENCE,
        evidence_items=_options_evidence_items(options=options, bias=bias, confidence=confidence, source_refs=source_refs),
        input_payload={
            "bullish_drivers": bullish_drivers,
            "bearish_drivers": bearish_drivers,
        },
    )


def _input_snapshot_ids(snapshot: dict[str, Any]) -> dict[str, Any]:
    value = snapshot.get("input_snapshot_ids")
    ids = dict(value) if isinstance(value, dict) else {}
    snapshot_id = snapshot.get("snapshot_id")
    if snapshot_id is not None:
        ids.setdefault("analysis_snapshot", snapshot_id)
    return ids


def _source_refs(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    refs = snapshot.get("source_refs")
    return [dict(item) for item in refs if isinstance(item, dict)] if isinstance(refs, list) else []


def _options_evidence_items(
    *,
    options: dict[str, Any],
    bias: AgentBias,
    confidence: float,
    source_refs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    source_tier = "exchange" if str(_source_status(options) or "").upper() == "FINAL" else "exchange_prelim"
    base = {
        "agent": _AGENT_NAME,
        "module": _MODULE,
        "source_tier": source_tier,
        "confidence": confidence,
        "source_refs": [dict(ref) for ref in source_refs],
    }
    items: list[dict[str, Any]] = []
    intent = _dict(options.get("intent"))
    intent_score = _to_float(intent.get("score"))
    if intent_score is not None or intent.get("type"):
        items.append(
            {
                **base,
                "factor": "options_intent",
                "direction": _bias_from_score(intent_score or 0.0).value,
                "strength": min(abs(intent_score or 0.0), 1.0),
                "freshness": 1.0,
                "invalidation_hint": "Intent score changes sign or source status is not FINAL.",
            }
        )
    wall_scores = _list_of_dicts(options.get("wall_scores"))
    if wall_scores:
        top_wall = wall_scores[0]
        wall_score = _to_float(top_wall.get("wall_score"))
        direction_score = _direction_from_wall(top_wall) * (wall_score or 0.5)
        items.append(
            {
                **base,
                "factor": "option_wall",
                "direction": _bias_from_score(direction_score).value,
                "strength": min(abs(wall_score or 0.5), 1.0),
                "freshness": 1.0,
                "strike_or_level": top_wall.get("strike") or top_wall.get("price") or top_wall.get("level"),
                "invalidation_hint": "Top wall migrates, loses OI support, or volume confirms the opposite side.",
            }
        )
    gamma_zero = _dict(_dict(_dict(_dict(options.get("gex")).get("netgex_aggregate")).get("gamma_zero")))
    gamma_zero_price = _to_float(gamma_zero.get("price") or gamma_zero.get("level"))
    if gamma_zero_price is not None:
        items.append(
            {
                **base,
                "factor": "gamma_positioning",
                "direction": bias.value,
                "strength": confidence,
                "freshness": 1.0,
                "strike_or_level": gamma_zero_price,
                "invalidation_hint": "Price crosses gamma zero or net GEX regime flips.",
            }
        )
    return items


def _add_support_resistance(
    options: dict[str, Any],
    key_findings: list[str],
    risk_points: list[str],
    invalid_conditions: list[str],
) -> None:
    sr = _dict(options.get("support_resistance"))
    support = _first_with_number(sr.get("support"), ("strike", "price", "level"))
    resistance = _first_with_number(sr.get("resistance"), ("strike", "price", "level"))
    if support is not None:
        key_findings.append(f"Nearest options support is {support:g}.")
    if resistance is not None:
        key_findings.append(f"Nearest options resistance is {resistance:g}.")
    if support is None and resistance is None:
        risk_points.append("Support/resistance levels are unavailable from the precomputed options snapshot.")
        invalid_conditions.append("Support/resistance entries have no numeric strike/price/level fields.")


def _add_gex(
    options: dict[str, Any],
    key_findings: list[str],
    risk_points: list[str],
    invalid_conditions: list[str],
) -> None:
    aggregate = _dict(_dict(_dict(options.get("gex")).get("netgex_aggregate")))
    gamma_zero = _dict(aggregate.get("gamma_zero"))
    gamma_zero_price = _to_float(gamma_zero.get("price") or gamma_zero.get("level"))
    if gamma_zero_price is not None:
        key_findings.append(f"Aggregate gamma zero is {gamma_zero_price:g}.")
    else:
        invalid_conditions.append("Gamma zero price/level is missing; exact pin-zone level was not invented.")

    by_expiry = _dict(_dict(options.get("gex")).get("by_expiry"))
    summaries = []
    for expiry, data in by_expiry.items():
        summary = _dict(_dict(data).get("summary"))
        net_gex = _to_float(summary.get("net_gex") or summary.get("net_gex_total"))
        dominant_side = _text(summary.get("dominant_side"))
        if net_gex is not None or dominant_side:
            parts = [str(expiry)]
            if net_gex is not None:
                parts.append(f"net GEX {net_gex:g}")
            if dominant_side:
                parts.append(f"dominant {dominant_side}")
            summaries.append(" ".join(parts))
    if summaries:
        key_findings.append("GEX summaries: " + "; ".join(summaries[:3]) + ".")
    else:
        risk_points.append("Per-expiry GEX summaries are unavailable or incomplete.")


def _add_expiry_structure_findings(options: dict[str, Any], key_findings: list[str]) -> list[dict[str, Any]]:
    structures = _expiry_structures(options)
    for item in structures[:2]:
        expiry = item["expiry"]
        structure_label = item["structure_label"]
        net_gex = item["net_gex"]
        gamma_zero = item["gamma_zero"]
        f_value = item["f_value"]
        phrase = f"{expiry} {structure_label}"
        if net_gex is not None:
            phrase += f"，NetGEX {net_gex / 1_000_000:.2f}M"
        if f_value is not None and gamma_zero is not None:
            relation = "低于" if f_value < gamma_zero else "高于" if f_value > gamma_zero else "贴近"
            phrase += f"，F {f_value:g} {relation} Gamma Zero {gamma_zero:.1f}"
        elif gamma_zero is not None:
            phrase += f"，Gamma Zero {gamma_zero:.1f}"
        key_findings.append(phrase + "。")
    return structures


def _add_iv_skew(options: dict[str, Any], key_findings: list[str]) -> None:
    by_expiry = _dict(_dict(options.get("gex")).get("by_expiry"))
    for expiry, data in by_expiry.items():
        skew = _dict(_dict(data).get("iv_skew"))
        if not skew:
            continue
        metrics = []
        for key in ("risk_reversal_25d", "put_call_skew", "skew", "slope"):
            value = _to_float(skew.get(key))
            if value is not None:
                metrics.append(f"{key} {value:.2f}")
        if metrics:
            key_findings.append(f"IV skew for {expiry}: " + ", ".join(metrics[:3]) + ".")
            return


def _add_block_pnt(options: dict[str, Any], key_findings: list[str]) -> None:
    block_pnt = _list_of_dicts(_dict(options.get("walls")).get("block_pnt_walls"))
    if not block_pnt:
        return
    top = block_pnt[0]
    strike = _to_float(top.get("strike") or top.get("price") or top.get("level"))
    block = _to_float(top.get("block")) or 0.0
    pnt = _to_float(top.get("pnt")) or 0.0
    if strike is not None:
        key_findings.append(f"Block/PNT activity appears near {strike:g} with block {block:g} and PNT {pnt:g}.")
    else:
        key_findings.append(f"Block/PNT activity is present with block {block:g} and PNT {pnt:g}, but no exact level is available.")


def _add_expiration_summary(options: dict[str, Any], key_findings: list[str]) -> None:
    expiries = _list(_dict(options.get("data_source")).get("expiries"))
    if expiries:
        key_findings.append("Expiration coverage: " + ", ".join(str(item) for item in expiries[:5]) + ".")
    roll_signals = _list_of_dicts(options.get("roll_signals"))
    if roll_signals:
        parts: list[str] = []
        for signal in roll_signals[:2]:
            roll_type = _text(signal.get("roll_type"))
            near = _text(signal.get("near_expiry"))
            far = _text(signal.get("far_expiry"))
            confidence = _to_float(signal.get("confidence"))
            phrase = roll_type or "roll"
            if near or far:
                phrase += f" {near or '?'}->{far or '?'}"
            if confidence is not None:
                phrase += f" ({confidence:.2f})"
            parts.append(phrase)
        if parts:
            key_findings.append("Expiration roll signals: " + "; ".join(parts) + ".")
        else:
            key_findings.append(f"Expiration roll signals available: {len(roll_signals)}.")


def _source_status(options: dict[str, Any]) -> str:
    return _text(_dict(options.get("data_source")).get("status"))


def _prelim_count(options: dict[str, Any]) -> float:
    categories = _dict(_dict(options.get("data_quality")).get("categories"))
    return _to_float(categories.get("prelim_data")) or 0.0


def _data_quality_warnings(options: dict[str, Any]) -> list[str]:
    warnings = _list(_dict(options.get("data_quality")).get("warnings"))
    return [str(warning) for warning in warnings if warning]


def _has_numeric_price(options: dict[str, Any]) -> bool:
    if _first_with_number(options.get("wall_scores"), ("strike", "price", "level")) is not None:
        return True
    sr = _dict(options.get("support_resistance"))
    if _first_with_number(sr.get("support"), ("strike", "price", "level")) is not None:
        return True
    if _first_with_number(sr.get("resistance"), ("strike", "price", "level")) is not None:
        return True
    gamma_zero = _dict(_dict(_dict(_dict(options.get("gex")).get("netgex_aggregate")).get("gamma_zero")))
    return _to_float(gamma_zero.get("price") or gamma_zero.get("level")) is not None


def _first_with_number(value: Any, keys: tuple[str, ...]) -> float | None:
    for item in _list_of_dicts(value):
        for key in keys:
            number = _to_float(item.get(key))
            if number is not None:
                return number
    return None


def _wall_label(wall: dict[str, Any]) -> str:
    for key in ("wall_type", "side", "type"):
        value = _text(wall.get(key))
        if value:
            return value
    return "unknown wall"


def _direction_from_wall(wall: dict[str, Any]) -> float:
    text = " ".join(_text(wall.get(key)).lower() for key in ("wall_type", "side", "type"))
    if "support" in text or "put" in text:
        return 1.0
    if "resistance" in text or "call" in text:
        return -1.0
    return 0.0


def _bias_from_score(score: float) -> AgentBias:
    if score >= 0.35:
        return AgentBias.BULLISH
    if score <= -0.35:
        return AgentBias.BEARISH
    if score != 0:
        return AgentBias.MIXED
    return AgentBias.NEUTRAL


def _directional_drivers(options: dict[str, Any]) -> tuple[list[str], list[str]]:
    support, resistance = _support_resistance_levels(options)
    bullish = [f"put/support wall at {support:g}"] if support is not None else []
    bearish = [f"call/resistance wall at {resistance:g}"] if resistance is not None else []
    return bullish, bearish


def _summary(
    bias: AgentBias,
    status: AgentStatus,
    confidence: float,
    options: dict[str, Any],
    expiry_structures: list[dict[str, Any]],
) -> str:
    aggregate_gamma_zero = _aggregate_gamma_zero(options)
    support, resistance = _support_resistance_levels(options)
    source_status = _source_status(options).upper()
    if expiry_structures:
        phrases: list[str] = []
        if aggregate_gamma_zero is not None:
            phrases.append(f"跨月 Gamma Zero 约 {aggregate_gamma_zero:.1f}")
        if len(expiry_structures) >= 2:
            first = expiry_structures[0]
            second = expiry_structures[1]
            same_structure = first["structure_label"] == second["structure_label"]
            same_side = first["position_vs_gamma_zero"] == second["position_vs_gamma_zero"] and first["position_vs_gamma_zero"] != "unknown"
            if same_structure and same_side:
                relation = {"below": "均低于", "above": "均高于", "near": "均贴近"}.get(first["position_vs_gamma_zero"], "均围绕")
                phrases.append(
                    f"{first['expiry']} / {second['expiry']} {relation}各自零轴，且{first['structure_label']}"
                )
            else:
                phrases.append(_summary_phrase_for_expiry(first))
                phrases.append(_summary_phrase_for_expiry(second))
        else:
            phrases.append(_summary_phrase_for_expiry(expiry_structures[0]))
        if support is not None or resistance is not None:
            sr_parts: list[str] = []
            if support is not None:
                sr_parts.append(f"{support:g} 附近支撑")
            if resistance is not None:
                sr_parts.append(f"{resistance:g} 上方初阻")
            phrases.append("、".join(sr_parts))
        prefix = "CME 期权 PRELIM 只读结构" if source_status and source_status != "FINAL" else "CME 期权只读结构"
        suffix = "，仍需等待 FINAL 确认" if status is AgentStatus.PARTIAL else ""
        return f"{prefix}：{'；'.join(phrases)}；确信度 {confidence:.2f}{suffix}。"
    if status is AgentStatus.PARTIAL:
        return f"CME 期权只读视图 {bias.value}（输入不完整/临时）；确信度 {confidence:.2f}。"
    return f"CME 期权只读视图 {bias.value}；确信度 {confidence:.2f}。"


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    return [item for item in _list(value) if isinstance(item, dict)]


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _to_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ── P4-06: multi-day calibration findings ─────────────────────────────


def _add_calibration_findings(
    options: dict[str, Any],
    key_findings: list[str],
    risk_points: list[str],
) -> None:
    """Extract calibration findings from the options snapshot."""
    cal = _dict(options.get("calibration"))
    if not cal:
        return

    method = _text(cal.get("calculation_method"))
    if method and method != "unavailable":
        key_findings.append(f"Multi-day wall calibration available (method: {method}).")

    # OI deltas
    oi_deltas = _dict(cal.get("oi_change_by_strike"))
    if oi_deltas:
        # Report the 3 largest OI changes
        by_total = sorted(
            [(int(s), d.get("total_oi_delta", 0)) for s, d in oi_deltas.items()],
            key=lambda x: abs(x[1]),
            reverse=True,
        )[:3]
        if by_total:
            parts = [f"{s} ({'+' if d > 0 else ''}{d})" for s, d in by_total]
            key_findings.append("Largest OI deltas vs prior day: " + ", ".join(parts) + ".")

    # Wall score changes
    score_delta = _dict(cal.get("wall_score_delta_1d"))
    if score_delta:
        top_changes = sorted(score_delta.items(), key=lambda x: abs(x[1]), reverse=True)[:2]
        if top_changes:
            parts = [f"{k}: {'+' if v > 0 else ''}{v:.3f}" for k, v in top_changes]
            key_findings.append("Wall score changes (1d): " + "; ".join(parts) + ".")

    # Roll signals
    roll_list = cal.get("expiry_roll_signal")
    if isinstance(roll_list, list):
        for sig in roll_list:
            sig_dict = _dict(sig)
            activity = _text(sig_dict.get("roll_activity"))
            if activity and activity != "none":
                near = _text(sig_dict.get("near_month", ""))
                next_m = _text(sig_dict.get("next_month", ""))
                conf = sig_dict.get("roll_confidence", 0)
                key_findings.append(
                    f"Expiry roll {activity} ({near} → {next_m}, confidence {conf:.2f})."
                )

    # Calibration warnings
    warnings = cal.get("calibration_warnings")
    if isinstance(warnings, list) and warnings:
        risk_points.extend(str(w) for w in warnings[:2])


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, round(value, 2)))


def _aggregate_gamma_zero(options: dict[str, Any]) -> float | None:
    aggregate = _dict(_dict(_dict(options.get("gex")).get("netgex_aggregate")))
    gamma_zero = _dict(aggregate.get("gamma_zero"))
    return _to_float(gamma_zero.get("price") or gamma_zero.get("level"))


def _expiry_structures(options: dict[str, Any]) -> list[dict[str, Any]]:
    by_expiry = _dict(_dict(options.get("gex")).get("by_expiry"))
    expiry_order = {
        str(expiry): index for index, expiry in enumerate(_list(_dict(options.get("data_source")).get("expiries")))
    }
    structures: list[dict[str, Any]] = []
    for expiry, data in by_expiry.items():
        summary = _dict(_dict(data).get("summary"))
        if not summary:
            continue
        net_gex = _to_float(summary.get("net_gex") or summary.get("net_gex_total"))
        call_gex = _to_float(summary.get("call_gex"))
        put_gex = _to_float(summary.get("put_gex"))
        gamma_zero = _to_float(summary.get("gamma_zero"))
        f_value = _to_float(summary.get("f_value") or summary.get("f"))
        structure_text = _text(summary.get("structure"))
        structure_label = _structure_label(structure_text, net_gex, call_gex, put_gex)
        if f_value is not None and gamma_zero is not None:
            if abs(f_value - gamma_zero) <= max(abs(gamma_zero), 1.0) * 0.002:
                position_vs_gamma_zero = "near"
            elif f_value < gamma_zero:
                position_vs_gamma_zero = "below"
            else:
                position_vs_gamma_zero = "above"
        else:
            position_vs_gamma_zero = "unknown"
        structures.append(
            {
                "expiry": str(expiry),
                "net_gex": net_gex,
                "call_gex": call_gex,
                "put_gex": put_gex,
                "gamma_zero": gamma_zero,
                "f_value": f_value,
                "structure_label": structure_label,
                "position_vs_gamma_zero": position_vs_gamma_zero,
            }
        )
    structures.sort(key=lambda item: expiry_order.get(item["expiry"], len(expiry_order)))
    return structures


def _structure_label(
    structure_text: str,
    net_gex: float | None,
    call_gex: float | None,
    put_gex: float | None,
) -> str:
    lower = structure_text.lower()
    if "put" in lower:
        return "Put-GEX 主导"
    if "call" in lower:
        return "Call-GEX 主导"
    if "pin" in lower or "balance" in lower or "rebalance" in lower:
        return "双边再平衡"
    if net_gex is not None:
        if abs(net_gex) <= max(abs(call_gex or 0.0) + abs(put_gex or 0.0), 1.0) * 0.05:
            return "双边再平衡"
        if net_gex < 0:
            return "Put-GEX 主导"
        if net_gex > 0:
            return "Call-GEX 主导"
    return "结构待确认"


def _structure_score(expiry_structures: list[dict[str, Any]]) -> float:
    score = 0.0
    for index, item in enumerate(expiry_structures[:2]):
        weight = 1.0 if index == 0 else 0.85
        label = item["structure_label"]
        position = item["position_vs_gamma_zero"]
        if "Put-GEX" in label:
            score -= 0.28 * weight
        elif "Call-GEX" in label:
            score += 0.28 * weight
        if position == "below":
            score -= 0.14 * weight
        elif position == "above":
            score += 0.14 * weight
    return score


def _structure_confidence_bonus(expiry_structures: list[dict[str, Any]]) -> float:
    if not expiry_structures:
        return 0.0
    bonus = 0.05
    if len(expiry_structures) >= 2:
        bonus += 0.04
        first, second = expiry_structures[0], expiry_structures[1]
        if first["structure_label"] == second["structure_label"]:
            bonus += 0.04
        if first["position_vs_gamma_zero"] == second["position_vs_gamma_zero"] and first["position_vs_gamma_zero"] != "unknown":
            bonus += 0.03
    if all(item["gamma_zero"] is not None for item in expiry_structures[:2]):
        bonus += 0.03
    return bonus


def _summary_phrase_for_expiry(item: dict[str, Any]) -> str:
    expiry = item["expiry"]
    label = item["structure_label"]
    position = item["position_vs_gamma_zero"]
    gamma_zero = item["gamma_zero"]
    if position == "below" and gamma_zero is not None:
        return f"{expiry} 当前低于 Gamma Zero {gamma_zero:.1f}，{label}"
    if position == "above" and gamma_zero is not None:
        return f"{expiry} 当前高于 Gamma Zero {gamma_zero:.1f}，{label}"
    if gamma_zero is not None:
        return f"{expiry} 围绕 Gamma Zero {gamma_zero:.1f}，{label}"
    return f"{expiry} {label}"


def _support_resistance_levels(options: dict[str, Any]) -> tuple[float | None, float | None]:
    sr = _dict(options.get("support_resistance"))
    support = _first_with_number(sr.get("support"), ("strike", "price", "level"))
    resistance = _first_with_number(sr.get("resistance"), ("strike", "price", "level"))
    return support, resistance
