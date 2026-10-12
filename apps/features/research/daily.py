"""Pure daily data passport; no provider calls or directional state decisions."""

from copy import deepcopy
from datetime import date, datetime
from math import isfinite
from typing import Any

from apps.features.macro.snapshot import MACRO_INDICATOR_SPECS

PASSPORT_SYMBOLS = (
    "US03M", "US02Y", "US05Y", "US10Y", "US30Y",
    "BREAKEVEN_5Y", "BREAKEVEN_10Y", "FORWARD_5Y5Y",
    "REAL_10Y", "REAL5Y", "REAL10Y", "REAL30Y",
    "YIELD_SPREAD_10Y_2Y", "YIELD_SPREAD_2Y_3M", "YIELD_SPREAD_30Y_10Y",
    "DXY", "BROAD_DOLLAR",
    "DIESEL_GULF_SPOT", "GASOLINE_GULF_SPOT",
    "WTI_SPOT", "BRENT_SPOT", "RESERVES", "WALCL", "TGA", "TGA_WEEKLY_AVERAGE", "ON_RRP_USAGE",
    "SOFR", "EFFR", "IORB", "SOFR_MINUS_IORB", "EFFR_MINUS_IORB", "HY_OAS", "VIX",
    "CPI", "PPI", "PPI_ALL_COMMODITIES", "PCE", "JOLTS", "INITIAL_CLAIMS", "ISM_MANUFACTURING", "GDP_NOW",
)
_SPECS = {spec.symbol: spec for spec in MACRO_INDICATOR_SPECS}
_WEEKLY_SYMBOLS = {"RESERVES", "WALCL", "TGA_WEEKLY_AVERAGE", "INITIAL_CLAIMS"}
_MONTHLY_SYMBOLS = {"CPI", "PPI", "PPI_ALL_COMMODITIES", "PCE", "JOLTS", "ISM_MANUFACTURING"}
_MONTHLY_FRESHNESS_DAYS = {
    "CPI": 75,
    "PPI": 75,
    "PPI_ALL_COMMODITIES": 75,
    "PCE": 100,
    "JOLTS": 100,
    "ISM_MANUFACTURING": 75,
}


def merge_research_passport(existing, observations, *, as_of):
    """Advance sourced daily facts in a child snapshot; retain originals upstream.

    Intraday quotes and ambiguous same-date revisions have separate owners.
    Updating one tenor never recomputes a spread against an asynchronous tenor.
    """
    result = deepcopy(existing)
    cutoff = datetime.fromisoformat(as_of.replace('Z', '+00:00')).date()
    for candidate in observations:
        value = candidate.get('value')
        if (not candidate.get('symbol') or not candidate.get('source_refs')
                or isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value)):
            continue
        try:
            observed = date.fromisoformat(candidate.get('observation_date', ''))
        except (ValueError, TypeError):
            continue
        if observed > cutoff:
            continue
        index = next((i for i, row in enumerate(result) if row.get('symbol') == candidate['symbol']), None)
        if index is None:
            result.append(deepcopy(candidate))
            continue
        prior = result[index]
        if prior.get('unit') and candidate.get('unit') != prior['unit']:
            continue
        if prior.get('value') is not None:
            try:
                prior_date = date.fromisoformat(prior.get('observation_date', ''))
            except (ValueError, TypeError):
                continue
            if observed <= prior_date:
                continue
        result[index] = deepcopy(candidate)
    return result


def build_daily_research_features(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Attach observation dates and comparison anchors to existing features.

    Values/deltas already belong to macro/technical/CFTC/ETF feature owners.
    This projection never converts a delayed oil spot series into a futures
    settlement, or a model futures anchor into a spot price.
    """
    macro = _data(snapshot, "macro")
    technical = _data(snapshot, "technical")
    indicators = macro.get("indicators", {})
    refs = macro.get("source_refs", {})
    ref_map = refs if isinstance(refs, dict) else {}
    rows = []
    for symbol in PASSPORT_SYMBOLS:
        item = indicators.get(symbol, {})
        spec = _SPECS[symbol]
        source_refs = [deepcopy(ref_map[key]) for key in spec.source_symbols if key in ref_map]
        lineage_valid = len(source_refs) == len(spec.source_symbols) and all(_valid_ref(ref, snapshot.get("snapshot_time")) for ref in source_refs)
        is_monthly = symbol in _MONTHLY_SYMBOLS
        monthly_change = item.get("monthly_change") if is_monthly else None
        rows.append({
            "symbol": symbol, "label": spec.label, "value": item.get("value"), "unit": spec.unit,
            "observation_date": item.get("date"), "previous_date": item.get("previous_date"),
            "previous_value": item.get("previous_value"),
            # A monthly release's previous observation is not a 1D change.
            "change": None if is_monthly else item.get("daily_change"),
            "weekly_anchor_date": item.get("weekly_anchor_date"), "weekly_anchor_value": item.get("weekly_anchor_value"),
            "weekly_change": None if is_monthly else item.get("weekly_change"),
            "monthly_change": monthly_change,
            "monthly_change_pct": _monthly_change_pct(item) if is_monthly else None,
            "yoy_change": _same_vintage_yoy(item) if is_monthly else None,
            "yoy_status": _yoy_status(item) if is_monthly else "not_applicable",
            "frequency": (
                "monthly" if is_monthly
                else "weekly" if symbol in {"WALCL", "INITIAL_CLAIMS"}
                else "weekly_average" if symbol in {"RESERVES", "TGA_WEEKLY_AVERAGE"}
                else "daily"
            ),
            "comparison": "monthly_observation" if is_monthly else "previous_observation", "source_refs": source_refs,
            "components": deepcopy(item.get("components", [])),
            "provenance_kind": "deterministic_calculation" if len(spec.source_symbols) > 1 else "observed",
            "status": _status(
                item.get("date"),
                snapshot.get("trade_date"),
                weekly=symbol in _WEEKLY_SYMBOLS,
                monthly=is_monthly,
                monthly_max_age_days=_MONTHLY_FRESHNESS_DAYS.get(symbol),
            ) if item.get("value") is not None and lineage_valid else "unavailable",
            "lineage_status": "verified" if lineage_valid else "missing_or_future_source",
            "freshness_note": (
                "历史代理；NAPM 数据若未更新不能称为当前 ISM"
                if symbol == "ISM_MANUFACTURING" else
                "月度发布，非实时行情；当前变化只在月度观察窗口内解释"
                if is_monthly else None
            ),
        })
    growth = macro.get("growth", {})
    for symbol, metric in growth.get("metrics", {}).items():
        ref = metric.get("source_ref", {})
        lineage = bool(ref) and _valid_ref(ref, snapshot.get("snapshot_time"))
        monthly = symbol.startswith("ISM_")
        replacement = {"symbol": symbol, "label": metric.get("label", symbol), "value": metric.get("value"), "unit": metric.get("unit"),
            "observation_date": metric.get("observation_date"), "reference_period": metric.get("reference_period"), "release_date": metric.get("release_date"), "release_time": metric.get("release_time"),
            "previous_date": None, "previous_value": metric.get("previous_value"), "change": None, "monthly_change": metric.get("change") if monthly else None,
            "monthly_change_pct": None, "yoy_change_pct": None, "weekly_change": None, "frequency": "monthly" if monthly else "event_driven",
            "comparison": "previous_reference_period" if monthly else "previous_official_update", "source_refs": [deepcopy(ref)] if ref else [],
            "status": "fresh" if metric.get("status") == "available" and lineage else "unavailable", "lineage_status": "verified" if lineage else "missing_or_future_source",
            "provenance_kind": "observed", "freshness_note": "官方发布与本地观察值按 collector health 核对；参考期、发布日期和采集时间分列"}
        existing = next((i for i, row in enumerate(rows) if row["symbol"] == symbol), None)
        if existing is None:
            rows.append(replacement)
        else:
            rows[existing] = replacement
    if technical:
        rows.insert(0, {"symbol": "XAUUSD_DAILY", "label": "XAUUSD 日线（独立 OTC 现货代理）", "value": technical.get("price"), "unit": "USD/oz", "observation_date": technical.get("as_of"), "previous_date": technical.get("previous_date"), "previous_value": technical.get("previous_price"), "change": technical.get("daily_change"), "weekly_change": None, "frequency": "daily", "comparison": "previous_observation" if technical.get("previous_date") else "unavailable", "source_refs": deepcopy(technical.get("source_refs") or []), "retrieved_at": technical.get("retrieved_at"), "status": _status(technical.get("as_of"), snapshot.get("trade_date")), "quality_status": technical.get("quality_status")})
        if not rows[0]["source_refs"] or not all(_valid_ref(ref, snapshot.get("snapshot_time")) for ref in rows[0]["source_refs"]):
            rows[0]["status"] = "unavailable"
    for domain, field, symbol, label, unit in (
        ("market_context", "dxy", "DXY_DAILY_PROXY", "DXY 完整日线（指数代理）", "index"),
        ("market_prices", "gc_futures", "GC_CONTINUOUS", "GC 连续期货日线（非指定合约结算）", "USD/oz"),
        ("oil", "wti", "WTI_FUTURES_PROXY", "WTI 连续期货日线（非官方结算）", "USD/bbl"),
        ("oil", "brent", "BRENT_FUTURES_PROXY", "Brent 连续期货日线（非官方结算）", "USD/bbl"),
    ):
        item = _data(snapshot, domain).get(field, {})
        formal_refs = [dict(ref, source_url=ref.get("reference")) for ref in item.get("source_refs", [])]
        qualified = item.get("quality_status") == "accepted" and item.get("alignment_status") == "aligned" and item.get("freshness_status") == "fresh" and bool(formal_refs) and all(_valid_ref(ref, snapshot.get("snapshot_time")) and _retrieved_after_close(ref, item.get("bar_close_time")) for ref in formal_refs)
        rows.append({"symbol": symbol, "label": label, "value": item.get("value") if qualified else None, "unit": unit, "observation_date": str(item.get("bar_open_time"))[:10] if item.get("bar_open_time") else None, "bar_close_time": item.get("bar_close_time"), "previous_date": None, "previous_value": None, "change": None, "weekly_change": None, "frequency": "daily", "comparison": "unavailable", "source_refs": formal_refs, "status": "fresh" if qualified else "unavailable", "provenance_kind": "observed", "quality_status": item.get("quality_status", "blocked")})
    by_symbol = {row["symbol"]: row for row in rows}
    _augment_treasury_breakeven(by_symbol)
    dollar = by_symbol["DXY"]
    for ref in dollar["source_refs"]:
        prior, reported = _number(ref.get("previous_close")), _number(ref.get("reported_daily_change"))
        if dollar["status"] == "fresh" and ref.get("previous_close_status") == "verified_by_provider_change" and prior is not None and reported is not None and abs(dollar["value"] - prior - reported) <= 0.005:
            dollar.update(provider_previous_close=prior, provider_reported_change=reported,
                          provider_comparison="provider_previous_session", provider_previous_date=ref.get("previous_observation_date"),
                          provider_observation_time=ref.get("provider_observation_time"))
    short = by_symbol["US02Y"]
    long = by_symbol["US10Y"]
    curve_comparable = bool(short["observation_date"] and short["previous_date"] and short["observation_date"] == long["observation_date"] and short["previous_date"] == long["previous_date"])
    result = {
        "schema_version": "daily_research.v1", "as_of": snapshot.get("snapshot_time"),
        "input_snapshot_ids": deepcopy(snapshot.get("input_snapshot_ids", {})),
        "passport": rows, "rate_changes_same_window": curve_comparable,
        "project_signals": _build_project_signals(by_symbol),
        "employment": deepcopy(macro.get("employment", {})),
        "growth": deepcopy(growth),
        "official_etf": deepcopy(macro.get("official_etf", {})),
        "cot_reports": deepcopy(macro.get("cot_reports", {})),
        "spot_anchor": _extract_spot_anchor(snapshot, technical),
        "execution_timeframes": _extract_execution_timeframes(snapshot, technical),
        "source_refs": deepcopy(snapshot.get("source_refs", [])),
    }
    from apps.features.research.market_session import resolve_market_session
    session = resolve_market_session(snapshot.get("snapshot_time"))
    result["market_session"] = session
    if not session["new_intraday_confirmation_allowed"]:
        anchor = result["spot_anchor"]
        anchor["data_status"] = anchor.get("status")
        if anchor.get("status") not in {"partial", "unavailable", "failed"} and anchor.get("price") is not None:
            result["spot_anchor"]["status"] = "market_closed" if session["state"] == "CLOSED" else "session_unconfirmed"
        anchor["live_confirmation_allowed"] = False
        anchor["session_reason"] = session["reason"]
    inflation = macro.get("inflation", {})
    if inflation:
        result["inflation"] = deepcopy(inflation)
        names = {"CPI": "headline_cpi", "PPI": "ppi_final_demand", "PCE": "headline_pce"}
        for row in result["passport"]:
            feature = inflation.get("series", {}).get(names.get(row["symbol"]), {})
            if (feature.get("status") == "available" and feature.get("source_refs")
                    and feature.get("observation_date") == row.get("observation_date")):
                row["monthly_change_pct"] = feature.get("mom_pct")
                row["yoy_change"] = feature.get("yoy_pct")
                row["yoy_status"] = "available_same_vintage_" + feature.get("yoy_basis", "unknown")
                row["inflation_momentum"] = deepcopy(feature)
    return result


def _augment_treasury_breakeven(rows: dict[str, dict[str, Any]]) -> None:
    """Research-only same-day nominal minus TIPS; leave legacy REAL_10Y intact.

    Each comparison is independently aligned. An older FRED BE never supplies
    a missing Treasury leg or a comparison endpoint.
    """
    nominal, real = rows.get("US10Y", {}), rows.get("REAL10Y", {})
    legs = (nominal, real)
    if any(row.get("status") != "fresh" or row.get("lineage_status") != "verified"
           or _number(row.get("value")) is None or not row.get("source_refs")
           or any(ref.get("source") != "treasury_rates" for ref in row["source_refs"])
           for row in legs):
        return
    day = nominal.get("observation_date")
    if not day or day != real.get("observation_date"):
        return
    be = rows["BREAKEVEN_10Y"]
    refs = _merge_source_refs(list(legs))
    be.update(
        value=round(_number(nominal["value"]) - _number(real["value"]), 6), observation_date=day,
        status="fresh", lineage_status="verified", source_refs=refs,
        provenance_kind="deterministic_calculation", derivation_version="treasury_be10y.v1",
        formula="DGS10 - DFII10 (same observation date)",
        components=[{"source_symbol": symbol, "date": day, "value": row["value"],
                     "source_refs": deepcopy(row["source_refs"])}
                    for symbol, row in zip(("DGS10", "DFII10"), legs)],
    )
    for date_key, value_key, change_key in (
        ("previous_date", "previous_value", "change"),
        ("weekly_anchor_date", "weekly_anchor_value", "weekly_change"),
    ):
        aligned = (nominal.get(date_key) and nominal.get(date_key) == real.get(date_key)
                   and nominal[date_key] < day and _number(nominal.get(value_key)) is not None
                   and _number(real.get(value_key)) is not None)
        value = round(_number(nominal[value_key]) - _number(real[value_key]), 6) if aligned else None
        be[date_key] = nominal[date_key] if aligned else None
        be[value_key] = value
        be[change_key] = round(be["value"] - value, 6) if value is not None else None
        for component, row in zip(be["components"], legs):
            component["observation_date"] = day
            component[date_key] = row[date_key] if aligned else None
            component[value_key] = row[value_key] if aligned else None
    be["comparison"] = "previous_observation" if be.get("previous_date") else "unavailable"


def _build_project_signals(rows: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Expose aligned project-specific facts without adding a second authority.

    The passport rows remain the source of truth.  These grouped views only
    join rows that have the same current, previous, and weekly dates and that
    carry verified source references.  A missing leg or a mismatched window
    makes the grouped signal unavailable; no legacy macro value is consulted.
    """

    return {
        "short_curve": _build_curve_signal(
            rows,
            left_symbol="US02Y",
            right_symbol="US03M",
            spread_symbol="YIELD_SPREAD_2Y_3M",
            signal_id="short_curve",
            left_change_name="two_year_change",
            right_change_name="three_month_change",
            formula="US02Y - US03M (DGS2 - DGS3MO)",
        ),
        "long_curve": _build_curve_signal(
            rows,
            left_symbol="US10Y",
            right_symbol="US02Y",
            spread_symbol="YIELD_SPREAD_10Y_2Y",
            signal_id="long_curve",
            left_change_name="ten_year_change",
            right_change_name="two_year_change",
            formula="US10Y - US02Y (DGS10 - DGS2)",
        ),
        "long_end_curve": _build_curve_signal(
            rows,
            left_symbol="US30Y",
            right_symbol="US10Y",
            spread_symbol="YIELD_SPREAD_30Y_10Y",
            signal_id="long_end_curve",
            left_change_name="thirty_year_change",
            right_change_name="ten_year_change",
            formula="US30Y - US10Y (DGS30 - DGS10)",
        ),
        "policy_corridor": _build_policy_corridor_signal(rows),
        "real_rate": _build_real_rate_signal(rows),
    }


def _build_curve_signal(
    rows: dict[str, dict[str, Any]],
    *,
    left_symbol: str,
    right_symbol: str,
    spread_symbol: str,
    signal_id: str,
    left_change_name: str,
    right_change_name: str,
    formula: str,
) -> dict[str, Any]:
    left = rows.get(left_symbol)
    right = rows.get(right_symbol)
    spread = rows.get(spread_symbol)
    all_rows = [item for item in (left, right, spread) if isinstance(item, dict)]
    aligned = _aligned_rows(left, right, spread)
    source_refs = _merge_source_refs(all_rows)
    current_date = _common_date(all_rows, "observation_date")
    previous_date = _common_date(all_rows, "previous_date")
    weekly_anchor_date = _common_date(all_rows, "weekly_anchor_date")
    left_change = _number(left.get("change")) if isinstance(left, dict) else None
    right_change = _number(right.get("change")) if isinstance(right, dict) else None
    weekly_left_change = _number(left.get("weekly_change")) if isinstance(left, dict) else None
    weekly_right_change = _number(right.get("weekly_change")) if isinstance(right, dict) else None
    spread_value = _number(spread.get("value")) if isinstance(spread, dict) else None
    spread_change = _number(spread.get("change")) if isinstance(spread, dict) else None
    weekly_spread_change = _number(spread.get("weekly_change")) if isinstance(spread, dict) else None
    status = "fresh" if aligned else "unavailable"
    change_type = _curve_change_type(spread_value, weekly_spread_change)
    driver = _curve_driver(weekly_left_change, weekly_right_change)
    if status == "fresh":
        state = "倒挂" if spread_value is not None and spread_value < 0 else "正斜率" if spread_value is not None and spread_value > 0 else "持平"
        curve_label = {
            "short_curve": "2Y−3M",
            "long_curve": "10Y−2Y",
            "long_end_curve": "30Y−10Y",
        }.get(signal_id, signal_id)
        summary = (
            f"{curve_label} 当前为{state} {spread_value:.2f}个百分点（{spread_value * 100:.1f}bp）；"
            f"比较窗口为周度 {weekly_anchor_date} 至 {current_date}；"
            f"两腿变化为 {left_symbol} {weekly_left_change * 100:+.1f}bp、{right_symbol} {weekly_right_change * 100:+.1f}bp，"
            f"{_curve_driver_summary(left_symbol, right_symbol, weekly_left_change, weekly_right_change)}；"
            "该信号只描述利率结构与政策定价，不单独决定黄金方向。"
        )
    else:
        summary = f"{signal_id} 需要两腿、利差及共同的当前/前值/周度日期；当前未形成可验证的对齐信号。"
    signal = {
        "signal_id": signal_id,
        "status": status,
        "as_of": current_date,
        "observation_date": current_date,
        "previous_date": previous_date,
        "weekly_anchor_date": weekly_anchor_date,
        "comparison_window": "weekly",
        "daily_comparison_window": "previous_observation",
        "formula": formula,
        "spread": spread_value,
        "spread_change": spread_change,
        "weekly_spread_change": weekly_spread_change,
        "slope": spread_value,
        "slope_change": spread_change,
        "weekly_slope_change": weekly_spread_change,
        "change_type": change_type if status == "fresh" else "unavailable",
        "driver": driver if status == "fresh" else "unavailable",
        "summary": summary,
        "directional_role": "context_only",
        "source_refs": source_refs,
        "legs": [_signal_leg(item) for item in (left, right) if isinstance(item, dict)],
    }
    signal[left_change_name] = left_change
    signal[right_change_name] = right_change
    signal[f"weekly_{left_change_name}"] = weekly_left_change
    signal[f"weekly_{right_change_name}"] = weekly_right_change
    return signal


def _build_policy_corridor_signal(rows: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if any(symbol in rows for symbol in ("SOFR_MINUS_IORB", "EFFR_MINUS_IORB")):
        return _build_policy_corridor_from_common_history(rows)

    legs = [rows.get("SOFR"), rows.get("EFFR"), rows.get("IORB")]
    present = [item for item in legs if isinstance(item, dict)]
    aligned = _aligned_rows(*legs)
    source_refs = _merge_source_refs(present)
    current_date = _common_date(present, "observation_date")
    previous_date = _common_date(present, "previous_date")
    weekly_anchor_date = _common_date(present, "weekly_anchor_date")
    sofr_iorb = _build_pair_spread(rows.get("SOFR"), rows.get("IORB"), name="sofr_minus_iorb", aligned=aligned)
    effr_iorb = _build_pair_spread(rows.get("EFFR"), rows.get("IORB"), name="effr_minus_iorb", aligned=aligned)
    status = "fresh" if aligned else "unavailable"
    driver = _corridor_driver(sofr_iorb, effr_iorb) if status == "fresh" else "unavailable"
    if status == "fresh":
        summary = (
            f"SOFR-IORB {sofr_iorb['spread']:+.4f}个百分点、EFFR-IORB {effr_iorb['spread']:+.4f}个百分点；"
            f"{_corridor_summary(sofr_iorb, effr_iorb)}"
        )
    else:
        summary = "SOFR、EFFR、IORB 需要共同当前/前值/周度日期和已验证来源；当前走廊信号不可用。"
    spreads = {"sofr_minus_iorb": sofr_iorb, "effr_minus_iorb": effr_iorb}
    return {
        "signal_id": "policy_corridor",
        "status": status,
        "as_of": current_date,
        "observation_date": current_date,
        "previous_date": previous_date,
        "weekly_anchor_date": weekly_anchor_date,
        "comparison_window": "weekly",
        "daily_comparison_window": "previous_observation",
        "change_type": "paired_policy_spreads" if status == "fresh" else "unavailable",
        "driver": driver,
        "summary": summary,
        "directional_role": "same_family_confirmation",
        "legs": [_signal_leg(item) for item in present],
        "spreads": spreads,
        "sofr_minus_iorb": sofr_iorb,
        "effr_minus_iorb": effr_iorb,
        "source_refs": source_refs,
    }


def _build_policy_corridor_from_common_history(rows: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Use snapshot-derived spreads whose legs were joined on the same dates."""
    sofr_spread = rows.get("SOFR_MINUS_IORB")
    effr_spread = rows.get("EFFR_MINUS_IORB")
    derived_rows = [item for item in (sofr_spread, effr_spread) if isinstance(item, dict)]
    as_of = _common_date(derived_rows, "observation_date")
    previous_date = _common_date(derived_rows, "previous_date")
    weekly_anchor_date = _common_date(derived_rows, "weekly_anchor_date")
    derived_aligned = _aligned_rows(sofr_spread, effr_spread)
    component_values = _component_values_at_date(derived_rows, as_of)
    leg_rows = [
        _historical_leg_at_date(rows.get("SOFR"), as_of, component_value=component_values.get("SOFR")),
        _historical_leg_at_date(rows.get("EFFR"), as_of, component_value=component_values.get("EFFR")),
        _historical_leg_at_date(rows.get("IORB"), as_of, component_value=component_values.get("IORB")),
    ]
    legs_aligned = bool(as_of) and all(item.get("status") == "fresh" for item in leg_rows)
    status = "fresh" if derived_aligned and legs_aligned else "unavailable"
    sofr_pair = _pair_from_common_history(sofr_spread, name="sofr_minus_iorb", usable=status == "fresh")
    effr_pair = _pair_from_common_history(effr_spread, name="effr_minus_iorb", usable=status == "fresh")
    driver = _corridor_driver(sofr_pair, effr_pair) if status == "fresh" else "unavailable"
    source_refs = _merge_source_refs([*derived_rows, *leg_rows])
    if status == "fresh":
        summary = (
            f"共同观察日 {as_of}：SOFR-IORB {sofr_pair['spread']:+.4f}个百分点、"
            f"EFFR-IORB {effr_pair['spread']:+.4f}个百分点；比较窗口为周度 "
            f"{weekly_anchor_date} 至 {as_of}。{_corridor_summary(sofr_pair, effr_pair)}"
        )
    else:
        historical_values = bool(as_of) and all(
            item.get("status") in {"fresh", "stale"}
            and item.get("lineage_status") == "verified"
            and _number(item.get("value")) is not None
            for item in derived_rows
        ) and set(component_values) == {"SOFR", "EFFR", "IORB"}
        if historical_values and any(item.get("status") == "stale" for item in derived_rows):
            summary = (
                f"可核验的共同观察日仍为 {as_of}：SOFR-IORB "
                f"{sofr_spread['value'] * 100:+.1f}bp、EFFR-IORB {effr_spread['value'] * 100:+.1f}bp。"
                "这组历史数据已超出本报告的日频时效窗口，不能据此确认当前融资状况；等待来源更新后再检查走廊是否走阔。"
            )
        else:
            summary = "SOFR-IORB/EFFR-IORB 需要共同历史交集及可验证两腿；不能用不同日期的最新值拼算走廊。"
    spreads = {"sofr_minus_iorb": sofr_pair, "effr_minus_iorb": effr_pair}
    return {
        "signal_id": "policy_corridor",
        "status": status,
        "as_of": as_of,
        "observation_date": as_of,
        "previous_date": previous_date,
        "weekly_anchor_date": weekly_anchor_date,
        "comparison_window": "weekly",
        "daily_comparison_window": "previous_observation",
        "change_type": "paired_policy_spreads" if status == "fresh" else "unavailable",
        "driver": driver,
        "summary": summary,
        "directional_role": "same_family_confirmation",
        "legs": leg_rows,
        "spreads": spreads,
        "sofr_minus_iorb": sofr_pair,
        "effr_minus_iorb": effr_pair,
        "source_refs": source_refs,
    }


def _component_values_at_date(rows: list[dict[str, Any]], observation_date: str | None) -> dict[str, float]:
    values: dict[str, float] = {}
    if not observation_date:
        return values
    for row in rows:
        for component in row.get("components") or []:
            if not isinstance(component, dict) or component.get("date") != observation_date:
                continue
            value = _number(component.get("value"))
            symbol = str(component.get("source_symbol") or "")
            if symbol and value is not None:
                values.setdefault(symbol, value)
    return values


def _historical_leg_at_date(
    row: dict[str, Any] | None,
    observation_date: str | None,
    *,
    component_value: float | None = None,
) -> dict[str, Any]:
    if (
        not isinstance(row, dict)
        or not observation_date
        or row.get("status") != "fresh"
        or row.get("lineage_status") != "verified"
    ):
        return {
            "symbol": row.get("symbol") if isinstance(row, dict) else None,
            "status": "unavailable",
            "source_refs": deepcopy(row.get("source_refs") or []) if isinstance(row, dict) else [],
        }
    candidates = (
        (row.get("observation_date"), row.get("value")),
        (row.get("previous_date"), row.get("previous_value")),
        (row.get("weekly_anchor_date"), row.get("weekly_anchor_value")),
    )
    value = component_value
    if value is None:
        value = next(
            (
                candidate_value
                for candidate_date, candidate_value in candidates
                if candidate_date == observation_date and _number(candidate_value) is not None
            ),
            None,
        )
    valid = value is not None and bool(row.get("source_refs"))
    return {
        "symbol": row.get("symbol"),
        "value": value,
        "unit": row.get("unit"),
        "observation_date": observation_date,
        "previous_date": None,
        "previous_value": None,
        "change": None,
        "weekly_anchor_date": None,
        "weekly_anchor_value": None,
        "weekly_change": None,
        "status": "fresh" if valid else "unavailable",
        "lineage_status": row.get("lineage_status"),
        "source_refs": deepcopy(row.get("source_refs") or []),
    }


def _pair_from_common_history(row: dict[str, Any] | None, *, name: str, usable: bool) -> dict[str, Any]:
    valid = (
        usable
        and isinstance(row, dict)
        and row.get("status") == "fresh"
        and _number(row.get("value")) is not None
        and _number(row.get("previous_value")) is not None
        and _number(row.get("change")) is not None
        and _number(row.get("weekly_change")) is not None
    )
    return {
        "signal_id": name,
        "status": "fresh" if valid else "unavailable",
        "spread": _number(row.get("value")) if isinstance(row, dict) else None,
        "spread_change": _number(row.get("change")) if isinstance(row, dict) else None,
        "weekly_change": _number(row.get("weekly_change")) if isinstance(row, dict) else None,
        "previous_spread": _number(row.get("previous_value")) if isinstance(row, dict) else None,
        "source_refs": deepcopy(row.get("source_refs") or []) if isinstance(row, dict) else [],
    }


def _build_pair_spread(
    left: dict[str, Any] | None,
    right: dict[str, Any] | None,
    *,
    name: str,
    aligned: bool,
) -> dict[str, Any]:
    source_refs = _merge_source_refs([item for item in (left, right) if isinstance(item, dict)])
    current = _number(left.get("value")) - _number(right.get("value")) if isinstance(left, dict) and isinstance(right, dict) and _number(left.get("value")) is not None and _number(right.get("value")) is not None else None
    previous = _number(left.get("previous_value")) - _number(right.get("previous_value")) if isinstance(left, dict) and isinstance(right, dict) and _number(left.get("previous_value")) is not None and _number(right.get("previous_value")) is not None else None
    weekly = _number(left.get("weekly_change")) - _number(right.get("weekly_change")) if isinstance(left, dict) and isinstance(right, dict) and _number(left.get("weekly_change")) is not None and _number(right.get("weekly_change")) is not None else None
    spread_change = _number(left.get("change")) - _number(right.get("change")) if isinstance(left, dict) and isinstance(right, dict) and _number(left.get("change")) is not None and _number(right.get("change")) is not None else None
    return {
        "signal_id": name,
        "status": "fresh" if aligned and current is not None and previous is not None and weekly is not None else "unavailable",
        "spread": round(current, 6) if current is not None else None,
        "spread_change": round(spread_change, 6) if spread_change is not None else None,
        "weekly_change": round(weekly, 6) if weekly is not None else None,
        "previous_spread": round(previous, 6) if previous is not None else None,
        "source_refs": source_refs,
    }


def _build_single_project_signal(row: dict[str, Any] | None, *, signal_id: str, summary: str) -> dict[str, Any]:
    valid = isinstance(row, dict) and row.get("status") == "fresh" and row.get("lineage_status") == "verified" and row.get("value") is not None and bool(row.get("source_refs"))
    return {
        "signal_id": signal_id,
        "status": "fresh" if valid else "unavailable",
        "as_of": row.get("observation_date") if isinstance(row, dict) else None,
        "observation_date": row.get("observation_date") if isinstance(row, dict) else None,
        "previous_date": row.get("previous_date") if isinstance(row, dict) else None,
        "weekly_anchor_date": row.get("weekly_anchor_date") if isinstance(row, dict) else None,
        "comparison_window": "previous_observation",
        "value": row.get("value") if isinstance(row, dict) else None,
        "change": row.get("change") if isinstance(row, dict) else None,
        "weekly_change": row.get("weekly_change") if isinstance(row, dict) else None,
        "driver": "observed_change" if valid else "unavailable",
        "summary": summary if valid else f"{signal_id} 当前缺少可验证的观察值或来源。",
        "source_refs": deepcopy(row.get("source_refs") or []) if isinstance(row, dict) else [],
    }


def _build_real_rate_signal(rows: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Prefer the official DFII10 observation for research display.

    ``REAL_10Y`` remains in the passport and remains the legacy component
    calculation used by the Gold contract.  This research projection may
    select the direct Treasury/FRED TIPS observation when it is usable, while
    retaining an explicit derived fallback instead of silently changing the
    old contract's authority.
    """

    direct = rows.get("REAL10Y")
    derived = rows.get("REAL_10Y")
    direct_valid = (
        isinstance(direct, dict)
        and direct.get("status") == "fresh"
        and direct.get("lineage_status") == "verified"
        and _number(direct.get("value")) is not None
        and bool(direct.get("source_refs"))
    )
    selected = direct if direct_valid else derived
    signal = _build_single_project_signal(
        selected,
        signal_id="real_rate",
        summary=(
            "研究显示优先采用官方 DFII10/TIPS 10Y 实际利率；"
            "REAL_10Y = US10Y - T10YIE 仅作为旧合约兼容和缺失时的显式后备，"
            "该事实不能单独替代完整黄金方向判断。"
            if direct_valid
            else "官方 DFII10 当前不可用，研究显示退回 REAL_10Y = US10Y - T10YIE；不能把后备口径写成官方实际利率。"
        ),
    )
    signal["selected_symbol"] = selected.get("symbol") if isinstance(selected, dict) else None
    signal["authority"] = "official_dfii10" if direct_valid else "derived_legacy_fallback"
    signal["fallback_used"] = not direct_valid
    return signal


def _aligned_rows(*items: dict[str, Any] | None) -> bool:
    if not items or any(not isinstance(item, dict) for item in items):
        return False
    rows = [item for item in items if isinstance(item, dict)]
    required_numeric_fields = ("value", "previous_value", "change", "weekly_change", "weekly_anchor_value")
    if any(
        item.get("status") != "fresh"
        or item.get("lineage_status") != "verified"
        or not item.get("source_refs")
        or any(_number(item.get(field)) is None for field in required_numeric_fields)
        for item in rows
    ):
        return False
    for field in ("observation_date", "previous_date", "weekly_anchor_date"):
        dates = {str(item.get(field) or "") for item in rows}
        if len(dates) != 1 or "" in dates:
            return False
    return True


def _common_date(rows: list[dict[str, Any]], field: str) -> str | None:
    values = {str(row.get(field) or "") for row in rows if isinstance(row, dict)}
    return next(iter(values)) if len(values) == 1 and "" not in values else None


def _signal_leg(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "symbol": row.get("symbol"),
        "value": row.get("value"),
        "unit": row.get("unit"),
        "observation_date": row.get("observation_date"),
        "previous_date": row.get("previous_date"),
        "previous_value": row.get("previous_value"),
        "change": row.get("change"),
        "weekly_anchor_date": row.get("weekly_anchor_date"),
        "weekly_change": row.get("weekly_change"),
        "status": row.get("status"),
        "lineage_status": row.get("lineage_status"),
        "source_refs": deepcopy(row.get("source_refs") or []),
    }


def _merge_source_refs(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for row in rows:
        for ref in row.get("source_refs") or []:
            if not isinstance(ref, dict):
                continue
            key = tuple(str(ref.get(field) or "") for field in ("source", "source_url", "raw_path", "retrieved_at"))
            if key in seen:
                continue
            seen.add(key)
            result.append(deepcopy(ref))
    return result


def _curve_change_type(spread: float | None, weekly_change: float | None) -> str:
    if spread is None or weekly_change is None:
        return "unavailable"
    if spread < 0:
        return "inversion_narrowing" if weekly_change > 0 else "inversion_deepening" if weekly_change < 0 else "inversion_unchanged"
    if spread > 0:
        return "steepening" if weekly_change > 0 else "flattening" if weekly_change < 0 else "positive_unchanged"
    return "crossing_or_flat" if weekly_change != 0 else "flat"


def _curve_driver_summary(
    left_symbol: str,
    right_symbol: str,
    left_change: float | None,
    right_change: float | None,
) -> str:
    if left_change is None or right_change is None:
        return "两腿周变化缺失，无法拆分变化来源"
    if left_symbol == "US02Y" and right_symbol == "US03M":
        if left_change > 0 and right_change < 0:
            return "2Y 上行而 3M 下行，鹰派预期与近期政策价格转松并存，曲线变化不能单向解读"
        if left_change < 0 and right_change > 0:
            return "2Y 下行而 3M 上行，未来紧缩溢价缓和但当前短端更紧，信号分裂"
        if left_change >= 0 and right_change >= 0:
            if left_change > right_change:
                return "2Y 与 3M 同升且 2Y 升幅更大，未来利率溢价偏鹰"
            if right_change > left_change:
                return "2Y 与 3M 同升且 3M 升幅更大，当前短端价格收紧更明显"
            if left_change > 0:
                return "2Y 与 3M 同幅上行，曲线未变但短端价格整体收紧"
            return "2Y 与 3M 均持平，曲线本身未提供新增方向确认"
        if left_change <= 0 and right_change <= 0:
            if abs(right_change) > abs(left_change):
                return "2Y 与 3M 同降且 3M 降幅更大，近期政策价格转松信号较强"
            if abs(left_change) > abs(right_change):
                if right_change == 0:
                    return "2Y 下行而 3M 未降，仅代表未来紧缩溢价缓和，当前短端尚未宽松"
                return "2Y 与 3M 同降但 2Y 降幅更大，未来紧缩溢价缓和更明显"
            return "2Y 与 3M 同幅下行，短端价格整体转松但曲线未变"
        return "2Y 与 3M 变化接近，曲线本身未提供新增方向确认"
    return f"{left_symbol} 与 {right_symbol} 周度变化分别为 {left_change:+.4f}、{right_change:+.4f}，需结合两腿拆分解读"


def _curve_driver(left_change: float | None, right_change: float | None) -> str:
    if left_change is None or right_change is None:
        return "unavailable"
    if left_change > 0 and right_change < 0:
        return "left_up_right_down"
    if left_change < 0 and right_change > 0:
        return "left_down_right_up"
    if left_change > 0 and right_change > 0:
        return "left_rise_dominant" if left_change > right_change else "right_rise_dominant" if right_change > left_change else "both_rising"
    if left_change < 0 and right_change < 0:
        return "left_fall_dominant" if abs(left_change) > abs(right_change) else "right_fall_dominant" if abs(right_change) > abs(left_change) else "both_falling"
    return "mixed_or_flat"


def _corridor_summary(sofr: dict[str, Any], effr: dict[str, Any]) -> str:
    a, b = _number(sofr.get("weekly_change")), _number(effr.get("weekly_change"))
    if a is None or b is None:
        return "走廊比较窗口仍有缺口，暂不能判断融资压力是否扩大。"
    values = f"SOFR 相对 IORB 的周变化 {a * 100:+.1f}bp，EFFR 相对 IORB 的周变化 {b * 100:+.1f}bp。"
    if a > 0 and b > 0:
        return values + "两项融资利差均扩大，应与准备金下降联合观察，检查压力是否持续。"
    if a <= 0 and b <= 0:
        return values + "两项价差均未扩大，融资价格暂未确认压力加剧。"
    return values + "融资价格反应分化，尚不能据此把准备金下降升级为全面融资压力。"


def _corridor_driver(sofr: dict[str, Any], effr: dict[str, Any]) -> str:
    changes = [item.get("weekly_change") for item in (sofr, effr) if item.get("status") == "fresh"]
    if len(changes) != 2 or any(value is None for value in changes):
        return "unavailable"
    if all(value > 0 for value in changes):
        return "both_spreads_wider"
    if all(value < 0 for value in changes):
        return "both_spreads_narrower"
    return "mixed_spread_change"


def _number(value: Any) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        number = float(value)
        return number if isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _monthly_change_pct(item: dict[str, Any]) -> float | None:
    """Return a monthly percentage only when a same-vintage base is present."""

    current = _number(item.get("value"))
    anchor = _number(item.get("monthly_anchor_value"))
    if current is None or anchor in (None, 0.0):
        return None
    return round((current - anchor) / abs(anchor) * 100.0, 6)


def _same_vintage_yoy(item: dict[str, Any]) -> float | None:
    """Do not infer YoY from a 30-day feature or mixed vintage observations."""

    if item.get("year_ago_same_vintage") is not True:
        return None
    current = _number(item.get("value"))
    year_ago = _number(item.get("year_ago_value"))
    if current is None or year_ago in (None, 0.0):
        return None
    return round((current - year_ago) / abs(year_ago) * 100.0, 6)


def _yoy_status(item: dict[str, Any]) -> str:
    if item.get("year_ago_same_vintage") is True and _number(item.get("year_ago_value")) not in (None, 0.0):
        return "available_same_vintage"
    return "unavailable_no_12m_same_vintage"


def _extract_spot_anchor(snapshot: dict[str, Any], technical: dict[str, Any]) -> dict[str, Any]:
    cutoff = snapshot.get("snapshot_time")
    selected = _selected_technical_refs(snapshot, technical)
    direct = technical.get("spot_anchor") if isinstance(technical, dict) else None
    if isinstance(direct, dict):
        return _sanitize_spot_anchor(direct, cutoff=cutoff, selected_refs=selected)
    for ref in selected:
        notes = ref.get("notes")
        if isinstance(notes, dict) and isinstance(notes.get("spot_anchor"), dict):
            return _sanitize_spot_anchor(notes["spot_anchor"], cutoff=cutoff, selected_refs=selected)
    return {
        "price": None,
        "price_time": None,
        "instrument_type": "spot",
        "timezone": "UTC",
        "delay": "unavailable",
        "source_refs": [],
        "status": "partial",
        "reason": "no_spot_anchor_source_ref",
    }


def _extract_execution_timeframes(snapshot: dict[str, Any], technical: dict[str, Any]) -> dict[str, Any]:
    cutoff = snapshot.get("snapshot_time")
    selected = _selected_technical_refs(snapshot, technical)
    # Independent intraday requests may succeed while the daily technical
    # module has no price points and therefore no selected daily source.
    if not selected:
        selected = [ref for ref in snapshot.get("source_refs", [])
                    if ref.get("source") == "twelvedata_xauusd_daily"
                    and ref.get("symbol") == "XAUUSD"
                    and _timestamp_at_or_before(ref.get("retrieved_at"), cutoff)]
    raw = technical.get("execution_timeframes") if isinstance(technical, dict) else None
    if not isinstance(raw, dict):
        for ref in selected:
            notes = ref.get("notes")
            if isinstance(notes, dict) and isinstance(notes.get("execution_timeframes"), dict):
                raw = notes["execution_timeframes"]
                break
    if not isinstance(raw, dict):
        return {
            "status": "unavailable",
            "reason": "no_intraday_timeframe_source_ref",
            "timeframes": {},
        }
    from apps.features.research.timeframes import build_execution_timeframe_features

    safe_raw: dict[str, Any] = {}
    for timeframe, item in raw.items():
        if not isinstance(item, dict):
            safe_raw[str(timeframe)] = {"status": "unavailable", "reason": "invalid_timeframe_payload"}
            continue
        retrieved_at = item.get("retrieved_at")
        if not _timestamp_at_or_before(retrieved_at, cutoff):
            safe_raw[str(timeframe)] = {"status": "unavailable", "reason": "future_timeframe_source"}
            continue
        safe_raw[str(timeframe)] = deepcopy(item)
    return {
        "status": "available" if any(isinstance(item, dict) and item.get("bars") for item in safe_raw.values()) else "partial",
        "timeframes": build_execution_timeframe_features(safe_raw),
    }


def _selected_technical_refs(snapshot: dict[str, Any], technical: dict[str, Any]) -> list[dict[str, Any]]:
    """Resolve full refs by the already-selected technical source identity."""

    selected_keys = {
        (str(ref.get("source") or ""), str(ref.get("raw_path") or ""))
        for ref in (technical.get("source_refs") or [])
        if isinstance(ref, dict) and ref.get("source") and ref.get("raw_path")
    }
    if not selected_keys:
        return []
    cutoff = snapshot.get("snapshot_time")
    refs: list[dict[str, Any]] = []
    for ref in snapshot.get("source_refs") or []:
        if not isinstance(ref, dict) or ref.get("symbol") != "XAUUSD":
            continue
        key = (str(ref.get("source") or ""), str(ref.get("raw_path") or ""))
        if key not in selected_keys or not _timestamp_at_or_before(ref.get("retrieved_at"), cutoff):
            continue
        refs.append(ref)
    return refs


def _sanitize_spot_anchor(
    anchor: dict[str, Any],
    *,
    cutoff: str | None,
    selected_refs: list[dict[str, Any]],
) -> dict[str, Any]:
    result = deepcopy(anchor)
    raw_nested = [ref for ref in (anchor.get("source_refs") or []) if isinstance(ref, dict)]
    nested = [
        ref for ref in (anchor.get("source_refs") or [])
        if isinstance(ref, dict) and _timestamp_at_or_before(ref.get("retrieved_at"), cutoff)
    ]
    price_time_valid = _timestamp_at_or_before(anchor.get("price_time"), cutoff)
    nested_lineage_valid = bool(raw_nested) and len(nested) == len(raw_nested)
    if not nested_lineage_valid or not price_time_valid or not selected_refs:
        result["status"] = "partial"
        result["reason"] = "spot_anchor_lineage_unavailable_or_future"
        if not nested:
            result["source_refs"] = []
        else:
            result["source_refs"] = nested
        if not nested_lineage_valid or not price_time_valid:
            result["price"] = None
    else:
        result["source_refs"] = nested
    return result


def _timestamp_at_or_before(value: Any, cutoff: Any) -> bool:
    if not isinstance(value, str) or not isinstance(cutoff, str):
        return False
    try:
        left = datetime.fromisoformat(value.replace("Z", "+00:00"))
        right = datetime.fromisoformat(cutoff.replace("Z", "+00:00"))
    except ValueError:
        return False
    return left.tzinfo is not None and right.tzinfo is not None and left <= right


def _data(snapshot: dict[str, Any], key: str) -> dict[str, Any]:
    section = snapshot.get(key, {})
    return section.get("data", {}) if section.get("status") == "available" else {}


def _status(
    observation: str | None,
    context: str | None,
    *,
    weekly: bool = False,
    monthly: bool = False,
    monthly_max_age_days: int | None = None,
) -> str:
    if not observation or not context:
        return "unavailable"
    try:
        age = (date.fromisoformat(context[:10]) - date.fromisoformat(observation[:10])).days
    except ValueError:
        return "unavailable"
    if age < 0:
        return "unavailable"
    if monthly:
        # Monthly observation dates are usually month-start labels; use a
        # longer explicit release window rather than the daily four-day gate.
        return "fresh" if age <= (monthly_max_age_days or 75) else "stale"
    return "fresh" if age <= (10 if weekly else 4) else "stale"


def _valid_ref(ref: dict[str, Any], cutoff: str | None) -> bool:
    if not all(ref.get(key) for key in ("source", "source_url", "raw_path", "retrieved_at")):
        return False
    try:
        retrieved = datetime.fromisoformat(str(ref["retrieved_at"]).replace("Z", "+00:00"))
        as_of = datetime.fromisoformat(str(cutoff).replace("Z", "+00:00"))
        return retrieved.tzinfo is not None and as_of.tzinfo is not None and retrieved <= as_of
    except (TypeError, ValueError):
        return False


def _retrieved_after_close(ref: dict[str, Any], close: str | None) -> bool:
    """An archived intraday bar cannot become complete merely by aging."""
    try:
        retrieved = datetime.fromisoformat(str(ref.get("retrieved_at")).replace("Z", "+00:00"))
        bar_close = datetime.fromisoformat(str(close).replace("Z", "+00:00"))
        return retrieved.tzinfo is not None and bar_close.tzinfo is not None and retrieved >= bar_close
    except (TypeError, ValueError):
        return False
