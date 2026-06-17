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

    bias = _bias_from_score(score)
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
        summary=_summary(bias, status, confidence),
        source_refs=source_refs,
        status=status,
        created_at=created_at,
        data_category=DataCategory.SYSTEM_INFERENCE,
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
    roll_signals = _list(options.get("roll_signals"))
    if roll_signals:
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


def _summary(bias: AgentBias, status: AgentStatus, confidence: float) -> str:
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
