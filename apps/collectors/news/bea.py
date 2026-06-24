from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from apps.collectors.news.base import (
    NewsCollectionResult,
    RawNewsItem,
    archive_news_payload,
    stable_news_item_id,
    utc_now_iso,
)

BEA_RELEASE_DATES_URL = "https://apps.bea.gov/API/signup/release_dates.json"
BEA_SOURCE_NAME = "BEA Release Schedule"
BEA_DEFAULT_URL = "https://www.bea.gov/news/schedule"
BEA_RELEVANT_RELEASES = (
    "Personal Income and Outlays",
    "Gross Domestic Product",
)


def collect_bea_schedule(
    *,
    retrieved_date: str,
    storage_root: Path,
    schedule_url: str = BEA_RELEASE_DATES_URL,
    client: Any | None = None,
) -> NewsCollectionResult:
    if client is not None:
        return _collect_with_client(
            retrieved_date=retrieved_date,
            storage_root=storage_root,
            schedule_url=schedule_url,
            client=client,
        )
    with httpx.Client(timeout=20.0, headers={"User-Agent": "finance-agent/0.1"}, trust_env=False) as http_client:
        return _collect_with_client(
            retrieved_date=retrieved_date,
            storage_root=storage_root,
            schedule_url=schedule_url,
            client=http_client,
        )


def _collect_with_client(
    *,
    retrieved_date: str,
    storage_root: Path,
    schedule_url: str,
    client: Any,
) -> NewsCollectionResult:
    try:
        response = client.get(schedule_url)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        return NewsCollectionResult(
            source_key="bea_calendar",
            status="unavailable",
            items=[],
            unavailable_feeds=["release_schedule"],
            source_refs=[{
                "source_ref": "bea_calendar:release_schedule",
                "source": "bea_calendar",
                "source_url": schedule_url,
                "status": "failed",
                "reason": f"{type(exc).__name__}: {exc}",
            }],
        )

    fetched_at = utc_now_iso()
    raw_path = archive_news_payload(
        storage_root=storage_root,
        layer="raw",
        source_key="bea",
        retrieved_date=retrieved_date,
        name="schedule",
        payload={"source_key": "bea_calendar", "source_url": schedule_url, "fetched_at": fetched_at, "payload": payload},
    )
    items = _parse_bea_release_dates(payload=payload, fetched_at=fetched_at)
    parsed_path = archive_news_payload(
        storage_root=storage_root,
        layer="parsed",
        source_key="bea",
        retrieved_date=retrieved_date,
        name="schedule",
        payload={
            "source_key": "bea_calendar",
            "source_url": schedule_url,
            "fetched_at": fetched_at,
            "items": [item.to_dict() for item in items],
        },
    )
    items = [RawNewsItem(**{**item.to_dict(), "raw_path": raw_path, "parsed_path": parsed_path}) for item in items]
    status = "success" if items else "unavailable"
    return NewsCollectionResult(
        source_key="bea_calendar",
        status=status,
        items=items,
        source_refs=[{
            "source_ref": "bea_calendar:release_schedule",
            "source": "bea_calendar",
            "source_url": schedule_url,
            "raw_path": raw_path,
            "parsed_path": parsed_path,
            "status": "ok" if items else "empty",
        }],
        unavailable_feeds=[] if items else ["release_schedule"],
    )


def _parse_bea_release_dates(*, payload: dict[str, Any], fetched_at: str) -> list[RawNewsItem]:
    items: list[RawNewsItem] = []
    seen: set[tuple[str, str]] = set()
    for release_name, release_payload in payload.items():
        if not _is_relevant_bea_release(release_name):
            continue
        release_dates = release_payload.get("release_dates", []) if isinstance(release_payload, dict) else []
        release_url = release_payload.get("url", BEA_DEFAULT_URL) if isinstance(release_payload, dict) else BEA_DEFAULT_URL
        for published_at in release_dates:
            if not isinstance(published_at, str) or not published_at:
                continue
            event_key = (release_name, published_at)
            if event_key in seen:
                continue
            seen.add(event_key)
            duplicate_key = stable_news_item_id(
                source_key="bea_calendar",
                title=f"{release_name} {published_at}",
                url=release_url,
            )
            items.append(RawNewsItem(
                source_key="bea_calendar",
                source_name=BEA_SOURCE_NAME,
                source_type="official",
                feed_key="release_schedule",
                title=release_name,
                url=release_url,
                domain=urlparse(release_url).netloc.lower().removeprefix("www.") or "bea.gov",
                published_at=published_at,
                fetched_at=fetched_at,
                summary=None,
                source_country="US",
                source_language="en",
                event_type=_classify_bea_event(release_name),
                verification_status="official_confirmed",
                duplicate_key=duplicate_key,
                raw_payload={"release_name": release_name},
            ))
    return items


def _is_relevant_bea_release(release_name: str) -> bool:
    normalized = release_name.lower()
    return any(name.lower() in normalized for name in BEA_RELEVANT_RELEASES)


def _classify_bea_event(release_name: str) -> str:
    normalized = release_name.lower()
    if "personal income" in normalized or "outlays" in normalized or "pce" in normalized:
        return "pce_release"
    if "gross domestic product" in normalized or "gdp" in normalized:
        return "gdp_release"
    return "official_macro_data_release"
