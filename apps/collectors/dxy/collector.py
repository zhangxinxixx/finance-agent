from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import httpx

from apps.parsers.macro.models import CollectorResult, MacroPoint
from apps.parsers.macro.storage import archive_raw_payload, utc_now_iso

TRADINGVIEW_SCAN_URL = "https://scanner.tradingview.com/america/scan"
CNBC_DXY_URL = "https://quote.cnbc.com/quote-html-webservice/quote.htm"


def collect_dxy_series(*, retrieved_date: str, storage_root: Path) -> CollectorResult:
    tv_result = _collect_from_tradingview(retrieved_date=retrieved_date, storage_root=storage_root)
    if tv_result.points:
        return tv_result
    cnbc_result = _collect_from_cnbc(retrieved_date=retrieved_date, storage_root=storage_root)
    if cnbc_result.points:
        return cnbc_result
    return CollectorResult(points=[], unavailable_symbols=["DXY"], source_refs=[*tv_result.source_refs, *cnbc_result.source_refs])


def _collect_from_tradingview(*, retrieved_date: str, storage_root: Path) -> CollectorResult:
    payload = {"symbols": {"tickers": ["TVC:DXY"], "query": {"types": []}}, "columns": ["close", "Perf.W", "Perf.1M", "description"]}
    try:
        with httpx.Client(timeout=30.0, headers={"User-Agent": "Mozilla/5.0"}, trust_env=False) as client:
            response = client.post(TRADINGVIEW_SCAN_URL, json=payload)
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        return _unavailable("tradingview", f"TradingView request failed: {type(exc).__name__}: {exc}")
    raw_path = archive_raw_payload(storage_root=storage_root, source="tradingview", retrieved_date=retrieved_date, symbol="DXY", payload=data)
    try:
        row = data["data"][0]
        close, perf_w, perf_1m, *_ = row["d"]
        current = float(close)
        weekly_perf = float(perf_w)
        monthly_perf = float(perf_1m)
    except Exception as exc:
        return CollectorResult(points=[], unavailable_symbols=["DXY"], source_refs=[{"symbol": "DXY", "source": "tradingview", "source_url": TRADINGVIEW_SCAN_URL, "raw_path": raw_path, "reason": f"Payload parse: {type(exc).__name__}: {exc}"}])
    as_date = date.fromisoformat(retrieved_date)
    retrieved_at = utc_now_iso()
    points = [
        _point("DXY", as_date - timedelta(days=30), _prior_from_perf(current, monthly_perf), "tradingview", raw_path, retrieved_at),
        _point("DXY", as_date - timedelta(days=7), _prior_from_perf(current, weekly_perf), "tradingview", raw_path, retrieved_at),
        _point("DXY", as_date, current, "tradingview", raw_path, retrieved_at),
    ]
    return CollectorResult(points=points, unavailable_symbols=[], source_refs=[{"symbol": "DXY", "source": "tradingview", "source_url": TRADINGVIEW_SCAN_URL, "raw_path": raw_path}])


def _collect_from_cnbc(*, retrieved_date: str, storage_root: Path) -> CollectorResult:
    params = {"symbols": ".DXY", "requestMethod": "quick", "noform": "1", "partnerId": "2", "fund": "1", "exthrs": "1", "output": "json"}
    try:
        with httpx.Client(timeout=30.0, headers={"User-Agent": "Mozilla/5.0"}, trust_env=False) as client:
            response = client.get(CNBC_DXY_URL, params=params)
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        return _unavailable("cnbc", f"CNBC fallback failed: {type(exc).__name__}: {exc}")
    raw_path = archive_raw_payload(storage_root=storage_root, source="cnbc", retrieved_date=retrieved_date, symbol="DXY", payload=data)
    try:
        quote = data["QuickQuoteResult"]["QuickQuote"][0]
        value = float(str(quote["last"]).replace(",", ""))
    except Exception as exc:
        return CollectorResult(points=[], unavailable_symbols=["DXY"], source_refs=[{"symbol": "DXY", "source": "cnbc", "source_url": CNBC_DXY_URL, "raw_path": raw_path, "reason": f"Payload parse: {type(exc).__name__}: {exc}"}])
    point = _point("DXY", date.fromisoformat(retrieved_date), value, "cnbc", raw_path, utc_now_iso())
    return CollectorResult(points=[point], unavailable_symbols=[], source_refs=[{"symbol": "DXY", "source": "cnbc", "source_url": CNBC_DXY_URL, "raw_path": raw_path}])


def _prior_from_perf(current, perf_pct):
    return round(current / (1.0 + perf_pct / 100.0), 6)


def _point(symbol, point_date, value, source, raw_path, retrieved_at):
    return MacroPoint(symbol=symbol, date=point_date.isoformat(), value=round(value, 6), source=source, source_url=TRADINGVIEW_SCAN_URL if source == "tradingview" else CNBC_DXY_URL, retrieved_at=retrieved_at, raw_path=raw_path)


def _unavailable(source, reason):
    return CollectorResult(points=[], unavailable_symbols=["DXY"], source_refs=[{"symbol": "DXY", "source": source, "source_url": TRADINGVIEW_SCAN_URL if source == "tradingview" else CNBC_DXY_URL, "reason": reason}])
