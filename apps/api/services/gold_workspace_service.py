"""Gold-only reading surface for collected observations and verified research.

This projection never grants strategy authority or writes upstream/artifacts.
Observed changes and their transmission mechanisms are not causal attribution.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import logging
from math import isfinite
from typing import Any
from zoneinfo import ZoneInfo

from apps.api.services.dashboard_research_service import get_dashboard_research_context
from apps.api.services.gold_research_horizons import project_research_horizons
from apps.api.services.gold_research_topics import project_research_topics
from apps.api.services.gold_market_evidence import cme_structure, environment_watch, macro_effect, short_effect
from apps.api.services.macro_service import get_market_macro_latest
from apps.api.services.market_service import get_market_tickers

logger = logging.getLogger(__name__)
QUOTE_MAX_AGE = timedelta(minutes=15)
RESEARCH_MAX_AGE = timedelta(hours=4)

# Key, label, accepted aliases, unit, frequency, mechanism.
_FACTORS = (
    ("DXY", "美元指数", ("DXY",), "index", "daily", "inverse"),
    ("US02Y", "美国 2Y 收益率", ("US02Y", "DGS2"), "%", "daily", "nominal"),
    ("US10Y", "美国 10Y 收益率", ("US10Y", "DGS10"), "%", "daily", "nominal"),
    ("US30Y", "美国 30Y 收益率", ("US30Y", "DGS30"), "%", "daily", "nominal"),
    ("REAL10Y", "10Y 实际利率", ("REAL10Y", "DFII10", "REAL_10Y"), "%", "daily", "inverse"),
    ("T10YIE", "10Y 通胀补偿", ("T10YIE", "BREAKEVEN_10Y"), "%", "daily", "mixed"),
    ("WTI_SPOT", "WTI 原油现货", ("WTI_SPOT", "DCOILWTICO"), "USD/bbl", "daily", "oil"),
    ("BRENT_SPOT", "Brent 原油现货", ("BRENT_SPOT", "DCOILBRENTEU"), "USD/bbl", "daily", "oil"),
    ("SOFR", "美元隔夜融资利率", ("SOFR",), "%", "daily", "funding"),
    ("TGA", "财政部账户余额", ("TGA",), "B", "daily", "liquidity"),
    ("RESERVES", "银行准备金", ("RESERVES", "WRESBAL", "WRESCRT"), "B", "weekly", "liquidity"),
    ("HY_OAS", "高收益信用利差", ("HY_OAS", "BAMLH0A0HYM2"), "%", "daily", "funding"),
)
_REF_ALIASES = {
    "US02Y": ("DGS2",), "US10Y": ("DGS10",), "US30Y": ("DGS30",),
    "REAL10Y": ("DFII10",), "REAL_10Y": ("DGS10", "T10YIE"),
    "RESERVES": ("WRESBAL", "WRESCRT"), "HY_OAS": ("BAMLH0A0HYM2",),
    "WTI_SPOT": ("DCOILWTICO",), "BRENT_SPOT": ("DCOILBRENTEU",),
}


def _object(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value):
        return float(value)
    return None


def _text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _json_safe(value: Any) -> Any:
    if isinstance(value, float) and not isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value if value is None or isinstance(value, (str, int, float, bool)) else None


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except (ValueError, OverflowError):
        return None


def _observation_date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        if len(value) == 10:
            return date.fromisoformat(value)
        stamp = _timestamp(value)
        return stamp.astimezone(ZoneInfo("America/New_York")).date() if stamp else None
    except ValueError:
        return None


def _references(value: Any) -> list[dict]:
    if isinstance(value, list):
        return [deepcopy(item) for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        if any(key in value for key in ("source", "reference", "source_url", "source_ref")):
            return [deepcopy(value)]
        return [deepcopy(item) for item in value.values() if isinstance(item, dict)]
    return []


def _factor_refs(macro: dict, row: dict, symbol: str) -> list[dict]:
    own = _references(row.get("source_refs"))
    if own:
        return own
    values = macro.get("source_refs")
    aliases = (symbol, *_REF_ALIASES.get(symbol, ()))
    if isinstance(values, dict):
        return [deepcopy(values[key]) for key in aliases if isinstance(values.get(key), dict)]
    return [item for item in _references(values)
            if item.get("symbol") in aliases or item.get("series_id") in aliases]


def _source(row: dict, refs: list[dict]) -> str | None:
    explicit = _text(row.get("source")) or _text(row.get("provider"))
    return explicit or next((_text(ref.get("source")) or _text(ref.get("provider"))
                             or _text(ref.get("source_url")) or _text(ref.get("reference"))
                             for ref in refs if any(ref.get(k) for k in ("source", "provider", "source_url", "reference"))), None)


def _freshness(value: float | None, observed: str | None, source: str | None,
               frequency: str, now: datetime) -> str:
    if value is None:
        return "unavailable"
    if not observed:
        return "unverified"
    if frequency == "intraday":
        stamp = _timestamp(observed)
        if stamp is None or stamp > now:
            return "unverified"
        if now - stamp > QUOTE_MAX_AGE:
            return "stale"
        return "fresh" if source else "unverified"
    day = _observation_date(observed)
    if len(observed) != 10:
        stamp = _timestamp(observed)
        if stamp is None or stamp > now:
            return "unverified"
    today = now.astimezone(ZoneInfo("America/New_York")).date()
    if day is None or day > today:
        return "unverified"
    if frequency == "daily":
        earliest = today - timedelta(days=1)
        while earliest.weekday() >= 5:
            earliest -= timedelta(days=1)
    else:
        earliest = today - timedelta(days=10 if frequency == "weekly" else 45)
    if day < earliest:
        return "stale"
    return "recent" if source else "unverified"


def _fact(*, key: str, label: str, row: dict, refs: list[dict], unit: str,
          frequency: str, now: datetime, mechanism: str = "unconfirmed") -> dict:
    value = _number(row.get("value"))
    quality = str(row.get("quality_status") or row.get("status") or "").lower()
    if quality in {"blocked", "failed", "unavailable", "invalid", "missing"}:
        value = None
    observed = _text(row.get("observed_at")) or _text(row.get("date")) or _text(row.get("as_of"))
    source = _source(row, refs)
    status = _freshness(value, observed, source, frequency, now)
    if quality in {"mock", "unverified"}:
        status = "unverified" if value is not None else "unavailable"
    if row.get("freshness_status") == "stale" and value is not None:
        status = "stale"
    change = _number(row.get("daily_change"))
    window = "1d" if change is not None else None
    if change is None:
        change = _number(row.get("weekly_change"))
        window = "1w" if change is not None else None
    unit = _text(row.get("unit")) or unit
    change_unit = unit
    if unit in {"%", "percent", "percentage_points"} and change is not None:
        change = round(change * 100, 6)
        change_unit = "bp"
    impact = "unconfirmed"
    if status in {"fresh", "recent"} and change is not None:
        if change == 0:
            impact = "neutral"
        elif mechanism in {"inverse", "nominal"}:
            impact = "pressure" if change > 0 else "supportive"
        elif mechanism in {"mixed", "oil", "liquidity", "funding"}:
            impact = "mixed"
        elif mechanism == "flows":
            impact = "supportive" if change > 0 else "pressure"
    period = "日度" if window == "1d" else "周度" if window == "1w" else ""
    movement = "上升" if change is not None and change > 0 else "下降" if change is not None and change < 0 else "持平"
    notes = {
        "inverse": "美元或实际持有成本的变化影响黄金修复条件，不能单独确认价格方向。",
        "nominal": "名义融资成本变化；实际利率须单独核验，不能将这段变动全部归因于实际利率。",
        "mixed": "通胀补偿还包含风险与流动性溢价，需配合实际利率和美元判断。",
        "oil": "能源成本、政策压力与避险需求可能相互抵消；此为原油现货，非期货或柴油价差。",
        "funding": "结合利率走廊与信用环境观察；单项读数不能确认融资挤兑。",
        "liquidity": "需配合财政支出、准备金和融资利率判断流动性，不用单项余额断言黄金方向。",
        "flows": "较慢披露的资金参与证据，不能证明当前价位存在即时买卖盘。",
    }
    interpretation = f"{period}观测{movement}。" if change is not None else "尚无可验证的同窗口变化。"
    interpretation += notes.get(mechanism, "以实际观测日期为准，暂不据此确认黄金方向。")
    if status in {"stale", "unverified", "unavailable"}:
        interpretation = {"stale": "历史观测，需更新后再判断当前影响。", "unverified": "观测日期或来源未核验，暂不判断当前影响。",
                          "unavailable": "未取得可用读数，等待采集。"}[status] + interpretation
    return {"key": key, "label": label, "value": value, "unit": unit, "change": change,
            "change_unit": change_unit, "change_window": window, "observed_at": observed,
            "source": source, "frequency": frequency, "status": status, "impact": impact,
            "interpretation": interpretation, "source_refs": refs,
            "macro_effect": macro_effect(row, key=key, status=status, mechanism=mechanism, unit=unit),
            "short_term_summary": short_effect(status=status, mechanism=mechanism, change=change, window=window)}


def _price(quotes: dict, now: datetime) -> dict:
    tickers = _object(quotes.get("tickers"))
    row = _object(tickers.get("xauusd") or tickers.get("XAUUSD"))
    kind = str(row.get("instrument_kind") or row.get("instrument_type") or "spot").lower()
    value = _number(row.get("price"))
    if kind not in {"spot", "xauusd", "xauusd_spot"} or value is None or value <= 0:
        value = None
    observed = _text(row.get("price_time")) or _text(row.get("time"))
    source = _text(row.get("source")) or _text(row.get("provider"))
    status = _freshness(value, observed, source, "intraday", now)
    quality = str(row.get("status") or row.get("quality_status") or "").lower()
    if quality in {"blocked", "failed", "unavailable", "invalid", "missing"}:
        value, status = None, "unavailable"
    elif quality == "stale":
        status = "stale"
    elif quality in {"mock", "unverified"} or source and any(token in source.lower() for token in ("mock", "fixture", "research_snapshot")):
        status = "unverified"
    bar = bool(source and ("candle" in source.lower() or any(frame in source.lower() for frame in ("_5m", "_1h", "_1d"))))
    note = "最新已采集现货 K 线读数，非逐笔实时报价。" if bar else "黄金现货报价，以来源标注的观测时点为准。"
    if status != "fresh":
        note = "当前现价无法核验；保留来源观测供查阅，需刷新数据。" + note
    return {"key": "XAUUSD", "label": "黄金现货 XAUUSD", "value": value, "unit": "USD/oz",
            "change": _number(row.get("change_pct")), "change_unit": "%", "change_window": "1d",
            "observed_at": observed, "source": source, "frequency": "intraday", "status": status,
            "impact": "unconfirmed", "interpretation": note, "source_refs": _references(row.get("source_refs"))}


def _spot_levels(value: Any) -> list[dict]:
    rows = value if isinstance(value, list) else []
    result = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        coordinate = str(row.get("coordinate") or row.get("coordinate_space") or "").lower()
        instrument = str(row.get("instrument") or "").lower()
        price = _number(row.get("price"))
        if (coordinate not in {"spot", "xauusd", "xauusd_spot", "xauusd spot"} or instrument not in {"xauusd", "spot", "xauusd_spot", "xauusd spot"}
                or price is None or price <= 0):
            continue
        result.append({key: deepcopy(row[key]) for key in (
            "price", "instrument", "coordinate", "coordinate_space", "role", "source_date", "status",
            "level_status", "activation", "invalidation", "verification_status",
            "source_type", "source_refs", "valid_until", "eligible_for_target", "validity",
        ) if key in row})
    return sorted(result, key=lambda row: row["price"], reverse=True)


def _research(value: dict, now: datetime) -> dict:
    usable = value.get("status") == "available" and all(_text(value.get(key)) for key in ("report_id", "run_id", "snapshot_id", "trade_date", "summary"))
    stamp = _timestamp(value.get("as_of"))
    trade_date = _text(value.get("trade_date"))
    current = usable and value.get("historical_only") is not True and stamp is not None and timedelta(0) <= now - stamp <= RESEARCH_MAX_AGE and trade_date == now.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()
    plan = _object(value.get("final_trade_plan"))
    plan_matches = usable and all(plan.get(key) == value.get(key) for key in ("report_id", "run_id", "snapshot_id", "trade_date"))
    plan_matches = plan_matches and plan.get("execution_ready") is False and plan.get("is_trade_instruction") is False
    plan_matches = (plan_matches and plan.get("schema_version") == "research_trade_plan.v1"
                    and plan.get("status") == "waiting" and plan.get("entry") is None
                    and plan.get("stop_loss") is None and plan.get("targets") == []
                    and plan.get("current_action") == "等待确认，暂不开新单")
    narrative = _text(value.get("summary")) or "" if usable else ""
    summary = _text(plan.get("summary")) or "" if plan_matches else ""
    return {
        "status": "current" if current else "historical" if usable else "unavailable",
        **{key: _text(value.get(key)) for key in ("report_id", "run_id", "snapshot_id", "trade_date", "as_of")},
        "bias": _text(value.get("bias")) if usable else None,
        "summary": summary, "narrative": narrative,
        "reason": _text(value.get("reason")) if not usable else None,
        "authority": "observation_only", "publish_allowed": False,
        "research_identity": deepcopy(value.get("research_identity")),
        "trade_plan": deepcopy(plan) if plan_matches else None,
        "key_levels": _spot_levels(value.get("key_levels")) if usable else [],
    }


def _comparison(price: dict, research: dict) -> dict:
    anchor = _object(research.get("price_anchor"))
    reference = _number(anchor.get("price"))
    reference_time = _text(anchor.get("price_time"))
    current_time = _timestamp(price.get("observed_at"))
    anchor_time = _timestamp(reference_time)
    compatible = (research.get("status") == "available" and all(_text(research.get(key)) for key in ("report_id", "run_id", "snapshot_id", "trade_date", "summary"))
                  and price["status"] == "fresh"
                  and anchor.get("instrument_type") == "spot" and reference is not None and reference > 0
                  and anchor_time is not None and current_time is not None and anchor_time <= current_time)
    change = round(price["value"] - reference, 6) if compatible else None
    return {"status": "available" if compatible else "unavailable", "reference_price": reference if compatible else None,
            "reference_time": reference_time if compatible else None, "price_change": change,
            "price_change_pct": round(change / reference * 100, 6) if compatible else None,
            "note": "较该研究现货参考报价变化；来源可能不同，不等于交易收益或同步价差。" if compatible
                    else "缺少可对齐的现货报价与研究参考，不计算变化；GC 不能替代现货。"}


def build_gold_workspace(*, macro: Any, quotes: Any, research: Any,
                         options: Any = None, now: datetime | None = None) -> dict[str, Any]:
    """Pure projection; caller supplies already verified feature/report contexts."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must include a timezone")
    now = now.astimezone(timezone.utc)
    macro, quotes, research = _object(macro), _object(quotes), _object(research)
    indicators = _object(macro.get("indicators"))
    factors = []
    for key, label, aliases, unit, frequency, mechanism in _FACTORS:
        symbol = next((alias for alias in aliases if _number(_object(indicators.get(alias)).get("value")) is not None), aliases[0])
        row = _object(indicators.get(symbol))
        refs = _factor_refs(macro, row, symbol)
        item = _fact(key=key, label=label, row=row, refs=refs, unit=unit, frequency=frequency, now=now, mechanism=mechanism)
        if symbol == "REAL_10Y":
            item["label"] += "（名义利率−通胀补偿估算）"
            item["interpretation"] = "估算值，非同期直接 TIPS 报价。" + item["interpretation"]
        factors.append(item)
    etf = _object(macro.get("official_etf"))
    factors.append(_fact(key="GLD_HOLDINGS", label="GLD 官方持金", row={
        "value": etf.get("gold_holdings_tonnes"), "date": etf.get("gold_holdings_tonnes_reported_on") or etf.get("as_of"),
        "weekly_change": etf.get("gold_holdings_tonnes_weekly_delta"),
    }, refs=_references(etf.get("source_refs")), unit="tonnes", frequency="daily", now=now, mechanism="flows"))
    cot = _object(_object(macro.get("cot_reports")).get("futures_only"))
    managed = _object(cot.get("managed_money"))
    factors.append(_fact(key="COT_GOLD_NET", label="CFTC 管理基金净持仓", row={
        "value": _object(managed.get("latest")).get("net"), "date": cot.get("report_date"),
        "weekly_change": _object(managed.get("delta")).get("net"),
    }, refs=_references(cot.get("source_refs")), unit="contracts", frequency="weekly", now=now, mechanism="flows"))
    price = _price(quotes, now)
    reading = research
    historical = _object(research.get("historical_research"))
    if (research.get("status") == "unavailable" and historical.get("status") == "available"
            and historical.get("historical_only") is True):
        reading = historical
    projection = _research(reading, now)
    projection["latest_status"] = "unavailable" if research.get("status") != "available" else "available"
    projection["latest_reason"] = research.get("reason") if research.get("status") != "available" else None
    projection["latest_run_id"] = _text(research.get("run_id"))
    projection["horizons"] = project_research_horizons(projection)
    projection["topics"] = project_research_topics(projection, reading.get("topic_analysis"))
    readable = [row for row in [price, *factors] if row["value"] is not None]
    warnings = []
    if price["status"] != "fresh":
        warnings.append("当前黄金现价无法核验，先更新行情；历史观测不能确认当前入场。")
    if projection["status"] != "current":
        warnings.append("当前未取得本时段的新研究；历史研究需重新分析，行情刷新不会自动更新研究判断。")
    warnings.append("因子颜色表示观测变化的机制参考，不是已证实的涨跌贡献；不同发布频率不能当作同一时点。")
    return _json_safe({
        "schema_version": "gold_workspace.v1", "generated_at": now.isoformat(),
        "status": "available" if price["status"] == "fresh" and projection["status"] == "current" and all(row["status"] in {"fresh", "recent"} for row in factors)
                  else "partial" if readable or projection["status"] != "unavailable" else "unavailable",
        "price": price, "factors": factors, "research": projection,
        "environment_watch": environment_watch(factors), "cme_structure": cme_structure(options, now=now),
        "comparison": _comparison(price, research), "warnings": warnings,
    })


def _read_research() -> dict[str, Any] | None:
    return get_dashboard_research_context(include_historical=True)


def _read_options() -> dict[str, Any] | None:
    from apps.api.services._storage import _try_db_session
    from apps.api.services.options_service import get_options_decision

    db = _try_db_session()
    if db is None:
        return get_options_decision(allow_archived_parse=False)
    with db:
        return get_options_decision(db=db, allow_archived_parse=False)


def get_gold_workspace() -> dict[str, Any]:
    """Read existing collected data; never start a collection or analysis job."""
    values = {}
    for key, loader in (("macro", get_market_macro_latest), ("quotes", get_market_tickers),
                        ("research", _read_research), ("options", _read_options)):
        try:
            values[key] = loader()
        except Exception as exc:
            logger.warning("Gold workspace %s unavailable (%s)", key, type(exc).__name__)
            values[key] = None
    return build_gold_workspace(**values)
