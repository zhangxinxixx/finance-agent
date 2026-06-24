"""Jin10 article/news collector.

Collects financial news articles via Jin10 MCP:
- ``list_news``  → article list with pagination
- ``search_news`` → keyword-based article search
- ``get_news``    → full article content by ID

Produces ``CollectorResult`` entries for downstream analysis.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from apps.collectors.jin10.mcp_client import Jin10MCPClient
from apps.parsers.macro.models import CollectorResult, MacroPoint
from apps.parsers.macro.storage import archive_raw_payload, utc_now_iso

logger = logging.getLogger(__name__)

# Default search keywords for XAUUSD context
DEFAULT_NEWS_KEYWORDS = ["黄金", "美联储", "非农", "CPI", "通胀"]
XNEWS_PUBLIC_SOURCE_KEY = "jin10_xnews_public"
HIGH_VALUE_XNEWS_CATEGORIES = {
    "30": {"label": "金十早餐", "kind": "category", "source_key": XNEWS_PUBLIC_SOURCE_KEY},
    "53": {"label": "热点头条", "kind": "category", "source_key": XNEWS_PUBLIC_SOURCE_KEY},
    "31": {"label": "精选分析", "kind": "category", "source_key": XNEWS_PUBLIC_SOURCE_KEY},
    "58": {"label": "财料", "kind": "category", "source_key": XNEWS_PUBLIC_SOURCE_KEY},
    "421": {"label": "突发新闻", "kind": "topic", "source_key": XNEWS_PUBLIC_SOURCE_KEY},
}

# Maximum full article fetches per run
MAX_FULL_ARTICLES = 5


def collect_articles(
    *,
    retrieved_date: str,
    storage_root: Path,
    keywords: list[str] | None = None,
    mcp_key: str | None = None,
) -> CollectorResult:
    """Collect financial articles from Jin10.

    Strategy:
      1. ``list_news`` → get latest article list (2 pages)
      2. ``search_news`` → keyword searches for gold/Fed/inflation context
      3. ``get_news`` → fetch full content for top articles (limited)

    Args:
        retrieved_date: ISO date string
        storage_root: Root directory for raw payload archives
        keywords: Search keywords (default: gold-related)
        mcp_key: Jin10 MCP API key

    Returns:
        CollectorResult with article MacroPoint entries
    """
    keywords = keywords or DEFAULT_NEWS_KEYWORDS
    points: list[MacroPoint] = []
    unavailable: list[str] = []
    refs: list[dict[str, Any]] = []
    retrieved_at = utc_now_iso()
    article_ids: set[str] = set()

    # Track cursor across paginated requests
    _last_cursor: str | None = None

    try:
        with Jin10MCPClient(mcp_key=mcp_key) as client:
            # ── list_news (2 pages) ────────────────────────────
            for page in range(2):
                cursor = _last_cursor if page > 0 else None
                data = client.list_news(cursor=cursor)
                _last_cursor = data.get("next_cursor", "")
                ref_path = _archive(
                    data, retrieved_date, f"news_list_p{page}", storage_root, refs
                )
                ids = _extract_article_list_points(
                    data, ref_path, points, retrieved_at, retrieved_date
                )
                article_ids.update(ids)
                if not _last_cursor:
                    break

            # ── search_news by keywords ───────────────────────
            for kw in keywords:
                data = client.search_news(kw)
                ref_path = _archive(
                    data, retrieved_date, f"news_search_{kw}", storage_root, refs
                )
                ids = _extract_article_list_points(
                    data, ref_path, points, retrieved_at, retrieved_date
                )
                article_ids.update(ids)

            # ── get_news for top articles ────────────────────
            full_articles = 0
            for aid in list(article_ids)[:MAX_FULL_ARTICLES]:
                try:
                    data = client.get_news(aid)
                    ref_path = _archive(
                        data, retrieved_date, f"news_article_{aid}", storage_root, refs
                    )
                    _extract_full_article(
                        data, aid, ref_path, points, retrieved_at, retrieved_date
                    )
                    full_articles += 1
                except Exception as exc:
                    logger.warning("Article %s fetch failed: %s", aid, exc)

            if full_articles == 0:
                unavailable.append("NEWS_ARTICLES_FULL")

    except RuntimeError as exc:
        logger.error("Jin10 MCP articles: %s", exc)
        unavailable.append("NEWS_ARTICLES")

    return CollectorResult(
        points=points,
        unavailable_symbols=unavailable,
        source_refs=refs,
    )


def _archive(
    data: dict[str, Any],
    retrieved_date: str,
    symbol: str,
    storage_root: Path,
    refs: list[dict[str, Any]],
) -> str:
    raw_path = archive_raw_payload(
        storage_root=storage_root,
        source="jin10_mcp",
        retrieved_date=retrieved_date,
        symbol=symbol,
        payload=data,
    )
    refs.append({
        "source": "jin10_mcp",
        "method": f"articles:{symbol}",
        "raw_path": str(raw_path),
    })
    return str(raw_path)


def _extract_article_list_points(
    data: dict[str, Any],
    raw_path: str,
    points: list[MacroPoint],
    retrieved_at: str,
    retrieved_date: str,
) -> set[str]:
    """Extract article IDs and create list-level MacroPoints.

    Article metadata (title, ID) is encoded in the symbol field as
    ``NEWS_ARTICLE:HEADLINE:<id>:<title_prefix>``.
    """
    inner = data.get("data", data)
    if not isinstance(inner, dict):
        return set()

    items = inner.get("list") or inner.get("data") or []
    if not isinstance(items, list):
        return set()

    ids: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        aid = str(item.get("id", ""))
        if not aid:
            continue
        ids.add(aid)

        title = item.get("title") or item.get("name") or ""
        # Encode article ID + title prefix in symbol
        title_prefix = title[:30] if isinstance(title, str) else ""
        encoded = f"NEWS_ARTICLE:HEADLINE:{aid}"
        if title_prefix:
            encoded = f"{encoded}:{title_prefix}"

        points.append(MacroPoint(
            symbol=encoded,
            date=retrieved_date,
            value=0.0,  # headline point; full content gets content length as value
            source="jin10_mcp",
            source_url=raw_path,
            retrieved_at=retrieved_at,
            raw_path=raw_path,
        ))

    return ids


def _extract_full_article(
    data: dict[str, Any],
    article_id: str,
    raw_path: str,
    points: list[MacroPoint],
    retrieved_at: str,
    retrieved_date: str,
):
    """Extract full article content into a MacroPoint.

    Content length is used as the value, and title + pub_time are encoded
    in the symbol field for downstream feature extraction.
    """
    inner = data.get("data", data)
    if not isinstance(inner, dict):
        return

    title = inner.get("title", "")
    content = inner.get("content") or inner.get("body") or ""
    pub_time = str(inner.get("pub_time") or inner.get("time") or "")

    if isinstance(content, str):
        content_len = float(len(content))
    else:
        content_len = 0.0

    # Encode full article metadata in symbol
    title_prefix = title[:40] if isinstance(title, str) else ""
    encoded = f"NEWS_ARTICLE:FULL:{article_id}:{title_prefix}:{pub_time}"

    points.append(MacroPoint(
        symbol=encoded,
        date=retrieved_date,
        value=content_len,
        source="jin10_mcp",
        source_url=raw_path,
        retrieved_at=retrieved_at,
        raw_path=raw_path,
    ))
