from __future__ import annotations

from datetime import date
from pathlib import Path

import httpx

from apps.parsers.macro.models import CollectorResult, MacroPoint
from apps.parsers.macro.storage import archive_raw_payload, utc_now_iso

FED_SERIES = ("IORB",)
FED_SOURCE_URL = "https://www.federalreserve.gov/monetarypolicy/prates/PRATES.json"


def collect_fed_series(*, retrieved_date: str, storage_root: Path) -> CollectorResult:
    try:
        with httpx.Client(timeout=30.0, headers={"User-Agent": "finance-agent/0.1"}, trust_env=False) as client:
            response = client.get(FED_SOURCE_URL)
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:
        return _unavailable(f"Fed PRATES request failed: {type(exc).__name__}: {exc}")

    raw_path = archive_raw_payload(storage_root=storage_root, source="fed", retrieved_date=retrieved_date, symbol="IORB", payload=payload)
    try:
        value = float(str(payload["Value"]).replace("%", ""))
        effective_date = _parse_us_date(str(payload.get("ForDate") or payload.get("EffectiveDate") or retrieved_date))
    except Exception as exc:
        return CollectorResult(points=[], unavailable_symbols=["IORB"], source_refs=[{"symbol": "IORB", "source": "fed_prates", "source_url": FED_SOURCE_URL, "raw_path": raw_path, "reason": f"Payload parse: {type(exc).__name__}: {exc}"}])

    point = MacroPoint(symbol="IORB", date=effective_date, value=value, source="fed_prates", source_url=FED_SOURCE_URL, retrieved_at=utc_now_iso(), raw_path=raw_path)
    return CollectorResult(points=[point], unavailable_symbols=[], source_refs=[{"symbol": "IORB", "source": "fed_prates", "source_url": FED_SOURCE_URL, "raw_path": raw_path}])


def _parse_us_date(value: str) -> str:
    if "-" in value:
        return date.fromisoformat(value[:10]).isoformat()
    month, day, year = value.split("/")
    return date(int(year), int(month), int(day)).isoformat()


def _unavailable(reason: str) -> CollectorResult:
    return CollectorResult(points=[], unavailable_symbols=["IORB"], source_refs=[{"symbol": "IORB", "source": "fed_prates", "source_url": FED_SOURCE_URL, "reason": reason}])
