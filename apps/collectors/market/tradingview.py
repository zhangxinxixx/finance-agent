"""Bounded public TV scanner read with immutable raw and parsed evidence."""

import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx

from apps.parsers.market.tradingview import ALL_INSTRUMENTS, COLUMNS, CORE_INSTRUMENTS, parse_tradingview
from apps.parsers.macro.storage import archive_raw_payload
from apps.runtime.immutable_artifact import immutable_json_item, write_immutable_artifact_bundle

URL = "https://scanner.tradingview.com/global/scan"


def collect_tradingview(*, retrieved_date, storage_root, client=None, symbols=None):
    symbols = tuple(CORE_INSTRUMENTS) if symbols is None else tuple(dict.fromkeys(symbols))
    if not symbols or any(symbol not in ALL_INSTRUMENTS for symbol in symbols):
        raise ValueError("unsupported TradingView symbol selection")
    instruments = {symbol: ALL_INSTRUMENTS[symbol] for symbol in symbols}
    request = {"symbols": {"tickers": list(symbols), "query": {"types": []}}, "columns": COLUMNS}
    owned = client is None
    client = client or httpx.Client(timeout=20, trust_env=False, headers={"User-Agent": "Mozilla/5.0"})
    payload, error = {}, None
    try:
        response = client.post(URL, json=request)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        error = "tradingview_collection_failed:" + type(exc).__name__
    finally:
        if owned:
            client.close()
    retrieved_at = datetime.now(UTC).isoformat()
    raw_path = archive_raw_payload(storage_root=Path(storage_root), source="tradingview_cross_asset",
                                   retrieved_date=retrieved_date, symbol="CROSS_ASSET",
                                   payload={"request": request, "response": payload, "error": error, "retrieved_at": retrieved_at})
    ref = {"source": "tradingview_cross_asset", "source_url": URL, "raw_path": raw_path,
           "retrieved_at": retrieved_at, "source_tier": "secondary", "evidence_scope": "provider_observation"}
    try:
        parsed = parse_tradingview(payload if not error else {"data": []}, retrieved_at=retrieved_at,
                                   source_ref=ref, instruments=instruments)
    except ValueError:
        error = "tradingview_payload_invalid"
        parsed = parse_tradingview({"data": []}, retrieved_at=retrieved_at, source_ref=ref,
                                   instruments=instruments)
    parsed["error"] = error
    path = Path(storage_root) / "parsed" / "tradingview" / retrieved_date / (uuid.uuid4().hex + ".json")
    write_immutable_artifact_bundle([immutable_json_item(path, parsed)], storage_root=storage_root)
    return {**parsed, "parsed_path": str(path.relative_to(Path(storage_root)))}
