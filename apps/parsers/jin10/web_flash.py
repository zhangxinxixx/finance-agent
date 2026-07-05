"""Parser for Jin10 homepage web flash items (fixture-first)."""

from __future__ import annotations

from html.parser import HTMLParser
from typing import Any


def parse_jin10_web_flash_html(
    html: str,
    *,
    fetched_at: str,
    raw_artifact_path: str | None = None,
) -> dict[str, Any]:
    """Parse Jin10 homepage HTML into normalized flash items."""
    parser = _Jin10FlashParser()
    parser.feed(html)

    # Normalize before dedupe because the stable item id is derived from data-id/title.
    seen: set[str] = set()
    items: list[dict[str, Any]] = []
    for raw_item in parser.items:
        item = _normalize_item(raw_item, fetched_at=fetched_at, raw_artifact_path=raw_artifact_path)
        dedupe_key = item.get("itemId") or item.get("url") or item.get("title")
        if dedupe_key in seen:
            continue
        seen.add(str(dedupe_key))
        items.append(item)

    if not items:
        return {
            "status": "schema_changed",
            "fetchedAt": fetched_at,
            "items": [],
            "qualityFlags": {"schema_changed": True},
        }

    return {
        "status": "ok",
        "fetchedAt": fetched_at,
        "items": items,
        "qualityFlags": {},
    }


# ---------------------------------------------------------------------------
# HTML parser
# ---------------------------------------------------------------------------


class _Jin10FlashParser(HTMLParser):
    """Minimal HTMLParser that extracts flash items from Jin10 homepage."""

    def __init__(self) -> None:
        super().__init__()
        self.items: list[dict[str, Any]] = []
        self._current: dict[str, Any] | None = None
        self._in_tag: str | None = None
        self._capture_text = False
        self._text_buf: list[str] = []
        self._div_depth: int = 0
        # top-list tracking
        self._in_top_item = False
        self._top_current: dict[str, Any] | None = None
        self._top_capture = False
        self._top_buf: list[str] = []
        self._top_in_tag: str | None = None
        self._top_depth: int = 0
        self._pending_flash_id: str | None = None
        self._in_right_content_title = False
        self._right_content_title_depth = 0
        # homepage recommended article cards
        self._in_article_item = False
        self._article_current: dict[str, Any] | None = None
        self._article_capture = False
        self._article_buf: list[str] = []
        self._article_in_tag: str | None = None
        self._article_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = dict(attrs)
        cls = attr_map.get("class", "") or ""
        classes = _class_tokens(cls)

        if tag == "div" and "jin-flash-item-container" in classes:
            container_id = attr_map.get("id") or ""
            if container_id.startswith("flash"):
                self._pending_flash_id = container_id.replace("flash", "", 1) or None

        # --- flash item ---
        if tag == "div" and "jin-flash-item" in classes and "flash" in classes:
            data_id = attr_map.get("data-id", "") or self._pending_flash_id or ""
            item: dict[str, Any] = {"data_id": data_id or None}
            if "is-important" in classes:
                item["type"] = "important"
            elif "is-vip" in classes:
                item["type"] = "vip"
            else:
                item["type"] = "flash"
            self._current = item
            self._div_depth = 1
            return

        if self._current is not None:
            if tag == "div":
                self._div_depth += 1
                if self._in_right_content_title:
                    self._right_content_title_depth += 1
            href = attr_map.get("href", "")
            data_text = attr_map.get("data-text")
            if tag == "span" and data_text:
                self._current.setdefault("labels", []).append(data_text)
            if tag == "a" and "flash-item-title" in classes:
                self._current["url"] = href or None
                self._in_tag = "title"
                self._capture_text = True
                self._text_buf = []
            elif tag == "a" and href and _is_flash_detail_link(href) and not self._current.get("url"):
                self._current["url"] = href
            elif tag == "a" and _is_content_link(href):
                self._current.setdefault("linked_urls", []).append(href)
            if tag == "img" and attr_map.get("src"):
                self._current.setdefault("image_urls", []).append(str(attr_map["src"]))
            if tag == "div" and "right-content_title" in classes:
                self._in_right_content_title = True
                self._right_content_title_depth = 1
            elif self._in_right_content_title and tag == "span" and "jin-tag" not in classes and not data_text:
                self._in_tag = "title"
                self._capture_text = True
                self._text_buf = []
            elif tag == "div" and "flash-item-title" in classes:
                self._in_tag = "title"
                self._capture_text = True
                self._text_buf = []
            elif tag == "div" and "flash-item-summary" in classes:
                self._in_tag = "summary"
                self._capture_text = True
                self._text_buf = []
            elif tag == "div" and "right-content_intro" in classes:
                self._in_tag = "summary"
                self._capture_text = True
                self._text_buf = []
            elif tag == "div" and ("flash-item-time" in classes or "item-time" in classes):
                self._in_tag = "time"
                self._capture_text = True
                self._text_buf = []
            elif tag == "div" and "flash-text" in classes:
                self._in_tag = "summary" if self._current.get("title") else "title"
                self._capture_text = True
                self._text_buf = []
            elif tag == "b" and "right-vip-title" in classes:
                self._in_tag = "title"
                self._capture_text = True
                self._text_buf = []
            elif tag == "b" and "right-common-title" in classes:
                self._in_tag = "label"
                self._capture_text = True
                self._text_buf = []
            elif tag == "span" and "color-label__item" in classes:
                self._in_tag = "label"
                self._capture_text = True
                self._text_buf = []
            return

        # --- top list item ---
        if tag in ("a", "div") and "flash-top-list__item" in classes:
            data_id = attr_map.get("data-id", "")
            href = attr_map.get("href", "")
            self._top_current = {
                "type": "top",
                "data_id": data_id or None,
                "url": href or None,
            }
            self._in_top_item = True
            self._top_depth = 1
            return

        if self._in_top_item and self._top_current is not None:
            if tag == "div":
                self._top_depth += 1
            if tag in ("span", "div") and (
                "flash-top-list__title" in classes or "flash-top-list__item-content" in classes
            ):
                self._top_in_tag = "title"
                self._top_capture = True
                self._top_buf = []
            elif tag in ("span", "div") and "flash-top-list__time" in classes:
                self._top_in_tag = "time"
                self._top_capture = True
                self._top_buf = []
            return

        # --- homepage recommended article item ---
        if tag == "div" and "recommend-article-item" in classes:
            self._article_current = {"type": "article"}
            self._in_article_item = True
            self._article_depth = 1
            return

        if self._in_article_item and self._article_current is not None:
            if tag == "div":
                self._article_depth += 1
            data_text = attr_map.get("data-text")
            if tag == "span" and data_text:
                self._article_current.setdefault("labels", []).append(data_text)
            if tag == "div" and "item-bg" in classes:
                image_url = _extract_css_background_url(attr_map.get("style"))
                if image_url:
                    self._article_current.setdefault("image_urls", []).append(image_url)
            elif tag == "span" and "text" in classes:
                self._article_in_tag = "title"
                self._article_capture = True
                self._article_buf = []
            elif tag == "div" and "item-time" in classes:
                self._article_in_tag = "time"
                self._article_capture = True
                self._article_buf = []

    def handle_endtag(self, tag: str) -> None:
        # --- flash item ---
        if self._current is not None and self._capture_text:
            text = "".join(self._text_buf).strip()
            if self._in_tag == "title":
                self._current["title"] = text
            elif self._in_tag == "summary":
                self._current["summary"] = text
            elif self._in_tag == "time":
                self._current["published_at"] = text
            elif self._in_tag == "label":
                self._current.setdefault("labels", []).append(text)
            self._capture_text = False
            self._in_tag = None
            self._text_buf = []

        # Close flash item only when outer wrapper div closes (depth back to 0)
        if tag == "div" and self._current is not None:
            if self._in_right_content_title:
                self._right_content_title_depth -= 1
                if self._right_content_title_depth <= 0:
                    self._in_right_content_title = False
                    self._right_content_title_depth = 0
            self._div_depth -= 1
            if self._div_depth <= 0:
                if self._current.get("title"):
                    self.items.append(self._current)
                self._current = None
                self._div_depth = 0
                self._pending_flash_id = None
                self._in_right_content_title = False
                self._right_content_title_depth = 0

        # --- top list item ---
        if self._in_top_item and self._top_current is not None and self._top_capture:
            text = "".join(self._top_buf).strip()
            if self._top_in_tag == "title":
                self._top_current["title"] = text
            elif self._top_in_tag == "time":
                self._top_current["published_at"] = text
            self._top_capture = False
            self._top_in_tag = None
            self._top_buf = []

        if tag == "a" and self._in_top_item and self._top_current is not None:
            if self._top_current.get("title"):
                self.items.append(self._top_current)
            self._top_current = None
            self._in_top_item = False
            self._top_depth = 0

        if tag == "div" and self._in_top_item and self._top_current is not None:
            self._top_depth -= 1
            if self._top_depth <= 0:
                if self._top_current.get("title"):
                    self.items.append(self._top_current)
                self._top_current = None
                self._in_top_item = False
                self._top_depth = 0

        # --- homepage recommended article item ---
        if self._in_article_item and self._article_current is not None and self._article_capture:
            text = "".join(self._article_buf).strip()
            if self._article_in_tag == "title":
                self._article_current["title"] = text
            elif self._article_in_tag == "time":
                self._article_current["published_at"] = text
            self._article_capture = False
            self._article_in_tag = None
            self._article_buf = []

        if tag == "div" and self._in_article_item and self._article_current is not None:
            self._article_depth -= 1
            if self._article_depth <= 0:
                if self._article_current.get("title"):
                    self.items.append(self._article_current)
                self._article_current = None
                self._in_article_item = False
                self._article_depth = 0

    def handle_data(self, data: str) -> None:
        if self._capture_text:
            self._text_buf.append(data)
        if self._top_capture:
            self._top_buf.append(data)
        if self._article_capture:
            self._article_buf.append(data)


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

_SOURCE_KEY_MAP = {
    "important": "jin10_web_important_flash",
    "vip": "jin10_web_vip_flash",
    "top": "jin10_web_important_flash",
}

_CONTENT_FAMILY_MAP = {
    "top": "web_important_flash.important_news_top",
    "article": "web_important_flash.report_article_flash",
}

_IMPORTANT_MACRO_KEYWORDS = ("美联储", "央行", "利率", "通胀", "非农", "CPI", "就业", "加息", "降息", "QE", "PMI")
_IMPORTANT_GEO_KEYWORDS = ("伊朗", "以色列", "红海", "袭击", "制裁", "战争", "无人机", "地缘", "导弹")
_IMPORTANT_MOVE_KEYWORDS = ("期货", "反弹", "下跌", "上涨", "涨幅", "跌幅", "走高", "走低", "跳水", "拉升")
_REPORT_ARTICLE_KEYWORDS = ("金十图示", "持仓报告", "研究报告", "报告全文", "图解", "图示")

_VIP_GOLD_KEYWORDS = ("黄金", "白银", "金价", "银价", "贵金属")
_VIP_GEO_OIL_KEYWORDS = ("原油", "油价", "OPEC", "霍尔木兹")
_VIP_INSTITUTION_KEYWORDS = ("投行", "机构", "高盛", "摩根", "瑞银", "花旗")
_VIP_TECHNICAL_KEYWORDS = ("支撑", "阻力", "关口", "均线", "突破", "回调", "技术位", "挂单")

_IMPORTANCE_SOURCE_MAP = {
    "important": "jin10_home_important_marker",
    "vip": "jin10_vip_marker",
    "top": "jin10_home_top_list",
    "article": "jin10_home_recommend_article",
}

_VERIFICATION_MAP = {
    "important": "single_source",
    "vip": "report_derived",
    "top": "single_source",
    "article": "single_source",
}


def _has_report_article_evidence(title: str, summary: str, labels: list[str], linked_urls: list[str], image_urls: list[str]) -> bool:
    text = " ".join([title, summary, *labels])
    return bool(linked_urls or image_urls or any(keyword in text for keyword in _REPORT_ARTICLE_KEYWORDS))


def _classify_important_family(title: str, summary: str, labels: list[str], linked_urls: list[str], image_urls: list[str]) -> str:
    if _has_report_article_evidence(title, summary, labels, linked_urls, image_urls):
        return "web_important_flash.report_article_flash"
    text = " ".join([title, summary, *labels])
    if any(kw in text for kw in _IMPORTANT_MACRO_KEYWORDS):
        return "web_important_flash.macro_policy_flash"
    if any(kw in text for kw in _IMPORTANT_GEO_KEYWORDS):
        return "web_important_flash.geo_risk_flash"
    if any(kw in text for kw in _IMPORTANT_MOVE_KEYWORDS):
        return "web_important_flash.market_move_flash"
    return "web_important_flash.market_flash_important"


def _classify_vip_family(title: str, summary: str, labels: list[str], linked_urls: list[str], image_urls: list[str]) -> str:
    if _has_report_article_evidence(title, summary, labels, linked_urls, image_urls):
        return "web_vip_flash.vip_report_article"
    text = " ".join([title, summary, *labels])
    if any(kw in text for kw in _VIP_GOLD_KEYWORDS):
        return "web_vip_flash.vip_gold_silver_flash"
    if any(kw in text for kw in _VIP_GEO_OIL_KEYWORDS):
        return "web_vip_flash.vip_geo_oil_flash"
    if any(kw in text for kw in _VIP_INSTITUTION_KEYWORDS):
        return "web_vip_flash.vip_institution_view"
    if any(kw in text for kw in _VIP_TECHNICAL_KEYWORDS):
        return "web_vip_flash.vip_technical_flash"
    return "web_vip_flash.vip_macro_flash"


def _content_family(
    item_type: str,
    title: str,
    summary: str,
    labels: list[str],
    linked_urls: list[str],
    image_urls: list[str],
) -> str:
    if _has_report_article_evidence(title, summary, labels, linked_urls, image_urls):
        if item_type == "vip":
            return "web_vip_flash.vip_report_article"
        return "web_important_flash.report_article_flash"
    if item_type in _CONTENT_FAMILY_MAP:
        return _CONTENT_FAMILY_MAP[item_type]
    if item_type == "important":
        return _classify_important_family(title, summary, labels, linked_urls, image_urls)
    if item_type == "vip":
        return _classify_vip_family(title, summary, labels, linked_urls, image_urls)
    return "web_important_flash.market_flash_important"


def _normalize_item(
    raw: dict[str, Any],
    *,
    fetched_at: str,
    raw_artifact_path: str | None,
) -> dict[str, Any]:
    item_type = raw.get("type", "flash")
    labels = list(raw.get("labels") or [])
    linked_urls = _dedupe_strings(raw.get("linked_urls") or [])
    image_urls = _dedupe_strings(raw.get("image_urls") or [])
    data_id = raw.get("data_id")
    original_url = raw.get("url")
    flash_id = data_id or _extract_flash_id(original_url)
    item_id = f"jin10_flash_{flash_id}" if flash_id else f"jin10_{item_type}_{_slug(raw.get('title', ''))}"
    url = f"https://flash.jin10.com/detail/{flash_id}" if flash_id else original_url

    source_refs: dict[str, Any] = {
        "selector": _selector_for_type(item_type),
        "fetchedAt": fetched_at,
    }
    if original_url:
        source_refs["sourceUrl"] = original_url
    if flash_id:
        source_refs["flashId"] = flash_id
    if raw_artifact_path:
        source_refs["rawArtifactPath"] = raw_artifact_path

    artifact_refs: dict[str, Any] = {}
    if raw_artifact_path:
        artifact_refs["rawArtifactPath"] = raw_artifact_path

    return {
        "itemId": item_id,
        "sourceKey": _SOURCE_KEY_MAP.get(item_type, "jin10_web_important_flash"),
        "contentFamily": _content_family(
            item_type,
            raw.get("title", ""),
            raw.get("summary", ""),
            labels,
            linked_urls,
            image_urls,
        ),
        "title": raw.get("title", "").strip(),
        "summary": raw.get("summary", "").strip() or None,
        "publishedAt": raw.get("published_at") or None,
        "url": url or None,
        "importanceSource": _IMPORTANCE_SOURCE_MAP.get(item_type, "jin10_home_important_marker"),
        "verificationStatus": _VERIFICATION_MAP.get(item_type, "single_source"),
        "accessStatus": "readable",
        "tags": labels,
        "linkedUrls": linked_urls,
        "imageUrls": image_urls,
        "sourceRefs": [source_refs],
        "artifactRefs": [artifact_refs] if artifact_refs else [],
    }


def _selector_for_type(item_type: str) -> str:
    if item_type == "vip":
        return ".jin-flash-item.flash.is-vip"
    if item_type == "top":
        return ".flash-top-list__item"
    return ".jin-flash-item.flash.is-important"


def _slug(text: str) -> str:
    """Derive a short stable slug from title text."""
    import hashlib

    clean = text.strip()[:40]
    if not clean:
        return hashlib.md5(b"empty").hexdigest()[:8]
    return hashlib.md5(clean.encode()).hexdigest()[:8]


def _extract_flash_id(url: Any) -> str | None:
    if not isinstance(url, str) or not url:
        return None
    for marker in ("/detail/", "id=", "#id="):
        if marker not in url:
            continue
        value = url.split(marker, 1)[1].split("&", 1)[0].split("#", 1)[0].strip("/")
        return value or None
    return None


def _class_tokens(class_attr: str) -> set[str]:
    return {token for token in class_attr.split() if token}


def _is_content_link(href: Any) -> bool:
    if not isinstance(href, str) or not href:
        return False
    if href.startswith("javascript:") or href.startswith("#"):
        return False
    if _is_flash_detail_link(href):
        return False
    return href.startswith("http://") or href.startswith("https://")


def _is_flash_detail_link(href: str) -> bool:
    return "flash.jin10.com/detail/" in href or "flash-api.jin10.com/get" in href


def _dedupe_strings(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _extract_css_background_url(style: Any) -> str | None:
    if not isinstance(style, str) or "url(" not in style:
        return None
    value = style.split("url(", 1)[1].split(")", 1)[0].strip().strip("\"'")
    return value or None
