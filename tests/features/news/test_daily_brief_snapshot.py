from __future__ import annotations

import json
from pathlib import Path

from apps.features.news.daily_brief_snapshot import (
    archive_daily_brief_input_snapshot,
    build_daily_brief_input_snapshot,
)


def _daily_market_brief(*, confirmed: bool = False, reaction: bool = True) -> dict[str, object]:
    verification_status = "official_confirmed" if confirmed else "single_source"
    event = {
        "event_id": "evt-hormuz",
        "event_type": "hormuz_risk",
        "what_happened": "中东风险推动油价和通胀预期变化",
        "verification_status": verification_status,
        "risk_level": "high",
        "impact_path": "oil_to_inflation_to_rates",
        "gold_impact": "bearish",
        "pricing_status": "partially_priced" if reaction else "unknown",
        "source_refs": [{"source": "reuters", "source_ref": "wire:1", "url": "https://example.com/wire"}],
    }
    return {
        "as_of": "2026-06-12T08:00:00+00:00",
        "market_mainline": {
            "status": "available",
            "summary": "中东风险推动油价和通胀预期变化",
            "primary_event_id": "evt-hormuz",
            "risk_level": "high",
            "verification_status": verification_status,
            "pricing_status": "partially_priced" if reaction else "unknown",
        },
        "confirmed_events": [event] if confirmed else [],
        "candidate_events": [] if confirmed else [event],
        "unconfirmed_risks": [] if confirmed else [event],
        "asset_reactions": [
            {
                "event_id": "evt-hormuz",
                "window": "30m",
                "asset": "WTI",
                "direction": "up",
                "pct_change": 1.2,
                "threshold_hit": True,
                "pricing_status": "partially_priced",
            }
        ]
        if reaction
        else [],
        "report_inputs": {
            "news_highlights": [event],
            "watchlist": [event],
            "risk_points": ["中东风险 | high | oil_to_inflation_to_rates"],
        },
        "source_refs": [{"source": "reuters", "source_ref": "wire:1", "url": "https://example.com/wire"}],
        "warnings": [],
    }


def _trigger(*, priority: str = "high", verification_status: str = "single_source") -> dict[str, object]:
    return {
        "trigger_id": "trigger:jin10:1",
        "priority": priority,
        "status": "queued",
        "source_title": "能源推升通胀数据，美联储已难兑现宽松。黄金动量仍为负。",
        "source_url": "https://xnews.jin10.com/details/221688",
        "source_event_id": "evt-hormuz",
        "impact_path": "oil_to_inflation_to_rates",
        "gold_impact": "bearish",
        "evidence_text": "黄金乐观情绪被清除，收复4500是第一道槛。",
        "asset_tags": ["XAUUSD", "WTI", "US10Y"],
        "topic_tags": ["gold", "rates", "inflation"],
        "source_refs": [{"source": "jin10_feishu", "source_ref": "msg:1"}],
        "data_quality": {
            "trigger_score": 0.88,
            "verification_status": verification_status,
            "source_count": 1,
        },
    }


def _article(*, article_class: str = "gold_macro_market_reference") -> dict[str, object]:
    return {
        "brief_id": "jin10_brief:1",
        "article_class": article_class,
        "display_bucket": "重点分析",
        "headline": "能源推升通胀数据，美联储已难兑现宽松",
        "source_url": "https://xnews.jin10.com/details/221688",
        "final_url": "https://xnews.jin10.com/details/221688",
        "access_status": "readable",
        "original_excerpt": "黄金乐观情绪被清除，短期动量仍为负。多头交易仍需等新的催化剂，收复4500是第一道槛。",
        "key_points": ["黄金乐观情绪被清除", "收复4500是第一道槛"],
        "analysis_summary": "这是一条黄金主线重点分析。",
        "asset_tags": ["XAUUSD", "WTI", "US10Y"],
        "topic_tags": ["gold", "rates", "inflation"],
        "suggested_actions": ["show_in_news_flash", "link_detail_page", "queue_daily_analysis"],
        "source_refs": [
            {"source": "jin10_feishu", "source_ref": "msg:1"},
            {"source": "jin10_feishu", "source_ref": "msg:1"},
        ],
        "detail_artifacts": {"image_asset_count": 2, "vlm_insight_count": 1},
        "data_quality": {"access_status": "readable", "used_detail_text": True},
    }


def test_build_daily_brief_input_snapshot_selects_hybrid_when_news_and_key_article_exist() -> None:
    snapshot = build_daily_brief_input_snapshot(
        retrieved_date="2026-06-12",
        run_id="run-news",
        daily_market_brief=_daily_market_brief(),
        daily_analysis_triggers={"triggers": [_trigger()]},
        jin10_article_briefs={"briefs": [_article()]},
        report_events={"items": []},
        market_reactions=[],
    )

    data = snapshot.to_dict()

    assert data["report_mode"] == "hybrid"
    assert data["should_generate"] is True
    assert data["one_line_inputs"] == [
        "中东风险推动油价和通胀预期变化",
        "能源推升通胀数据，美联储已难兑现宽松。黄金动量仍为负。",
    ]
    assert data["core_events"][0]["event_id"] == "evt-hormuz"
    assert data["core_events"][0]["source_confidence"] == "single_source"
    assert data["key_articles"][0]["headline"] == "能源推升通胀数据，美联储已难兑现宽松"
    assert data["key_articles"][0]["detail_artifacts"]["image_asset_count"] == 2
    assert data["source_refs"] == [
        {"source": "reuters", "source_ref": "wire:1", "url": "https://example.com/wire"},
        {"source": "jin10_feishu", "source_ref": "msg:1"},
    ]
    assert "single_source_verification_required" in data["quality_flags"]


def test_build_daily_brief_input_snapshot_selects_news_driven_for_official_event_or_market_reaction() -> None:
    snapshot = build_daily_brief_input_snapshot(
        retrieved_date="2026-06-12",
        run_id="run-news",
        daily_market_brief=_daily_market_brief(confirmed=True),
        daily_analysis_triggers={"triggers": []},
        jin10_article_briefs={"briefs": []},
        report_events={"items": []},
        market_reactions=[],
    )

    data = snapshot.to_dict()

    assert data["report_mode"] == "news_driven"
    assert data["should_generate"] is True
    assert data["core_events"][0]["source_confidence"] == "official_confirmed"
    assert data["market_reactions"][0]["asset"] == "WTI"
    assert "missing_market_validation" not in data["quality_flags"]


def test_build_daily_brief_input_snapshot_selects_report_driven_for_high_value_jin10_article_only() -> None:
    snapshot = build_daily_brief_input_snapshot(
        retrieved_date="2026-06-12",
        run_id="run-news",
        daily_market_brief={"market_mainline": {"status": "unavailable"}, "source_refs": []},
        daily_analysis_triggers={"triggers": []},
        jin10_article_briefs={"briefs": [_article()]},
        report_events={"items": []},
        market_reactions=[],
    )

    data = snapshot.to_dict()

    assert data["report_mode"] == "report_driven"
    assert data["should_generate"] is True
    assert data["core_events"] == []
    assert data["key_articles"][0]["source_confidence"] == "report_derived"
    assert "missing_market_validation" in data["quality_flags"]


def test_build_daily_brief_input_snapshot_empty_mode_is_explicitly_degraded() -> None:
    snapshot = build_daily_brief_input_snapshot(
        retrieved_date="2026-06-12",
        run_id="run-news",
        daily_market_brief={"market_mainline": {"status": "unavailable"}, "source_refs": []},
        daily_analysis_triggers={"triggers": []},
        jin10_article_briefs={"briefs": []},
        report_events={"items": []},
        market_reactions=[],
    )

    data = snapshot.to_dict()

    assert data["report_mode"] == "empty"
    assert data["should_generate"] is False
    assert data["one_line_inputs"] == []
    assert data["quality_flags"] == ["no_actionable_inputs"]


def test_news_driven_brief_without_articles_or_market_validation_is_partial() -> None:
    snapshot = build_daily_brief_input_snapshot(
        retrieved_date="2026-06-12",
        run_id="run-news-no-confirmation",
        daily_market_brief={"market_mainline": {"status": "unavailable"}, "source_refs": []},
        daily_analysis_triggers={"triggers": [_trigger()]},
        jin10_article_briefs={"briefs": []},
        report_events={"items": []},
        market_reactions=[],
    )

    data = snapshot.to_dict()

    assert data["report_mode"] == "news_driven"
    assert data["key_articles"] == []
    assert data["market_reactions"] == []
    assert "missing_market_validation" in data["quality_flags"]
    assert "missing_key_articles" in data["quality_flags"]


def test_archive_daily_brief_input_snapshot_writes_feature_artifact(tmp_path: Path) -> None:
    snapshot = build_daily_brief_input_snapshot(
        retrieved_date="2026-06-12",
        run_id="run-news",
        daily_market_brief=_daily_market_brief(),
        daily_analysis_triggers={"triggers": [_trigger()]},
        jin10_article_briefs={"briefs": [_article()]},
        report_events={"items": []},
        market_reactions=[],
    )

    artifact_path = archive_daily_brief_input_snapshot(
        storage_root=tmp_path,
        retrieved_date="2026-06-12",
        run_id="run-news",
        snapshot=snapshot,
    )

    assert artifact_path == "features/news/2026-06-12/run-news/daily_brief_input_snapshot.json"
    payload = json.loads((tmp_path / artifact_path).read_text(encoding="utf-8"))
    assert payload["retrieved_date"] == "2026-06-12"
    assert payload["run_id"] == "run-news"
    assert payload["daily_brief_input_snapshot"]["report_mode"] == "hybrid"
