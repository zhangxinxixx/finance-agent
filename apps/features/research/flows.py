"""Pure CFTC positioning and official ETF flow diagnostics.

This module deliberately stays below the Gold state machine.  It reads the
already materialized ``daily_research`` snapshot, verifies an exact COT-to-spot
window from the snapshot's technical source lineage, and returns local flow
evidence.  It never reads files, calls providers, or attributes a move to a
news item or a speech.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
from math import isfinite
from typing import Any, Mapping


FLOW_DIAGNOSTICS_SCHEMA_VERSION = "gold_flow_diagnostics.v1"
REPORT_TYPES = ("combined", "futures_only")


def build_flow_diagnostics(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Build date-bound CFTC/ETF evidence without making a macro call.

    COT classification is confirmed only when the report has an accepted,
    source-backed current/previous pair and the exact two report dates occur in
    the matching technical source's ``notes.dates``/``notes.closes`` arrays.
    Missing one endpoint, a wrong source/raw path, or a future observation
    leaves the classification ``unconfirmed`` while preserving position deltas.
    """

    if not isinstance(snapshot, Mapping):
        return _empty_result(reason="snapshot_not_mapping")

    research = _section_data(snapshot.get("daily_research"))
    cot_reports = research.get("cot_reports", {})
    if not isinstance(cot_reports, Mapping):
        cot_reports = {}
    cutoff = _analysis_date(snapshot)
    price_index = _build_price_index(snapshot, cutoff)

    report_results: dict[str, dict[str, Any]] = {}
    used_refs: list[dict[str, Any]] = []
    limitations: list[str] = []
    for report_type in REPORT_TYPES:
        report = cot_reports.get(report_type)
        result = _build_report_diagnostic(
            report_type,
            report,
            price_index=price_index,
            cutoff=cutoff,
        )
        report_results[report_type] = result
        used_refs.extend(result.get("source_refs", []))
        used_refs.extend(result.get("window", {}).get("source_refs", []))
        limitations.extend(result.get("limitations", []))

    etf = _build_etf_diagnostic(research)
    for name in ('IAU', 'WGC'):
        supplemental = research.get('supplemental_sources', {}).get(name)
        if supplemental:
            etf['auxiliary'][name] = deepcopy(supplemental)
            used_refs.extend(supplemental.get('source_refs', []))
    used_refs.extend(etf.get("source_refs", []))
    limitations.extend(etf.get("limitations", []))

    window_reports = {name: result["window"] for name, result in report_results.items()}
    delta_reports = {name: result["delta"] for name, result in report_results.items()}
    classifications = {name: result["classification"] for name, result in report_results.items()}
    primary_report = report_results["combined"] if report_results["combined"]["status"] != "unavailable" else report_results["futures_only"]
    any_report_data = any(result["status"] != "unavailable" for result in report_results.values())
    any_confirmed = any(result["classification_status"] == "confirmed" for result in report_results.values())
    status = "complete" if any_confirmed else "partial" if any_report_data or etf["status"] != "unavailable" else "unavailable"

    return {
        "schema_version": FLOW_DIAGNOSTICS_SCHEMA_VERSION,
        "snapshot_id": snapshot.get("snapshot_id"),
        "status": status,
        "report_date": _report_date_summary(report_results),
        "reports": report_results,
        "primary_report_type": primary_report["report_type"],
        "classification": primary_report["classification"],
        "classification_status": primary_report["classification_status"],
        "window": {
            "status": "verified" if any(item.get("status") == "verified" for item in window_reports.values()) else "unavailable",
            "reports": window_reports,
            "price_source_refs": deepcopy(price_index.get("source_refs", [])),
        },
        "delta": delta_reports,
        "classifications": classifications,
        "position_contraction": {name: result["position_contraction"] for name, result in report_results.items()},
        "etf": etf,
        "event_attribution": {
            "status": "not_performed",
            "reason": "flow_diagnostics_does_not_attribute_position_changes_to_news_or_speeches",
        },
        "source_refs": _dedupe_refs(used_refs),
        "input_snapshot_ids": _input_snapshot_ids(snapshot, research),
        "limitations": _unique_text(
            [
                *limitations,
                "CFTC 与 ETF 观察窗口不同步时，只保留各自日期和局部变化，不合并为同一时点资金流。",
                "未执行新闻或讲话归因；没有精确价格窗口时不把仓位变化命名为新多、回补、多头平仓或新空。",
            ]
        ),
    }


def _build_report_diagnostic(
    report_type: str,
    report: Any,
    *,
    price_index: Mapping[str, Any],
    cutoff: date | None,
) -> dict[str, Any]:
    if not isinstance(report, Mapping):
        return _empty_report(report_type, "report_missing")

    report_date = _parse_date(report.get("report_date"))
    previous_date = _parse_date(report.get("previous_report_date"))
    refs = _refs(report.get("source_refs"))
    report_dates_valid = bool(report_date and previous_date and previous_date < report_date)
    future_report = bool(cutoff and ((report_date and report_date > cutoff) or (previous_date and previous_date > cutoff)))
    lineage_valid = bool(refs) and _report_ready(report) and not future_report
    positioning = _positioning(report)
    delta = positioning["delta"]
    window = _exact_window(
        report_date=report_date,
        previous_date=previous_date,
        price_index=price_index,
        cutoff=cutoff,
    )
    data_present = bool(report_date or previous_date or refs or positioning["current"])
    status = "available" if data_present else "unavailable"
    limitations: list[str] = []
    if not report_dates_valid:
        limitations.append(f"{report_type}: CFTC 当前/前一 report_date 不完整或顺序无效。")
    if future_report:
        limitations.append(f"{report_type}: CFTC report_date 超过分析截止日，拒绝未来数据。")
    if not lineage_valid:
        limitations.append(f"{report_type}: CFTC readiness/quality/source lineage 未达到 accepted。")
    if window["status"] != "verified":
        limitations.append(f"{report_type}: 未在匹配 technical source/raw_path 的 notes.dates 中找到两端精确价格，禁止最近日替代。")

    classification, classification_reason = _classify(
        price_delta=window.get("price_delta"),
        delta=delta,
        eligible=bool(report_dates_valid and lineage_valid and window["status"] == "verified"),
    )
    if classification == "unconfirmed":
        limitations.append(f"{report_type}: {classification_reason}")

    position_only = _position_only_result(delta, exact_window=window["status"] == "verified")
    if position_only["regime"] == "position_contraction":
        limitations.append(f"{report_type}: 仅能观察仓位收缩，未获得可用于归因的精确价格窗口。")

    return {
        "report_type": report_type,
        "status": status,
        "readiness": report.get("readiness"),
        "quality_status": report.get("quality_status"),
        "alignment_status": report.get("alignment_status"),
        "report_date": _date_text(report_date),
        "previous_report_date": _date_text(previous_date),
        "positioning": positioning,
        "current": positioning["current"],
        "previous": positioning["previous"],
        "delta": delta,
        "window": window,
        "classification": classification,
        "classification_status": "confirmed" if classification != "unconfirmed" else "unconfirmed",
        "classification_reason": classification_reason,
        "position_contraction": position_only,
        "source_refs": refs,
        "limitations": _unique_text(limitations),
    }


def _positioning(report: Mapping[str, Any]) -> dict[str, Any]:
    managed = _mapping(report.get("managed_money"))
    other = _mapping(report.get("other_reportables") or report.get("other_reportable"))
    spreading = report.get("spreading")
    if spreading is None:
        spreading = managed.get("spreading")
    if spreading is None and any(
        isinstance(managed.get(name), Mapping) and "spreading" in managed[name]
        for name in ("latest", "previous", "delta")
    ):
        spreading = {
            name: _mapping(managed.get(name)).get("spreading")
            for name in ("latest", "previous", "delta")
        }
    managed_series = _series(managed)
    managed_series["spreading"] = _scalar_series(spreading)
    other_series = _series(other)
    oi = _open_interest(report.get("open_interest"))

    current = {
        "managed_money": managed_series["latest"],
        "managed_money_spreading": managed_series["spreading"]["latest"],
        "spreading": managed_series["spreading"]["latest"],
        "other_reportables": other_series["latest"],
        "open_interest": oi["latest"],
    }
    previous = {
        "managed_money": managed_series["previous"],
        "managed_money_spreading": managed_series["spreading"]["previous"],
        "spreading": managed_series["spreading"]["previous"],
        "other_reportables": other_series["previous"],
        "open_interest": oi["previous"],
    }
    delta = {
        "managed_money": managed_series["delta"],
        "managed_money_spreading": managed_series["spreading"]["delta"],
        "spreading": managed_series["spreading"]["delta"],
        "other_reportables": other_series["delta"],
        "open_interest": oi["delta"],
        # Flat aliases keep the report easy to consume without dropping the
        # long/short/net grouping used by the formal COT snapshot.
        "managed_money_long": managed_series["delta"].get("long"),
        "managed_money_short": managed_series["delta"].get("short"),
        "other_reportables_long": other_series["delta"].get("long"),
        "other_reportables_short": other_series["delta"].get("short"),
    }
    return {"current": current, "previous": previous, "delta": delta}


def _series(value: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    latest = _long_short(value.get("latest"))
    previous = _long_short(value.get("previous"))
    provided = _long_short(value.get("delta"))
    delta = _delta_series(latest, previous, provided)
    return {"latest": latest, "previous": previous, "delta": delta}


def _scalar_series(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {"latest": _num(value), "previous": None, "delta": None}
    latest = _num(value.get("latest", value.get("value")))
    previous = _num(value.get("previous"))
    delta = _num(value.get("delta"))
    if delta is None and latest is not None and previous is not None:
        delta = latest - previous
    return {"latest": latest, "previous": previous, "delta": delta}


def _long_short(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {"long": None, "short": None, "net": None}
    return {
        "long": _num(value.get("long")),
        "short": _num(value.get("short")),
        "net": _num(value.get("net")),
    }


def _delta_series(
    latest: Mapping[str, Any],
    previous: Mapping[str, Any],
    provided: Mapping[str, Any],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in ("long", "short", "net"):
        value = provided.get(key)
        if value is None and latest.get(key) is not None and previous.get(key) is not None:
            value = latest[key] - previous[key]
        result[key] = _num(value)
    return result


def _open_interest(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        value = {}
    latest = _num(value.get("value", value.get("latest")))
    previous = _num(value.get("previous"))
    delta = _num(value.get("delta"))
    if delta is None and latest is not None and previous is not None:
        delta = latest - previous
    return {"latest": latest, "previous": previous, "delta": delta}


def _exact_window(
    *,
    report_date: date | None,
    previous_date: date | None,
    price_index: Mapping[str, Any],
    cutoff: date | None,
) -> dict[str, Any]:
    dates = [_date_text(previous_date), _date_text(report_date)]
    if not report_date or not previous_date or previous_date >= report_date:
        return _unavailable_window(dates, "report_dates_invalid")
    if cutoff and any(item and date.fromisoformat(item) > cutoff for item in dates):
        return _unavailable_window(dates, "report_date_after_analysis_cutoff")
    closes = price_index.get("closes", {})
    if not isinstance(closes, Mapping) or any(item not in closes for item in dates):
        return _unavailable_window(dates, "exact_price_dates_missing")
    previous_price = _num(closes.get(dates[0]))
    current_price = _num(closes.get(dates[1]))
    if previous_price is None or current_price is None:
        return _unavailable_window(dates, "exact_price_values_invalid")
    return {
        "status": "verified",
        "previous_date": dates[0],
        "current_date": dates[1],
        "previous_price": previous_price,
        "current_price": current_price,
        "price_delta": current_price - previous_price,
        "source_refs": deepcopy(price_index.get("source_refs", [])),
        "reason": None,
    }


def _unavailable_window(dates: list[str | None], reason: str) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "previous_date": dates[0],
        "current_date": dates[1],
        "previous_price": None,
        "current_price": None,
        "price_delta": None,
        "source_refs": [],
        "reason": reason,
    }


def _classify(*, price_delta: float | None, delta: Mapping[str, Any], eligible: bool) -> tuple[str, str]:
    if not eligible:
        return "unconfirmed", "exact two-ended price window or accepted CFTC lineage is unavailable; position changes are not price-attributed."
    long_delta = _num(delta.get("managed_money", {}).get("long"))
    short_delta = _num(delta.get("managed_money", {}).get("short"))
    oi_delta = _num(delta.get("open_interest"))
    if price_delta is None or long_delta is None or short_delta is None or oi_delta is None:
        return "unconfirmed", "required price, Managed Money long/short, or OI delta is missing."
    if price_delta > 0 and long_delta > 0 and oi_delta > 0:
        return "new_longs", "price up, Managed Money long up, and OI up."
    if price_delta > 0 and short_delta < 0 and oi_delta <= 0:
        return "short_covering", "price up, Managed Money short down, and OI flat/down."
    if price_delta < 0 and long_delta < 0 and oi_delta < 0:
        return "long_liquidation", "price down, Managed Money long down, and OI down."
    if price_delta < 0 and short_delta > 0 and oi_delta > 0:
        return "new_shorts", "price down, Managed Money short up, and OI up."
    return "unconfirmed", "the exact price/position/OI combination does not match one of the four approved classifications."


def _position_only_result(delta: Mapping[str, Any], *, exact_window: bool) -> dict[str, Any]:
    mm = delta.get("managed_money", {})
    long_delta = _num(mm.get("long"))
    short_delta = _num(mm.get("short"))
    oi_delta = _num(delta.get("open_interest"))
    contraction = bool(
        not exact_window
        and oi_delta is not None
        and oi_delta < 0
        and ((long_delta is not None and long_delta < 0) or (short_delta is not None and short_delta > 0))
    )
    return {
        "regime": "position_contraction" if contraction else "unconfirmed",
        "status": "observed" if contraction else "not_confirmed",
        "classification": "unconfirmed",
        "price_attribution": False,
        "managed_money_long_delta": long_delta,
        "managed_money_short_delta": short_delta,
        "open_interest_delta": oi_delta,
    }


def _build_price_index(snapshot: Mapping[str, Any], cutoff: date | None) -> dict[str, Any]:
    if cutoff is None:
        return {"status": "unavailable", "closes": {}, "source_refs": [], "reason": "analysis_cutoff_missing"}
    technical = _section_data(snapshot.get("technical"))
    technical_refs = _refs(technical.get("source_refs"))
    identities = {
        (str(ref.get("source")), str(ref.get("raw_path")))
        for ref in technical_refs
        if ref.get("source") and ref.get("raw_path")
    }
    if not identities:
        return {"status": "unavailable", "closes": {}, "source_refs": [], "reason": "technical_source_identity_missing"}

    candidates: list[dict[str, Any]] = []
    for ref in _refs(snapshot.get("source_refs")):
        identity = (str(ref.get("source")), str(ref.get("raw_path")))
        if identity not in identities:
            continue
        notes = ref.get("notes")
        if not isinstance(notes, Mapping):
            continue
        dates = notes.get("dates")
        closes = notes.get("closes")
        if not isinstance(dates, list) or not isinstance(closes, list) or len(dates) != len(closes) or not dates:
            continue
        parsed_dates: list[str] = []
        parsed_closes: list[float] = []
        valid = True
        for raw_date, raw_close in zip(dates, closes):
            parsed = _parse_date(raw_date)
            value = _num(raw_close)
            if parsed is None or value is None or (cutoff and parsed > cutoff):
                valid = False
                break
            parsed_dates.append(_date_text(parsed) or "")
            parsed_closes.append(value)
        if not valid or len(set(parsed_dates)) != len(parsed_dates):
            continue
        close_map = dict(zip(parsed_dates, parsed_closes))
        candidates.append({"status": "verified", "closes": close_map, "source_refs": [deepcopy(ref)]})

    if not candidates:
        return {"status": "unavailable", "closes": {}, "source_refs": [], "reason": "matching_technical_price_source_missing_or_invalid"}
    first = candidates[0]
    if any(item["closes"] != first["closes"] for item in candidates[1:]):
        return {"status": "unavailable", "closes": {}, "source_refs": [], "reason": "ambiguous_matching_price_sources"}
    return first


def _build_etf_diagnostic(research: Mapping[str, Any]) -> dict[str, Any]:
    raw = research.get("official_etf", {})
    if not isinstance(raw, Mapping):
        raw = {}
    shares = _etf_delta(raw, "shares")
    holdings = _etf_delta(raw, "gold_holdings_tonnes")
    shares_weekly = _etf_delta(raw, "shares", weekly=True)
    holdings_weekly = _etf_delta(raw, "gold_holdings_tonnes", weekly=True)
    daily = {"shares": shares, "holdings_tonnes": holdings}
    weekly = {"shares": shares_weekly, "holdings_tonnes": holdings_weekly}
    divergences = {
        metric: _direction_relation(daily[metric], weekly[metric])
        for metric in ("shares", "holdings_tonnes")
    }
    available_metric = shares is not None or holdings is not None
    source_refs = _refs(raw.get("source_refs"))
    lineage_valid = bool(source_refs)
    status = str(raw.get("status") or ("available" if available_metric else "unavailable"))
    limitations: list[str] = []
    if not available_metric:
        limitations.append("GLD shares/holdings 未取得；不使用 AUM 变化替代资金流。")
    if available_metric and not lineage_valid:
        status = "partial"
        limitations.append("GLD shares/holdings 缺少 source_refs；本地变化只作未核验观察。")
    if raw.get("total_net_assets_usd") is not None or raw.get("total_net_asset_value_usd") is not None:
        limitations.append("GLD AUM 仅保留为规模水平，不作为 flow 或申赎方向。")
    return {
        "status": status,
        "lineage_status": "verified" if lineage_valid else "unavailable",
        "primary_fund": "GLD",
        "daily": daily,
        "weekly": weekly,
        "daily_vs_weekly": divergences,
        "levels": {
            "shares_outstanding": _num(raw.get("shares_outstanding")),
            "gold_holdings_tonnes": _num(raw.get("gold_holdings_tonnes")),
            "aum_level_usd": _num(raw.get("total_net_assets_usd") or raw.get("total_net_asset_value_usd")),
            "aum_flow_used": False,
        },
        "reported_on": {
            "shares": raw.get("shares_reported_on"),
            "holdings_tonnes": raw.get("gold_holdings_tonnes_reported_on"),
        },
        "missing_data": list(raw.get("missing_data") or []),
        "source_refs": source_refs,
        "auxiliary": {
            "IAU": _missing_auxiliary_etf("IAU"),
            "WGC": _missing_auxiliary_etf("WGC"),
        },
        "limitations": _unique_text(limitations),
    }


def _direction_relation(daily: float | None, weekly: float | None) -> str:
    if daily is None or weekly is None:
        return "unavailable"
    if daily == 0 or weekly == 0:
        return "flat_or_mixed"
    return "aligned" if (daily > 0) == (weekly > 0) else "divergent"


def _etf_delta(raw: Mapping[str, Any], prefix: str, *, weekly: bool = False) -> float | None:
    suffix = "_weekly_delta" if weekly else "_delta"
    value = _num(raw.get(f"{prefix}{suffix}"))
    if value is not None:
        return value
    current_key = "shares_outstanding" if prefix == "shares" else prefix
    current = _num(raw.get(current_key))
    previous_key = (
        f"{prefix}_weekly_anchor_value"
        if weekly
        else f"{prefix}_previous_value"
    )
    previous = _num(raw.get(previous_key))
    if current is None or previous is None:
        return None
    return current - previous


def _missing_auxiliary_etf(name: str) -> dict[str, Any]:
    return {"status": "unavailable", "reason": f"{name} shares/holdings not collected in this snapshot", "source_refs": []}


def _report_ready(report: Mapping[str, Any]) -> bool:
    return (
        report.get("readiness") == "ready"
        and report.get("quality_status") == "accepted"
        and report.get("alignment_status") == "aligned"
    )


def _report_date_summary(reports: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    return {
        name: {
            "report_date": report.get("report_date"),
            "previous_report_date": report.get("previous_report_date"),
        }
        for name, report in reports.items()
    }


def _input_snapshot_ids(snapshot: Mapping[str, Any], research: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for value in (snapshot.get("input_snapshot_ids"), research.get("input_snapshot_ids")):
        if isinstance(value, Mapping):
            result.update(deepcopy(dict(value)))
    return result


def _empty_report(report_type: str, reason: str) -> dict[str, Any]:
    empty_delta = {
        "managed_money": {"long": None, "short": None, "net": None},
        "managed_money_spreading": None,
        "spreading": None,
        "other_reportables": {"long": None, "short": None, "net": None},
        "open_interest": None,
        "managed_money_long": None,
        "managed_money_short": None,
        "other_reportables_long": None,
        "other_reportables_short": None,
    }
    return {
        "report_type": report_type,
        "status": "unavailable",
        "readiness": None,
        "quality_status": None,
        "alignment_status": None,
        "report_date": None,
        "previous_report_date": None,
        "positioning": {"current": {}, "previous": {}, "delta": empty_delta},
        "current": {},
        "previous": {},
        "delta": empty_delta,
        "window": _unavailable_window([None, None], reason),
        "classification": "unconfirmed",
        "classification_status": "unconfirmed",
        "classification_reason": reason,
        "position_contraction": _position_only_result(empty_delta, exact_window=False),
        "source_refs": [],
        "limitations": [f"{report_type}: {reason}"],
    }


def _empty_result(*, reason: str) -> dict[str, Any]:
    reports = {name: _empty_report(name, reason) for name in REPORT_TYPES}
    return {
        "schema_version": FLOW_DIAGNOSTICS_SCHEMA_VERSION,
        "snapshot_id": None,
        "status": "unavailable",
        "report_date": _report_date_summary(reports),
        "reports": reports,
        "primary_report_type": "combined",
        "classification": "unconfirmed",
        "classification_status": "unconfirmed",
        "window": {"status": "unavailable", "reports": {name: item["window"] for name, item in reports.items()}, "price_source_refs": []},
        "delta": {name: item["delta"] for name, item in reports.items()},
        "classifications": {name: "unconfirmed" for name in REPORT_TYPES},
        "position_contraction": {name: item["position_contraction"] for name, item in reports.items()},
        "etf": _build_etf_diagnostic({}),
        "event_attribution": {"status": "not_performed", "reason": "flow_diagnostics_does_not_attribute_position_changes_to_news_or_speeches"},
        "source_refs": [],
        "input_snapshot_ids": {},
        "limitations": [reason],
    }


def _section_data(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    if value.get("status") == "available" and isinstance(value.get("data"), Mapping):
        return dict(value["data"])
    return dict(value)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _refs(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, (list, tuple)):
        return []
    return [deepcopy(dict(item)) for item in value if isinstance(item, Mapping)]


def _dedupe_refs(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ref in refs:
        key = repr(sorted((str(k), repr(v)) for k, v in ref.items()))
        if key in seen:
            continue
        seen.add(key)
        result.append(deepcopy(ref))
    return result


def _parse_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _analysis_date(snapshot: Mapping[str, Any]) -> date | None:
    trade_date = _parse_date(snapshot.get("trade_date"))
    if trade_date is not None:
        return trade_date
    timestamp = snapshot.get("snapshot_time")
    if isinstance(timestamp, str):
        return _parse_date(timestamp[:10])
    return None


def _date_text(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if isfinite(result) else None


def _unique_text(values: list[Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        if text and text not in result:
            result.append(text)
    return result


__all__ = ["FLOW_DIAGNOSTICS_SCHEMA_VERSION", "build_flow_diagnostics"]
