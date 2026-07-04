from __future__ import annotations

import json
from pathlib import Path

from apps.features.news.jin10_web_flash_briefs import (
    archive_jin10_web_flash_briefs,
    build_jin10_web_flash_briefs,
)


def _parsed_payload(
    *,
    status: str = "ok",
    items: list[dict] | None = None,
    quality_flags: dict | None = None,
    raw_artifact_path: str = "raw/news/jin10_web_flash/2026-06-23/index.html",
    parsed_artifact_path: str = "parsed/news/jin10_web_flash/2026-06-23/index.json",
    source_refs: list[dict] | None = None,
) -> dict:
    return {
        "status": status,
        "retrievedDate": "2026-06-23",
        "runId": "run-abc",
        "items": items if items is not None else [],
        "qualityFlags": quality_flags or {},
        "rawArtifactPath": raw_artifact_path,
        "parsedArtifactPath": parsed_artifact_path,
        "sourceRefs": source_refs or [{"source": "jin10_homepage"}],
    }


def _important_item(item_id: str = "jin10_flash_100") -> dict:
    return {
        "itemId": item_id,
        "sourceKey": "jin10_web_important_flash",
        "contentFamily": "web_important_flash.market_flash_important",
        "title": "美联储主席鲍威尔发表重要讲话",
        "summary": "美联储主席鲍威尔今日发表重要讲话，暗示未来可能调整利率政策。",
        "publishedAt": "2026-06-23 10:00",
        "url": "https://flash.jin10.com/detail/100",
        "importanceSource": "jin10_home_important_marker",
        "verificationStatus": "single_source",
        "accessStatus": "readable",
        "tags": ["美联储"],
        "sourceRefs": [{"selector": ".jin-flash-item.flash.is-important", "fetchedAt": "2026-06-23T10:00:00+08:00"}],
        "artifactRefs": [{"rawArtifactPath": "raw/news/jin10_web_flash/2026-06-23/index.html"}],
    }


def _vip_item(item_id: str = "jin10_flash_200") -> dict:
    return {
        "itemId": item_id,
        "sourceKey": "jin10_web_vip_flash",
        "contentFamily": "web_vip_flash.vip_macro_flash",
        "title": "独家：央行黄金储备数据曝光",
        "summary": "据知情人士透露，某国央行近期大幅增持黄金储备。",
        "publishedAt": "2026-06-23 11:00",
        "url": "https://flash.jin10.com/detail/200",
        "importanceSource": "jin10_vip_marker",
        "verificationStatus": "report_derived",
        "accessStatus": "readable",
        "tags": ["黄金"],
        "sourceRefs": [{"selector": ".jin-flash-item.flash.is-vip", "fetchedAt": "2026-06-23T10:00:00+08:00"}],
        "artifactRefs": [],
    }


def _vip_gold_item(item_id: str = "jin10_flash_201") -> dict:
    item = _vip_item(item_id=item_id)
    item.update(
        {
            "contentFamily": "web_vip_flash.vip_gold_silver_flash",
            "title": "现货黄金关键支撑位守住后反弹",
            "summary": "金价围绕4000美元关口反复测试，白银同步走高。",
            "tags": ["黄金"],
        }
    )
    return item


def _geo_risk_item(item_id: str = "jin10_flash_101") -> dict:
    item = _important_item(item_id=item_id)
    item.update(
        {
            "contentFamily": "web_important_flash.geo_risk_flash",
            "title": "伊朗称将回应以色列袭击，红海航运风险升温",
            "tags": ["地缘"],
        }
    )
    return item


def _report_article_item(item_id: str = "jin10_flash_102") -> dict:
    item = _important_item(item_id=item_id)
    item.update(
        {
            "contentFamily": "web_important_flash.report_article_flash",
            "title": "金十图示：2026年06月24日黄金ETF持仓报告",
            "imageUrls": ["https://img.jin10.com/mp/26/06/example.jpg/pcover"],
            "linkedUrls": [],
        }
    )
    return item


def _vip_report_article_item(item_id: str = "jin10_flash_202") -> dict:
    item = _vip_item(item_id=item_id)
    item.update(
        {
            "contentFamily": "web_vip_flash.vip_report_article",
            "title": "投资经理认为，黄金大部分下行空间已被市场定价",
            "linkedUrls": ["https://www.tradinghero.com/?symbol=XAUUSD.GOODS"],
            "imageUrls": [],
        }
    )
    return item


def _top_item(item_id: str = "jin10_flash_300") -> dict:
    return {
        "itemId": item_id,
        "sourceKey": "jin10_web_important_flash",
        "contentFamily": "web_important_flash.important_news_top",
        "title": "今日重大财经事件一览",
        "summary": "",
        "publishedAt": "2026-06-23 09:00",
        "url": "https://flash.jin10.com/detail/300",
        "importanceSource": "jin10_home_top_list",
        "verificationStatus": "single_source",
        "accessStatus": "readable",
        "tags": [],
        "sourceRefs": [{"selector": ".flash-top-list__item", "fetchedAt": "2026-06-23T10:00:00+08:00"}],
        "artifactRefs": [],
    }


def _unknown_family_item(item_id: str = "jin10_flash_999") -> dict:
    return {
        "itemId": item_id,
        "sourceKey": "jin10_web_important_flash",
        "contentFamily": "web_unknown.something_new",
        "title": "未知类型快讯",
        "summary": "这是一条未知类型的快讯。",
        "publishedAt": "2026-06-23 12:00",
        "url": "https://flash.jin10.com/detail/999",
        "importanceSource": "jin10_home_important_marker",
        "verificationStatus": "single_source",
        "accessStatus": "readable",
        "tags": [],
        "sourceRefs": [],
        "artifactRefs": [],
    }


# ---- Test 1: mixed items, counts, display buckets, priority, source/verification/access ----


def test_build_mixed_items_assert_counts_buckets_and_statuses() -> None:
    payload = _parsed_payload(
        items=[
            _important_item(),
            _vip_item(),
            _top_item(),
            _unknown_family_item(),
            _vip_gold_item(),
            _geo_risk_item(),
            _report_article_item(),
            _vip_report_article_item(),
        ]
    )
    bundle = build_jin10_web_flash_briefs(parsed_payload=payload, as_of="2026-06-23T12:05:00+08:00")

    assert bundle.status == "ok"
    assert bundle.brief_count == 8

    briefs_by_item_id = {b.item_id: b for b in bundle.briefs}

    # important -> display bucket 重要新闻Top (per content_family map: market_flash_important -> 首页重要快讯)
    important = briefs_by_item_id["jin10_flash_100"]
    assert important.display_bucket == "首页重要快讯"
    assert important.priority_bucket == "P0"
    assert important.verification_status == "single_source"
    assert important.access_status == "readable"
    assert important.importance_source == "jin10_home_important_marker"

    # vip
    vip = briefs_by_item_id["jin10_flash_200"]
    assert vip.display_bucket == "VIP快讯"
    assert vip.priority_bucket == "P0"
    assert vip.verification_status == "report_derived"

    # top
    top = briefs_by_item_id["jin10_flash_300"]
    assert top.display_bucket == "重要新闻Top"
    assert top.priority_bucket == "P0"

    # fine-grained categories
    vip_gold = briefs_by_item_id["jin10_flash_201"]
    assert vip_gold.display_bucket == "VIP贵金属快讯"
    assert vip_gold.priority_bucket == "P0"

    geo_risk = briefs_by_item_id["jin10_flash_101"]
    assert geo_risk.display_bucket == "地缘风险快讯"
    assert geo_risk.priority_bucket == "P0"

    report_article = briefs_by_item_id["jin10_flash_102"]
    assert report_article.display_bucket == "图文/报告快讯"
    assert report_article.priority_bucket == "P0"
    assert report_article.data_quality["image_count"] == 1
    assert report_article.data_quality["linked_url_count"] == 0

    vip_report_article = briefs_by_item_id["jin10_flash_202"]
    assert vip_report_article.display_bucket == "VIP报告/文章"
    assert vip_report_article.priority_bucket == "P0"
    assert vip_report_article.data_quality["image_count"] == 0
    assert vip_report_article.data_quality["linked_url_count"] == 1

    # unknown
    unknown = briefs_by_item_id["jin10_flash_999"]
    assert unknown.display_bucket == "待复核"
    assert unknown.priority_bucket == "P1"

    # data_quality counts
    dq = bundle.data_quality
    assert dq["input_count"] == 8
    assert dq["brief_count"] == 8
    assert dq["priority_bucket_counts"]["P0"] == 7
    assert dq["priority_bucket_counts"]["P1"] == 1
    assert dq["verification_status_counts"]["single_source"] == 5
    assert dq["verification_status_counts"]["report_derived"] == 3
    assert dq["access_status_counts"]["readable"] == 8
    assert dq["content_family_counts"]["web_important_flash.market_flash_important"] == 1
    assert dq["content_family_counts"]["web_vip_flash.vip_macro_flash"] == 1
    assert dq["content_family_counts"]["web_vip_flash.vip_gold_silver_flash"] == 1
    assert dq["content_family_counts"]["web_important_flash.geo_risk_flash"] == 1
    assert dq["content_family_counts"]["web_important_flash.report_article_flash"] == 1
    assert dq["content_family_counts"]["web_vip_flash.vip_report_article"] == 1
    assert dq["content_format_counts"]["report_article"] == 2
    assert dq["content_format_counts"]["flash"] == 6


# ---- Test 2: dedupe by itemId ----


def test_dedupe_by_item_id_produces_one_brief() -> None:
    duplicate = _important_item(item_id="jin10_flash_100")
    payload = _parsed_payload(items=[_important_item(), duplicate, _vip_item()])
    bundle = build_jin10_web_flash_briefs(parsed_payload=payload, as_of="2026-06-23T12:05:00+08:00")

    assert bundle.brief_count == 2
    item_ids = [b.item_id for b in bundle.briefs]
    assert item_ids.count("jin10_flash_100") == 1
    assert bundle.data_quality["input_count"] == 3
    assert bundle.data_quality["source_key_counts"] == {
        "jin10_web_important_flash": 1,
        "jin10_web_vip_flash": 1,
    }
    assert bundle.data_quality["content_family_counts"] == {
        "web_important_flash.market_flash_important": 1,
        "web_vip_flash.vip_macro_flash": 1,
    }


# ---- Test 3: schema_changed / unavailable produces no briefs ----


def test_schema_changed_produces_no_briefs_preserves_status_and_flags() -> None:
    payload = _parsed_payload(
        status="schema_changed",
        items=[],
        quality_flags={"schema_changed": True},
    )
    bundle = build_jin10_web_flash_briefs(parsed_payload=payload, as_of="2026-06-23T12:05:00+08:00")

    assert bundle.status == "schema_changed"
    assert bundle.brief_count == 0
    assert bundle.quality_flags == {"schema_changed": True}
    assert bundle.data_quality["input_count"] == 0
    assert bundle.data_quality["brief_count"] == 0


def test_unavailable_produces_no_briefs() -> None:
    payload = _parsed_payload(
        status="unavailable",
        items=[],
        quality_flags={"unavailable": True, "reason": "blocked"},
    )
    bundle = build_jin10_web_flash_briefs(parsed_payload=payload, as_of="2026-06-23T12:05:00+08:00")

    assert bundle.status == "unavailable"
    assert bundle.brief_count == 0
    assert bundle.quality_flags["reason"] == "blocked"


# ---- Test 4: archive writes exact path and wrapper JSON ----


def test_archive_writes_exact_path_and_wrapper_json(tmp_path: Path) -> None:
    payload = _parsed_payload(items=[_important_item()])
    bundle = build_jin10_web_flash_briefs(parsed_payload=payload, as_of="2026-06-23T12:05:00+08:00")

    artifact_path = archive_jin10_web_flash_briefs(
        storage_root=tmp_path,
        retrieved_date="2026-06-23",
        run_id="run-abc",
        bundle=bundle,
    )

    assert artifact_path == "features/news/2026-06-23/run-abc/jin10_web_flash_briefs.json"

    payload_json = json.loads((tmp_path / artifact_path).read_text(encoding="utf-8"))
    assert payload_json["retrieved_date"] == "2026-06-23"
    assert payload_json["run_id"] == "run-abc"
    inner = payload_json["jin10_web_flash_briefs"]
    assert inner["brief_count"] == 1
    assert inner["briefs"][0]["display_bucket"] == "首页重要快讯"
