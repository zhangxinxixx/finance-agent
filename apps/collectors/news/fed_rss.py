from __future__ import annotations

import html
import re
from datetime import timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from xml.etree import ElementTree

import httpx

from apps.collectors.news.base import (
    NewsCollectionResult,
    RawNewsItem,
    archive_news_payload,
    stable_news_item_id,
    utc_now_iso,
)

FED_RSS_FEEDS: dict[str, str] = {
    "press_releases": "https://www.federalreserve.gov/feeds/press_all.xml",
    "monetary_policy": "https://www.federalreserve.gov/feeds/press_monetary.xml",
    "speeches_testimony": "https://www.federalreserve.gov/feeds/speeches_and_testimony.xml",
    "h41": "https://www.federalreserve.gov/feeds/h41.xml",
    "h15": "https://www.federalreserve.gov/feeds/h15.xml",
}

FED_RSS_SOURCE_NAME = "Federal Reserve RSS"


def collect_fed_rss(
    *,
    retrieved_date: str,
    storage_root: Path,
    feeds: dict[str, str] | None = None,
    client: Any | None = None,
) -> NewsCollectionResult:
    feed_urls = feeds or FED_RSS_FEEDS
    items: list[RawNewsItem] = []
    source_refs: list[dict[str, Any]] = []
    unavailable_feeds: list[str] = []

    if client is not None:
        for feed_key, feed_url in feed_urls.items():
            _collect_single_feed(
                feed_key=feed_key,
                feed_url=feed_url,
                retrieved_date=retrieved_date,
                storage_root=storage_root,
                client=client,
                items=items,
                source_refs=source_refs,
                unavailable_feeds=unavailable_feeds,
            )
    else:
        with httpx.Client(timeout=20.0, headers={"User-Agent": "finance-agent/0.1"}, trust_env=False) as http_client:
            for feed_key, feed_url in feed_urls.items():
                _collect_single_feed(
                    feed_key=feed_key,
                    feed_url=feed_url,
                    retrieved_date=retrieved_date,
                    storage_root=storage_root,
                    client=http_client,
                    items=items,
                    source_refs=source_refs,
                    unavailable_feeds=unavailable_feeds,
                )

    if items and unavailable_feeds:
        status = "partial"
    elif items:
        status = "success"
    else:
        status = "unavailable"
    return NewsCollectionResult(
        source_key="fed_rss",
        status=status,
        items=items,
        source_refs=source_refs,
        unavailable_feeds=unavailable_feeds,
    )


def _collect_single_feed(
    *,
    feed_key: str,
    feed_url: str,
    retrieved_date: str,
    storage_root: Path,
    client: Any,
    items: list[RawNewsItem],
    source_refs: list[dict[str, Any]],
    unavailable_feeds: list[str],
) -> None:
    try:
        response = client.get(feed_url)
        response.raise_for_status()
        feed_text = response.text
    except Exception as exc:
        unavailable_feeds.append(feed_key)
        source_refs.append({
            "source_ref": f"fed_rss:{feed_key}",
            "source": "fed_rss",
            "feed_key": feed_key,
            "source_url": feed_url,
            "status": "failed",
            "reason": f"{type(exc).__name__}: {exc}",
        })
        return

    fetched_at = utc_now_iso()
    raw_path = archive_news_payload(
        storage_root=storage_root,
        layer="raw",
        source_key="fed_rss",
        retrieved_date=retrieved_date,
        name=feed_key,
        payload={"feed_key": feed_key, "source_url": feed_url, "fetched_at": fetched_at, "xml": feed_text},
    )
    parsed_items = _parse_rss_items(feed_text=feed_text, feed_key=feed_key, fetched_at=fetched_at)
    parsed_payload = {
        "source_key": "fed_rss",
        "feed_key": feed_key,
        "source_url": feed_url,
        "fetched_at": fetched_at,
        "items": [item.to_dict() for item in parsed_items],
    }
    parsed_path = archive_news_payload(
        storage_root=storage_root,
        layer="parsed",
        source_key="fed_rss",
        retrieved_date=retrieved_date,
        name=feed_key,
        payload=parsed_payload,
    )

    for item in parsed_items:
        items.append(RawNewsItem(
            **{**item.to_dict(), "raw_path": raw_path, "parsed_path": parsed_path}
        ))
    source_refs.append({
        "source_ref": f"fed_rss:{feed_key}",
        "source": "fed_rss",
        "feed_key": feed_key,
        "source_url": feed_url,
        "raw_path": raw_path,
        "parsed_path": parsed_path,
        "status": "ok",
    })


def _parse_rss_items(*, feed_text: str, feed_key: str, fetched_at: str) -> list[RawNewsItem]:
    root = ElementTree.fromstring(feed_text)
    result: list[RawNewsItem] = []
    for node in root.findall(".//item"):
        title = _node_text(node, "title")
        url = _node_text(node, "link")
        if not title or not url:
            continue
        summary = _clean_summary(_node_text(node, "description"))
        published_at = _parse_datetime(_node_text(node, "pubDate"))
        duplicate_key = stable_news_item_id(source_key="fed_rss", title=title, url=url)
        result.append(RawNewsItem(
            source_key="fed_rss",
            source_name=FED_RSS_SOURCE_NAME,
            source_type="official",
            feed_key=feed_key,
            title=title,
            url=url,
            domain=urlparse(url).netloc.lower().removeprefix("www."),
            published_at=published_at,
            fetched_at=fetched_at,
            summary=summary,
            source_country="US",
            source_language="en",
            event_type=_classify_fed_event(feed_key=feed_key, title=title),
            verification_status="official_confirmed",
            duplicate_key=duplicate_key,
            raw_payload={"feed_key": feed_key},
        ))
    return result


def _node_text(node: ElementTree.Element, tag: str) -> str:
    child = node.find(tag)
    if child is None or child.text is None:
        return ""
    return child.text.strip()


def _clean_summary(value: str) -> str | None:
    if not value:
        return None
    without_tags = re.sub(r"<[^>]+>", " ", value)
    normalized = re.sub(r"\s+", " ", html.unescape(without_tags)).strip()
    return normalized or None


def _parse_datetime(value: str) -> str | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _classify_fed_event(*, feed_key: str, title: str) -> str:
    normalized = title.lower()
    if "minutes" in normalized:
        return "fomc_minutes"
    if "fomc" in normalized or "federal open market committee" in normalized or "statement" in normalized:
        return "fomc_statement"
    if feed_key == "speeches_testimony":
        return "fed_speech"
    if feed_key == "h15":
        return "official_rate_data_release"
    if feed_key == "h41":
        return "fed_balance_sheet_release"
    return "fed_policy_release"
