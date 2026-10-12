"""TradingView scanner observations, not official settlements or tick quotes."""

import math
import re
from datetime import UTC, datetime

CORE_INSTRUMENTS = {
    "NYMEX:CL1!": ("WTI", "futures", "USD/bbl", "WTI连续期货；能源通胀盘中代理"),
    "ICEEUR:BRN1!": ("BRENT", "futures", "USD/bbl", "Brent连续期货；全球能源冲击代理"),
    "OANDA:XAUUSD": ("XAUUSD", "commodity", "USD/oz", "OTC现货黄金代理"),
    "TVC:DXY": ("DXY", "index", "index", "美元指数盘中代理"),
    "TVC:US03MY": ("US03M", "bond", "%", "3个月美债收益率盘中代理"),
    "TVC:US02Y": ("US02Y", "bond", "%", "2年期美债收益率盘中代理"),
    "TVC:US10Y": ("US10Y", "bond", "%", "10年期美债收益率盘中代理"),
    "TVC:US30Y": ("US30Y", "bond", "%", "30年期美债收益率盘中代理"),
}
OPTIONAL_INSTRUMENTS = {
    "TVC:SILVER": ("SILVER_SPOT_PROXY", "commodity", "USD/oz", "TradingView白银现货基准代理；检验贵金属共振"),
    "COMEX:GC1!": ("GC_FRONT", "futures", "USD/oz", "COMEX黄金连续期货；与现货分开使用"),
    "COMEX:SI1!": ("SI_FRONT", "futures", "USD/oz", "COMEX白银连续期货"),
    "CBOE:VIX": ("VIX", "index", "index", "VIX盘中代理；检验风险厌恶"),
    "SP:SPX": ("SPX", "index", "index", "标普500指数；检验风险资产方向"),
    "NASDAQ:NDX": ("NDX", "index", "index", "纳斯达克100指数；检验成长风险偏好"),
    "OANDA:USDJPY": ("USDJPY", "forex", "JPY/USD", "美元兑日元；检验日元避险与套息平仓"),
}
# Historical imports retain the deterministic baseline meaning.
INSTRUMENTS = CORE_INSTRUMENTS
ALL_INSTRUMENTS = {**CORE_INSTRUMENTS, **OPTIONAL_INSTRUMENTS}
COLUMNS = ["close", "time", "update_mode", "type", "exchange", "currency", "description",
           "change", "change_abs", "close|1", "time|1", "current_session"]


def number(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def timestamp(value):
    if number(value) is None:
        return None
    try:
        return datetime.fromtimestamp(value, UTC).isoformat()
    except (ValueError, OverflowError, OSError):
        return None


def parse_tradingview(payload, *, retrieved_at, source_ref, instruments=None):
    instruments = CORE_INSTRUMENTS if instruments is None else instruments
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        raise ValueError("scanner data must be a list")
    grouped = {}
    for entry in data:
        if isinstance(entry, dict) and entry.get("s") in instruments:
            grouped.setdefault(entry["s"], []).append(entry)
    observations = []
    for ticker, (symbol, instrument_type, unit, _description) in instruments.items():
        row = {"ticker": ticker, "symbol": symbol, "instrument_type": instrument_type, "unit": unit,
               "retrieved_at": retrieved_at, "source_refs": [source_ref], "status": "missing",
               "value": None, "quote_time": None, "quote_time_verified": False,
               "value_kind": "unavailable", "delay_seconds": None, "provider_bar_time": None,
               "minute_bar_time": None, "continuous_contract": instrument_type == "futures"}
        entries = grouped.get(ticker, [])
        if not entries:
            row["reason"] = "symbol_not_returned"
        elif len(entries) != 1 or not isinstance(entries[0].get("d"), list) or len(entries[0]["d"]) != len(COLUMNS):
            row.update(status="invalid", reason="duplicate_or_malformed_row")
        else:
            values = dict(zip(COLUMNS, entries[0]["d"]))
            current, minute = number(values["close"]), number(values["close|1"])
            identity_ok = (values["type"] == instrument_type and values["exchange"] == ticker.split(":")[0]
                           and (unit not in {"USD/bbl", "USD/oz"} or values["currency"] == "USD"))
            if not identity_ok or current is None or current <= 0:
                row.update(status="invalid", reason="instrument_unit_or_value_mismatch")
            else:
                mode = str(values["update_mode"] or "unknown")
                delay = re.fullmatch(r"delayed_streaming_(\d+)", mode)
                minute_time = timestamp(values["time|1"])
                has_minute = minute is not None and minute > 0 and minute_time is not None
                row.update(status="available", reason=None, value=minute if has_minute else current,
                           value_kind="minute_bar_close" if has_minute else "scanner_current_value_without_quote_clock",
                           scanner_close=current, provider_bar_time=timestamp(values["time"]),
                           minute_bar_time=minute_time if has_minute else None, update_mode=mode,
                           delay_seconds=int(delay[1]) if delay else 0 if mode == "streaming" else None,
                           current_session=values["current_session"], description=values["description"],
                           provider_change_pct=number(values["change"]), provider_change_abs=number(values["change_abs"]),
                           change_basis="provider_session_comparison_previous_timestamp_unavailable")
        observations.append(row)
    return {"schema_version": "tradingview_observations.v1", "retrieved_at": retrieved_at,
            "observations": observations, "source_refs": [source_ref],
            "limitations": ["bar_time_is_not_quote_time", "continuous_futures_are_not_spot_or_official_settlement",
                            "provider_session_change_is_not_same_window_return"]}
