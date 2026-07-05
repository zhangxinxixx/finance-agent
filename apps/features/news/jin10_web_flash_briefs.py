from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

RULE_VERSION = "jin10-web-flash-briefs-v1"

_DISPLAY_BUCKET_MAP: dict[str, str] = {
    "web_important_flash.important_news_top": "重要新闻Top",
    "web_important_flash.market_flash_important": "首页重要快讯",
    "web_important_flash.macro_policy_flash": "宏观政策快讯",
    "web_important_flash.geo_risk_flash": "地缘风险快讯",
    "web_important_flash.market_move_flash": "市场异动快讯",
    "web_important_flash.report_article_flash": "图文/报告快讯",
    "web_vip_flash.vip_macro_flash": "VIP快讯",
    "web_vip_flash.vip_gold_silver_flash": "VIP贵金属快讯",
    "web_vip_flash.vip_geo_oil_flash": "VIP地缘原油快讯",
    "web_vip_flash.vip_institution_view": "VIP机构观点",
    "web_vip_flash.vip_technical_flash": "VIP技术位快讯",
    "web_vip_flash.vip_report_article": "VIP报告/文章",
}
_DISPLAY_BUCKET_UNKNOWN = "待复核"

_PRIORITY_MAP: dict[str, str] = {
    "重要新闻Top": "P0",
    "首页重要快讯": "P0",
    "宏观政策快讯": "P0",
    "地缘风险快讯": "P0",
    "市场异动快讯": "P0",
    "图文/报告快讯": "P0",
    "VIP快讯": "P0",
    "VIP贵金属快讯": "P0",
    "VIP地缘原油快讯": "P0",
    "VIP机构观点": "P1",
    "VIP技术位快讯": "P1",
    "VIP报告/文章": "P0",
}


@dataclass(frozen=True)
class Jin10WebFlashBrief:
    brief_id: str
    item_id: str
    source_key: str
    content_family: str
    display_bucket: str
    headline: str
    summary: str
    published_at: str
    url: str
    priority_bucket: str
    importance_source: str
    verification_status: str
    access_status: str
    tags: list[str]
    source_refs: list[dict[str, Any]]
    artifact_refs: list[dict[str, Any]]
    created_at: str
    data_quality: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Jin10WebFlashBriefBundle:
    as_of: str
    rule_version: str
    status: str
    briefs: list[Jin10WebFlashBrief]
    quality_flags: dict[str, Any]
    source_refs: list[dict[str, Any]]
    artifact_refs: list[dict[str, Any]]
    data_quality: dict[str, Any] = field(default_factory=dict)

    @property
    def brief_count(self) -> int:
        return len(self.briefs)

    def to_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of,
            "rule_version": self.rule_version,
            "status": self.status,
            "brief_count": self.brief_count,
            "briefs": [brief.to_dict() for brief in self.briefs],
            "data_quality": self.data_quality,
            "source_refs": self.source_refs,
            "artifact_refs": self.artifact_refs,
            "quality_flags": self.quality_flags,
        }


def build_jin10_web_flash_briefs(
    *,
    parsed_payload: dict,
    as_of: str,
) -> Jin10WebFlashBriefBundle:
    status = str(parsed_payload.get("status", ""))
    quality_flags = dict(parsed_payload.get("qualityFlags") or {})
    source_refs = list(parsed_payload.get("sourceRefs") or [])

    raw_artifact = str(parsed_payload.get("rawArtifactPath") or "")
    parsed_artifact = str(parsed_payload.get("parsedArtifactPath") or "")
    artifact_refs: list[dict[str, Any]] = []
    if raw_artifact:
        artifact_refs.append({"rawArtifactPath": raw_artifact})
    if parsed_artifact:
        artifact_refs.append({"parsedArtifactPath": parsed_artifact})

    if status in ("schema_changed", "unavailable"):
        return Jin10WebFlashBriefBundle(
            as_of=as_of,
            rule_version=RULE_VERSION,
            status=status,
            briefs=[],
            quality_flags=quality_flags,
            source_refs=source_refs,
            artifact_refs=artifact_refs,
            data_quality=_empty_data_quality(parsed_payload),
        )

    raw_items = list(parsed_payload.get("items") or [])
    seen: set[str] = set()
    briefs: list[Jin10WebFlashBrief] = []
    for item in raw_items:
        item_id = str(item.get("itemId") or "")
        if not item_id or item_id in seen:
            continue
        seen.add(item_id)
        briefs.append(_build_brief(item=item, as_of=as_of))

    briefs.sort(key=lambda b: (0 if b.priority_bucket == "P0" else 1, b.headline))

    return Jin10WebFlashBriefBundle(
        as_of=as_of,
        rule_version=RULE_VERSION,
        status=status,
        briefs=briefs,
        quality_flags=quality_flags,
        source_refs=source_refs,
        artifact_refs=artifact_refs,
        data_quality=_build_data_quality(raw_items, briefs, parsed_payload),
    )


def archive_jin10_web_flash_briefs(
    *,
    storage_root: Path,
    retrieved_date: str,
    run_id: str,
    bundle: Jin10WebFlashBriefBundle,
) -> str:
    target = storage_root / "features" / "news" / retrieved_date / run_id / "jin10_web_flash_briefs.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    wrapper = {
        "retrieved_date": retrieved_date,
        "run_id": run_id,
        "jin10_web_flash_briefs": bundle.to_dict(),
    }
    target.write_text(json.dumps(wrapper, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target.relative_to(storage_root).as_posix()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_brief(*, item: dict[str, Any], as_of: str) -> Jin10WebFlashBrief:
    content_family = str(item.get("contentFamily") or "")
    display_bucket = _classify_display_bucket(content_family)
    item_id = str(item.get("itemId") or "")
    linked_urls = [str(value) for value in item.get("linkedUrls") or [] if str(value).strip()]
    image_urls = [str(value) for value in item.get("imageUrls") or [] if str(value).strip()]
    content_format = _classify_content_format(content_family, linked_urls, image_urls)
    return Jin10WebFlashBrief(
        brief_id=_brief_id(item_id),
        item_id=item_id,
        source_key=str(item.get("sourceKey") or ""),
        content_family=content_family,
        display_bucket=display_bucket,
        headline=str(item.get("title") or "").strip(),
        summary=str(item.get("summary") or "").strip(),
        published_at=str(item.get("publishedAt") or ""),
        url=str(item.get("url") or ""),
        priority_bucket=_PRIORITY_MAP.get(display_bucket, "P1"),
        importance_source=str(item.get("importanceSource") or ""),
        verification_status=str(item.get("verificationStatus") or ""),
        access_status=str(item.get("accessStatus") or ""),
        tags=list(item.get("tags") or []),
        source_refs=list(item.get("sourceRefs") or []),
        artifact_refs=list(item.get("artifactRefs") or []),
        created_at=as_of,
        data_quality={
            "source_key": str(item.get("sourceKey") or ""),
            "verification_status": str(item.get("verificationStatus") or ""),
            "access_status": str(item.get("accessStatus") or ""),
            "content_format": content_format,
            "image_count": len(image_urls),
            "linked_url_count": len(linked_urls),
            "image_urls": image_urls,
            "linked_urls": linked_urls,
        },
    )


def _classify_display_bucket(content_family: str) -> str:
    return _DISPLAY_BUCKET_MAP.get(content_family, _DISPLAY_BUCKET_UNKNOWN)


def _classify_content_format(content_family: str, linked_urls: list[str], image_urls: list[str]) -> str:
    if content_family.endswith("report_article_flash") or content_family.endswith("vip_report_article"):
        return "report_article"
    if linked_urls or image_urls:
        return "report_article"
    return "flash"


def _brief_id(item_id: str) -> str:
    digest = hashlib.sha256(item_id.encode("utf-8")).hexdigest()[:16]
    return f"jin10_web_brief:{digest}"


def _empty_data_quality(parsed_payload: dict) -> dict[str, Any]:
    return {
        "input_count": 0,
        "brief_count": 0,
        "source_key_counts": {},
        "content_family_counts": {},
        "verification_status_counts": {},
        "access_status_counts": {},
        "priority_bucket_counts": {},
        "content_format_counts": {},
    }


def _build_data_quality(
    raw_items: list[dict[str, Any]],
    briefs: list[Jin10WebFlashBrief],
    parsed_payload: dict,
) -> dict[str, Any]:
    return {
        "input_count": len(raw_items),
        "brief_count": len(briefs),
        "source_key_counts": _count_by(briefs, "source_key"),
        "content_family_counts": _count_by(briefs, "content_family"),
        "verification_status_counts": _count_by(briefs, "verification_status"),
        "access_status_counts": _count_by(briefs, "access_status"),
        "priority_bucket_counts": _count_by(briefs, "priority_bucket"),
        "content_format_counts": _count_data_quality_by(briefs, "content_format"),
    }


def _count_by(briefs: list[Jin10WebFlashBrief], field_name: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for brief in briefs:
        value = str(getattr(brief, field_name))
        counts[value] = counts.get(value, 0) + 1
    return counts


def _count_data_quality_by(briefs: list[Jin10WebFlashBrief], field_name: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for brief in briefs:
        value = str(brief.data_quality.get(field_name) or "")
        if not value:
            continue
        counts[value] = counts.get(value, 0) + 1
    return counts
