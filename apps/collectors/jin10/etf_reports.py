"""Collector for Jin10 Mini Program gold and silver ETF reports."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from apps.collectors.news.base import NewsCollectionResult, archive_news_payload


SOURCE_KEY = "jin10_minipro_etf_reports"
API_URL = "https://mp-api.jin10.com/api/etf-reports"
APP_ID = "fiXF2nOnDycGutVA"
ETF_REPORTS = {
    "gold": {"attr_id": 1, "fund_name": "SPDR Gold Trust"},
    "silver": {"attr_id": 2, "fund_name": "iShares Silver Trust"},
}
DEFAULT_HEADERS = {
    "User-Agent": "finance-agent/0.1",
    "Accept": "application/json",
    "x-app-id": APP_ID,
    "x-version": "1.0",
}


def collect_jin10_etf_reports(
    *,
    retrieved_date: str,
    storage_root: Path,
    client: Any | None = None,
) -> NewsCollectionResult:
    """Fetch both ETF reports and archive the unmodified API envelopes."""

    close_client = False
    if client is None:
        import httpx

        client = httpx.Client(timeout=20.0, follow_redirects=True)
        close_client = True

    source_refs: list[dict[str, Any]] = []
    unavailable: list[str] = []
    warnings: list[str] = []
    fetched_at = datetime.now(timezone.utc).isoformat()
    try:
        for asset, config in ETF_REPORTS.items():
            try:
                envelope = fetch_jin10_etf_report(
                    client=client,
                    retrieved_date=retrieved_date,
                    asset=asset,
                    config=config,
                    fetched_at=fetched_at,
                )
                payload = envelope["payload"]
                raw_path = archive_news_payload(
                    storage_root=storage_root,
                    layer="raw",
                    source_key=SOURCE_KEY,
                    retrieved_date=retrieved_date,
                    name=asset,
                    payload=envelope,
                )
                api_status = payload.get("status")
                rows = payload.get("data")
                status = "ok" if api_status == 200 and isinstance(rows, list) and rows else "unavailable"
                if status != "ok":
                    unavailable.append(asset)
                    warnings.append(f"{asset} ETF report returned no usable rows")
                source_refs.append(
                    {
                        "source": "jin10_minipro",
                        "source_key": SOURCE_KEY,
                        "source_url": API_URL,
                        "asset": asset,
                        "attr_id": config["attr_id"],
                        "fund_name": config["fund_name"],
                        "raw_path": raw_path,
                        "status": status,
                        "provider_role": "supplemental_source",
                        "source_tier": "supplemental",
                        "verification_status": "single_source",
                    }
                )
            except Exception as exc:
                unavailable.append(asset)
                warnings.append(f"{asset} ETF report failed: {type(exc).__name__}: {exc}")
    finally:
        if close_client:
            client.close()

    success_count = sum(ref.get("status") == "ok" for ref in source_refs)
    status = "success" if success_count == len(ETF_REPORTS) else "partial_success" if success_count else "unavailable"
    return NewsCollectionResult(
        source_key=SOURCE_KEY,
        status=status,
        items=[],
        source_refs=source_refs,
        unavailable_feeds=unavailable,
        warnings=warnings,
    )


def fetch_jin10_etf_report(
    *,
    client: Any,
    retrieved_date: str,
    asset: str,
    config: dict[str, Any],
    fetched_at: str | None = None,
) -> dict[str, Any]:
    """Fetch one report envelope without archiving it."""

    params = {
        "attr_id": config["attr_id"],
        "date": retrieved_date,
        "date_start": _lookback_start(retrieved_date),
        "all": 1,
    }
    response = client.get(API_URL, params=params, headers=DEFAULT_HEADERS)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("ETF report response is not an object")
    return {
        "source_key": SOURCE_KEY,
        "asset": asset,
        "attr_id": config["attr_id"],
        "fund_name": config["fund_name"],
        "fetched_at": fetched_at or datetime.now(timezone.utc).isoformat(),
        "request_params": params,
        "payload": payload,
    }


def _lookback_start(retrieved_date: str) -> str:
    from datetime import date, timedelta

    try:
        value = date.fromisoformat(retrieved_date)
    except ValueError:
        value = datetime.now(timezone.utc).date()
    return (value - timedelta(days=45)).isoformat()
