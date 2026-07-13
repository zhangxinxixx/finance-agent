"""Shared Jin10 report classification helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Jin10ReportClassification:
    category_code: str
    category: str
    report_type: str
    report_family: str
    asset_scope: str
    series: str = ""
    subcategory: str = ""


_CATEGORY_BY_CODE: dict[str, str] = {
    "270": "金银报告",
    "271": "外汇报告",
    "272": "原油报告",
    "274": "持仓报告",
    "301": "点位报告",
    "380": "挂单报告",
    "458": "VIP智库",
    "536": "黄金周报",
    "786": "周末·大师复盘",
}

_REPORT_TYPE_BY_CODE: dict[str, str] = {
    "270": "daily",
    "271": "fx",
    "272": "oil",
    "274": "positioning",
    "301": "technical_levels",
    "380": "pending_orders",
    "458": "research",
    "536": "weekly",
    "786": "research",
}

_FAMILY_BY_TYPE: dict[str, str] = {
    "daily": "jin10_gold_report",
    "weekly": "jin10_gold_weekly_report",
    "fx": "jin10_fx_report",
    "oil": "jin10_oil_report",
    "positioning": "jin10_positioning_report",
    "technical_levels": "jin10_technical_levels_report",
    "pending_orders": "jin10_pending_orders_report",
    "market_observation": "jin10_market_observation_report",
    "research": "jin10_research_report",
}

_ASSET_SCOPE_BY_TYPE: dict[str, str] = {
    "daily": "XAUUSD",
    "weekly": "XAUUSD",
    "fx": "FX",
    "oil": "OIL",
    "positioning": "cross_asset_positioning",
    "technical_levels": "XAUUSD",
    "pending_orders": "XAUUSD",
    "market_observation": "cross_asset",
    "research": "cross_asset",
}

_NON_DAILY_GOLD_ARTICLE_MARKERS = ("黄金头条", "投行金评", "财料", "一周热榜精选")
_MARKET_OBSERVATION_MARKERS = ("VIP每日市场观察", "每日市场观察", "市场赔率表", "市场赔率数据表")
_MASTER_REVIEW_MARKERS = ("周末·大师复盘", "大师复盘", "master_review")
_CLASSIFICATION_LABELS: tuple[tuple[str, str], ...] = (
    ("黄金投资者周报", "weekly"),
    ("每日金银报告", "daily"),
    ("黄金周报", "weekly"),
    ("持仓报告", "positioning"),
    ("点位报告", "technical_levels"),
    ("挂单报告", "pending_orders"),
    ("外汇报告", "fx"),
    ("原油报告", "oil"),
)


def report_type_by_category() -> dict[str, str]:
    return dict(_REPORT_TYPE_BY_CODE)


def category_name_by_code() -> dict[str, str]:
    return dict(_CATEGORY_BY_CODE)


def classify_jin10_report(
    *,
    category_code: str | None = None,
    category: str | None = None,
    title: str | None = None,
    report_type: str | None = None,
) -> Jin10ReportClassification:
    code = str(category_code or "").strip()
    text = f"{category or ''} {title or ''}".strip()
    explicit_type = str(report_type or "").strip().lower()
    original_category = str(category or "").strip()

    if not code:
        code = _infer_category_code(text=text, explicit_type=explicit_type)

    resolved_type = _resolve_report_type(code=code, text=text, explicit_type=explicit_type)
    if resolved_type == "market_observation":
        resolved_category = "市场观察"
    elif code == "786" or _looks_like_master_review(text=text):
        resolved_category = "周末·大师复盘"
    elif resolved_type == "research" and original_category:
        resolved_category = original_category
    elif original_category == "报告" and any(marker in text for marker in _NON_DAILY_GOLD_ARTICLE_MARKERS):
        resolved_category = "报告"
    else:
        resolved_category = _CATEGORY_BY_CODE.get(code) or _category_for_type(resolved_type) or (category or "报告")
    return Jin10ReportClassification(
        category_code=code or _infer_category_code(text=resolved_category, explicit_type=resolved_type),
        category=resolved_category,
        report_type=resolved_type,
        report_family=_FAMILY_BY_TYPE.get(resolved_type, f"jin10_{resolved_type}_report"),
        asset_scope=_ASSET_SCOPE_BY_TYPE.get(resolved_type, "cross_asset"),
        series=_series_for_category(code=code, text=text),
        subcategory=_subcategory_for_category(code=code, text=text),
    )


def resolve_jin10_report_identity(
    *,
    category_code: str | None = None,
    category: str | None = None,
    title: str | None = None,
    report_type: str | None = None,
    cover_text: str | None = None,
) -> dict[str, Any]:
    """Resolve formal report identity without treating the issue theme as its family."""

    listing = classify_jin10_report(
        category_code=category_code,
        category=category,
        title=title,
        report_type=report_type,
    )
    cover_label, cover_type = _classification_from_cover(cover_text)
    resolved_type = cover_type or listing.report_type
    verification_status = "confirmed"
    if str(cover_text or "").strip() and not cover_type:
        verification_status = "needs_review"
    elif cover_type and cover_type != listing.report_type:
        verification_status = "needs_review"

    classification_label = cover_label or _classification_label_for_listing(listing)
    report_family = (
        "jin10_weekly_visual"
        if resolved_type == "weekly"
        else "jin10_daily_visual"
        if resolved_type == "daily"
        else _FAMILY_BY_TYPE.get(resolved_type, f"jin10_{resolved_type}_report")
    )
    evidence: list[dict[str, Any]] = [
        {
            "source": "listing",
            "category_code": listing.category_code,
            "category": listing.category,
            "report_type": listing.report_type,
            "title": _clean_report_theme(title),
        }
    ]
    if str(cover_text or "").strip():
        evidence.append(
            {
                "source": "cover",
                "classification_label": cover_label,
                "report_type": cover_type,
                "recognized_text": str(cover_text).strip(),
            }
        )

    return {
        "report_type": resolved_type,
        "report_family": report_family,
        "classification_label": classification_label,
        "report_theme": _clean_report_theme(title),
        "verification_status": verification_status,
        "evidence": evidence,
    }


def _classification_from_cover(cover_text: str | None) -> tuple[str, str]:
    compact = re.sub(r"\s+", "", str(cover_text or ""))
    for label, report_type in _CLASSIFICATION_LABELS:
        if label in compact:
            return label, report_type
    return "", ""


def _classification_label_for_listing(classification: Jin10ReportClassification) -> str:
    if classification.report_type == "weekly":
        return "黄金投资者周报"
    return classification.category


def _clean_report_theme(title: str | None) -> str:
    value = str(title or "").strip()
    return re.sub(r"\s*-\s*金十数据VIP\s*$", "", value).strip()


def _infer_category_code(*, text: str, explicit_type: str) -> str:
    if _looks_like_market_observation(text=text, explicit_type=explicit_type):
        return "458"
    if _looks_like_master_review(text=text):
        return "786"
    if any(marker in text for marker in _NON_DAILY_GOLD_ARTICLE_MARKERS):
        return "458"
    if "外汇报告" in text or explicit_type == "fx":
        return "271"
    if "原油报告" in text or explicit_type == "oil":
        return "272"
    if "持仓报告" in text or explicit_type == "positioning":
        return "274"
    if "点位报告" in text or explicit_type == "technical_levels":
        return "301"
    if "挂单报告" in text or explicit_type == "pending_orders":
        return "380"
    if "黄金周报" in text or explicit_type == "weekly" or "一周热榜精选" in text:
        return "536"
    if "金银报告" in text or explicit_type == "daily":
        return "270"
    return ""


def _resolve_report_type(*, code: str, text: str, explicit_type: str) -> str:
    if _looks_like_market_observation(text=text, explicit_type=explicit_type):
        return "market_observation"
    if any(marker in text for marker in _NON_DAILY_GOLD_ARTICLE_MARKERS):
        return "research"
    return _REPORT_TYPE_BY_CODE.get(code) or _normalize_report_type(explicit_type) or "daily"


def _looks_like_market_observation(*, text: str, explicit_type: str) -> bool:
    return explicit_type == "market_observation" or any(marker in text for marker in _MARKET_OBSERVATION_MARKERS)


def _looks_like_master_review(*, text: str) -> bool:
    return any(marker in text for marker in _MASTER_REVIEW_MARKERS)


def _normalize_report_type(value: str) -> str:
    if value in set(_FAMILY_BY_TYPE):
        return value
    return ""


def _category_for_type(report_type: str) -> str:
    if report_type == "market_observation":
        return "市场观察"
    for code, value in _REPORT_TYPE_BY_CODE.items():
        if value == report_type:
            return _CATEGORY_BY_CODE.get(code, "")
    return ""


def _series_for_category(*, code: str, text: str) -> str:
    if code == "786" or _looks_like_master_review(text=text):
        return "master_review"
    return ""


def _subcategory_for_category(*, code: str, text: str) -> str:
    if code == "786" or _looks_like_master_review(text=text):
        return "master_review"
    return ""
