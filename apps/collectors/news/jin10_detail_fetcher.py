from __future__ import annotations

import re
import hashlib
import os
import shutil
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin, urlparse

import cv2
import httpx
from bs4 import BeautifulSoup

from apps.collectors.news.base import archive_news_payload
from apps.parsers.jin10.qwen_vl_markdown import DashScopeVisionMarkdownClient, MissingDashScopeApiKey

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 finance-agent/0.1",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
MIN_VLM_IMAGE_WIDTH = 600
MIN_VLM_IMAGE_HEIGHT = 300
MIN_VLM_IMAGE_BYTES = 10_000
JIN10_DETAIL_SOURCE_KEY = "jin10_detail_pages"
JIN10_XNEWS_PUBLIC_SOURCE_KEY = "jin10_xnews_public"
DEFAULT_JIN10_BROWSER_PROFILE = Path.home() / ".finance-agent" / "jin10_browser_profile"
LIMITED_ACCESS_STATUSES = {"empty", "javascript_required", "vip_locked"}

VlmRunner = Callable[[list[dict[str, Any]]], list[dict[str, Any]]]
BrowserHtmlFetcher = Callable[..., "RenderedDetailPage"]


@dataclass(frozen=True)
class RenderedDetailPage:
    final_url: str
    html: str
    content_type: str = "text/html; rendered=playwright"


@dataclass(frozen=True)
class Jin10DetailFetchResult:
    detail_url: str
    final_url: str | None
    status: str
    access_status: str = "unknown"
    content_type: str | None = None
    title: str = ""
    raw_text: str = ""
    raw_html_path: str | None = None
    parsed_path: str | None = None
    image_assets: list[dict[str, Any]] = field(default_factory=list)
    image_insights: list[dict[str, Any]] = field(default_factory=list)
    error_reason: str | None = None
    fetched_at: str = ""
    fetch_method: str = "http"
    source_key: str = JIN10_XNEWS_PUBLIC_SOURCE_KEY
    access_method: str = "http_document"
    browser_fallback_attempted: bool = False
    browser_fallback_status: str | None = None
    browser_fallback_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def fetch_jin10_detail_page(
    *,
    url: str,
    storage_root: Path,
    retrieved_date: str,
    client: Any | None = None,
    run_vlm: bool = False,
    vlm_runner: VlmRunner | None = None,
    max_images: int = 8,
    min_vlm_width: int = MIN_VLM_IMAGE_WIDTH,
    min_vlm_height: int = MIN_VLM_IMAGE_HEIGHT,
    min_vlm_bytes: int = MIN_VLM_IMAGE_BYTES,
    run_browser_fallback: bool = False,
    browser_profile: Path | str | None = None,
    executable_path: Path | str | None = None,
    browser_html_fetcher: BrowserHtmlFetcher | None = None,
) -> Jin10DetailFetchResult:
    fetched_at = datetime.now(timezone.utc).isoformat()
    owns_client = client is None
    http_client = client or httpx.Client(timeout=20.0, follow_redirects=True, headers=DEFAULT_HEADERS)
    try:
        try:
            response = http_client.get(url, headers=DEFAULT_HEADERS)
            final_url = str(response.url)
            content_type = str(response.headers.get("content-type") or "")
            response.raise_for_status()
        except Exception as exc:
            return Jin10DetailFetchResult(
                detail_url=url,
                final_url=None,
                status="fetch_failed",
                access_status="unavailable",
                error_reason=f"{type(exc).__name__}: {exc}",
                fetched_at=fetched_at,
            )

        html = response.text if response.content else ""
        result = _build_result_from_html(
            storage_root=storage_root,
            retrieved_date=retrieved_date,
            url=url,
            html=html,
            final_url=final_url,
            content_type=content_type,
            fetched_at=fetched_at,
            http_client=http_client,
            run_vlm=run_vlm,
            vlm_runner=vlm_runner,
            max_images=max_images,
            min_vlm_width=min_vlm_width,
            min_vlm_height=min_vlm_height,
            min_vlm_bytes=min_vlm_bytes,
            fetch_method="http",
        )
        if not run_browser_fallback or result.access_status not in LIMITED_ACCESS_STATUSES:
            return result
        profile = Path(browser_profile).expanduser() if browser_profile else DEFAULT_JIN10_BROWSER_PROFILE
        try:
            rendered = (browser_html_fetcher or _fetch_rendered_html_via_browser_profile)(
                url=url,
                user_data_dir=profile,
                executable_path=executable_path,
            )
        except Exception as exc:
            return Jin10DetailFetchResult(
                **{
                    **result.to_dict(),
                    "browser_fallback_attempted": True,
                    "browser_fallback_status": "failed",
                    "browser_fallback_error": f"{type(exc).__name__}: {exc}",
                }
            )

        rendered_result = _build_result_from_html(
            storage_root=storage_root,
            retrieved_date=retrieved_date,
            url=url,
            html=rendered.html,
            final_url=rendered.final_url,
            content_type=rendered.content_type,
            fetched_at=datetime.now(timezone.utc).isoformat(),
            http_client=http_client,
            run_vlm=run_vlm,
            vlm_runner=vlm_runner,
            max_images=max_images,
            min_vlm_width=min_vlm_width,
            min_vlm_height=min_vlm_height,
            min_vlm_bytes=min_vlm_bytes,
            fetch_method="browser_profile",
            browser_fallback_attempted=True,
            browser_fallback_status="success",
        )
        return rendered_result
    finally:
        if owns_client:
            http_client.close()


def _build_result_from_html(
    *,
    storage_root: Path,
    retrieved_date: str,
    url: str,
    html: str,
    final_url: str,
    content_type: str,
    fetched_at: str,
    http_client: Any,
    run_vlm: bool,
    vlm_runner: VlmRunner | None,
    max_images: int,
    min_vlm_width: int,
    min_vlm_height: int,
    min_vlm_bytes: int,
    fetch_method: str,
    browser_fallback_attempted: bool = False,
    browser_fallback_status: str | None = None,
    browser_fallback_error: str | None = None,
) -> Jin10DetailFetchResult:
    archive_name = _archive_name(url=url, fetch_method=fetch_method)
    raw_html_path = _write_raw_html(
        storage_root=storage_root,
        retrieved_date=retrieved_date,
        url=url,
        html=html,
        archive_name=archive_name,
    )
    raw_text = _visible_text(html)
    access_status = _classify_access_status(raw_text=raw_text, final_url=final_url)
    title = _extract_title(html) or raw_text[:120]
    image_urls = _extract_image_urls(html=html, base_url=final_url)
    image_assets = _download_images(
        client=http_client,
        storage_root=storage_root,
        retrieved_date=retrieved_date,
        detail_url=final_url,
        image_urls=image_urls[:max_images],
        min_vlm_width=min_vlm_width,
        min_vlm_height=min_vlm_height,
        min_vlm_bytes=min_vlm_bytes,
    )
    image_insights = _run_vlm_if_requested(
        run_vlm=run_vlm,
        image_assets=image_assets,
        storage_root=storage_root,
        vlm_runner=vlm_runner,
    )
    result = Jin10DetailFetchResult(
        detail_url=url,
        final_url=final_url,
        status="fetched",
        access_status=access_status,
        content_type=content_type,
        title=title,
        raw_text=raw_text,
        raw_html_path=raw_html_path,
        image_assets=image_assets,
        image_insights=image_insights,
        fetched_at=fetched_at,
        fetch_method=fetch_method,
        access_method="vip_browser_profile" if fetch_method == "browser_profile" else "http_document",
        browser_fallback_attempted=browser_fallback_attempted,
        browser_fallback_status=browser_fallback_status,
        browser_fallback_error=browser_fallback_error,
    )
    parsed_path = archive_news_payload(
        storage_root=storage_root,
        layer="parsed",
        source_key=JIN10_DETAIL_SOURCE_KEY,
        retrieved_date=retrieved_date,
        name=archive_name,
        payload=result.to_dict(),
    )
    return Jin10DetailFetchResult(**{**result.to_dict(), "parsed_path": parsed_path})


def _fetch_rendered_html_via_browser_profile(
    *,
    url: str,
    user_data_dir: Path | str,
    executable_path: Path | str | None = None,
) -> RenderedDetailPage:
    chromium = Path(executable_path) if executable_path else _find_chromium_executable()
    if chromium is None:
        raise RuntimeError("No Chromium executable found for Jin10 detail browser-profile fetch.")
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("Playwright is required for browser-profile Jin10 detail fetch.") from exc

    profile_dir = Path(user_data_dir).expanduser()
    if not profile_dir.exists():
        raise RuntimeError(f"Browser profile not found: {profile_dir}")

    with tempfile.TemporaryDirectory(prefix="jin10-detail-playwright-runtime-") as runtime_dir:
        profile_copy = Path(runtime_dir) / "profile"
        _copy_browser_profile_for_readonly_launch(profile_dir, profile_copy)
        env = {**os.environ, "XDG_RUNTIME_DIR": runtime_dir}
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(profile_copy),
                executable_path=str(chromium),
                headless=True,
                args=["--disable-dev-shm-usage"],
                env=env,
            )
            try:
                page = context.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                _wait_for_detail_render(page)
                return RenderedDetailPage(final_url=page.url, html=page.content())
            finally:
                context.close()


def _wait_for_detail_render(page: Any) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    try:
        page.wait_for_function(
            """
            () => {
              const text = (document.body?.innerText || '').replace(/\\s+/g, '');
              if (!text) return false;
              if (/doesn'tworkproperlywithoutJavaScriptenabled/i.test(text)) return false;
              if (/请登录|登录后查看/.test(text)) return true;
              const hasVipLock = /VIP专享文章|钻石VIP专享文章|解锁文章/.test(text);
              return text.length >= 120 && !hasVipLock;
            }
            """,
            timeout=12000,
        )
    except Exception:
        page.wait_for_timeout(2500)


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


def _write_raw_html(*, storage_root: Path, retrieved_date: str, url: str, html: str, archive_name: str | None = None) -> str:
    target_dir = storage_root / "raw" / "news" / JIN10_DETAIL_SOURCE_KEY / retrieved_date
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{archive_name or _safe_name(url)}.html"
    target.write_text(html, encoding="utf-8", errors="ignore")
    return target.relative_to(storage_root).as_posix()


def _extract_title(html: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.I | re.S)
    if not match:
        return ""
    return re.sub(r"\s+", " ", match.group(1)).strip()


def _visible_text(html: str) -> str:
    return _extract_main_text(html) or _fallback_visible_text(html)


def _extract_main_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()

    candidates: list[tuple[int, int, str]] = []
    selectors = [
        ".jin10-news-cdetails-content",
        ".jin10vip-image-viewer",
        ".jin10-news-details-contexts",
        ".jin10-news-details-body",
        ".course-detail-tab-panel",
        ".course-detail-content",
        ".desktop-detail",
        ".desktop-layout__content",
        "article",
        "main",
    ]
    for selector in selectors:
        for node in soup.select(selector):
            text = _clean_extracted_text(node.get_text(" ", strip=True))
            if len(text) < 80:
                continue
            score = _main_text_score(text=text, class_name=" ".join(node.get("class") or []), selector=selector)
            candidates.append((score, len(text), text))

    if not candidates:
        return ""
    candidates.sort(reverse=True)
    best_score, _, best_text = candidates[0]
    if best_score <= 0:
        return ""
    return best_text


def _main_text_score(*, text: str, class_name: str, selector: str) -> int:
    lower_class = class_name.lower()
    score = 0
    selector_bonus = {
        ".jin10-news-cdetails-content": 80,
        ".jin10vip-image-viewer": 65,
        ".course-detail-content": 70,
        ".course-detail-tab-panel": 55,
        ".jin10-news-details-contexts": 45,
        ".jin10-news-details-body": 40,
        ".desktop-detail": 20,
        ".desktop-layout__content": 15,
        "article": 30,
        "main": 20,
    }
    score += selector_bonus.get(selector, 0)
    for marker in (
        "行情回顾",
        "关键指标",
        "观点分享",
        "第一部分",
        "第二部分",
        "Better News",
        "边听边想",
        "风险提示及免责条款",
        "CME突改",
    ):
        if marker in text:
            score += 12
    for marker in ("trial-home", "comments", "comment", "footer", "header", "menu", "drawer", "recommend"):
        if marker in lower_class:
            score -= 80
    if "专属客服" in text or "试读内容 免费读全文" in text:
        score -= 60
    if "金十数据 首页 头条 VIP专区" in text[:240]:
        score -= 35
    if 250 <= len(text) <= 5000:
        score += 20
    elif len(text) > 10000:
        score -= 25
    return score


def _fallback_visible_text(html: str) -> str:
    text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return _clean_extracted_text(text)


def _clean_extracted_text(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    cleaned = re.sub(r"当前文章\s+专栏目录\s+简介\s+", "", cleaned)
    cleaned = re.sub(r"We're sorry but .*?doesn't work properly without JavaScript enabled\. Please enable it to continue\.\s*", "", cleaned)
    cleaned = re.sub(r"\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\s+00:00\s+\d{2}:\d{2}\s+1X\s*", "", cleaned)
    cleaned = re.sub(r"00:00\s+\d{2}:\d{2}\s+1X\s*", "", cleaned)
    cleaned = re.sub(r"字体：\s*小\s*中\s*大\s*超大\s*夜间\s*评论\s*收藏\s*分享：\s*", "", cleaned)
    cleaned = re.sub(r"微信扫一扫：分享 微信里点“发现”，扫一下 二维码便可将本文分享至朋友圈。\s*", "", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _classify_access_status(*, raw_text: str, final_url: str) -> str:
    text = raw_text.strip()
    if not text:
        return "empty"
    lower_text = text.lower()
    lower_url = final_url.lower()
    compact_text = re.sub(r"\s+", "", text)
    is_logged_in = ("用户ID" in text and "退出登录" in text) or "已订阅" in text
    has_full_report = bool(
        re.search(r"[1１][、.．]行情回顾[：:].{30,}[2２][、.．]关键指标[：:]", compact_text)
        or re.search(r"[2２][、.．]关键指标[：:].{30,}[3３][、.．]观点分享[：:]", compact_text)
    )
    has_rendered_logged_in_content = is_logged_in and (has_full_report or len(compact_text) >= 800)
    has_rendered_vip_column_content = len(compact_text) >= 120 and any(
        marker in text for marker in ("Better News", "边听边想", "CME突改", "黄金", "期权", "流动性")
    )
    if "doesn't work properly without javascript enabled" in lower_text or "please enable it to continue" in lower_text:
        if has_rendered_logged_in_content:
            return "readable"
        return "javascript_required"
    if _is_disclaimer_only_text(text):
        return "vip_locked"
    if "/vip_column/index.html" in lower_url:
        if has_rendered_logged_in_content or has_rendered_vip_column_content:
            return "readable"
        return "javascript_required"
    if any(marker in text for marker in ("VIP专享文章", "钻石VIP专享文章", "解锁文章")):
        if has_rendered_logged_in_content:
            return "readable"
        return "vip_locked"
    return "readable"


def _is_disclaimer_only_text(text: str) -> bool:
    compact_text = re.sub(r"\s+", "", text)
    if len(compact_text) > 260:
        return False
    return "风险提示及免责条款" in compact_text and "不构成个人投资建议" in compact_text


def _extract_image_urls(*, html: str, base_url: str) -> list[str]:
    urls: list[str] = []
    patterns = [
        r"https?://[^\"'<>\\s]+?\.(?:png|jpg|jpeg|webp)(?:\?[^\"'<>\\s]*)?",
        r"<img[^>]+(?:src|data-src)=[\"']([^\"']+)[\"']",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, html, flags=re.I):
            value = match.group(1) if match.lastindex else match.group(0)
            candidate = urljoin(base_url, value.replace("\\/", "/"))
            if candidate not in urls:
                urls.append(candidate)
    return urls


def _download_images(
    *,
    client: Any,
    storage_root: Path,
    retrieved_date: str,
    detail_url: str,
    image_urls: list[str],
    min_vlm_width: int,
    min_vlm_height: int,
    min_vlm_bytes: int,
) -> list[dict[str, Any]]:
    target_dir = (
        storage_root
        / "raw"
        / "news"
        / JIN10_DETAIL_SOURCE_KEY
        / retrieved_date
        / "images"
        / _safe_name(detail_url)
    )
    target_dir.mkdir(parents=True, exist_ok=True)
    assets: list[dict[str, Any]] = []
    for seq, image_url in enumerate(image_urls, start=1):
        asset: dict[str, Any] = {"seq": seq, "url": image_url}
        try:
            response = client.get(image_url, headers={"Referer": detail_url, "User-Agent": DEFAULT_HEADERS["User-Agent"]})
            content_type = str(response.headers.get("content-type") or "")
            asset["status_code"] = response.status_code
            asset["content_type"] = content_type
            asset["bytes"] = len(response.content)
            if response.status_code != 200 or not content_type.startswith("image/"):
                asset["vlm_eligible"] = False
                asset["vlm_skip_reason"] = "not_image_response"
                assets.append(asset)
                continue
            suffix = Path(urlparse(image_url).path).suffix or ".jpg"
            target = target_dir / f"{seq:02d}-{_safe_name(image_url)}{suffix}"
            target.write_bytes(response.content)
            asset["file"] = target.name
            asset["path"] = target.relative_to(storage_root).as_posix()
            width, height = _image_dimensions(target)
            asset["width"] = width
            asset["height"] = height
            eligible = (
                width >= min_vlm_width
                and height >= min_vlm_height
                and len(response.content) >= min_vlm_bytes
            )
            asset["vlm_eligible"] = eligible
            if not eligible:
                asset["vlm_skip_reason"] = "image_too_small_for_vlm"
        except Exception as exc:
            asset["error"] = f"{type(exc).__name__}: {exc}"
            asset["vlm_eligible"] = False
            asset["vlm_skip_reason"] = "download_failed"
        assets.append(asset)
    return assets


def _run_vlm_if_requested(
    *,
    run_vlm: bool,
    image_assets: list[dict[str, Any]],
    storage_root: Path,
    vlm_runner: VlmRunner | None,
) -> list[dict[str, Any]]:
    if not run_vlm:
        return []
    eligible = [asset for asset in image_assets if asset.get("vlm_eligible") and asset.get("path")]
    if not eligible:
        return []
    if vlm_runner is not None:
        return vlm_runner(eligible)
    try:
        client = DashScopeVisionMarkdownClient()
    except MissingDashScopeApiKey:
        return [
            {
                "seq": asset.get("seq"),
                "file": asset.get("file"),
                "path": asset.get("path"),
                "status": "unavailable",
                "reason": "missing_dashscope_api_key",
            }
            for asset in eligible
        ]
    insights: list[dict[str, Any]] = []
    for asset in eligible:
        result = client.recognize_page_markdown(
            image_path=storage_root / str(asset["path"]),
            page_no=int(asset.get("seq") or 0),
            figures=[],
        )
        insights.append({
            "seq": asset.get("seq"),
            "file": asset.get("file"),
            "path": asset.get("path"),
            "status": result.get("status"),
            "model": result.get("model"),
            "markdown": result.get("markdown") or "",
        })
    return insights


def _image_dimensions(path: Path) -> tuple[int, int]:
    image = cv2.imread(str(path))
    if image is None:
        return (0, 0)
    return (int(image.shape[1]), int(image.shape[0]))


def _safe_name(value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    stem = re.sub(r"[^a-zA-Z0-9_-]+", "-", urlparse(value).path.strip("/") or "detail").strip("-")
    return f"{stem[:64] or 'detail'}-{digest}"


def _archive_name(*, url: str, fetch_method: str) -> str:
    base = _safe_name(url)
    if fetch_method == "http":
        return base
    suffix = re.sub(r"[^a-zA-Z0-9-]+", "-", fetch_method.replace("_", "-")).strip("-") or "fallback"
    return f"{base}-{suffix}"


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
