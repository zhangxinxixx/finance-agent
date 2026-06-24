from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from apps.collectors.news.base import RawNewsItem
from apps.collectors.news.jin10_detail_fetcher import Jin10DetailFetchResult

RULE_VERSION = "jin10-article-briefs-v1"


@dataclass(frozen=True)
class Jin10ArticleBrief:
    brief_id: str
    article_class: str
    display_bucket: str
    headline: str
    source_url: str
    final_url: str | None
    access_status: str
    original_excerpt: str
    key_points: list[str]
    analysis_summary: str
    asset_tags: list[str]
    topic_tags: list[str]
    suggested_actions: list[str]
    source_refs: list[dict[str, Any]]
    detail_artifacts: dict[str, Any]
    data_quality: dict[str, Any]
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Jin10ArticleBriefBundle:
    as_of: str
    rule_version: str
    briefs: list[Jin10ArticleBrief]
    data_quality: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of,
            "rule_version": self.rule_version,
            "brief_count": len(self.briefs),
            "briefs": [brief.to_dict() for brief in self.briefs],
            "data_quality": self.data_quality,
        }


def build_jin10_article_briefs(
    *,
    items_with_details: list[tuple[RawNewsItem, Jin10DetailFetchResult | dict[str, Any]]],
    as_of: str,
) -> Jin10ArticleBriefBundle:
    briefs = [
        _build_brief(item=item, detail=_detail_dict(detail), as_of=as_of)
        for item, detail in items_with_details
    ]
    briefs = sorted(_dedupe_briefs([brief for brief in briefs if brief is not None]), key=_sort_key)
    return Jin10ArticleBriefBundle(
        as_of=as_of,
        rule_version=RULE_VERSION,
        briefs=briefs,
        data_quality={
            "input_count": len(items_with_details),
            "brief_count": len(briefs),
            "access_status_counts": _count_by(briefs, "access_status"),
            "article_class_counts": _count_by(briefs, "article_class"),
            "display_bucket_counts": _count_by(briefs, "display_bucket"),
        },
    )


def archive_jin10_article_briefs(
    *,
    storage_root: Path,
    retrieved_date: str,
    run_id: str,
    bundle: Jin10ArticleBriefBundle,
) -> str:
    target = storage_root / "features" / "news" / retrieved_date / run_id / "jin10_article_briefs.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(bundle.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target.relative_to(storage_root).as_posix()


def _build_brief(*, item: RawNewsItem, detail: dict[str, Any], as_of: str) -> Jin10ArticleBrief:
    access_status = str(detail.get("access_status") or "unknown")
    text_for_display = _display_text(item=item, detail=detail)
    headline = _headline(item=item, detail=detail, access_status=access_status)
    asset_tags = _asset_tags(item=item, text=text_for_display)
    topic_tags = _topic_tags(text_for_display)
    article_class, display_bucket = _classify_article(
        item=item,
        detail=detail,
        access_status=access_status,
        text=text_for_display,
        asset_tags=asset_tags,
    )
    key_points = _key_points(text_for_display)
    analysis_summary = _analysis_summary(
        article_class=article_class,
        access_status=access_status,
        detail=detail,
        text=text_for_display,
        asset_tags=asset_tags,
        key_points=key_points,
    )
    return Jin10ArticleBrief(
        brief_id=_brief_id(item=item, final_url=str(detail.get("final_url") or "")),
        article_class=article_class,
        display_bucket=display_bucket,
        headline=headline,
        source_url=item.url,
        final_url=detail.get("final_url"),
        access_status=access_status,
        original_excerpt=text_for_display[:800],
        key_points=key_points,
        analysis_summary=analysis_summary,
        asset_tags=asset_tags,
        topic_tags=topic_tags,
        suggested_actions=_suggested_actions(article_class=article_class, access_status=access_status),
        source_refs=_source_refs(item, detail=detail),
        detail_artifacts={
            "raw_html_path": detail.get("raw_html_path"),
            "parsed_path": detail.get("parsed_path"),
            "image_asset_count": len(detail.get("image_assets") or []),
            "vlm_eligible_image_count": _vlm_eligible_image_count(detail),
            "vlm_insight_count": len(detail.get("image_insights") or []),
            "fetch_method": detail.get("fetch_method"),
            "access_method": detail.get("access_method"),
            "browser_fallback_attempted": bool(detail.get("browser_fallback_attempted")),
            "browser_fallback_status": detail.get("browser_fallback_status"),
            "browser_fallback_error": detail.get("browser_fallback_error"),
        },
        data_quality={
            "source_key": str(detail.get("source_key") or item.source_key),
            "verification_status": item.verification_status,
            "access_status": access_status,
            "raw_text_chars": len(str(detail.get("raw_text") or "")),
            "used_detail_text": _uses_detail_text(detail),
            "fetch_method": detail.get("fetch_method"),
            "access_method": detail.get("access_method"),
            "image_asset_count": len(detail.get("image_assets") or []),
            "vlm_eligible_image_count": _vlm_eligible_image_count(detail),
            "browser_fallback_attempted": bool(detail.get("browser_fallback_attempted")),
            "browser_fallback_status": detail.get("browser_fallback_status"),
        },
        created_at=as_of,
    )


def _detail_dict(detail: Jin10DetailFetchResult | dict[str, Any]) -> dict[str, Any]:
    return detail.to_dict() if isinstance(detail, Jin10DetailFetchResult) else dict(detail)


def _display_text(*, item: RawNewsItem, detail: dict[str, Any]) -> str:
    raw_text = str(detail.get("raw_text") or "").strip()
    if _uses_detail_text(detail):
        return _clean_text(raw_text)
    return _clean_text(item.summary or item.title)


def _uses_detail_text(detail: dict[str, Any]) -> bool:
    access_status = str(detail.get("access_status") or "")
    raw_text = str(detail.get("raw_text") or "").strip()
    if access_status == "readable":
        return bool(raw_text)
    if access_status == "javascript_required":
        return False
    if "doesn't work properly without javascript enabled" in raw_text.lower():
        return False
    return bool(raw_text)


def _headline(*, item: RawNewsItem, detail: dict[str, Any], access_status: str) -> str:
    title = str(detail.get("title") or "").strip()
    if access_status == "javascript_required" or title.lower().startswith("we're sorry"):
        title = item.title
    return _clean_text(title or item.title)[:160]


def _classify_article(
    *,
    item: RawNewsItem,
    detail: dict[str, Any],
    access_status: str,
    text: str,
    asset_tags: list[str],
) -> tuple[str, str]:
    lower_url = str(detail.get("final_url") or item.url).lower()
    if access_status == "javascript_required":
        return ("javascript_required", "待渲染")
    if access_status == "vip_locked":
        return ("vip_market_reference", "VIP预览")
    if "flash.jin10.com" in lower_url:
        return ("flash_news", "快讯")
    has_gold = "XAUUSD" in asset_tags
    has_macro = _contains_any(text, ["美联储", "通胀", "宽松", "降息", "利率", "收益率", "美元", "fed", "inflation"])
    has_energy = _contains_any(text, ["能源", "原油", "油价", "欧佩克", "opec", "oil"])
    has_level = _contains_any(text, ["动量", "催化剂", "收复", "关键位", "支撑", "阻力", "破位", "均线"]) or bool(
        re.search(r"(?<!\d)(?:[34]\d{3}|5\d{3})(?!\d)", text)
    )
    if has_gold and (has_macro or has_energy or has_level):
        return ("gold_macro_market_reference", "重点分析")
    if has_energy:
        return ("energy_macro_reference", "能源宏观")
    if has_gold:
        return ("gold_market_reference", "黄金观察")
    return ("market_reference", "市场参考")


def _key_points(text: str) -> list[str]:
    sentences = [
        _clean_text(part)
        for part in re.split(r"[。！？!?]\s*", text)
        if _clean_text(part)
    ]
    result: list[str] = []
    for sentence in sentences:
        if len(sentence) < 6:
            continue
        if sentence in result:
            continue
        result.append(sentence[:120])
        if len(result) >= 4:
            break
    return result


def _analysis_summary(
    *,
    article_class: str,
    access_status: str,
    detail: dict[str, Any],
    text: str,
    asset_tags: list[str],
    key_points: list[str],
) -> str:
    browser_attempted = bool(detail.get("browser_fallback_attempted"))
    browser_status = str(detail.get("browser_fallback_status") or "")
    browser_error = str(detail.get("browser_fallback_error") or "").strip()
    if access_status == "javascript_required":
        if browser_attempted:
            suffix = f"；fallback错误：{browser_error[:120]}" if browser_error else ""
            return f"已尝试复用金十浏览器登录态，但当前仍只拿到 JS 渲染壳页，需检查 profile 登录状态或页面反爬{suffix}。"
        return "该文章当前抓到的是 JS 渲染壳页，需要用金十 VIP 浏览器登录态重新打开后再提取正文。"
    if access_status == "vip_locked":
        if browser_attempted:
            suffix = f"；fallback错误：{browser_error[:120]}" if browser_status == "failed" and browser_error else ""
            return f"已尝试复用金十浏览器登录态，但当前仍只拿到 VIP 预览，需检查该 profile 是否仍有 VIP 权限或登录是否失效{suffix}。"
        return "该文章只抓到 VIP 预览内容，需要金十 VIP 登录态补全文；当前可作为小快讯预览和后续分析线索。"
    if article_class == "gold_macro_market_reference":
        return "这是一条黄金主线重点分析：利率/通胀压力、美元或能源通胀路径正在压制黄金情绪，适合排队生成日报分析。"
    if article_class == "flash_news":
        return "这是一条金十快讯，适合作为事件流补充证据；是否进入日报取决于后续多源验证和市场反应。"
    if "WTI" in asset_tags or "Brent" in asset_tags:
        return "这是一条能源宏观线索，重点观察油价到通胀预期再到美债收益率和黄金的传导。"
    return "这是一条金十市场参考文章，可先展示原文摘录和要点，后续结合行情与多源验证决定是否进入日报。"


def _asset_tags(*, item: RawNewsItem, text: str) -> list[str]:
    raw_payload = item.raw_payload if isinstance(item.raw_payload, dict) else {}
    relevance = raw_payload.get("relevance_decision") if isinstance(raw_payload.get("relevance_decision"), dict) else {}
    tags = [str(tag) for tag in relevance.get("asset_tags") or [] if tag]
    if _contains_any(text, ["黄金", "金价", "xau", "gold"]):
        tags.append("XAUUSD")
    if _contains_any(text, ["原油", "油价", "欧佩克", "opec", "wti"]):
        tags.extend(["WTI", "Brent"])
    if _contains_any(text, ["美元", "dxy"]):
        tags.append("DXY")
    if _contains_any(text, ["美联储", "利率", "收益率", "fed"]):
        tags.extend(["US02Y", "US10Y"])
    return _dedupe(tags)


def _topic_tags(text: str) -> list[str]:
    tags: list[str] = []
    if _contains_any(text, ["黄金", "金价", "xau", "gold"]):
        tags.append("gold")
    if _contains_any(text, ["美联储", "利率", "宽松", "降息", "fed"]):
        tags.append("rates")
    if _contains_any(text, ["通胀", "inflation"]):
        tags.append("inflation")
    if _contains_any(text, ["能源", "原油", "油价", "欧佩克", "opec", "oil"]):
        tags.append("energy")
    if _contains_any(text, ["动量", "催化剂", "收复", "关键位", "支撑", "阻力", "破位", "均线"]):
        tags.append("technical_level")
    return _dedupe(tags)


def _suggested_actions(*, article_class: str, access_status: str) -> list[str]:
    if access_status == "javascript_required":
        return ["show_in_news_flash", "run_browser_profile_fallback"]
    if access_status == "vip_locked":
        return ["show_in_news_flash", "link_detail_page", "run_browser_profile_fallback"]
    actions = ["show_in_news_flash", "link_detail_page"]
    if article_class == "gold_macro_market_reference":
        actions.append("queue_daily_analysis")
    return actions


def _source_refs(item: RawNewsItem, *, detail: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    raw_payload = item.raw_payload if isinstance(item.raw_payload, dict) else {}
    for ref in raw_payload.get("source_refs") or []:
        if isinstance(ref, dict):
            refs.append(dict(ref))
    if not refs:
        refs.append({"source": item.source_key, "source_ref": item.duplicate_key, "url": item.url})
    if detail:
        detail_source_key = str(detail.get("source_key") or "").strip()
        if detail_source_key:
            refs.append(
                {
                    "source": detail_source_key,
                    "source_key": detail_source_key,
                    "access_method": detail.get("access_method"),
                    "access_status": detail.get("access_status"),
                    "url": detail.get("final_url") or item.url,
                    "raw_html_path": detail.get("raw_html_path"),
                    "parsed_path": detail.get("parsed_path"),
                }
            )
    return refs


def _vlm_eligible_image_count(detail: dict[str, Any]) -> int:
    return sum(1 for asset in detail.get("image_assets") or [] if isinstance(asset, dict) and asset.get("vlm_eligible"))


def _brief_id(*, item: RawNewsItem, final_url: str) -> str:
    digest = hashlib.sha256(f"{item.duplicate_key}|{item.url}|{final_url}".encode("utf-8")).hexdigest()[:16]
    return f"jin10_brief:{digest}"


def _dedupe_briefs(briefs: list[Jin10ArticleBrief]) -> list[Jin10ArticleBrief]:
    seen: set[str] = set()
    result: list[Jin10ArticleBrief] = []
    for brief in briefs:
        if brief.brief_id in seen:
            continue
        seen.add(brief.brief_id)
        result.append(brief)
    return result


def _sort_key(brief: Jin10ArticleBrief) -> tuple[int, str]:
    bucket_rank = {
        "重点分析": 0,
        "VIP预览": 1,
        "待渲染": 2,
        "快讯": 3,
        "能源宏观": 4,
        "黄金观察": 5,
    }
    return (bucket_rank.get(brief.display_bucket, 99), brief.headline)


def _count_by(briefs: list[Jin10ArticleBrief], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for brief in briefs:
        value = str(getattr(brief, field))
        counts[value] = counts.get(value, 0) + 1
    return counts


def _contains_any(text: str, keywords: list[str]) -> bool:
    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in keywords)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _clean_text(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    cleaned = re.sub(r"字体：\s*小\s*中\s*大\s*超大\s*夜间\s*评论\s*收藏\s*分享：\s*", "", cleaned)
    cleaned = re.sub(r"首页\s+快讯详情\s+书签\s+分享：\s+微信扫码分享\s+\d{4}-\d{2}-\d{2}\s+周.\s+\d{2}:\d{2}:\d{2}\s*", "", cleaned)
    cleaned = re.sub(r"\s*-\s*金十数据\s+首页\s+快讯详情\s+书签\s+分享：\s+微信扫码分享\s+\d{4}-\d{2}-\d{2}\s+周.\s+\d{2}:\d{2}:\d{2}\s*", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()
