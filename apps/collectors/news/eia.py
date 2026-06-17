from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import httpx

from apps.collectors.news.base import (
    NewsCollectionResult,
    RawNewsItem,
    archive_news_payload,
    stable_news_item_id,
    utc_now_iso,
)

EIA_WPSR_SCHEDULE_URL = "https://www.eia.gov/petroleum/supply/weekly/schedule.php"
EIA_WPSR_URL = "https://www.eia.gov/petroleum/supply/weekly/"
EIA_SOURCE_NAME = "EIA Energy Events"


def collect_eia_energy_events(
    *,
    retrieved_date: str,
    storage_root: Path,
    schedule_url: str = EIA_WPSR_SCHEDULE_URL,
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
        html_text = response.text
    except Exception as exc:
        return NewsCollectionResult(
            source_key="eia_energy",
            status="unavailable",
            items=[],
            unavailable_feeds=["weekly_petroleum_status_report"],
            source_refs=[{
                "source_ref": "eia_energy:weekly_petroleum_status_report",
                "source": "eia_energy",
                "source_url": schedule_url,
                "status": "failed",
                "reason": f"{type(exc).__name__}: {exc}",
            }],
        )

    fetched_at = utc_now_iso()
    raw_path = archive_news_payload(
        storage_root=storage_root,
        layer="raw",
        source_key="eia",
        retrieved_date=retrieved_date,
        name="weekly_petroleum_status_report",
        payload={"source_key": "eia_energy", "source_url": schedule_url, "fetched_at": fetched_at, "html": html_text},
    )
    items = _parse_eia_schedule(html_text=html_text, fetched_at=fetched_at)
    parsed_path = archive_news_payload(
        storage_root=storage_root,
        layer="parsed",
        source_key="eia",
        retrieved_date=retrieved_date,
        name="weekly_petroleum_status_report",
        payload={
            "source_key": "eia_energy",
            "source_url": schedule_url,
            "fetched_at": fetched_at,
            "items": [item.to_dict() for item in items],
        },
    )
    items = [RawNewsItem(**{**item.to_dict(), "raw_path": raw_path, "parsed_path": parsed_path}) for item in items]
    status = "success" if items else "unavailable"
    return NewsCollectionResult(
        source_key="eia_energy",
        status=status,
        items=items,
        source_refs=[{
            "source_ref": "eia_energy:weekly_petroleum_status_report",
            "source": "eia_energy",
            "source_url": schedule_url,
            "raw_path": raw_path,
            "parsed_path": parsed_path,
            "status": "ok" if items else "empty",
        }],
        unavailable_feeds=[] if items else ["weekly_petroleum_status_report"],
    )


def _parse_eia_schedule(*, html_text: str, fetched_at: str) -> list[RawNewsItem]:
    rows = re.findall(r"<tr[^>]*>.*?</tr>", html_text, flags=re.IGNORECASE | re.DOTALL)
    items: list[RawNewsItem] = []
    for row in rows:
        cells = [_clean_cell(cell) for cell in re.findall(r"<(?:td|th)[^>]*>(.*?)</(?:td|th)>", row, flags=re.IGNORECASE | re.DOTALL)]
        if len(cells) < 5 or cells[0].lower().startswith("data for the week"):
            continue
        week_ending, release_date, _release_day, release_time, holiday = cells[:5]
        published_at = _parse_eia_release_datetime(release_date=release_date, release_time=release_time)
        if not published_at:
            continue
        summary = f"Data for the week ending {week_ending}"
        if holiday:
            summary += f"; holiday: {holiday}"
        duplicate_key = stable_news_item_id(
            source_key="eia_energy",
            title=f"Weekly Petroleum Status Report {release_date}",
            url=EIA_WPSR_URL,
        )
        items.append(RawNewsItem(
            source_key="eia_energy",
            source_name=EIA_SOURCE_NAME,
            source_type="official",
            feed_key="weekly_petroleum_status_report",
            title="Weekly Petroleum Status Report",
            url=EIA_WPSR_URL,
            domain=urlparse(EIA_WPSR_URL).netloc.lower().removeprefix("www."),
            published_at=published_at,
            fetched_at=fetched_at,
            summary=summary,
            source_country="US",
            source_language="en",
            event_type="energy_inventory_release",
            verification_status="official_confirmed",
            duplicate_key=duplicate_key,
            raw_payload={"week_ending": week_ending, "release_date": release_date, "release_time": release_time, "holiday": holiday},
        ))
    return items


def _clean_cell(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(without_tags)).strip()


def _parse_eia_release_datetime(*, release_date: str, release_time: str) -> str | None:
    try:
        release_date_part = datetime.strptime(release_date, "%B %d, %Y")
        release_time_part = _parse_eia_time(release_time)
    except ValueError:
        return None
    eastern = ZoneInfo("America/New_York")
    combined = release_date_part.replace(
        hour=release_time_part[0],
        minute=release_time_part[1],
        tzinfo=eastern,
    )
    return combined.astimezone(timezone.utc).isoformat()


def _parse_eia_time(value: str) -> tuple[int, int]:
    normalized = value.lower().replace(".", "").strip()
    match = re.match(r"^(\d{1,2}):(\d{2})\s*([ap]m)$", normalized)
    if not match:
        raise ValueError(f"Unsupported EIA release time: {value}")
    hour = int(match.group(1))
    minute = int(match.group(2))
    meridiem = match.group(3)
    if meridiem == "pm" and hour != 12:
        hour += 12
    if meridiem == "am" and hour == 12:
        hour = 0
    return hour, minute
