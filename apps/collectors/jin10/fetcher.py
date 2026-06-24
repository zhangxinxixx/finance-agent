"""Fetch Jin10 category listings and detail pages into external report layout."""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

XNEWS_CATEGORY_URL = "https://xnews.jin10.com/category/{category_code}"
SVIP_DETAIL_URL = "https://svip.jin10.com/news/{article_id}"
DEFAULT_HEADERS = {
    "User-Agent": "finance-agent/0.1",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
REPORT_BODY_CLASSES = (
    "jin10vip-news-details-article-body",
    "jin10vip-news-details-content",
)
REPORT_SECTION_PATTERN = re.compile(r"\d+[、.．](行情回顾|关键指标|观点分享|核心逻辑|技术分析|操作建议)[：:]")
REPORT_PLACEHOLDER_PATTERN = re.compile(r"\d+[、.．][^：:]{1,20}[：:](?:\.{2,}|…+)")


@dataclass(slots=True)
class Jin10CategoryEntry:
    article_id: str
    title: str
    source_url: str
    published_at: str | None = None
    summary: str | None = None


@dataclass(slots=True)
class Jin10FetchedReport:
    article_id: str
    date: str
    title: str
    category: str
    report_type: str  # "daily" | "weekly"
    source_url: str
    report_markdown: str
    raw_html: str
    image_urls: list[str]
    fetched_at: str


def fetch_category_entries(
    *,
    category_code: str = "270",
    client: Any,
) -> list[Jin10CategoryEntry]:
    response = client.get(XNEWS_CATEGORY_URL.format(category_code=category_code), headers=DEFAULT_HEADERS)
    response.raise_for_status()
    return parse_category_entries(response.text)


def parse_category_entries(html: str) -> list[Jin10CategoryEntry]:
    entries: list[Jin10CategoryEntry] = []
    seen_ids: set[str] = set()
    for match in re.finditer(r'href="(?P<href>https://xnews\.jin10\.com/details/(?P<id>\d+)|/details/(?P<id2>\d+))"', html):
        article_id = match.group("id") or match.group("id2")
        if not article_id or article_id in seen_ids:
            continue
        seen_ids.add(article_id)
        href = match.group("href")
        source_url = href if href.startswith("http") else urljoin("https://xnews.jin10.com", href)
        title = _extract_anchor_text(html, match.start()) or f"Jin10 report {article_id}"
        entries.append(
            Jin10CategoryEntry(
                article_id=article_id,
                title=title,
                source_url=source_url,
                published_at=_extract_time_nearby(html, match.end()),
                summary=_extract_summary_nearby(html, match.end()),
            )
        )
    return entries


def fetch_svip_report(
    *,
    article_id: str,
    client: Any,
    cookie: str | None = None,
) -> Jin10FetchedReport:
    headers = dict(DEFAULT_HEADERS)
    if cookie:
        headers["Cookie"] = cookie
    url = SVIP_DETAIL_URL.format(article_id=article_id)
    response = client.get(url, headers=headers)
    response.raise_for_status()
    return parse_svip_report_html(response.text, article_id=article_id, source_url=url)


def fetch_svip_report_via_browser_profile(
    *,
    article_id: str,
    user_data_dir: Path | str,
    executable_path: Path | str | None = None,
) -> Jin10FetchedReport:
    chromium = Path(executable_path) if executable_path else _find_chromium_executable()
    if chromium is None:
        raise RuntimeError("No Chromium executable found for Jin10 browser-profile fetch.")
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("Playwright is required for browser-profile Jin10 fetch.") from exc

    target_url = SVIP_DETAIL_URL.format(article_id=article_id)
    profile_dir = Path(user_data_dir).expanduser()
    if not profile_dir.exists():
        raise RuntimeError(f"Browser profile not found: {profile_dir}")

    with tempfile.TemporaryDirectory(prefix="jin10-playwright-runtime-") as runtime_dir:
        env = {**os.environ, "XDG_RUNTIME_DIR": runtime_dir}
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                executable_path=str(chromium),
                headless=True,
                args=["--disable-dev-shm-usage"],
                env=env,
            )
            try:
                page = context.new_page()
                page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
                _wait_for_jin10_article_render(page)
                html = page.content()
            finally:
                context.close()
    return parse_svip_report_html(html, article_id=article_id, source_url=target_url)


def _wait_for_jin10_article_render(page: Any) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    try:
        page.wait_for_function(
            """
            () => {
              const body = document.querySelector('.jin10vip-news-details-article-body');
              if (!body) return false;
              const text = (body.innerText || '').replace(/\\s+/g, '');
              const hasFullDailySection =
                /[1１][、.．]行情回顾[：:].{20,}/.test(text) ||
                /[2２][、.．]关键指标[：:].{20,}/.test(text) ||
                /[3３][、.．]观点分享[：:].{20,}/.test(text);
              const hasPlaceholder = /[1１][、.．]行情回顾[：:](?:\\.{2,}|…+)/.test(text);
              const imageCount = body.querySelectorAll(
                'img[src*="img.jin10.com/news/"], img[src*="cdn-news.jin10.com/"]'
              ).length;
              return hasFullDailySection || (imageCount >= 2 && text.length >= 80 && !hasPlaceholder);
            }
            """,
            timeout=12000,
        )
    except Exception:
        page.wait_for_timeout(2500)


def parse_svip_report_html(html: str, *, article_id: str, source_url: str) -> Jin10FetchedReport:
    title = (
        _match_group(html, r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"')
        or _match_group(html, r"<title>([^<]+)</title>")
        or f"Jin10 report {article_id}"
    )
    date = _extract_report_date(html) or datetime.now(timezone.utc).date().isoformat()
    category = _match_group(html, r"(金银报告|黄金周报|报告)") or "报告"
    # 确定 report_type：日报(270/金银报告) vs 周报(536/黄金周报)
    report_type = "weekly" if category == "黄金周报" else "daily"
    article_html = _extract_article_body_html(html)
    reduced_html = _extract_reduced_content(html)
    content_html = _select_report_content_html(html, article_html=article_html, reduced_html=reduced_html)
    image_urls = _extract_image_urls(content_html or "")
    if not image_urls:
        image_urls = _extract_best_image_urls(article_html, reduced_html, html)
    body = _extract_report_body(content_html or html)
    markdown_lines = [
        f"# {title.strip()}",
        "",
        f"- 来源: {source_url}",
        f"- 日期: {date}",
        f"- 分类: {category}",
        f"- 图片: {len(image_urls)} 张",
        "",
        "## 正文",
        "",
        body or "证据不足：仅抓取到详情页 HTML，未稳定解析出正文。",
    ]
    if image_urls:
        markdown_lines.extend(["", "## 报告图片", ""])
        markdown_lines.extend(f"![{Path(urlparse(item).path).name}]({item})" for item in image_urls)
    return Jin10FetchedReport(
        article_id=article_id,
        date=date,
        title=title.strip(),
        category=category,
        report_type=report_type,
        source_url=source_url,
        report_markdown="\n".join(markdown_lines).strip() + "\n",
        raw_html=html,
        image_urls=image_urls,
        fetched_at=datetime.now(timezone.utc).isoformat(),
    )


def _extract_report_date(html: str) -> str | None:
    patterns = [
        r'jin10news__articleheader_time">\s*(\d{4}-\d{2}-\d{2})\s+\d{2}:\d{2}\s*<',
        r'"display_datetime":"?(\d{4}-\d{2}-\d{2})\s+\d{2}:\d{2}:\d{2}"?',
        r'display_datetime:.*?(\d{4}-\d{2}-\d{2})\s+\d{2}:\d{2}:\d{2}',
        r'<meta[^>]+property="article:published_time"[^>]+content="(\d{4}-\d{2}-\d{2})',
        r'(\d{4}-\d{2}-\d{2})',
    ]
    for pattern in patterns:
        value = _match_group(html, pattern)
        if value:
            return value
    return None


def write_external_report(
    report: Jin10FetchedReport,
    *,
    external_root: Path | str = Path("~/jin10-reports"),
    client: Any | None = None,
    image_insights: list[dict[str, Any]] | None = None,
) -> Path:
    root = Path(external_root).expanduser()
    report_dir = root / report.date / report.report_type / report.article_id
    report_dir.mkdir(parents=True, exist_ok=True)
    images = _download_report_images(report_dir, report.image_urls, client=client)
    insights = image_insights or []
    markdown = _render_report_markdown(report, images, insights)
    (report_dir / "report.md").write_text(markdown, encoding="utf-8")
    (report_dir / "detail.html").write_text(report.raw_html, encoding="utf-8")
    meta = {
        "date": report.date,
        "id": report.article_id,
        "title": report.title,
        "category": report.category,
        "report_type": report.report_type,
        "images": images,
        "image_insights": insights,
        "source_url": report.source_url,
        "fetched_at": report.fetched_at,
    }
    (report_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report_dir


def _download_report_images(report_dir: Path, image_urls: list[str], *, client: Any | None) -> list[dict[str, Any]]:
    images_dir = report_dir / "images"
    if images_dir.exists():
        for path in images_dir.iterdir():
            if path.is_file() or path.is_symlink():
                path.unlink()
            elif path.is_dir():
                shutil.rmtree(path)
    images_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    for index, url in enumerate(image_urls, start=1):
        original_name = Path(urlparse(url).path).name or f"image-{index}.png"
        file_name = f"{index:02d}-{original_name}"
        path = images_dir / file_name
        if client is not None:
            response = client.get(url, headers=DEFAULT_HEADERS)
            response.raise_for_status()
            path.write_bytes(response.content)
        results.append(
            {
                "seq": index,
                "file": file_name,
                "url": url,
                "path": str(path),
            }
        )
    if not any(images_dir.iterdir()):
        images_dir.rmdir()
    return results


def _render_report_markdown(
    report: Jin10FetchedReport,
    images: list[dict[str, Any]],
    insights: list[dict[str, Any]],
) -> str:
    body = report.report_markdown
    if "## 报告图片" in body:
        body = body.split("## 报告图片", 1)[0].rstrip()
    lines = [body]
    if images:
        lines.extend(["", "## 报告图片", ""])
        insight_map = {item.get("file"): item for item in insights}
        for image in images:
            lines.append(f"![{image['file']}](images/{image['file']})")
            insight = insight_map.get(image["file"])
            if insight is not None:
                status = insight.get("status")
                if status == "ok":
                    lines.extend(["", f"### 图表解析 {image['seq']}", ""])
                    lines.append(f"- 图表类型: {insight.get('chart_type') or 'unknown'}")
                    lines.append(f"- 识别文字: {insight.get('text') or 'unavailable'}")
                    lines.append(f"- 图表摘要: {insight.get('summary') or 'unavailable'}")
            lines.append("")
    return "\n".join(line for line in lines if line is not None).strip() + "\n"


def _extract_anchor_text(html: str, start: int) -> str | None:
    snippet = html[start:start + 1200]
    match = re.search(r">([^<]{6,200})</a>", snippet)
    if not match:
        return None
    return _clean_text(match.group(1))


def _extract_time_nearby(html: str, start: int) -> str | None:
    snippet = html[start:start + 600]
    return _match_group(snippet, r"(\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2})?)")


def _extract_summary_nearby(html: str, start: int) -> str | None:
    snippet = html[start:start + 1200]
    match = re.search(r"<p[^>]*>([^<]{12,300})</p>", snippet)
    return _clean_text(match.group(1)) if match else None


def _extract_report_body(html: str) -> str:
    html = (html or "").strip()
    if not html:
        return ""

    paragraphs = _extract_clean_paragraphs(html)
    if paragraphs:
        if _extract_image_urls(html):
            informative_paragraphs = _informative_paragraphs(paragraphs)
            if informative_paragraphs:
                paragraphs = informative_paragraphs
        return "\n\n".join(paragraphs[:30]).strip()

    reduced = _extract_reduced_content(html)
    if reduced:
        reduced_paragraphs = _extract_clean_paragraphs(reduced)
        if reduced_paragraphs:
            return "\n\n".join(reduced_paragraphs[:30]).strip()
    return ""


def _extract_clean_paragraphs(html: str) -> list[str]:
    body_blocks: list[str] = []
    for match in re.finditer(r"<p[^>]*>(.*?)</p>", html, re.S | re.I):
        text = _clean_text(match.group(1))
        if not text:
            continue
        if text in {"上一篇", "下一篇"}:
            continue
        if re.fullmatch(r"(报告名称：.*|页数：\d+|下载地址：.*|（仅VIP查看）)", text):
            continue
        if _looks_like_noise_paragraph(text):
            continue
        body_blocks.append(text)
    if body_blocks:
        return body_blocks

    for match in re.finditer(r"<div[^>]*>(.*?)</div>", html, re.S | re.I):
        text = _clean_text(match.group(1))
        if not text or len(text) < 8:
            continue
        if _looks_like_noise_paragraph(text):
            continue
        body_blocks.append(text)
    return body_blocks


def _looks_like_noise_paragraph(text: str) -> bool:
    compact = re.sub(r"\s+", "", text)
    if not compact:
        return True
    if re.fullmatch(r"每日金银报告\d{4}\.\d{2}\.\d{2}(（仅VIP查看）)?", compact):
        return True
    noise_patterns = (
        "金十VIP专享",
        "欢迎点击查看",
        "风险提示及免责条款",
        "本文不构成个人投资建议",
        "用户应考虑本文中的任何意见",
        "据此投资，责任自负",
        "立即下载",
        "更多金银信号和消息汇总",
        "来看今天最新的金银报告",
    )
    return any(token in compact for token in noise_patterns)


def _extract_image_urls(html: str) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for source in _image_search_sources(html):
        for match in re.finditer(r"https?://[^\"'<>\s\\]+?\.(?:png|jpg|jpeg|webp)(?:/lite)?", source, re.I):
            url = _normalize_image_url(match.group(0))
            if not _is_report_image(url):
                continue
            if url in seen:
                continue
            seen.add(url)
            urls.append(url)
    return _trim_report_edge_images(urls)


def _trim_report_edge_images(urls: list[str]) -> list[str]:
    if len(urls) >= 4:
        return urls[1:-1]
    return urls


def _extract_article_body_html(html: str) -> str | None:
    body_blocks = _extract_report_body_blocks(html)
    if body_blocks:
        return max(body_blocks, key=_article_body_score)
    reduced = _extract_reduced_content(html)
    return reduced if reduced else None


def _select_report_content_html(html: str, *, article_html: str | None, reduced_html: str | None) -> str:
    candidates: list[str] = []
    seen: set[str] = set()

    def add_candidate(candidate: str | None) -> None:
        candidate = (candidate or "").strip()
        if not candidate or candidate in seen:
            return
        if not _extract_report_body(candidate) and not _extract_image_urls(candidate):
            return
        seen.add(candidate)
        candidates.append(candidate)

    add_candidate(article_html)
    for block in _extract_report_body_blocks(html):
        add_candidate(block)
    add_candidate(reduced_html)

    if not candidates:
        return html
    return max(candidates, key=_report_content_score)


def _extract_best_image_urls(*html_candidates: str | None) -> list[str]:
    best_urls: list[str] = []
    best_score = -1
    for candidate in html_candidates:
        urls = _extract_image_urls(candidate or "")
        if not urls:
            continue
        score = _report_content_score(candidate or "")
        if score > best_score:
            best_score = score
            best_urls = urls
    return best_urls


def _extract_report_body_blocks(html: str) -> list[str]:
    blocks: list[str] = []
    seen: set[str] = set()
    for class_name in REPORT_BODY_CLASSES:
        for block in _extract_divs_by_class(html, class_name):
            if block in seen:
                continue
            seen.add(block)
            blocks.append(block)
    return blocks


def _extract_divs_by_class(html: str, class_name: str) -> list[str]:
    blocks: list[str] = []
    pattern = re.compile(r'<div\b[^>]*class="[^"]*' + re.escape(class_name) + r'[^"]*"[^>]*>', re.I)
    for match in pattern.finditer(html):
        block = _extract_balanced_div(html, match.start())
        if block:
            blocks.append(block)
    return blocks


def _extract_balanced_div(html: str, start: int) -> str | None:
    tag_pattern = re.compile(r"</?div\b[^>]*>", re.I)
    depth = 0
    for tag in tag_pattern.finditer(html, start):
        token = tag.group(0).lower()
        if token.startswith("</"):
            depth -= 1
            if depth == 0:
                return html[start : tag.end()]
        else:
            depth += 1
    return None


def _report_content_score(block: str) -> int:
    paragraphs = _extract_clean_paragraphs(block)
    images = _extract_image_urls(block)
    if not paragraphs:
        return len(images) * 1000

    placeholder_count = sum(1 for paragraph in paragraphs if _is_placeholder_paragraph(paragraph))
    informative = _informative_paragraphs(paragraphs)
    full_section_count = sum(1 for paragraph in informative if _has_report_section_marker(paragraph))
    char_count = sum(len(paragraph) for paragraph in informative)
    score = (
        len(informative) * 1000
        + full_section_count * 2500
        + min(char_count, 4000)
        + len(images) * 100
        - placeholder_count * 2000
    )
    if full_section_count >= 2:
        score += 3000
    if placeholder_count and not informative:
        score -= 5000
    return score


def _informative_paragraphs(paragraphs: list[str]) -> list[str]:
    return [paragraph for paragraph in paragraphs if not _is_placeholder_paragraph(paragraph)]


def _is_placeholder_paragraph(text: str) -> bool:
    compact = re.sub(r"\s+", "", text)
    return bool(REPORT_PLACEHOLDER_PATTERN.fullmatch(compact))


def _has_report_section_marker(text: str) -> bool:
    compact = re.sub(r"\s+", "", text)
    return bool(REPORT_SECTION_PATTERN.match(compact))


def _article_body_score(block: str) -> int:
    return _report_content_score(block) + len(_clean_text(block))


def _image_search_sources(html: str) -> list[str]:
    raw = html or ""
    decoded = _decode_escaped_html(raw)
    sources = [raw]
    if decoded != raw:
        sources.append(decoded)
    return sources


def _decode_escaped_html(text: str) -> str:
    decoded = unescape(text)
    replacements = {
        "\\u003C": "<",
        "\\u003E": ">",
        "\\u002F": "/",
        "\\/": "/",
        "\\n": "\n",
        '\\"': '"',
        "\\'": "'",
    }
    for src, target in replacements.items():
        decoded = decoded.replace(src, target)
    return decoded


def _normalize_image_url(url: str) -> str:
    normalized = unescape(url).replace("\\u002F", "/").replace("\\/", "/").replace("\\", "")
    if normalized.endswith("/lite"):
        normalized = normalized[: -len("/lite")]
    return normalized


def _extract_reduced_content(html: str) -> str | None:
    match = re.search(r'reduced_content\s*:\s*"(.*?)"\s*,\s*audio_url\s*:', html, re.I | re.S)
    if not match:
        return None
    raw = match.group(1)
    return _decode_escaped_html(raw)


def _match_group(text: str, pattern: str) -> str | None:
    match = re.search(pattern, text, re.I | re.S)
    if not match:
        return None
    return _clean_text(match.group(1))


def _clean_text(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _is_report_image(url: str) -> bool:
    return any(
        token in url
        for token in (
            "img.jin10.com/news/",
            "cdn-news.jin10.com/",
        )
    )


def _find_chromium_executable() -> Path | None:
    env_path = os.getenv("CHROMIUM_EXECUTABLE_PATH")
    candidates = [
        Path(env_path) if env_path else None,
        Path("/snap/chromium/current/usr/lib/chromium-browser/chrome"),
        Path("/snap/bin/chromium"),
        Path("/usr/bin/chromium"),
    ]
    for candidate in candidates:
        if candidate and candidate.is_file():
            return candidate
    for binary in ("chromium", "chromium-browser"):
        resolved = shutil.which(binary)
        if resolved:
            return Path(resolved)
    return None
