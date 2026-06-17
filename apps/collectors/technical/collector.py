from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from apps.runtime.secret_resolver import resolve_runtime_secret
from apps.parsers.macro.models import CollectorResult, MacroPoint

YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/GC=F"
YAHOO_TICKER = "GC=F"
DISPLAY_SYMBOL = "XAUUSD"
JIN10_MCP_URL = "https://mcp.jin10.com/mcp"
JIN10_MCP_KEY_ENV = "JIN10_MCP_KEY"
JIN10_SYMBOL = "XAUUSD"


def collect_technical(*, retrieved_date: str, storage_root: Path) -> CollectorResult:
    """Collect XAUUSD price data from Yahoo Finance chart API (v8).

    Archives raw payload to ``storage/raw/technical/yahoo/<date>/``.
    Returns a CollectorResult with one MacroPoint (XAUUSD, source=yahoo_finance)
    and OHLC/SMA data in source_refs notes.
    """

    jin10_result = _collect_from_jin10_quote(retrieved_date=retrieved_date, storage_root=storage_root)
    if jin10_result.points:
        return jin10_result

    params = {"range": "3mo", "interval": "1d"}
    try:
        with httpx.Client(timeout=30.0, headers={"User-Agent": "Mozilla/5.0"}, trust_env=False) as client:
            response = client.get(YAHOO_CHART_URL, params=params)
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        return CollectorResult(
            points=[],
            unavailable_symbols=[DISPLAY_SYMBOL],
            source_refs=[
                {
                    "symbol": DISPLAY_SYMBOL,
                    "source": "yahoo_finance",
                    "source_url": YAHOO_CHART_URL,
                    "reason": f"Yahoo Finance request failed: {type(exc).__name__}: {exc}",
                }
            ],
        )

    raw_path = _archive_raw(
        storage_root=storage_root,
        source="yahoo",
        retrieved_date=retrieved_date,
        symbol=YAHOO_TICKER,
        payload=data,
    )

    try:
        result = data["chart"]["result"][0]
        meta = result["meta"]
        quote = result["indicators"]["quote"][0]

        latest_close = float(meta["regularMarketPrice"])
        previous_close = float(meta.get("chartPreviousClose") or latest_close)

        # Extract OHLC arrays (filter None values)
        closes_all = [float(x) for x in quote["close"] if x is not None]
        opens_all = [float(x) for x in quote["open"] if x is not None]
        highs_all = [float(x) for x in quote["high"] if x is not None]
        lows_all = [float(x) for x in quote["low"] if x is not None]

        if not closes_all:
            raise ValueError("No valid close data in Yahoo Finance response")

        # Latest day OHLC
        latest_open = float(opens_all[-1]) if opens_all else latest_close
        latest_high = float(highs_all[-1]) if highs_all else latest_close
        latest_low = float(lows_all[-1]) if lows_all else latest_close

        # Daily change
        change = round(latest_close - previous_close, 4)

        # SMA20: average of last 20 valid closes
        sma20 = None
        if len(closes_all) >= 20:
            sma20 = round(sum(closes_all[-20:]) / 20.0, 6)

        # SMA50: average of last 50 valid closes
        sma50 = None
        if len(closes_all) >= 50:
            sma50 = round(sum(closes_all[-50:]) / 50.0, 6)

        # Keep up to 50 closes, highs, lows for downstream RSI/ATR computation
        closes_trimmed = closes_all[-50:]
        highs_trimmed = highs_all[-50:] if len(highs_all) >= 50 else highs_all
        lows_trimmed = lows_all[-50:] if len(lows_all) >= 50 else lows_all

    except Exception as exc:
        return CollectorResult(
            points=[],
            unavailable_symbols=[DISPLAY_SYMBOL],
            source_refs=[
                {
                    "symbol": DISPLAY_SYMBOL,
                    "source": "yahoo_finance",
                    "source_url": YAHOO_CHART_URL,
                    "raw_path": raw_path,
                    "reason": f"Payload parse: {type(exc).__name__}: {exc}",
                }
            ],
        )

    retrieved_at = _utc_now_iso()

    extra: dict = {
        "open": latest_open,
        "high": latest_high,
        "low": latest_low,
        "change": change,
        "ma20": sma20,
        "ma50": sma50,
        "closes": closes_trimmed,
        "highs": highs_trimmed,
        "lows": lows_trimmed,
    }

    point = MacroPoint(
        symbol=DISPLAY_SYMBOL,
        date=retrieved_date,
        value=latest_close,
        source="yahoo_finance",
        source_url=YAHOO_CHART_URL,
        retrieved_at=retrieved_at,
        raw_path=raw_path,
    )
    return CollectorResult(
        points=[point],
        unavailable_symbols=[],
        source_refs=[
            {
                "symbol": DISPLAY_SYMBOL,
                "source": "yahoo_finance",
                "source_url": YAHOO_CHART_URL,
                "raw_path": raw_path,
                "notes": extra,
            }
        ],
    )


def _collect_from_jin10_quote(*, retrieved_date: str, storage_root: Path) -> CollectorResult:
    mcp_key = resolve_runtime_secret(JIN10_MCP_KEY_ENV)
    if not mcp_key:
        return CollectorResult(points=[], unavailable_symbols=[], source_refs=[])

    try:
        with httpx.Client(timeout=15.0, headers={"User-Agent": "finance-agent/0.1"}, trust_env=False) as client:
            sid = _mcp_handshake(client, mcp_key)
            if not sid:
                return CollectorResult(points=[], unavailable_symbols=[DISPLAY_SYMBOL], source_refs=[{"symbol": DISPLAY_SYMBOL, "source": "jin10_quote", "reason": "Jin10 MCP handshake failed"}])
            payload = _mcp_tool_call(client, mcp_key, sid, "get_quote", {"code": JIN10_SYMBOL})
    except Exception as exc:
        return CollectorResult(points=[], unavailable_symbols=[], source_refs=[{"symbol": DISPLAY_SYMBOL, "source": "jin10_quote", "reason": f"Jin10 quote failed: {type(exc).__name__}: {exc}"}])

    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return CollectorResult(points=[], unavailable_symbols=[DISPLAY_SYMBOL], source_refs=[{"symbol": DISPLAY_SYMBOL, "source": "jin10_quote", "reason": "Jin10 quote response missing data"}])

    try:
        close = _to_float(data.get("close") or data.get("price") or data.get("last"))
        quote_time = str(data.get("time") or retrieved_date)
        point_date = quote_time.split("T", 1)[0]
        notes = {
            "name": data.get("name"),
            "open": _to_float(data.get("open")),
            "high": _to_float(data.get("high")),
            "low": _to_float(data.get("low")),
            "change": _to_float(data.get("ups_price") or data.get("change")),
            "change_pct": _to_float(data.get("ups_percent") or data.get("change_pct")),
            "volume": data.get("volume"),
            "quote_time": quote_time,
        }
    except Exception as exc:
        return CollectorResult(points=[], unavailable_symbols=[DISPLAY_SYMBOL], source_refs=[{"symbol": DISPLAY_SYMBOL, "source": "jin10_quote", "reason": f"Jin10 quote parse failed: {type(exc).__name__}: {exc}"}])

    raw_path = _archive_raw(storage_root=storage_root, source="jin10_quote", retrieved_date=retrieved_date, symbol=DISPLAY_SYMBOL, payload=payload)
    point = MacroPoint(symbol=DISPLAY_SYMBOL, date=point_date, value=close, source="jin10_quote", source_url=JIN10_MCP_URL, retrieved_at=_utc_now_iso(), raw_path=raw_path)
    return CollectorResult(
        points=[point],
        unavailable_symbols=[],
        source_refs=[{"symbol": DISPLAY_SYMBOL, "source": "jin10_quote", "source_url": JIN10_MCP_URL, "raw_path": raw_path, "notes": notes}],
    )


def _mcp_handshake(client: httpx.Client, mcp_key: str) -> str:
    init_r = client.post(
        JIN10_MCP_URL,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "finance-agent", "version": "0.1"},
            },
        },
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {mcp_key}"},
    )
    sid = init_r.headers.get("Mcp-Session-Id", "")
    if not sid:
        return ""
    client.post(
        JIN10_MCP_URL,
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {mcp_key}", "Mcp-Session-Id": sid},
    )
    return sid


def _mcp_tool_call(client: httpx.Client, mcp_key: str, sid: str, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    resp = client.post(
        JIN10_MCP_URL,
        json={"jsonrpc": "2.0", "id": 99, "method": "tools/call", "params": {"name": tool_name, "arguments": arguments}},
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {mcp_key}", "Mcp-Session-Id": sid},
    )
    result = _parse_sse_result(resp.text)
    if result is None:
        raise RuntimeError(f"Failed to parse SSE for {tool_name}")
    sc = result.get("structuredContent", {})
    if not isinstance(sc, dict):
        return {}
    status = sc.get("status")
    if status and status != 200:
        raise RuntimeError(f"{tool_name} returned status={status}: {sc.get('message', '')}")
    return sc


def _parse_sse_result(text: str) -> dict[str, Any] | None:
    for line in text.split("\n"):
        if line.startswith("data:"):
            data = json.loads(line[5:])
            result = data.get("result")
            return result if isinstance(result, dict) else None
    return None


def _to_float(value: object) -> float:
    if value is None or value == "":
        raise ValueError("empty numeric value")
    return float(str(value).replace(",", ""))


# ---------------------------------------------------------------------------
# Internal helpers (mirror apps/parsers/macro/storage.py pattern)
# ---------------------------------------------------------------------------


def _archive_raw(
    *,
    storage_root: Path,
    source: str,
    retrieved_date: str,
    symbol: str,
    payload: dict,
) -> str:
    raw_dir = storage_root / "raw" / "technical" / source / retrieved_date
    raw_dir.mkdir(parents=True, exist_ok=True)
    suffix = datetime.now(timezone.utc).strftime("%H%M%S%f")
    raw_path = raw_dir / f"{symbol}-{suffix}-{uuid4().hex[:8]}.json"
    raw_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return raw_path.relative_to(storage_root).as_posix()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
