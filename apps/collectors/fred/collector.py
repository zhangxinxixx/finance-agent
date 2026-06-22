from __future__ import annotations

import csv
import time
from datetime import date, timedelta
from io import StringIO
from pathlib import Path

from apps.runtime.secret_resolver import resolve_runtime_secret
from apps.parsers.macro.models import CollectorResult, MacroPoint
from apps.parsers.macro.storage import archive_raw_payload, utc_now_iso

FRED_SERIES = (
    "RRPONTSYD",
    "RRPONTSYAWARD",
    "WRESBAL",
    "SOFR",
    "EFFR",
    "IORB",
    "DGS2",
    "DGS10",
    "DFII10",
    "T10YIE",
)
FRED_MILLIONS_TO_BILLIONS = frozenset({"WRESBAL"})
FRED_OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"
FRED_GRAPH_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"


def collect_fred_series_from_payload(*, symbol: str, payload: dict, retrieved_date: str, storage_root: Path, source_url: str, retrieved_at: str | None = None) -> CollectorResult:
    raw_path = archive_raw_payload(storage_root=storage_root, source="fred", retrieved_date=retrieved_date, symbol=symbol, payload=payload)
    retrieved_at = retrieved_at or utc_now_iso()
    points: list[MacroPoint] = []
    for observation in payload.get("observations", []):
        observation_date = str(observation.get("date") or "")
        if not observation_date or observation_date > retrieved_date:
            continue
        value = observation.get("value")
        if value in (None, "", "."):
            continue
        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            continue
        if symbol in FRED_MILLIONS_TO_BILLIONS:
            numeric_value = round(numeric_value / 1000.0, 6)
        points.append(MacroPoint(symbol=symbol, date=observation_date, value=numeric_value, source="fred", source_url=source_url, retrieved_at=retrieved_at, raw_path=raw_path))
    source_refs = [{"symbol": symbol, "source": "fred", "source_url": source_url, "raw_path": raw_path}]
    unavailable = [] if points else [symbol]
    return CollectorResult(points=points, unavailable_symbols=unavailable, source_refs=source_refs)


def collect_fred_series(*, retrieved_date: str, storage_root: Path, symbols: tuple[str, ...] = FRED_SERIES, api_key: str | None = None) -> CollectorResult:
    api_key = api_key or resolve_runtime_secret("FRED_API_KEY")
    all_points: list[MacroPoint] = []
    unavailable: list[str] = []
    refs: list[dict[str, str]] = []
    import httpx
    with httpx.Client(timeout=30.0, headers={"User-Agent": "finance-agent/0.1"}, trust_env=False) as client:
        for symbol in symbols:
            try:
                if api_key:
                    payload = _fetch_fred_payload_with_retry(client, symbol=symbol, api_key=api_key, retrieved_date=retrieved_date)
                    source_url = _safe_fred_source_url(symbol)
                else:
                    payload = _fetch_fred_graph_csv_payload_with_retry(client, symbol=symbol, retrieved_date=retrieved_date)
                    source_url = fred_graph_csv_url(symbol)
            except Exception as exc:
                unavailable.append(symbol)
                refs.append({"symbol": symbol, "source": "fred", "source_url": fred_source_url(symbol) if api_key else fred_graph_csv_url(symbol), "reason": f"FRED request failed: {type(exc).__name__}: {exc}"})
                continue
            result = collect_fred_series_from_payload(symbol=symbol, payload=payload, retrieved_date=retrieved_date, storage_root=storage_root, source_url=source_url)
            all_points.extend(result.points)
            unavailable.extend(result.unavailable_symbols)
            refs.extend(result.source_refs)
    return CollectorResult(points=all_points, unavailable_symbols=unavailable, source_refs=refs)


def _fetch_fred_payload_with_retry(client, *, symbol: str, api_key: str, retrieved_date: str, attempts: int = 3) -> dict:
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            response = client.get(
                FRED_OBSERVATIONS_URL,
                params={
                    "series_id": symbol,
                    "api_key": api_key,
                    "file_type": "json",
                    "sort_order": "asc",
                    "observation_end": retrieved_date,
                },
            )
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            last_exc = exc
            if attempt < attempts - 1:
                time.sleep(0.5 * (attempt + 1))
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("FRED request failed without exception")


def _fetch_fred_graph_csv_payload_with_retry(client, *, symbol: str, retrieved_date: str, attempts: int = 2) -> dict:
    last_exc: Exception | None = None
    start_date = (date.fromisoformat(retrieved_date) - timedelta(days=90)).isoformat()
    for attempt in range(attempts):
        try:
            response = client.get(FRED_GRAPH_CSV_URL, params={"id": symbol, "cosd": start_date, "coed": retrieved_date})
            response.raise_for_status()
            return _fred_csv_to_observations_payload(symbol=symbol, csv_text=response.text)
        except Exception as exc:
            last_exc = exc
            if attempt < attempts - 1:
                time.sleep(0.5 * (attempt + 1))
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("FRED CSV request failed without exception")


def _fred_csv_to_observations_payload(*, symbol: str, csv_text: str) -> dict:
    observations: list[dict[str, str]] = []
    reader = csv.DictReader(StringIO(csv_text))
    value_field = symbol if symbol in (reader.fieldnames or []) else (reader.fieldnames or ["", ""])[-1]
    for row in reader:
        date_value = row.get("observation_date") or row.get("DATE") or row.get("date")
        value = row.get(value_field)
        if not date_value:
            continue
        observations.append({"date": date_value, "value": value or "."})
    return {"observations": observations, "source": "fred_graph_csv", "symbol": symbol}


def fred_source_url(symbol: str) -> str:
    return f"{FRED_OBSERVATIONS_URL}?series_id={symbol}&file_type=json&sort_order=asc"


def fred_graph_csv_url(symbol: str) -> str:
    return f"{FRED_GRAPH_CSV_URL}?id={symbol}"


def _safe_fred_source_url(symbol: str) -> str:
    return fred_source_url(symbol)
