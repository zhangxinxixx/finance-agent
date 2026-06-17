from __future__ import annotations

import json
from pathlib import Path

from apps.collectors.news.base import RawNewsItem
from apps.features.news.daily_analysis_triggers import (
    archive_daily_analysis_triggers,
    build_daily_analysis_triggers,
)
from apps.features.news.event_candidates import build_event_candidates
from apps.features.news.impact_classifier import build_impact_assessments


def _jin10_feishu_item(
    *,
    title: str,
    url: str = "https://xnews.jin10.com/details/trigger",
    event_type: str = "fed_hawkish",
    relevance_decision: str = "high_value",
    relevance_score: float = 0.86,
) -> RawNewsItem:
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
        event_type=event_type,
        verification_status="single_source",
        duplicate_key="news:jin10_feishu:daily-trigger",
        raw_payload={
            "ingest_channel": "feishu_chat_pull",
            "message_id": "om_trigger",
            "detail_urls": [url],
            "relevance_decision": {
                "decision": relevance_decision,
                "score": relevance_score,
                "asset_tags": ["XAUUSD", "DXY", "US02Y", "US10Y"],
                "topic_tags": ["gold", "macro", "rates"],
                "reasons": ["rates_macro_path", "gold_direct", "detail_link_present"],
            },
            "source_refs": [{"source": "jin10_feishu", "source_ref": "jin10_feishu:oc_jin10:om_trigger"}],
        },
    )


def test_jin10_gold_fed_inflation_push_builds_daily_analysis_trigger() -> None:
    item = _jin10_feishu_item(
        title=(
            "能源推升通胀数据，美联储已难兑现宽松。黄金乐观情绪被清除，短期动量仍为负。"
            "多头交易仍需等新的催化剂，收复4500是第一道槛。"
        )
    )
    event_bundle = build_event_candidates([item], as_of="2026-06-11T12:05:00+00:00")
    assessments = build_impact_assessments(event_bundle.event_candidates, as_of="2026-06-11T12:05:00+00:00")

    bundle = build_daily_analysis_triggers(
        event_bundle=event_bundle,
        impact_assessments=assessments,
        as_of="2026-06-11T12:05:00+00:00",
    )

    assert len(bundle.triggers) == 1
    trigger = bundle.triggers[0]
    assert trigger.trigger_type == "jin10_daily_analysis"
    assert trigger.priority == "high"
    assert trigger.source_key == "jin10_feishu"
    assert trigger.source_url == "https://xnews.jin10.com/details/trigger"
    assert trigger.event_type == "fed_hawkish"
    assert trigger.impact_path == "strong_data_to_higher_for_longer"
    assert trigger.reason_codes >= {
        "gold_daily_topic",
        "fed_inflation_path",
        "energy_inflation_path",
        "key_level_or_momentum",
        "detail_link_present",
        "high_value_relevance",
    }
    assert trigger.suggested_actions == [
        "fetch_detail_page",
        "run_browser_profile_fallback_if_access_limited",
        "run_jin10_daily_analysis",
        "keep_single_source_verification_flag",
    ]
    assert trigger.data_quality["verification_status"] == "single_source"


def test_non_gold_jin10_message_does_not_trigger_daily_analysis() -> None:
    item = _jin10_feishu_item(
        title="欧佩克月报：2027年全球原油需求增速预测为173万桶/日。",
        event_type="oil_supply_shock",
        relevance_decision="candidate",
        relevance_score=0.48,
    )
    event_bundle = build_event_candidates([item], as_of="2026-06-11T12:05:00+00:00")
    assessments = build_impact_assessments(event_bundle.event_candidates, as_of="2026-06-11T12:05:00+00:00")

    bundle = build_daily_analysis_triggers(
        event_bundle=event_bundle,
        impact_assessments=assessments,
        as_of="2026-06-11T12:05:00+00:00",
    )

    assert bundle.triggers == []
    assert bundle.data_quality["rejected_event_count"] == 1


def test_archive_daily_analysis_triggers_writes_feature_artifact(tmp_path: Path) -> None:
    event_bundle = build_event_candidates(
        [
            _jin10_feishu_item(
                title=(
                    "能源推升通胀数据，美联储已难兑现宽松。黄金乐观情绪被清除，短期动量仍为负。"
                    "多头交易仍需等新的催化剂，收复4500是第一道槛。"
                )
            )
        ],
        as_of="2026-06-11T12:05:00+00:00",
    )
    bundle = build_daily_analysis_triggers(
        event_bundle=event_bundle,
        impact_assessments=build_impact_assessments(event_bundle.event_candidates),
        as_of="2026-06-11T12:05:00+00:00",
    )

    artifact_path = archive_daily_analysis_triggers(
        storage_root=tmp_path,
        retrieved_date="2026-06-11",
        run_id="run-news",
        bundle=bundle,
    )

    assert artifact_path == "features/news/2026-06-11/run-news/daily_analysis_triggers.json"
    payload = json.loads((tmp_path / artifact_path).read_text(encoding="utf-8"))
    assert payload["trigger_count"] == 1
    assert payload["triggers"][0]["trigger_type"] == "jin10_daily_analysis"
