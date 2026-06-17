from __future__ import annotations

import json
from pathlib import Path

from apps.collectors.news.base import RawNewsItem
from apps.collectors.news.jin10_detail_fetcher import Jin10DetailFetchResult
from apps.features.news.jin10_article_briefs import archive_jin10_article_briefs, build_jin10_article_briefs


def _item(title: str, *, url: str = "https://xnews.jin10.com/details/221688") -> RawNewsItem:
    return RawNewsItem(
        source_key="jin10_feishu",
        source_name="Jin10 Feishu Chat Pull",
        source_type="supplemental",
        feed_key="oc_jin10",
        title=title,
        url=url,
        domain="xnews.jin10.com",
        published_at="2026-06-11T12:00:00+00:00",
        fetched_at="2026-06-11T12:00:01+00:00",
        summary=title,
        source_country="CN",
        source_language="zh-CN",
        event_type="fed_hawkish",
        verification_status="single_source",
        duplicate_key=f"news:jin10_feishu:{title}",
        raw_payload={
            "relevance_decision": {
                "decision": "high_value",
                "score": 0.86,
                "asset_tags": ["XAUUSD", "DXY", "US02Y", "US10Y"],
                "topic_tags": ["gold", "macro", "rates"],
            },
            "source_refs": [{"source": "jin10_feishu", "source_ref": "jin10_feishu:oc_jin10:om_1"}],
        },
    )


def _detail(
    *,
    url: str = "https://xnews.jin10.com/details/221688",
    access_status: str = "readable",
    title: str = "黄金技术破位标志着行情拐点，新的多空绞肉机已启动-市场参考-金十数据",
    text: str = "",
) -> Jin10DetailFetchResult:
    return Jin10DetailFetchResult(
        detail_url=url,
        final_url=url,
        status="fetched",
        access_status=access_status,
        content_type="text/html; charset=utf-8",
        title=title,
        raw_text=text
        or (
            "黄金技术破位标志着行情拐点。能源推升通胀数据，美联储已难兑现宽松。"
            "黄金乐观情绪被清除，短期动量仍为负。多头交易仍需等新的催化剂，收复4500是第一道槛。"
        ),
        raw_html_path="raw/news/jin10_detail_pages/2026-06-11/detail.html",
        parsed_path="parsed/news/jin10_detail_pages/2026-06-11/detail.json",
        image_assets=[],
        image_insights=[],
        fetched_at="2026-06-11T12:00:02+00:00",
    )


def test_build_jin10_article_briefs_classifies_gold_macro_market_reference() -> None:
    bundle = build_jin10_article_briefs(
        items_with_details=[(_item("能源推升通胀数据，美联储已难兑现宽松。黄金乐观情绪被清除，收复4500是第一道槛。"), _detail())],
        as_of="2026-06-11T12:05:00+00:00",
    )

    assert len(bundle.briefs) == 1
    assert bundle.data_quality["display_bucket_counts"] == {"重点分析": 1}
    brief = bundle.briefs[0]
    assert brief.article_class == "gold_macro_market_reference"
    assert brief.display_bucket == "重点分析"
    assert brief.access_status == "readable"
    assert brief.headline.startswith("黄金技术破位")
    assert "能源推升通胀数据" in brief.original_excerpt
    assert brief.key_points[:3] == [
        "黄金技术破位标志着行情拐点",
        "能源推升通胀数据，美联储已难兑现宽松",
        "黄金乐观情绪被清除，短期动量仍为负",
    ]
    assert "利率/通胀压力" in brief.analysis_summary
    assert "XAUUSD" in brief.asset_tags
    assert brief.suggested_actions == ["show_in_news_flash", "link_detail_page", "queue_daily_analysis"]


def test_build_jin10_article_briefs_exposes_xnews_public_detail_metadata() -> None:
    detail = {
        **_detail().to_dict(),
        "source_key": "jin10_xnews_public",
        "access_method": "http_document",
        "image_assets": [
            {"path": "raw/news/jin10_detail_pages/2026-06-11/images/01-chart.png", "vlm_eligible": True},
            {"path": "raw/news/jin10_detail_pages/2026-06-11/images/02-logo.png", "vlm_eligible": False},
        ],
    }
    bundle = build_jin10_article_briefs(
        items_with_details=[(_item("黄金动量仍为负，收复4500是第一道槛。"), detail)],
        as_of="2026-06-11T12:05:00+00:00",
    )

    brief = bundle.briefs[0]
    assert brief.detail_artifacts["image_asset_count"] == 2
    assert brief.detail_artifacts["vlm_eligible_image_count"] == 1
    assert brief.data_quality["source_key"] == "jin10_xnews_public"
    assert brief.data_quality["access_method"] == "http_document"
    assert any(ref.get("source_key") == "jin10_xnews_public" for ref in brief.source_refs)


def test_build_jin10_article_briefs_marks_vip_locked_summary() -> None:
    bundle = build_jin10_article_briefs(
        items_with_details=[
            (
                _item("黄金跌破200日均线后，市场目光转向关键回撤位。"),
                _detail(access_status="vip_locked", text="黄金跌破200日均线后，市场目光转向关键回撤位。钻石VIP专享文章 解锁文章"),
            )
        ],
        as_of="2026-06-11T12:05:00+00:00",
    )

    brief = bundle.briefs[0]
    assert brief.article_class == "vip_market_reference"
    assert brief.display_bucket == "VIP预览"
    assert brief.data_quality["access_status"] == "vip_locked"
    assert "需要金十 VIP 登录态" in brief.analysis_summary
    assert brief.suggested_actions == ["show_in_news_flash", "link_detail_page", "run_browser_profile_fallback"]


def test_build_jin10_article_briefs_marks_js_required_without_using_shell_text() -> None:
    bundle = build_jin10_article_briefs(
        items_with_details=[
            (
                _item("特朗普宣布1亿桶原油入场，华尔街却说快没油了。", url="https://cdn.jin10.com/vip_column/index.html#/detail?id=1"),
                _detail(
                    url="https://cdn.jin10.com/vip_column/index.html#/detail?id=1",
                    access_status="javascript_required",
                    title="We're sorry but 投资者心理学 doesn't work properly without JavaScript enabled.",
                    text="We're sorry but 投资者心理学 doesn't work properly without JavaScript enabled. Please enable it to continue.",
                ),
            )
        ],
        as_of="2026-06-11T12:05:00+00:00",
    )

    brief = bundle.briefs[0]
    assert brief.article_class == "javascript_required"
    assert brief.display_bucket == "待渲染"
    assert brief.original_excerpt == "特朗普宣布1亿桶原油入场，华尔街却说快没油了。"
    assert "JS 渲染" in brief.analysis_summary
    assert brief.suggested_actions == ["show_in_news_flash", "run_browser_profile_fallback"]


def test_build_jin10_article_briefs_uses_readable_browser_text_even_if_vue_shell_marker_remains() -> None:
    rendered_text = (
        "We're sorry but 投资者心理学 doesn't work properly without JavaScript enabled. "
        "用户ID：4087042 用户中心 退出登录 CME突改周末规则，推动黄金更易反转？"
        "正文显示，周末金价新锚需要结合期权、流动性和市场情绪重新评估。"
    )
    bundle = build_jin10_article_briefs(
        items_with_details=[
            (
                _item("为何今年黄金频频出现V型走势？", url="https://cdn.jin10.com/vip_column/index.html#/detail?id=850550"),
                _detail(
                    url="https://cdn.jin10.com/vip_column/index.html#/detail?id=850550",
                    access_status="readable",
                    title="CME突改周末规则，推动黄金更易反转？",
                    text=rendered_text,
                ),
            )
        ],
        as_of="2026-06-11T12:05:00+00:00",
    )

    brief = bundle.briefs[0]
    assert brief.access_status == "readable"
    assert brief.data_quality["used_detail_text"] is True
    assert "周末金价新锚" in brief.original_excerpt


def test_archive_jin10_article_briefs_writes_feature_artifact(tmp_path: Path) -> None:
    bundle = build_jin10_article_briefs(
        items_with_details=[(_item("黄金动量仍为负，收复4500是第一道槛。"), _detail())],
        as_of="2026-06-11T12:05:00+00:00",
    )

    artifact_path = archive_jin10_article_briefs(
        storage_root=tmp_path,
        retrieved_date="2026-06-11",
        run_id="run-news",
        bundle=bundle,
    )

    assert artifact_path == "features/news/2026-06-11/run-news/jin10_article_briefs.json"
    payload = json.loads((tmp_path / artifact_path).read_text(encoding="utf-8"))
    assert payload["brief_count"] == 1
    assert payload["briefs"][0]["display_bucket"] == "重点分析"
