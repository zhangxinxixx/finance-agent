"""Pure read-model builder for the CME options decision endpoint.

This module deliberately accepts already-loaded snapshots and rows.  Database,
filesystem, and market-data access belong to the API service layer.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable, Mapping

from apps.features.options.black76 import sort_expiry_codes


SCHEMA_VERSION = "cme_options_decision.v1"
_MODEL_GEX_NOTICE = "Model GEX is a Black-76/proxy estimate, not real dealer inventory."
_NEARBY_OI_DISTANCE_PCT = 6.0


def build_options_decision(
    snapshot: Mapping[str, Any],
    *,
    current_rows: Iterable[Any],
    previous_rows: Iterable[Any] | None = None,
    previous_snapshot: Mapping[str, Any] | None = None,
    history_rows_by_date: Mapping[str, Iterable[Any]] | None = None,
    live_price_context: Mapping[str, Any] | None = None,
    lookback_days: int = 5,
    endpoint: str | None = None,
) -> dict[str, Any]:
    """Build the stable options-decision ViewModel without side effects."""
    current = [_row_dict(row) for row in current_rows]
    previous = None if previous_rows is None else [_row_dict(row) for row in previous_rows]
    trade_date = str(snapshot.get("trade_date") or _first(current, "trade_date") or "")
    previous_trade_date = _first(previous or [], "trade_date") if previous is not None else None
    history = {str(date): [_row_dict(row) for row in rows] for date, rows in (history_rows_by_date or {}).items()}
    live = dict(live_price_context or {})
    prices = _price_context(snapshot, live)
    usable_live_p0 = _usable_live_p0(prices)
    gamma = _gamma_summary(snapshot, usable_live_p0)
    previous_gamma = _gamma_summary(previous_snapshot or {}, None) if previous_snapshot else None
    oi_summary = _aggregate_oi(current, previous)
    by_expiry = _oi_by_expiry(current, previous)
    rankings = _oi_rankings(current, previous)
    report_reference = _number_or_none(prices.get("report_p0"))
    position_reference = report_reference or usable_live_p0
    position_reference_source = "report_p0" if report_reference is not None else "live_p0_fallback"
    large_oi_levels = _large_oi_levels(current, previous, reference_price=position_reference)
    nearby_large_oi_levels = _large_oi_levels(
        current,
        previous,
        reference_price=position_reference,
        distance_limit_pct=_NEARBY_OI_DISTANCE_PCT,
    )
    key_levels = _key_levels(snapshot, prices, gamma, live_p0=usable_live_p0)
    gamma_changes = _gamma_changes(gamma, previous_gamma)
    roll = _roll_summary(by_expiry)
    pnt_summary = _pnt_summary(current)
    history_count = sum(1 for rows in history.values() if rows)
    if trade_date and current and trade_date not in history:
        history_count += 1

    intraday = _intraday_strategy(gamma, key_levels, usable_live_p0)
    swing = _swing_strategy(history, current, roll, key_levels)
    intent_summary = _intent_summary(snapshot)
    structure_summary = _structure_summary(
        gamma=gamma,
        gamma_changes=gamma_changes,
        prices=prices,
        swing=swing,
        intent=intent_summary,
    )
    scenario_paths = _scenario_paths(intraday, structure_summary, key_levels, gamma)
    warnings = _warnings(snapshot)
    warnings.extend(pnt_summary.get("warnings") or [])
    if previous is None:
        warnings.append("Previous-trade-date CME rows are unavailable; 1d comparisons are null.")
    if usable_live_p0 is None:
        warnings.append("Canonical XAUUSD 5m live price is unavailable; intraday strategy is disabled.")
        if prices.get("live_price_status") not in {None, "fresh", "unavailable"}:
            warnings.append(f"Canonical XAUUSD 5m live price is {prices['live_price_status']}.")
        if prices.get("live_price_coverage_status") == "degraded":
            warnings.append("Canonical XAUUSD 5m coverage is degraded.")
    if gamma["gamma_zero"] is None:
        warnings.append("Gamma Zero is unavailable; gamma regime is disabled.")
    warnings.append(_MODEL_GEX_NOTICE)

    source_refs, artifact_refs = _lineage(snapshot, endpoint or _endpoint(trade_date))
    status = "available"
    if not current:
        status = "unavailable"
    elif previous is None or intraday["status"] != "available" or swing["status"] != "available":
        status = "partial"

    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "meta": {
            "current_trade_date": trade_date or None,
            "previous_trade_date": previous_trade_date,
            "product": _nested(snapshot, "data_source", "product") or _first(current, "product_code") or "OG",
            "lookback_days": lookback_days,
            "comparison_status": oi_summary["comparison_status"],
        },
        "executive_summary": _executive_summary(oi_summary, gamma, roll, intraday),
        "price_context": prices,
        "oi_summary": oi_summary,
        "oi_by_expiry": by_expiry,
        "oi_change_rankings": rankings,
        "large_oi_levels": large_oi_levels,
        "nearby_large_oi_levels": nearby_large_oi_levels,
        "pnt_summary": pnt_summary,
        "gamma_summary": gamma,
        "gamma_profile": _gamma_profile(snapshot),
        "gamma_changes": gamma_changes,
        "key_levels": key_levels,
        "wall_changes": _wall_changes(snapshot, previous_snapshot),
        "iv_skew_summary": _iv_skew(snapshot),
        "roll_summary": roll,
        "intent_summary": intent_summary,
        "structure_summary": structure_summary,
        "scenario_paths": scenario_paths,
        "intraday_strategy": intraday,
        "swing_strategy": swing,
        "data_quality": {
            "cme_status": _nested(snapshot, "data_source", "status") or _versions(current),
            "previous_trade_date": previous_trade_date,
            "lookback_sample_count": history_count,
            "black76_proxy_coverage": _proxy_coverage(snapshot),
            "live_price_context": {
                "status": prices.get("live_price_status"),
                "timestamp": prices.get("live_p0_timestamp"),
                "source": prices.get("live_p0_source"),
                "freshness_seconds": prices.get("live_price_freshness_seconds"),
                "coverage_status": prices.get("live_price_coverage_status"),
            },
            "gamma_zero_method": gamma.get("method"),
            "position_reference_price": position_reference,
            "position_reference_source": position_reference_source,
            "warnings": _unique(warnings),
            "model_gex_notice": _MODEL_GEX_NOTICE,
        },
        "source_refs": source_refs,
        "artifact_refs": artifact_refs,
    }


# Explicit alias for callers that prefer the ViewModel-oriented name.
build_options_decision_view_model = build_options_decision


def _row_dict(row: Any) -> dict[str, Any]:
    if isinstance(row, Mapping):
        return dict(row)
    return {
        name: getattr(row, name, None)
        for name in (
            "trade_date",
            "report_date",
            "product_code",
            "expiry",
            "strike",
            "option_type",
            "open_interest",
            "oi_change",
            "total_volume",
            "block_volume",
            "pnt_volume",
            "version_type",
            "raw_file_id",
        )
    }


def _aggregate_oi(current: list[dict[str, Any]], previous: list[dict[str, Any]] | None) -> dict[str, Any]:
    result: dict[str, Any] = {"comparison_status": "available" if previous is not None else "unavailable"}
    for label, option_type in (("total", None), ("call", "CALL"), ("put", "PUT")):
        now = _oi_total(current, option_type)
        before = _oi_total(previous, option_type) if previous is not None else None
        delta = now - before if before is not None else None
        result[label] = {
            "current": now,
            "previous": before,
            "delta": delta,
            "pct_change": _pct(delta, before),
        }
    return result


def _oi_by_expiry(current: list[dict[str, Any]], previous: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    current_groups = _group_expiry(current)
    previous_groups = _group_expiry(previous or [])
    rows: list[dict[str, Any]] = []
    for expiry in sorted(set(current_groups) | set(previous_groups)):
        now_rows = current_groups.get(expiry, [])
        old_rows = previous_groups.get(expiry, []) if previous is not None else None
        summary = _aggregate_oi(now_rows, old_rows)
        rows.append({"expiry": expiry, "expiry_scope": "contract_expiry", **summary})
    return rows


def _oi_rankings(current: list[dict[str, Any]], previous: list[dict[str, Any]] | None) -> dict[str, Any]:
    if previous is None:
        return {"comparison_status": "unavailable", "largest_increases": [], "largest_decreases": []}
    current_index = {_row_key(row): row for row in current}
    previous_index = {_row_key(row): row for row in previous}
    changes: list[dict[str, Any]] = []
    for key in set(current_index) | set(previous_index):
        row = current_index.get(key, {})
        old_row = previous_index.get(key, {})
        current_oi = _number(row.get("open_interest"))
        previous_oi = _number(old_row.get("open_interest"))
        delta = current_oi - previous_oi
        changes.append(
            {
                "expiry": row.get("expiry") or old_row.get("expiry"),
                "strike": row.get("strike") if row else old_row.get("strike"),
                "option_type": row.get("option_type") or old_row.get("option_type"),
                "current_oi": current_oi,
                "previous_oi": previous_oi,
                "delta": delta,
                "volume": _number_or_none(row.get("total_volume")),
                "block": _number_or_none(row.get("block_volume")),
                "pnt": _number_or_none(row.get("pnt_volume")),
            }
        )
    return {
        "comparison_status": "available",
        "largest_increases": sorted(changes, key=lambda item: item["delta"], reverse=True)[:10],
        "largest_decreases": sorted(changes, key=lambda item: item["delta"])[:10],
    }


def _large_oi_levels(
    current: list[dict[str, Any]],
    previous: list[dict[str, Any]] | None,
    *,
    reference_price: float | None,
    distance_limit_pct: float | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Aggregate absolute OI by expiry/strike without conflating it with WallScore."""
    groups: dict[tuple[str, float], dict[str, Any]] = {}
    previous_totals: dict[tuple[str, float], float] | None = None
    if previous is not None:
        previous_totals = defaultdict(float)
        for row in previous:
            expiry = str(row.get("expiry") or "")
            strike = _number_or_none(row.get("strike"))
            if not expiry or strike is None:
                continue
            previous_totals[(expiry, strike)] += _number(row.get("open_interest"))

    for row in current:
        expiry = str(row.get("expiry") or "")
        strike = _number_or_none(row.get("strike"))
        if not expiry or strike is None:
            continue
        key = (expiry, strike)
        group = groups.setdefault(
            key,
            {
                "expiry": expiry,
                "strike": strike,
                "call_oi": 0.0,
                "put_oi": 0.0,
                "total_oi": 0.0,
                "total_oi_change": None,
                "volume": 0.0,
                "distance_pct": ((strike - reference_price) / reference_price * 100) if reference_price else None,
            },
        )
        option_type = str(row.get("option_type") or "").upper()
        open_interest = _number(row.get("open_interest"))
        if option_type == "CALL":
            group["call_oi"] += open_interest
        elif option_type == "PUT":
            group["put_oi"] += open_interest
        group["total_oi"] += open_interest
        group["volume"] += _number(row.get("total_volume"))

    for key, group in groups.items():
        if previous_totals is not None:
            group["total_oi_change"] = group["total_oi"] - previous_totals.get(key, 0.0)
        group["dominant_side"] = (
            "CALL" if group["call_oi"] > group["put_oi"] else "PUT" if group["put_oi"] > group["call_oi"] else "BALANCED"
        )

    candidates = [
        group
        for group in groups.values()
        if distance_limit_pct is None
        or (
            group["distance_pct"] is not None
            and abs(group["distance_pct"]) <= distance_limit_pct
        )
    ]
    ranked = sorted(
        candidates,
        key=lambda item: (-item["total_oi"], abs(item["distance_pct"]) if item["distance_pct"] is not None else float("inf")),
    )
    return ranked[:limit]


def _pnt_summary(current: list[dict[str, Any]], *, limit: int = 10) -> dict[str, Any]:
    activity: list[dict[str, Any]] = []
    totals = {"call": 0.0, "put": 0.0, "total": 0.0}
    pnt_totals = {"call": 0.0, "put": 0.0, "total": 0.0}
    block_totals = {"call": 0.0, "put": 0.0, "total": 0.0}
    for row in current:
        pnt = _number(row.get("pnt_volume"))
        block = _number(row.get("block_volume"))
        amount = pnt + block
        option_type = str(row.get("option_type") or "").upper()
        if pnt > 0:
            pnt_totals["total"] += pnt
            if option_type == "CALL":
                pnt_totals["call"] += pnt
            elif option_type == "PUT":
                pnt_totals["put"] += pnt
        if block > 0:
            block_totals["total"] += block
            if option_type == "CALL":
                block_totals["call"] += block
            elif option_type == "PUT":
                block_totals["put"] += block
        if amount <= 0:
            continue
        if option_type == "CALL":
            totals["call"] += amount
        elif option_type == "PUT":
            totals["put"] += amount
        totals["total"] += amount
        activity.append(
            {
                "expiry": row.get("expiry"),
                "strike": _number_or_none(row.get("strike")),
                "option_type": option_type or None,
                "pnt": pnt,
                "block": block,
                "total_activity": amount,
                "open_interest": _number_or_none(row.get("open_interest")),
                "oi_change": _number_or_none(row.get("oi_change")),
                "volume": _number_or_none(row.get("total_volume")),
            }
        )
    activity.sort(key=lambda item: item["total_activity"], reverse=True)
    status = "available" if activity else "unavailable"
    block_coverage_status = "observed" if block_totals["total"] > 0 else ("not_verified" if activity else "unavailable")
    warnings: list[str] = []
    if block_coverage_status == "not_verified":
        warnings.append("Block volume has no non-zero observed rows; treat Block totals as not verified.")
    return {
        "status": status,
        "totals": totals,
        "pnt_totals": pnt_totals,
        "block_totals": block_totals,
        "block_coverage_status": block_coverage_status,
        "warnings": warnings,
        "top_activity": activity[:limit],
    }


def _intent_summary(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    intent = _nested(snapshot, "intent") or {}
    audit = _nested(snapshot, "audit", "intent_audit") or {}
    return {
        "type": intent.get("type") or audit.get("intent_label"),
        "score": _number_or_none(intent.get("score")),
        "confidence": _number_or_none(intent.get("confidence")),
        "wording": audit.get("wording"),
        "scores": {
            "I1_defensive": _number_or_none(audit.get("defense_score")),
            "I2_structured_rebalance": _number_or_none(audit.get("rebalance_score")),
            "I3_trap": _number_or_none(audit.get("trap_score")),
            "I4_trend_launch": _number_or_none(audit.get("trend_score")),
        },
        "evidence": [str(item) for item in intent.get("evidence") or []],
    }


def _structure_summary(
    *,
    gamma: Mapping[str, Any],
    gamma_changes: Mapping[str, Any],
    prices: Mapping[str, Any],
    swing: Mapping[str, Any],
    intent: Mapping[str, Any],
) -> dict[str, Any]:
    net_gex = _number_or_none(gamma.get("net_gex"))
    net_gex_change = _number_or_none(gamma_changes.get("net_gex_change_1d"))
    gamma_zero = _number_or_none(gamma.get("gamma_zero"))
    reference_price = _number_or_none(prices.get("live_p0")) or _number_or_none(prices.get("report_p0"))
    below_zero = reference_price is not None and gamma_zero is not None and reference_price < gamma_zero
    repair = net_gex is not None and net_gex < 0 and net_gex_change is not None and net_gex_change > 0
    call_change = _number_or_none(swing.get("call_oi_change"))
    put_change = _number_or_none(swing.get("put_oi_change"))
    trend_watch = repair and call_change is not None and call_change > max(put_change or 0.0, 0.0)
    trend_confirmed = net_gex is not None and net_gex >= 0 and not below_zero
    state = (
        "trend_confirmed"
        if trend_confirmed
        else "negative_gamma_repair"
        if repair
        else "negative_gamma_defensive"
        if net_gex is not None and net_gex < 0
        else "balanced"
        if net_gex is not None
        else "unavailable"
    )
    labels = {
        "trend_confirmed": "正 Gamma 趋势确认",
        "negative_gamma_repair": "负 Gamma 区内结构修复",
        "negative_gamma_defensive": "负 Gamma 防守结构",
        "balanced": "结构接近平衡",
        "unavailable": "结构不可用",
    }
    return {
        "state": state,
        "label": labels[state],
        "reference_price": reference_price,
        "gamma_zero": gamma_zero,
        "below_gamma_zero": below_zero,
        "net_gex": net_gex,
        "net_gex_change": net_gex_change,
        "repair_detected": repair,
        "trend_launch_watch": trend_watch,
        "trend_confirmed": trend_confirmed,
        "intent_type": intent.get("type"),
        "intent_wording": intent.get("wording"),
        "summary": (
            f"{labels[state]}；"
            + ("当前仍在 Gamma Zero 下方，转强尚未确认。" if below_zero else "当前价格已不在 Gamma Zero 下方。")
        ),
    }


def _scenario_paths(
    intraday: Mapping[str, Any],
    structure: Mapping[str, Any],
    levels: list[dict[str, Any]],
    gamma: Mapping[str, Any],
) -> list[dict[str, Any]]:
    gamma_zero = _number_or_none(gamma.get("gamma_zero"))
    if gamma_zero is None or not levels:
        return []
    long_setup = intraday.get("long_setup") if isinstance(intraday.get("long_setup"), Mapping) else {}
    short_setup = intraday.get("short_setup") if isinstance(intraday.get("short_setup"), Mapping) else {}
    no_trade_zone = [_number(item) for item in intraday.get("no_trade_zone") or []]
    supports = _unique_numbers(_level_values(levels, {"primary_support", "secondary_support", "tail_protection"}))
    resistances = _unique_numbers(_level_values(levels, {"primary_resistance", "secondary_resistance"}))
    hubs = _unique_numbers(_level_values(levels, {"magnet_pin", "volatility_hub"}))
    structural_targets = sorted(_unique_numbers([gamma_zero] + hubs + resistances))
    downside_targets = sorted(supports, reverse=True)
    base_targets = no_trade_zone or structural_targets[:3]
    long_triggers = [str(item) for item in long_setup.get("triggers") or []] or [
        "price accepts above the Gamma Flip band and confirms on retest",
        "subsequent CME trade dates retain or improve Call OI participation",
    ]
    short_triggers = [str(item) for item in short_setup.get("triggers") or []] or [
        "primary support breaks with price acceptance and the retest fails",
        "Put protection and downside skew strengthen again",
    ]
    long_targets = [_number(item) for item in long_setup.get("targets") or []] or [
        value for value in structural_targets if value > gamma_zero
    ][:4]
    short_targets = [_number(item) for item in short_setup.get("targets") or []] or downside_targets[:4]
    long_invalidation = [str(item) for item in long_setup.get("invalidation") or []] or [
        f"price falls back below Gamma Flip {gamma_zero:g}",
        "the reclaimed structure cannot hold on retest",
    ]
    short_invalidation = [str(item) for item in short_setup.get("invalidation") or []] or [
        f"broken support {supports[0]:g} is reclaimed and held" if supports else "broken support is reclaimed and held",
    ]
    return [
        {
            "path_id": "base_repair_range",
            "label": "主路径：修复震荡",
            "status": "active" if structure.get("repair_detected") else "watch",
            "triggers": [
                "primary support remains defended while price rotates toward the Gamma Flip band",
            ],
            "targets": base_targets,
            "invalidation": [
                f"primary support {supports[0]:g} breaks with acceptance" if supports else "structural support evidence becomes unavailable",
            ],
        },
        {
            "path_id": "bullish_acceptance",
            "label": "转强路径：接受 Gamma 翻转带",
            "status": "confirmed" if structure.get("trend_confirmed") else "watch",
            "triggers": long_triggers,
            "targets": long_targets,
            "invalidation": long_invalidation,
        },
        {
            "path_id": "bearish_breakdown",
            "label": "转弱路径：支撑失守",
            "status": "watch",
            "triggers": short_triggers,
            "targets": short_targets,
            "invalidation": short_invalidation,
        },
    ]


def _gamma_summary(snapshot: Mapping[str, Any], live_p0: float | None) -> dict[str, Any]:
    aggregate = _nested(snapshot, "gex", "netgex_aggregate") or {}
    gamma_zero = _number_or_none(_nested(aggregate, "gamma_zero", "price"))
    grid = [value for value in (_nested(aggregate, "price_grid") or []) if _number_or_none(value) is not None]
    step = _strike_step(grid)
    band = (
        {"lower": gamma_zero - step / 2, "upper": gamma_zero + step / 2, "step": step}
        if gamma_zero is not None and step
        else None
    )
    if live_p0 is None or gamma_zero is None:
        regime = "unavailable"
    elif band and band["lower"] <= live_p0 <= band["upper"]:
        regime = "flip_zone"
    elif live_p0 < gamma_zero:
        regime = "negative_gamma"
    else:
        regime = "positive_gamma"
    return {
        "regime": regime,
        "net_gex": _net_gex(snapshot),
        "gamma_zero": gamma_zero,
        "method": _nested(aggregate, "gamma_zero", "method"),
        "flip_band": band,
        "live_price": live_p0,
    }


def _price_context(snapshot: Mapping[str, Any], live: Mapping[str, Any]) -> dict[str, Any]:
    params = _nested(snapshot, "parameters") or {}
    report = _number_or_none(params.get("report_p0", params.get("p0")))
    live_p0 = _number_or_none(live.get("price", live.get("close")))
    live_status = str(live.get("status") or ("fresh" if live_p0 is not None else "unavailable"))
    return {
        "report_p0": report,
        "report_p0_source": params.get("report_p0_source", params.get("p0_source")),
        "report_p0_timestamp": params.get("report_p0_timestamp"),
        "live_p0": live_p0,
        "live_p0_source": live.get("source") if live_p0 is not None else None,
        "live_p0_timestamp": (live.get("timestamp") or live.get("time")) if live_p0 is not None else None,
        "live_price_status": live_status,
        "live_price_freshness_seconds": live.get("freshness_seconds"),
        "live_price_coverage_status": live.get("coverage_status") or ("complete" if live_p0 is not None else "unavailable"),
        "model_f": dict(params.get("model_f") or params.get("forward_by_expiry") or {}),
        "price_anchor_rule": params.get("price_anchor_rule"),
    }


def _usable_live_p0(prices: Mapping[str, Any]) -> float | None:
    if prices.get("live_price_status") != "fresh":
        return None
    if prices.get("live_price_coverage_status") != "complete":
        return None
    return _number_or_none(prices.get("live_p0"))


def _key_levels(
    snapshot: Mapping[str, Any], prices: Mapping[str, Any], gamma: Mapping[str, Any], *, live_p0: float | None
) -> list[dict[str, Any]]:
    levels: list[dict[str, Any]] = []
    report_p0 = _number_or_none(prices.get("report_p0"))
    wall_scores = sorted(
        list(_nested(snapshot, "wall_scores") or []),
        key=lambda item: _number(item.get("wall_score")),
        reverse=True,
    )
    support_resistance = _nested(snapshot, "support_resistance") or {}
    if not wall_scores:
        for base_role, key in (("support", "support"), ("resistance", "resistance")):
            for index, item in enumerate(list(support_resistance.get(key) or [])[:3]):
                strike = _number_or_none(item.get("strike"))
                if strike is None:
                    continue
                role = f"{'primary' if index == 0 else 'secondary'}_{base_role}"
                levels.append(
                    _level(
                        strike=strike,
                        role=role,
                        strength=item.get("wall_score"),
                        live_p0=live_p0,
                        evidence=[
                            "snapshot support_resistance wall-score candidate",
                            f"wall_score={item.get('wall_score')}",
                        ],
                        invalidation=[f"price accepts through {strike}"],
                        expiry_scope="aggregate",
                    )
                )
    for wall in wall_scores:
        wall_type = str(wall.get("wall_type") or "").lower()
        strike = _number_or_none(wall.get("strike"))
        if strike is None:
            continue
        expiry_scope = str(wall.get("expiry") or "aggregate")
        total_gex = abs(_number(wall.get("gex")))
        net_gex = _number(wall.get("net_gex"))
        dominant = str(wall.get("dominant_side") or "").lower()
        evidence = [
            f"wall_type={wall_type or 'unknown'}",
            f"wall_score={wall.get('wall_score')}",
            f"oi={wall.get('oi')}",
            f"net_gex={wall.get('net_gex')}",
        ]
        if "pin" in wall_type:
            levels.append(
                _level(
                    strike=strike,
                    role="magnet_pin",
                    strength=wall.get("wall_score"),
                    live_p0=live_p0,
                    evidence=evidence,
                    invalidation=[f"price accepts away from {strike} and the pin wall weakens"],
                    expiry_scope=expiry_scope,
                )
            )
        if total_gex and abs(net_gex) / total_gex <= 0.25 and report_p0 and abs(strike - report_p0) / report_p0 <= 0.02:
            levels.append(
                _level(
                    strike=strike,
                    role="volatility_hub",
                    strength=wall.get("wall_score"),
                    live_p0=live_p0,
                    evidence=evidence + ["two-sided GEX is large while net GEX is comparatively balanced"],
                    invalidation=[f"price accepts outside the {strike} hub and two-sided activity fades"],
                    expiry_scope=expiry_scope,
                )
            )
        if report_p0 and strike < report_p0 and (dominant == "put" or net_gex < 0):
            role = (
                "primary_support"
                if not any(item["role"] == "primary_support" for item in levels)
                else "secondary_support"
            )
            levels.append(
                _level(
                    strike=strike,
                    role=role,
                    strength=wall.get("wall_score"),
                    live_p0=live_p0,
                    evidence=evidence + ["put-dominant model exposure below report_p0"],
                    invalidation=[f"accepted break below {strike}; negative-gamma conditions may amplify downside"],
                    expiry_scope=expiry_scope,
                )
            )
        if report_p0 and strike > report_p0 and (dominant == "call" or net_gex > 0):
            role = (
                "primary_resistance"
                if not any(item["role"] == "primary_resistance" for item in levels)
                else "secondary_resistance"
            )
            levels.append(
                _level(
                    strike=strike,
                    role=role,
                    strength=wall.get("wall_score"),
                    live_p0=live_p0,
                    evidence=evidence + ["call-dominant model exposure above report_p0"],
                    invalidation=[f"price accepts above {strike} while the call wall weakens or rolls"],
                    expiry_scope=expiry_scope,
                )
            )
    primary_support = next(
        (_number_or_none(level.get("strike")) for level in levels if level.get("role") == "primary_support"),
        None,
    )
    put_walls_below = [
        wall
        for wall in wall_scores
        if report_p0
        and _number_or_none(wall.get("strike")) is not None
        and _number(wall.get("strike")) < (primary_support or report_p0)
        and (str(wall.get("dominant_side") or "").lower() == "put" or _number(wall.get("net_gex")) < 0)
    ]
    if put_walls_below:
        tail = max(put_walls_below, key=lambda item: _number(item.get("wall_score")))
        strike = _number(tail.get("strike"))
        levels.append(
            _level(
                strike=strike,
                role="tail_protection",
                strength=tail.get("wall_score"),
                live_p0=live_p0,
                evidence=[
                    f"strongest put-dominant wall below primary support; oi={tail.get('oi')}",
                    f"net_gex={tail.get('net_gex')}",
                ],
                invalidation=[f"tail-protection OI weakens or price accepts below {strike}"],
                expiry_scope=str(tail.get("expiry") or "aggregate"),
            )
        )
    band = gamma.get("flip_band")
    if isinstance(band, Mapping):
        levels.append(
            _level(
                band=dict(band),
                role="gamma_flip",
                strength="high",
                live_p0=live_p0,
                evidence=["aggregate Gamma Zero price grid", f"method={gamma.get('method') or 'unknown'}"],
                invalidation=[f"price holds outside {band['lower']}-{band['upper']}"],
                expiry_scope="aggregate",
            )
        )
    return _select_key_levels(_dedupe_levels(levels))


def _level(
    *,
    role: str,
    strength: Any,
    live_p0: float | None,
    evidence: list[str],
    invalidation: list[str],
    expiry_scope: str,
    strike: float | None = None,
    band: dict[str, Any] | None = None,
) -> dict[str, Any]:
    reference = strike if strike is not None else (band["lower"] + band["upper"]) / 2 if band else None
    distance = ((reference - live_p0) / live_p0 * 100) if reference is not None and live_p0 else None
    structural_role = role
    current_relation = None
    dynamic_role = role
    if reference is not None and live_p0 is not None:
        current_relation = "below_price" if reference < live_p0 else "above_price" if reference > live_p0 else "at_price"
        if "resistance" in role and current_relation == "below_price":
            dynamic_role = "retest_support_candidate"
        elif "support" in role and current_relation == "above_price":
            dynamic_role = "retest_resistance_candidate"
    return {
        "strike": strike,
        "band": band,
        "role": role,
        "strength": strength,
        "trend": "unchanged",
        "evidence": evidence,
        "invalidation": invalidation,
        "expiry_scope": expiry_scope,
        "distance_pct": distance,
        "structural_role_at_report": structural_role,
        "current_relation": current_relation,
        "dynamic_role": dynamic_role,
    }


def _roll_summary(expiries: list[dict[str, Any]]) -> dict[str, Any]:
    by_expiry = {str(item["expiry"]): item for item in expiries}
    ranked = [by_expiry[expiry] for expiry in sort_expiry_codes(list(by_expiry))]
    if len(ranked) < 2 or any(item["comparison_status"] == "unavailable" for item in ranked):
        return {"status": "unavailable", "reason": "previous-trade-date expiry comparison unavailable", "items": []}
    items: list[dict[str, Any]] = []
    for near, far in zip(ranked, ranked[1:]):
        near_delta = near["total"]["delta"]
        far_delta = far["total"]["delta"]
        put_delta = far["put"]["delta"]
        call_delta = far["call"]["delta"]
        labels: list[str] = []
        if near_delta is not None and near_delta < 0:
            labels.append("near_month_outflow")
        if far_delta is not None and far_delta > 0:
            labels.append("far_month_inflow")
        if put_delta is not None and call_delta is not None and put_delta > call_delta:
            labels.append("put_dominant_roll")
        items.append(
            {
                "near_expiry": near["expiry"],
                "far_expiry": far["expiry"],
                "near_oi_delta": near_delta,
                "far_oi_delta": far_delta,
                "far_put_delta": put_delta,
                "far_call_delta": call_delta,
                "labels": labels,
            }
        )
    return {"status": "available", "items": items}


def _intraday_strategy(gamma: Mapping[str, Any], levels: list[dict[str, Any]], live_p0: float | None) -> dict[str, Any]:
    if live_p0 is None or gamma.get("regime") == "unavailable":
        reason = "live_p0 unavailable" if live_p0 is None else "Gamma Zero unavailable"
        return {
            "status": "unavailable",
            "horizon": "intraday",
            "reason": reason,
            "long_setup": None,
            "short_setup": None,
            "risk_notes": ["Do not fabricate an intraday decision without canonical live price and gamma regime."],
        }
    band = gamma.get("flip_band")
    downside = gamma["regime"] == "negative_gamma"
    flip_zone = gamma["regime"] == "flip_zone"
    supports = _level_values(levels, {"primary_support", "secondary_support", "tail_protection"})
    resistances = _level_values(levels, {"primary_resistance", "secondary_resistance"})
    hubs = _level_values(levels, {"magnet_pin", "volatility_hub"})
    flip_upper = _number_or_none(band.get("upper")) if isinstance(band, Mapping) else None
    long_targets = sorted(
        (value for value in _unique_numbers(supports + hubs + [flip_upper] + resistances) if value > live_p0)
    )[:4]
    short_targets = sorted(
        (value for value in _unique_numbers(supports + hubs + resistances) if value < live_p0),
        reverse=True,
    )[:4]
    long_triggers = [
        "primary support rejects a break and price reclaims the level",
        "price accepts above the Gamma Flip band and confirms on retest",
    ]
    short_triggers = [
        "primary support breaks with price acceptance and the retest fails",
        "price remains below the Gamma Flip band while downside walls strengthen",
    ]
    return {
        "status": "available",
        "horizon": "intraday",
        "regime": gamma["regime"],
        "bias": "defensive_repair" if downside else "flip_watch" if flip_zone else "mean_reversion",
        "summary": (
            "Model negative-gamma regime: wait for boundary confirmation because breaks may extend."
            if downside
            else "Model gamma-flip regime: wait for price acceptance outside the flip band."
            if flip_zone
            else "Model positive-gamma regime: prefer range reversion until price acceptance confirms a break."
        ),
        "no_trade_zone": sorted(_unique_numbers(hubs), key=lambda value: abs(value - live_p0))[:3],
        "long_setup": {
            "triggers": long_triggers,
            "targets": long_targets,
            "invalidation": [
                f"price accepts below structural support {supports[0]}"
                if supports
                else "structural support is unavailable",
                "Gamma regime deteriorates after entry",
            ],
        },
        "short_setup": {
            "triggers": short_triggers,
            "targets": short_targets,
            "invalidation": [
                f"price accepts above Gamma Flip {flip_upper}"
                if flip_upper is not None
                else "Gamma Flip is unavailable",
                "broken support is reclaimed and held",
            ],
        },
        "risk_notes": [
            "Static decision card only; this is not the #63 intraday state machine.",
            "Avoid chasing the first move through a two-sided volatility hub.",
            _MODEL_GEX_NOTICE,
        ],
        "confidence": 0.65 if supports or resistances else 0.45,
        "evidence_refs": ["gamma_summary", "key_levels", "price_context.live_p0"],
    }


def _swing_strategy(
    history: Mapping[str, list[dict[str, Any]]],
    current: list[dict[str, Any]],
    roll: Mapping[str, Any],
    levels: list[dict[str, Any]],
) -> dict[str, Any]:
    current_expiries = {str(row.get("expiry")) for row in current if row.get("expiry")}
    complete: list[tuple[str, list[dict[str, Any]]]] = []
    for date, rows in sorted(history.items()):
        expiries = {str(row.get("expiry")) for row in rows if row.get("expiry")}
        if rows and current_expiries and current_expiries <= expiries:
            complete.append((date, rows))
    if len(complete) < 3:
        return {
            "status": "unavailable",
            "reason": "insufficient_history",
            "sample_count": len(complete),
            "required_sample_count": 3,
        }

    first_date, first_rows = complete[0]
    last_date, last_rows = complete[-1]
    first = _aggregate_oi(first_rows, None)
    last = _aggregate_oi(last_rows, None)
    total_delta = last["total"]["current"] - first["total"]["current"]
    call_delta = last["call"]["current"] - first["call"]["current"]
    put_delta = last["put"]["current"] - first["put"]["current"]
    if put_delta > max(call_delta, 0):
        structure_bias = "defensive_to_neutral"
    elif call_delta > max(put_delta, 0):
        structure_bias = "constructive"
    elif total_delta > 0:
        structure_bias = "two_sided_expansion"
    else:
        structure_bias = "contracting"
    targets = _unique_numbers(_level_values(levels, {"gamma_flip", "primary_resistance", "secondary_resistance"}))
    invalidation_levels = _unique_numbers(
        _level_values(levels, {"primary_support", "secondary_support", "tail_protection"})
    )
    return {
        "status": "available",
        "horizon": "swing",
        "sample_count": len(complete),
        "sample_window": {"from": first_date, "to": last_date},
        "structure_bias": structure_bias,
        "oi_trend": "rising" if total_delta > 0 else "falling" if total_delta < 0 else "flat",
        "call_oi_change": call_delta,
        "put_oi_change": put_delta,
        "roll_regime": [item.get("labels", []) for item in roll.get("items", [])],
        "confirmation": [
            "price acceptance beyond Gamma Flip",
            "OI expansion persists across subsequent CME trade dates",
        ],
        "invalidation": [f"price accepts below {value}" for value in invalidation_levels]
        or ["structural support evidence becomes unavailable"],
        "targets": targets,
        "risk_notes": [
            "This multi-day view uses observed OI history and does not infer dealer inventory.",
            _MODEL_GEX_NOTICE,
        ],
        "confidence": min(0.5 + 0.05 * len(complete), 0.8),
    }


def _gamma_changes(current: Mapping[str, Any], previous: Mapping[str, Any] | None) -> dict[str, Any]:
    if previous is None:
        return {"status": "unavailable", "reason": "previous_gamma_snapshot_unavailable"}
    current_zero = _number_or_none(current.get("gamma_zero"))
    previous_zero = _number_or_none(previous.get("gamma_zero"))
    current_net = _number_or_none(current.get("net_gex"))
    previous_net = _number_or_none(previous.get("net_gex"))
    return {
        "status": "available" if current_zero is not None or current_net is not None else "unavailable",
        "gamma_zero_current": current_zero,
        "gamma_zero_previous": previous_zero,
        "gamma_zero_change_1d": current_zero - previous_zero
        if current_zero is not None and previous_zero is not None
        else None,
        "net_gex_current": current_net,
        "net_gex_previous": previous_net,
        "net_gex_change_1d": current_net - previous_net
        if current_net is not None and previous_net is not None
        else None,
    }


def _wall_changes(snapshot: Mapping[str, Any], previous_snapshot: Mapping[str, Any] | None) -> dict[str, Any]:
    if previous_snapshot is None:
        return {"status": "unavailable", "reason": "previous_wall_snapshot_unavailable", "items": []}
    current = {_wall_key(item): item for item in list(snapshot.get("wall_scores") or []) if isinstance(item, Mapping)}
    previous = {
        _wall_key(item): item for item in list(previous_snapshot.get("wall_scores") or []) if isinstance(item, Mapping)
    }
    items: list[dict[str, Any]] = []
    for key in set(current) | set(previous):
        now = current.get(key)
        old = previous.get(key)
        now_score = _number_or_none(now.get("wall_score")) if now else None
        old_score = _number_or_none(old.get("wall_score")) if old else None
        if now is None:
            trend = "invalidated"
        elif old is None:
            trend = "new"
        elif now_score is not None and old_score is not None and now_score > old_score:
            trend = "strengthening"
        elif now_score is not None and old_score is not None and now_score < old_score:
            trend = "weakening"
        else:
            trend = "stable"
        items.append(
            {
                "expiry": key[0],
                "strike": key[1],
                "side": key[2],
                "current_wall_score": now_score,
                "previous_wall_score": old_score,
                "wall_score_change_1d": (
                    now_score - old_score if now_score is not None and old_score is not None else None
                ),
                "trend": trend,
            }
        )
    return {
        "status": "available",
        "items": sorted(items, key=lambda item: abs(item["wall_score_change_1d"] or 0), reverse=True)[:20],
    }


def _gamma_profile(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    aggregate = _nested(snapshot, "gex", "netgex_aggregate") or {}
    return {
        "price_grid": list(aggregate.get("price_grid") or []),
        "net_gex_values": list(aggregate.get("net_gex_values") or []),
        "scope": "aggregate_across_expiries",
    }


def _iv_skew(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    by_expiry = _nested(snapshot, "gex", "by_expiry") or {}
    return {
        expiry: value.get("iv_skew")
        for expiry, value in by_expiry.items()
        if isinstance(value, Mapping) and value.get("iv_skew") is not None
    }


def _lineage(snapshot: Mapping[str, Any], endpoint: str) -> tuple[list[dict[str, Any]], list[str]]:
    trace = [dict(item) for item in list(snapshot.get("source_trace") or []) if isinstance(item, Mapping)]
    refs = trace + [{"name": "options_decision_endpoint", "source_ref": endpoint, "endpoint": endpoint, "status": "ok"}]
    artifacts = [str(item.get("file")) for item in trace if item.get("file")]
    return refs, list(dict.fromkeys(artifacts))


def _executive_summary(
    oi: Mapping[str, Any], gamma: Mapping[str, Any], roll: Mapping[str, Any], intraday: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "oi_delta": oi["total"]["delta"],
        "gamma_regime": gamma["regime"],
        "roll_status": roll["status"],
        "intraday_status": intraday["status"],
    }


def _group_expiry(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        result[str(row.get("expiry") or "unknown")].append(row)
    return result


def _net_gex(snapshot: Mapping[str, Any]) -> float | None:
    direct = _number_or_none(_nested(snapshot, "gex", "netgex_aggregate", "net_gex"))
    if direct is not None:
        return direct
    audited = _number_or_none(_nested(snapshot, "audit", "gex_audit", "net_gex"))
    if audited is not None:
        return audited
    summaries = _nested(snapshot, "gex", "by_expiry") or {}
    values = [
        _number_or_none(_nested(value, "summary", "net_gex"))
        for value in summaries.values()
        if isinstance(value, Mapping)
    ]
    available = [value for value in values if value is not None]
    return sum(available) if available else None


def _wall_key(item: Mapping[str, Any]) -> tuple[str, float, str]:
    return (
        str(item.get("expiry") or "aggregate"),
        _number(item.get("strike")),
        str(item.get("side") or item.get("dominant_side") or "unknown"),
    )


def _dedupe_levels(levels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for level in levels:
        reference = level.get("strike") if level.get("strike") is not None else level.get("band")
        key = (str(level.get("role")), str(reference))
        if key in seen:
            continue
        seen.add(key)
        result.append(level)
    return result


def _select_key_levels(levels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    caps = {
        "primary_support": 1,
        "secondary_support": 2,
        "primary_resistance": 1,
        "secondary_resistance": 2,
        "magnet_pin": 3,
        "volatility_hub": 2,
        "gamma_flip": 1,
        "tail_protection": 1,
    }
    selected: list[dict[str, Any]] = []
    counts: dict[str, int] = defaultdict(int)
    for level in levels:
        role = str(level.get("role") or "")
        if counts[role] >= caps.get(role, 1):
            continue
        counts[role] += 1
        selected.append(level)
    return selected


def _level_values(levels: list[dict[str, Any]], roles: set[str]) -> list[float]:
    values: list[float] = []
    for level in levels:
        if level.get("role") not in roles:
            continue
        strike = _number_or_none(level.get("strike"))
        if strike is not None:
            values.append(strike)
            continue
        band = level.get("band")
        if isinstance(band, Mapping):
            upper = _number_or_none(band.get("upper"))
            if upper is not None:
                values.append(upper)
    return values


def _unique_numbers(values: list[float | None]) -> list[float]:
    return list(dict.fromkeys(value for value in values if value is not None))


def _oi_total(rows: list[dict[str, Any]] | None, option_type: str | None) -> float | None:
    if rows is None:
        return None
    return sum(
        _number(row.get("open_interest"))
        for row in rows
        if option_type is None or str(row.get("option_type")).upper() == option_type
    )


def _row_key(row: Mapping[str, Any]) -> tuple[Any, Any, Any]:
    return (row.get("expiry"), row.get("strike"), str(row.get("option_type")).upper())


def _first(rows: list[dict[str, Any]], key: str) -> Any:
    return next((row.get(key) for row in rows if row.get(key) is not None), None)


def _number(value: Any) -> float:
    return float(value or 0)


def _number_or_none(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _pct(delta: float | None, previous: float | None) -> float | None:
    return delta / previous * 100 if delta is not None and previous else None


def _nested(value: Mapping[str, Any] | Any, *keys: str) -> Any:
    current: Any = value
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _strike_step(grid: list[Any]) -> float | None:
    nums = sorted({_number_or_none(item) for item in grid if _number_or_none(item) is not None})
    diffs = [right - left for left, right in zip(nums, nums[1:]) if right > left]
    return min(diffs) if diffs else None


def _warnings(snapshot: Mapping[str, Any]) -> list[str]:
    return list(_nested(snapshot, "data_quality", "warnings") or []) + list(
        _nested(snapshot, "normalization", "warnings") or []
    )


def _versions(rows: list[dict[str, Any]]) -> list[str]:
    return sorted({str(row.get("version_type")) for row in rows if row.get("version_type")})


def _proxy_coverage(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    return dict(_nested(snapshot, "data_quality", "categories") or {})


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _endpoint(trade_date: str) -> str:
    return "/api/options/decision" + (f"?date={trade_date}" if trade_date else "")
