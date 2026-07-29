"""Collector helpers for structured Jin10 Reportory pages."""

from __future__ import annotations

import hashlib
import html as html_lib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from apps.collectors.jin10.fetcher import Jin10CategoryEntry
from apps.data_layer.jin10_image_assets import normalize_image_bytes_to_jpeg


REPORTORY_LISTING_URL = "https://svip.jin10.com/category/246"
REPORTORY_DAILY_GOLD_LISTING_URL = "https://xnews.jin10.com/category/270"
_REPORTORY_HOST = "reportory.jin10.com"
_MARKET_ODDS_PATH_MARKER = "/market-report/market-odds-report/"
_DAILY_GOLD_PATH_MARKER = "/market-report/daily-gold-silver-report/"
_DAILY_GOLD_TASK_ID = "daily-gold-silver-report"
_DAILY_GOLD_SCHEMA_VERSION = 3
_BEIJING = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True, slots=True)
class Jin10ReportoryMarketOddsPage:
    report_id: str
    report_date: str
    title: str
    published_at: str
    source_url: str
    raw_html: str
    report_data: dict[str, Any]
    card_images: tuple[bytes, ...]


@dataclass(frozen=True, slots=True)
class Jin10ReportoryDailyGoldPage:
    report_id: str
    report_date: str
    title: str
    published_at: str
    source_url: str
    raw_html: str
    report_data: dict[str, Any]
    page_images: tuple[bytes, ...]


def parse_reportory_market_odds_entries(html: str) -> list[Jin10CategoryEntry]:
    """Extract current Reportory market-odds links from the SVIP listing."""

    return _parse_reportory_entries(
        html,
        path_marker=_MARKET_ODDS_PATH_MARKER,
        default_title="市场赔率数据表",
    )


def parse_reportory_daily_gold_entries(html: str) -> list[Jin10CategoryEntry]:
    """Extract Reportory daily-gold links from the category 270 listing."""

    return _parse_reportory_entries(
        html,
        path_marker=_DAILY_GOLD_PATH_MARKER,
        default_title="每日金银报告",
    )


def _parse_reportory_entries(
    html: str,
    *,
    path_marker: str,
    default_title: str,
) -> list[Jin10CategoryEntry]:
    """Extract one allow-listed Reportory series without admitting sibling reports."""

    entries: list[Jin10CategoryEntry] = []
    seen: set[str] = set()
    pattern = re.compile(
        r'<a\s+[^>]*href="(?P<url>https://reportory\.jin10\.com/[^"]*'
        + re.escape(path_marker)
        + r'[^"]+\.html)"[^>]*>'
        r"(?P<title>.*?)</a>",
        flags=re.DOTALL | re.IGNORECASE,
    )
    for match in pattern.finditer(html or ""):
        source_url = html_lib.unescape(match.group("url"))
        report_id = _reportory_report_id(source_url, path_marker=path_marker)
        if report_id in seen:
            continue
        seen.add(report_id)
        item_html = _reportory_listing_item_html(html or "", match.start(), match.end())
        title = _clean_html_text(
            _first_group(
                item_html,
                r'class="jin10-news-list-item-title"[^>]*>(.*?)</p>',
            )
            or match.group("title")
        )
        published_at = _first_group(item_html, r'data-time="([^"]+)"') or _clean_html_text(
            _first_group(
                item_html,
                r'class="jin10-news-list-item-display_datetime"[^>]*>.*?<span>([^<]+)</span>\s*</span>',
            )
            or ""
        )
        summary = _first_group(
            item_html,
            r'class="(?:jin10vip-c-news-item-flex-introduction|jin10-news-list-item-introduction)"[^>]*>(.*?)</div>',
        )
        entries.append(
            Jin10CategoryEntry(
                article_id=report_id,
                title=title or default_title,
                source_url=source_url,
                published_at=published_at or None,
                summary=_clean_html_text(summary or ""),
            )
        )
    return entries


def _reportory_listing_item_html(html: str, match_start: int, match_end: int) -> str:
    item_start = html.rfind('<div data-id="', 0, match_start)
    if item_start < 0:
        item_start = match_start
    next_item = html.find('<div data-id="', match_end)
    if next_item < 0:
        next_item = min(len(html), match_end + 12_000)
    return html[item_start:next_item]


def fetch_reportory_market_odds_entries(*, client: Any) -> list[Jin10CategoryEntry]:
    response = client.get(REPORTORY_LISTING_URL)
    response.raise_for_status()
    return parse_reportory_market_odds_entries(response.text)


def fetch_reportory_daily_gold_entries(*, client: Any) -> list[Jin10CategoryEntry]:
    response = client.get(REPORTORY_DAILY_GOLD_LISTING_URL)
    response.raise_for_status()
    return parse_reportory_daily_gold_entries(response.text)


def reportory_report_id(source_url: str) -> str:
    return _reportory_report_id(source_url, path_marker=_MARKET_ODDS_PATH_MARKER)


def reportory_daily_gold_report_id(source_url: str) -> str:
    return _reportory_report_id(source_url, path_marker=_DAILY_GOLD_PATH_MARKER)


def reportory_daily_gold_report_date(source_url: str) -> str:
    reportory_daily_gold_report_id(source_url)
    return _daily_gold_date_from_url(source_url)


def _reportory_report_id(source_url: str, *, path_marker: str) -> str:
    parsed = urlparse(source_url)
    if parsed.scheme != "https" or parsed.hostname != _REPORTORY_HOST or path_marker not in parsed.path:
        raise ValueError("jin10_reportory_url_invalid")
    report_id = Path(parsed.path).stem
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,120}", report_id):
        raise ValueError("jin10_reportory_report_id_invalid")
    return report_id


def fetch_reportory_daily_gold_via_browser_profile(
    *,
    source_url: str,
    user_data_dir: Path | str,
    title: str | None = None,
    published_at: str | None = None,
    executable_path: Path | str | None = None,
) -> Jin10ReportoryDailyGoldPage:
    """Fetch one fully rendered Reportory daily-gold report with a copied login profile."""

    report_id = reportory_daily_gold_report_id(source_url)
    from apps.collectors.jin10.fetcher import _find_chromium_executable

    chromium = Path(executable_path) if executable_path else _find_chromium_executable()
    if chromium is None:
        raise RuntimeError("No Chromium executable found for Jin10 Reportory fetch.")
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - optional runtime dependency
        raise RuntimeError("Playwright is required for Jin10 Reportory fetch.") from exc

    profile_dir = Path(user_data_dir).expanduser()
    if not profile_dir.is_dir():
        raise RuntimeError(f"Browser profile not found: {profile_dir}")

    with tempfile.TemporaryDirectory(prefix="jin10-reportory-daily-gold-") as runtime_dir:
        profile_copy = Path(runtime_dir) / "profile"
        _copy_browser_profile_for_readonly_launch(profile_dir, profile_copy)
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(profile_copy),
                executable_path=str(chromium),
                headless=True,
                args=["--disable-dev-shm-usage"],
                env={**os.environ, "XDG_RUNTIME_DIR": runtime_dir},
            )
            try:
                page = context.new_page()
                page.goto(source_url, wait_until="domcontentloaded", timeout=60_000)
                page.wait_for_function(
                    """
                    () => window.GOLD_SILVER_REPORT_DATA
                      && window.GOLD_SILVER_REPORT_RENDER_STATE
                      && window.GOLD_SILVER_REPORT_RENDER_STATE.ready === true
                    """,
                    timeout=60_000,
                )
                report_data = page.evaluate("() => window.GOLD_SILVER_REPORT_DATA")
                render_state = page.evaluate("() => window.GOLD_SILVER_REPORT_RENDER_STATE")
                pages = page.locator(".report-page")
                page_images = tuple(
                    pages.nth(index).screenshot(type="jpeg", quality=92)
                    for index in range(pages.count())
                )
                raw_html = page.content()
            finally:
                context.close()

    _validate_daily_gold_report_data(
        report_data=report_data,
        render_state=render_state,
        page_count=len(page_images),
        source_url=source_url,
    )
    report_date = str(report_data["report_date"])
    resolved_published_at = _normalize_daily_gold_published_at(
        published_at,
        report_date=report_date,
        report_id=report_id,
    )
    resolved_title = str(report_data.get("title") or title or "每日金银报告").strip()
    return Jin10ReportoryDailyGoldPage(
        report_id=report_id,
        report_date=report_date,
        title=resolved_title,
        published_at=resolved_published_at,
        source_url=source_url,
        raw_html=raw_html,
        report_data=report_data,
        page_images=page_images,
    )


def fetch_reportory_market_odds_via_browser_profile(
    *,
    source_url: str,
    user_data_dir: Path | str,
    title: str | None = None,
    published_at: str | None = None,
    executable_path: Path | str | None = None,
) -> Jin10ReportoryMarketOddsPage:
    report_id = reportory_report_id(source_url)
    from apps.collectors.jin10.fetcher import _find_chromium_executable

    chromium = Path(executable_path) if executable_path else _find_chromium_executable()
    if chromium is None:
        raise RuntimeError("No Chromium executable found for Jin10 Reportory fetch.")
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - optional runtime dependency
        raise RuntimeError("Playwright is required for Jin10 Reportory fetch.") from exc

    profile_dir = Path(user_data_dir).expanduser()
    if not profile_dir.exists():
        raise RuntimeError(f"Browser profile not found: {profile_dir}")

    with tempfile.TemporaryDirectory(prefix="jin10-reportory-runtime-") as runtime_dir:
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                executable_path=str(chromium),
                headless=True,
                args=["--disable-dev-shm-usage"],
                env={"XDG_RUNTIME_DIR": runtime_dir},
            )
            try:
                page = context.new_page()
                page.goto(source_url, wait_until="domcontentloaded", timeout=60_000)
                page.wait_for_function("() => window.REPORT_DATA && Array.isArray(window.REPORT_DATA.items)", timeout=60_000)
                report_data = page.evaluate("() => window.REPORT_DATA")
                if not isinstance(report_data, dict):
                    raise RuntimeError("jin10_reportory_market_odds_data_missing")
                cards = page.locator(".report-card")
                card_images = tuple(
                    cards.nth(index).screenshot(type="jpeg", quality=92)
                    for index in range(cards.count())
                )
                raw_html = page.content()
            finally:
                context.close()

    report_date = str(report_data.get("report_date") or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", report_date):
        raise RuntimeError("jin10_reportory_market_odds_date_missing")
    resolved_published_at = str(published_at or _published_at_from_as_of(report_date, report_data.get("as_of"))).strip()
    resolved_title = str(title or "").strip() or _default_title(report_data)
    return Jin10ReportoryMarketOddsPage(
        report_id=report_id,
        report_date=report_date,
        title=resolved_title,
        published_at=resolved_published_at,
        source_url=source_url,
        raw_html=raw_html,
        report_data=report_data,
        card_images=card_images,
    )


def write_reportory_market_odds_report(
    report: Jin10ReportoryMarketOddsPage,
    *,
    external_root: Path | str,
) -> Path:
    root = Path(external_root).expanduser()
    report_dir = root / report.report_date / "market_observation" / report.report_id
    report_dir.mkdir(parents=True, exist_ok=True)
    images = _write_card_images(report_dir=report_dir, card_images=report.card_images, source_url=report.source_url)
    (report_dir / "detail.html").write_text(report.raw_html, encoding="utf-8")
    (report_dir / "report_data.json").write_text(
        json.dumps(report.report_data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (report_dir / "report.md").write_text(render_reportory_market_odds_markdown(report), encoding="utf-8")
    meta = {
        "date": report.report_date,
        "id": report.report_id,
        "title": report.title,
        "category": "市场观察",
        "report_type": "market_observation",
        "series": "market_odds",
        "subcategory": "market_odds",
        "vip_locked": False,
        "content_scope": "full_report",
        "body_complete": True,
        "source_format": "reportory_market_odds_v2",
        "published_at": report.published_at,
        "images": images,
        "image_insights": [],
        "source_url": report.source_url,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    (report_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report_dir


def write_reportory_daily_gold_report(
    report: Jin10ReportoryDailyGoldPage,
    *,
    external_root: Path | str,
) -> Path:
    root = Path(external_root).expanduser()
    if root.exists() and not root.is_dir():
        raise ValueError(f"jin10_reportory_daily_gold_external_root_not_directory: {root}")
    report_dir = root / report.report_date / "daily" / report.report_id
    if report_dir.exists():
        raise FileExistsError(f"jin10_reportory_daily_gold_artifact_exists: {report_dir}")
    report_dir.parent.mkdir(parents=True, exist_ok=True)
    staging_dir = Path(tempfile.mkdtemp(prefix=f".{report.report_id}.", dir=report_dir.parent))
    try:
        images = _write_card_images(
            report_dir=staging_dir,
            artifact_path_root=report_dir,
            card_images=report.page_images,
            source_url=report.source_url,
            fragment_prefix="page",
        )
        (staging_dir / "detail.html").write_text(report.raw_html, encoding="utf-8")
        (staging_dir / "report_data.json").write_text(
            json.dumps(report.report_data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (staging_dir / "report.md").write_text(render_reportory_daily_gold_markdown(report), encoding="utf-8")
        meta = {
            "date": report.report_date,
            "id": report.report_id,
            "title": report.title,
            "category": "金银报告",
            "report_type": "daily",
            "series": "daily_gold_silver",
            "subcategory": "gold_silver",
            "vip_locked": False,
            "content_scope": "full_report",
            "body_complete": True,
            "source_format": "reportory_daily_gold_silver_v3",
            "published_at": report.published_at,
            "images": images,
            "image_insights": [],
            "source_url": report.source_url,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
        (staging_dir / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        staging_dir.rename(report_dir)
        return report_dir
    finally:
        if staging_dir.exists():
            shutil.rmtree(staging_dir)


def render_reportory_market_odds_markdown(report: Jin10ReportoryMarketOddsPage) -> str:
    data = report.report_data
    lines = [f"# {report.title}", "", f"- 统计时间: {data.get('as_of') or report.published_at}", f"- 来源: {report.source_url}"]
    lead = str(data.get("lead") or "").strip()
    overview = str(data.get("overview") or "").strip()
    if lead:
        lines.extend(["", "## 导语", "", lead])
    if overview:
        lines.extend(["", "## 市场赔率概览", "", overview])
    for index, item in enumerate(data.get("items") or [], start=1):
        if not isinstance(item, dict):
            continue
        lines.extend(["", f"## {item.get('category') or '市场'} · {item.get('title') or item.get('event_id') or index}", ""])
        lines.append(f"- 市场结构: {item.get('market_structure') or 'unknown'}")
        for odds in item.get("odds") or []:
            if not isinstance(odds, dict):
                continue
            change = odds.get("change_24h")
            change_text = "" if change is None else f"，24小时变化 {float(change):+g} 个百分点"
            lines.append(
                f"- {odds.get('label') or odds.get('outcome_label') or '结果'}: "
                f"{odds.get('probability')}%{change_text}"
            )
        traditional = str(item.get("traditional_market_reference") or "").strip()
        vip_view = item.get("vip_view") if isinstance(item.get("vip_view"), dict) else {}
        focus = str(item.get("market_focus") or "").strip()
        if traditional:
            lines.extend(["", f"传统市场参照：{traditional}"])
        if vip_view:
            lines.extend(["", f"VIP 视角：{vip_view.get('title') or ''}", str(vip_view.get("text") or "")])
        if focus:
            lines.extend(["", f"市场焦点：{focus}"])
        lines.extend(["", f"![{item.get('title') or '赔率卡片'}](images/page-{index:03d}.jpg)"])
    return "\n".join(lines).strip() + "\n"


def render_reportory_daily_gold_markdown(report: Jin10ReportoryDailyGoldPage) -> str:
    """Render the structured v3 payload without copying embedded image data into markdown."""

    data = report.report_data
    lines = [
        f"# {report.title}",
        "",
        f"- 日期: {report.report_date}",
        f"- 发布时间: {report.published_at}",
        f"- 来源: {report.source_url}",
        f"- 上游质量状态: {data.get('quality_status') or 'unknown'}",
    ]
    lead = _clean_value(data.get("lead"))
    if lead:
        lines.extend(["", "## 导语", "", lead])

    _render_market_review(lines, data.get("market_review"))
    _render_today_focus(lines, data.get("today_focus"))
    _render_overnight_news(lines, data.get("overnight_news"))
    _render_analyses(lines, data.get("analyses"))
    _render_etf_tracking(lines, data.get("etf_tracking"))
    _render_sentiment_gauges(lines, data.get("sentiment_gauges"))
    _render_charts(lines, data.get("charts"))

    lines.extend(["", "## 原始报告逐页快照", ""])
    lines.extend(
        f"![原始报告第 {index} 页](images/page-{index:03d}.jpg)"
        for index in range(1, len(report.page_images) + 1)
    )
    return "\n".join(lines).strip() + "\n"


def _render_market_review(lines: list[str], payload: Any) -> None:
    items = _dict_items(payload)
    if not items:
        return
    lines.extend(["", "## 行情回顾"])
    for item in items:
        heading = _clean_value(item.get("metal") or item.get("instrument") or "市场")
        lines.extend(["", f"### {heading}", ""])
        values = []
        for label, key in (("品种", "instrument"), ("收盘", "close"), ("涨跌", "change"), ("涨跌幅", "change_pct")):
            value = item.get(key)
            if value not in (None, ""):
                values.append(f"{label}: {value}")
        if values:
            lines.append("；".join(values))
        summary = _clean_value(item.get("summary"))
        if summary:
            lines.extend(["", summary])


def _render_today_focus(lines: list[str], payload: Any) -> None:
    items = _dict_items(payload)
    if not items:
        return
    lines.extend(["", "## 今日市场聚焦", ""])
    for item in items:
        event = _clean_value(item.get("event") or item.get("kind") or "待观察事件")
        event_time = _clean_value(item.get("beijing_time") or item.get("scheduled_at"))
        details = [f"时间: {event_time}" if event_time else ""]
        for label, key in (("前值", "previous"), ("预期", "forecast"), ("影响", "impact")):
            value = item.get(key)
            if value not in (None, ""):
                details.append(f"{label}: {value}")
        suffix = "；".join(value for value in details if value)
        lines.append(f"- {event}" + (f"（{suffix}）" if suffix else ""))


def _render_overnight_news(lines: list[str], payload: Any) -> None:
    items = _dict_items(payload)
    if not items:
        return
    lines.extend(["", "## 隔夜要闻"])
    for item in items:
        title = _clean_value(item.get("title") or "未命名要闻")
        source = _clean_value(item.get("source_name"))
        published_at = _clean_value(item.get("published_at"))
        lines.extend(["", f"### {title}", ""])
        if source or published_at:
            lines.append("；".join(value for value in (f"来源: {source}" if source else "", f"时间: {published_at}" if published_at else "") if value))
        summary = _clean_value(item.get("summary"))
        if summary:
            lines.extend(["", summary])


def _render_analyses(lines: list[str], payload: Any) -> None:
    items = _dict_items(payload)
    if not items:
        return
    lines.extend(["", "## 市场分析"])
    for item in items:
        source = _clean_value(item.get("source_name") or item.get("source_key") or "市场观点")
        angle = _clean_value(item.get("angle"))
        lines.extend(["", f"### {source}" + (f" · {angle}" if angle else ""), ""])
        viewpoint = _clean_value(item.get("viewpoint"))
        if viewpoint:
            lines.append(viewpoint)
        paragraphs = item.get("paragraphs")
        if isinstance(paragraphs, list):
            lines.extend(["", *(_clean_value(value) for value in paragraphs if _clean_value(value))])


def _render_etf_tracking(lines: list[str], payload: Any) -> None:
    items = _dict_items(payload)
    if not items:
        return
    lines.extend(["", "## ETF 资金跟踪", ""])
    for item in items:
        fund = _clean_value(item.get("fund") or item.get("metal") or "ETF")
        values = [fund]
        for label, key in (("持仓", "trust"), ("变化", "change"), ("日期", "reported_on")):
            value = item.get(key)
            if value not in (None, ""):
                values.append(f"{label}: {value}")
        lines.append(f"- {'；'.join(values)}")
        analysis = _clean_value(item.get("analysis"))
        if analysis:
            lines.append(f"  - 解读: {analysis}")


def _render_sentiment_gauges(lines: list[str], payload: Any) -> None:
    items = _dict_items(payload)
    if not items:
        return
    lines.extend(["", "## 恐惧与贪婪指标", ""])
    for item in items:
        metal = _clean_value(item.get("metal") or "市场")
        timeframe = _clean_value(item.get("timeframe"))
        score = item.get("score")
        label = _clean_value(item.get("label"))
        lines.append(f"- {metal}" + (f" {timeframe}" if timeframe else "") + f": {score} / {label}")
        rationale = _clean_value(item.get("rationale"))
        if rationale:
            lines.append(f"  - 依据: {rationale}")


def _render_charts(lines: list[str], payload: Any) -> None:
    items = _dict_items(payload)
    if not items:
        return
    lines.extend(["", "## 关键图表"])
    for item in items:
        title = _clean_value(item.get("title") or item.get("id") or "图表")
        lines.extend(["", f"### {title}", ""])
        description = _clean_value(item.get("description"))
        if description:
            lines.append(description)
        sources = item.get("data_source_names")
        if isinstance(sources, list):
            source_text = "、".join(_clean_value(value) for value in sources if _clean_value(value))
            if source_text:
                lines.append(f"数据来源: {source_text}")


def _dict_items(payload: Any) -> list[dict[str, Any]]:
    return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []


def _clean_value(value: Any) -> str:
    return " ".join(str(value or "").split())


def _write_card_images(
    *,
    report_dir: Path,
    card_images: tuple[bytes, ...],
    source_url: str,
    fragment_prefix: str = "card",
    artifact_path_root: Path | None = None,
) -> list[dict[str, Any]]:
    images_dir = report_dir / "images"
    artifact_images_dir = (artifact_path_root or report_dir) / "images"
    staging_dir = Path(tempfile.mkdtemp(prefix=".images-", dir=report_dir))
    results: list[dict[str, Any]] = []
    try:
        for index, raw in enumerate(card_images, start=1):
            normalized = normalize_image_bytes_to_jpeg(raw)
            filename = f"page-{index:03d}.jpg"
            (staging_dir / filename).write_bytes(normalized.data)
            results.append(
                {
                    "seq": index,
                    "file": filename,
                    "url": f"{source_url}#{fragment_prefix}-{index}",
                    "source_file": f"report-{fragment_prefix}-{index:03d}.jpg",
                    "path": str(artifact_images_dir / filename),
                    "format": "jpeg",
                    "mime_type": "image/jpeg",
                    "w": normalized.width,
                    "h": normalized.height,
                    "size_bytes": len(normalized.data),
                    "sha256": hashlib.sha256(normalized.data).hexdigest(),
                }
            )
        if images_dir.exists():
            shutil.rmtree(images_dir)
        staging_dir.replace(images_dir)
        return results
    finally:
        if staging_dir.exists():
            shutil.rmtree(staging_dir)


def _validate_daily_gold_report_data(
    *,
    report_data: Any,
    render_state: Any,
    page_count: int,
    source_url: str,
) -> None:
    if not isinstance(report_data, dict):
        raise RuntimeError("jin10_reportory_daily_gold_data_missing")
    if report_data.get("schema_version") != _DAILY_GOLD_SCHEMA_VERSION:
        raise RuntimeError("jin10_reportory_daily_gold_schema_unsupported")
    if report_data.get("task_id") != _DAILY_GOLD_TASK_ID:
        raise RuntimeError("jin10_reportory_daily_gold_task_id_mismatch")
    report_date = str(report_data.get("report_date") or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", report_date):
        raise RuntimeError("jin10_reportory_daily_gold_date_missing")
    url_date = _daily_gold_date_from_url(source_url)
    if report_date != url_date:
        raise RuntimeError("jin10_reportory_daily_gold_date_mismatch")
    if not isinstance(render_state, dict) or render_state.get("ready") is not True:
        raise RuntimeError("jin10_reportory_daily_gold_render_incomplete")
    expected_page_count = render_state.get("pageCount")
    if not isinstance(expected_page_count, int) or expected_page_count <= 0 or page_count != expected_page_count:
        raise RuntimeError("jin10_reportory_daily_gold_page_count_mismatch")


def _daily_gold_date_from_url(source_url: str) -> str:
    parsed = urlparse(source_url)
    match = re.fullmatch(
        r"/jin10-report-hub/v2/market-report/daily-gold-silver-report/"
        r"(?P<year>\d{4})/(?P<month>\d{2})/(?P<day>\d{2})/[A-Za-z0-9_-]{8,120}\.html",
        parsed.path,
    )
    if not match:
        raise ValueError("jin10_reportory_daily_gold_url_invalid")
    return f"{match.group('year')}-{match.group('month')}-{match.group('day')}"


def _published_at_from_report_id(report_id: str) -> str:
    match = re.match(r"(?P<timestamp>\d{8}T\d{6}Z)-", report_id)
    if not match:
        raise RuntimeError("jin10_reportory_published_at_missing")
    published_at = datetime.strptime(match.group("timestamp"), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    return published_at.astimezone(_BEIJING).isoformat()


def _normalize_daily_gold_published_at(value: str | None, *, report_date: str, report_id: str) -> str:
    normalized = " ".join(str(value or "").split())
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            parsed = datetime.strptime(normalized, fmt).replace(tzinfo=_BEIJING)
        except ValueError:
            continue
        if parsed.date().isoformat() == report_date:
            return parsed.isoformat()
    for fmt in ("%m-%d %H:%M:%S", "%m-%d %H:%M"):
        try:
            parsed = datetime.strptime(normalized, fmt).replace(
                year=int(report_date[:4]),
                tzinfo=_BEIJING,
            )
        except ValueError:
            continue
        if parsed.date().isoformat() == report_date:
            return parsed.isoformat()
    return _published_at_from_report_id(report_id)


def _copy_browser_profile_for_readonly_launch(source_dir: Path, target_dir: Path) -> None:
    ignore = shutil.ignore_patterns(
        "Singleton*",
        "DevToolsActivePort",
        "BrowserMetrics*",
        "Crashpad",
        "Crash Reports",
        "ShaderCache",
        "GrShaderCache",
        "GraphiteDawnCache",
        "GPUCache",
        "Code Cache",
    )
    shutil.copytree(source_dir, target_dir, ignore=ignore)


def _published_at_from_as_of(report_date: str, as_of: Any) -> str:
    match = re.search(r"(?P<hour>\d{1,2}):(?P<minute>\d{2})", str(as_of or ""))
    if not match:
        return f"{report_date}T00:00:00+08:00"
    return f"{report_date}T{int(match.group('hour')):02d}:{int(match.group('minute')):02d}:00+08:00"


def _default_title(data: dict[str, Any]) -> str:
    lead = str(data.get("lead") or "").strip().rstrip("。")
    return f"{lead}｜市场赔率数据表" if lead else "市场赔率数据表"


def _clean_html_text(value: str) -> str:
    return " ".join(html_lib.unescape(re.sub(r"<[^>]+>", " ", value or "")).split())


def _first_group(value: str, pattern: str) -> str | None:
    match = re.search(pattern, value or "", flags=re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else None
