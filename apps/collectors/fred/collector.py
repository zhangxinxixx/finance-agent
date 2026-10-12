from __future__ import annotations

import csv
import os
import time
from concurrent.futures import ThreadPoolExecutor
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
    "WTREGEN",
    "WALCL",
    "SOFR",
    "EFFR",
    "IORB",
    "DGS2",
    "DGS3MO",
    "DGS5",
    "DGS10",
    "DGS30",
    "DFII10",
    "DFII5",
    "DFII30",
    "T5YIE",
    "T5YIFR",
    "T10YIE",
    "DTWEXBGS",
    "BAMLH0A0HYM2",
    "DCOILWTICO",
    "DCOILBRENTEU",
    "VIXCLS",
    # Official FRED macro releases used as dated context.  These are kept in
    # the raw/parsed chain even when a release is stale at the run cutoff;
    # the feature layer decides whether they can support a current signal.
    "CPIAUCSL", "CPILFESL", "CPIAUCNS", "CPILFENS", "PCEPILFE",
    "CPIENGSL", "CPIUFDSL", "CUSR0000SAH1", "CUSR0000SEHA", "CUSR0000SEHC",
    "CUSR0000SACL1E", "CUSR0000SASLE",
    "PPIFIS",
    "PPIACO",
    "PCEPI",
    "JTSJOL",
    "ICSA",
    "NAPM",
)
FRED_MILLIONS_TO_BILLIONS = frozenset({"WRESBAL", "WTREGEN", "WALCL"})
FRED_OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"
FRED_GRAPH_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
FRED_DEFAULT_REQUEST_TIMEOUT_SECONDS = 10.0
FRED_DEFAULT_MAX_WORKERS = 6
FRED_DEFAULT_OBSERVATION_WINDOW_DAYS = 90
FRED_MONTHLY_OBSERVATION_WINDOW_DAYS = 450
FRED_MONTHLY_SERIES = frozenset({
    "PAYEMS", "CES0500000003", "UNRATE", "CIVPART",
    "CPILFESL", "CPIAUCNS", "CPILFENS", "PCEPILFE", "CPIENGSL", "CPIUFDSL",
    "CUSR0000SAH1", "CUSR0000SEHA", "CUSR0000SEHC", "CUSR0000SACL1E", "CUSR0000SASLE",
    "CPIAUCSL", "PPIFIS", "PPIACO", "PCEPI", "JTSJOL", "NAPM",
})


class FredFetchError(RuntimeError):
    """A safe-to-render FRED failure that never includes request URLs."""

    def __init__(
        self,
        *,
        symbol: str,
        reason_code: str,
        error_type: str,
        http_status: int | None = None,
    ) -> None:
        self.symbol = symbol
        self.reason_code = reason_code
        self.error_type = error_type
        self.http_status = http_status
        details = [f"series_id={symbol}", f"error_type={error_type}"]
        if http_status is not None:
            details.append(f"http_status={http_status}")
        super().__init__(f"FRED request failed: {reason_code}; {'; '.join(details)}")


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
    if not symbols:
        return CollectorResult(points=[], unavailable_symbols=[], source_refs=[])

    timeout_seconds = _fred_request_timeout_seconds()
    max_workers = min(len(symbols), _fred_max_workers())
    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="fred") as executor:
        futures = {
            symbol: executor.submit(
                _collect_fred_symbol,
                symbol=symbol,
                retrieved_date=retrieved_date,
                storage_root=storage_root,
                api_key=api_key,
                timeout_seconds=timeout_seconds,
            )
            for symbol in symbols
        }
        # Merge in request order so artifacts and API results remain deterministic.
        for symbol in symbols:
            try:
                result = futures[symbol].result()
            except Exception as exc:
                unavailable.append(symbol)
                refs.append(
                    _fred_failure_ref(
                        symbol=symbol,
                        source_url=fred_source_url(symbol) if api_key else fred_graph_csv_url(symbol),
                        exc=exc,
                    )
                )
                continue
            all_points.extend(result.points)
            unavailable.extend(result.unavailable_symbols)
            refs.extend(result.source_refs)
    return CollectorResult(points=all_points, unavailable_symbols=unavailable, source_refs=refs)


def _collect_fred_symbol(
    *,
    symbol: str,
    retrieved_date: str,
    storage_root: Path,
    api_key: str | None,
    timeout_seconds: float,
) -> CollectorResult:
    import httpx

    with httpx.Client(
        timeout=timeout_seconds,
        headers={"User-Agent": "finance-agent/0.1"},
        trust_env=False,
    ) as client:
        if api_key:
            payload = _fetch_fred_payload_with_retry(
                client,
                symbol=symbol,
                api_key=api_key,
                retrieved_date=retrieved_date,
            )
            source_url = _safe_fred_source_url(symbol)
        else:
            payload = _fetch_fred_graph_csv_payload_with_retry(
                client,
                symbol=symbol,
                retrieved_date=retrieved_date,
            )
            source_url = fred_graph_csv_url(symbol)
    return collect_fred_series_from_payload(
        symbol=symbol,
        payload=payload,
        retrieved_date=retrieved_date,
        storage_root=storage_root,
        source_url=source_url,
    )


def _fred_request_timeout_seconds() -> float:
    raw = os.getenv(
        "FINANCE_AGENT_FRED_REQUEST_TIMEOUT_SECONDS",
        str(FRED_DEFAULT_REQUEST_TIMEOUT_SECONDS),
    )
    try:
        return max(1.0, min(float(raw), 30.0))
    except ValueError:
        return FRED_DEFAULT_REQUEST_TIMEOUT_SECONDS


def _fred_max_workers() -> int:
    raw = os.getenv("FINANCE_AGENT_FRED_MAX_WORKERS", str(FRED_DEFAULT_MAX_WORKERS))
    try:
        return max(1, min(int(raw), 12))
    except ValueError:
        return FRED_DEFAULT_MAX_WORKERS


def _fetch_fred_payload_with_retry(client, *, symbol: str, api_key: str, retrieved_date: str, attempts: int = 3) -> dict:
    last_exc: Exception | None = None
    start_date = _fred_observation_start(symbol=symbol, retrieved_date=retrieved_date)
    for attempt in range(attempts):
        try:
            response = client.get(
                FRED_OBSERVATIONS_URL,
                params={
                    "series_id": symbol,
                    "api_key": api_key,
                    "file_type": "json",
                    "sort_order": "asc",
                    "observation_start": start_date,
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
        raise _safe_fred_fetch_error(symbol=symbol, exc=last_exc) from None
    raise RuntimeError("FRED request failed without exception")


def _fetch_fred_graph_csv_payload_with_retry(client, *, symbol: str, retrieved_date: str, attempts: int = 2) -> dict:
    last_exc: Exception | None = None
    start_date = _fred_observation_start(symbol=symbol, retrieved_date=retrieved_date)
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
        raise _safe_fred_fetch_error(symbol=symbol, exc=last_exc) from None
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


def _safe_fred_fetch_error(*, symbol: str, exc: Exception) -> FredFetchError:
    import httpx

    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    if isinstance(status_code, int):
        reason_code = "http_error"
    elif isinstance(exc, httpx.TransportError):
        reason_code = "transport_error"
    else:
        reason_code = "request_error"
    return FredFetchError(
        symbol=symbol,
        reason_code=reason_code,
        error_type=type(exc).__name__,
        http_status=status_code if isinstance(status_code, int) else None,
    )


def _fred_failure_ref(*, symbol: str, source_url: str, exc: Exception) -> dict[str, str]:
    failure = exc if isinstance(exc, FredFetchError) else _safe_fred_fetch_error(symbol=symbol, exc=exc)
    ref = {
        "symbol": symbol,
        "source": "fred",
        "source_url": source_url,
        "status": "unavailable",
        "reason_code": failure.reason_code,
        "error_type": failure.error_type,
        "reason": str(failure),
    }
    if failure.http_status is not None:
        ref["http_status"] = str(failure.http_status)
    return ref


def _fred_observation_start(*, symbol: str, retrieved_date: str) -> str:
    window_days = FRED_MONTHLY_OBSERVATION_WINDOW_DAYS if symbol in FRED_MONTHLY_SERIES else FRED_DEFAULT_OBSERVATION_WINDOW_DAYS
    return (date.fromisoformat(retrieved_date) - timedelta(days=window_days)).isoformat()
