from __future__ import annotations

from pathlib import Path

import httpx

from apps.parsers.macro.models import CollectorResult, MacroPoint
from apps.parsers.macro.storage import archive_raw_payload, utc_now_iso

TREASURY_SERIES = ("TGA",)
TREASURY_SOURCE_URL = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/dts/operating_cash_balance"
TGA_ACCOUNT_TYPE = "Treasury General Account (TGA) Closing Balance"


def collect_treasury_series(*, retrieved_date: str, storage_root: Path) -> CollectorResult:
    params = {"filter": f"account_type:eq:{TGA_ACCOUNT_TYPE}", "sort": "-record_date", "page[size]": "120"}
    source_url = TREASURY_SOURCE_URL
    try:
        with httpx.Client(timeout=30.0, headers={"User-Agent": "finance-agent/0.1"}, trust_env=False) as client:
            response = client.get(TREASURY_SOURCE_URL, params=params)
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:
        return _unavailable(f"Treasury FiscalData request failed: {type(exc).__name__}: {exc}")

    raw_path = archive_raw_payload(storage_root=storage_root, source="treasury", retrieved_date=retrieved_date, symbol="TGA", payload=payload)
    retrieved_at = utc_now_iso()
    points: list[MacroPoint] = []
    for row in payload.get("data", []):
        value = _numeric_balance(row)
        if value is None:
            continue
        points.append(MacroPoint(symbol="TGA", date=str(row["record_date"]), value=round(value / 1000.0, 6), source="treasury_fiscaldata", source_url=source_url, retrieved_at=retrieved_at, raw_path=raw_path))

    if not points:
        return CollectorResult(points=[], unavailable_symbols=["TGA"], source_refs=[{"symbol": "TGA", "source": "treasury_fiscaldata", "source_url": source_url, "raw_path": raw_path, "reason": "No numeric TGA balances in payload"}])

    return CollectorResult(points=points, unavailable_symbols=[], source_refs=[{"symbol": "TGA", "source": "treasury_fiscaldata", "source_url": source_url, "raw_path": raw_path}])


def _numeric_balance(row: dict[str, object]) -> float | None:
    for field in ("open_today_bal", "close_today_bal"):
        raw_value = row.get(field)
        if raw_value in (None, "", "null"):
            continue
        try:
            return float(str(raw_value).replace(",", ""))
        except ValueError:
            continue
    return None


def _unavailable(reason: str) -> CollectorResult:
    return CollectorResult(points=[], unavailable_symbols=["TGA"], source_refs=[{"symbol": "TGA", "source": "treasury_fiscaldata", "source_url": TREASURY_SOURCE_URL, "reason": reason}])
