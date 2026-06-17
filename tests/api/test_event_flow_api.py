"""P1-08: Event Flow Read Model 测试。"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.services.event_flow_service import build_event_flow_briefs
from apps.api.services.event_flow_service import build_event_flow_event_detail
from apps.api.services.event_flow_service import build_event_flow_events
from apps.api.services.event_flow_service import build_event_flow_impact
from apps.api.services.event_flow_service import build_event_flow_market_reaction
from apps.api.services.event_flow_service import build_event_flow_overview
from apps.api.services.event_flow_service import build_event_flow_report_inputs
from apps.api.services.event_flow_service import _normalize_flashes
from tests.fixtures.news.replay import materialize_news_replay

client = TestClient(app)


@pytest.fixture(autouse=True)
def _isolated_event_flow_project_root(tmp_path, monkeypatch):
    monkeypatch.setattr("apps.api.services.event_flow_service._PROJECT_ROOT", tmp_path)
    return tmp_path


def test_build_overview_returns_required_keys():
    result = build_event_flow_overview()
    required = {
        "status",
        "source",
        "updated_at",
        "events",
        "flash_count",
        "calendar_count",
        "event_impact_summary",
        "brief_summary",
        "daily_analysis_triggers",
        "daily_analysis_followups",
        "article_briefs",
        "source_refs",
        "warnings",
    }
    assert required.issubset(result.keys()), f"Missing keys: {required - set(result.keys())}"


def test_build_overview_includes_agent_event_impact(monkeypatch):
    monkeypatch.setattr(
        "apps.api.services.event_flow_service.build_event_impact_agent_summary",
        lambda: {
            "agent_name": "event_impact",
            "summary": "事件冲击偏谨慎。",
            "events": [{"id": "event-1", "title": "CPI"}],
        },
    )

    result = build_event_flow_overview()

    assert result["event_impact_summary"]["summary"] == "事件冲击偏谨慎。"
    assert result["event_impact_summary"]["events"][0]["id"] == "event-1"


def test_build_overview_status_is_valid():
    result = build_event_flow_overview()
    assert result["status"] in ("available", "partial", "unavailable")


def test_build_overview_events_is_list():
    result = build_event_flow_overview()
    assert isinstance(result["events"], list)


def test_build_overview_consumes_latest_daily_market_brief(tmp_path, monkeypatch):
    replay = materialize_news_replay(
        tmp_path,
        scenario="manual_news_p011_live",
        include_features=True,
        include_collectors=False,
        include_outputs=False,
    )

    result = build_event_flow_overview()
    artifact_path = replay["brief_path"].relative_to(tmp_path).as_posix()
    primary_event = next(
        event for event in result["events"] if event["id"] == result["brief_summary"]["market_mainline"]["primary_event_id"]
    )

    assert result["status"] == "partial"
    assert result["source"] == "daily_market_brief"
    assert primary_event["kind"] == "confirmed_event"
    assert primary_event["event_type"] == "fomc_statement"
    assert primary_event["pricing"] == "partially_priced"
    assert primary_event["id"] == result["brief_summary"]["market_mainline"]["primary_event_id"]
    assert result["source_refs"][0]["source_ref"] == f"daily_market_brief:{replay['feature_date']}/{replay['feature_run_id']}"
    assert result["brief_summary"]["artifact_ref"]["path"] == artifact_path
    assert result["brief_summary"]["market_mainline"]["summary"].startswith("Kevin Warsh takes oath of office")
    assert result["brief_summary"]["counts"]["confirmed_event_count"] >= 1
    assert result["brief_summary"]["data_quality"]["event_candidate_count"] >= 1


def test_build_overview_passes_through_brief_event_market_context(tmp_path):
    brief_path = tmp_path / "storage" / "features" / "news" / "2026-06-12" / "run-news" / "daily_market_brief.json"
    brief_path.parent.mkdir(parents=True, exist_ok=True)
    brief_path.write_text(
        json.dumps(
            {
                "daily_market_brief": {
                    "as_of": "2026-06-12T12:00:00+00:00",
                    "confirmed_events": [
                        {
                            "event_id": "evt:market-context",
                            "event_time": "2026-06-12T11:00:00+00:00",
                            "what_happened": "Fed speaker leaned hawkish.",
                            "pricing_status": "partially_priced",
                            "affected_assets": ["XAUUSD", "DXY"],
                            "impact_path": ["rates", "dollar", "gold"],
                            "gold_impact": "bearish",
                            "silver_impact": "bearish",
                            "dollar_impact": "bullish",
                            "yield_impact": "bullish",
                            "oil_impact": "neutral",
                            "market_validation": {
                                "status": "validated",
                                "market_snapshot": {"XAUUSD": {"move_pct": -0.4}, "DXY": {"move_pct": 0.2}},
                            },
                            "source_refs": [{"source_ref": "jin10:flash:1", "label": "Jin10 flash"}],
                        }
                    ],
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = build_event_flow_overview()

    event = result["events"][0]
    assert event["affected_assets"] == ["XAUUSD", "DXY"]
    assert event["impact_path"] == ["rates", "dollar", "gold"]
    assert event["gold_impact"] == "bearish"
    assert event["silver_impact"] == "bearish"
    assert event["dollar_impact"] == "bullish"
    assert event["yield_impact"] == "bullish"
    assert event["oil_impact"] == "neutral"
    assert event["market_validation"]["status"] == "validated"
    assert event["market_snapshot"] == {"XAUUSD": {"move_pct": -0.4}, "DXY": {"move_pct": 0.2}}
    assert event["source_refs"] == [{"source_ref": "jin10:flash:1", "label": "Jin10 flash"}]


def test_build_overview_keeps_candidate_events_when_confirmed_events_exceed_limit(tmp_path):
    brief_path = tmp_path / "storage" / "features" / "news" / "2026-06-12" / "run-news" / "daily_market_brief.json"
    brief_path.parent.mkdir(parents=True, exist_ok=True)
    brief_path.write_text(
        json.dumps(
            {
                "daily_market_brief": {
                    "as_of": "2026-06-12T12:00:00+00:00",
                    "confirmed_events": [
                        {
                            "event_id": f"confirmed:{index}",
                            "event_time": f"2026-06-12T10:{index:02d}:00+00:00",
                            "what_happened": f"Confirmed event {index}",
                        }
                        for index in range(55)
                    ],
                    "candidate_events": [
                        {
                            "event_id": "candidate:market-validation",
                            "event_time": "2026-06-12T11:30:00+00:00",
                            "what_happened": "Candidate event with market validation.",
                            "market_validation": {"status": "candidate_validated"},
                        }
                    ],
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = build_event_flow_overview()

    assert len(result["events"]) == 50
    assert result["events"][0]["id"] == "candidate:market-validation"
    assert any(event["id"] == "candidate:market-validation" for event in result["events"])


def test_build_overview_includes_latest_daily_analysis_triggers(tmp_path):
    path = tmp_path / "storage" / "features" / "news" / "2026-06-11" / "run-news" / "daily_analysis_triggers.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "as_of": "2026-06-11T12:00:00+00:00",
                "rule_version": "jin10-daily-analysis-trigger-v1",
                "trigger_count": 1,
                "triggers": [
                    {
                        "trigger_id": "trigger:jin10_daily_analysis:test",
                        "trigger_type": "jin10_daily_analysis",
                        "priority": "high",
                        "source_key": "jin10_feishu",
                        "source_title": "黄金日报需跟进",
                        "suggested_actions": ["run_jin10_daily_analysis"],
                    }
                ],
                "data_quality": {"trigger_count": 1},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = build_event_flow_overview()

    assert result["status"] == "partial"
    assert result["source"] == "daily_analysis_triggers"
    assert result["daily_analysis_triggers"]["trigger_count"] == 1
    assert result["daily_analysis_triggers"]["priority_counts"] == {"high": 1}
    assert result["daily_analysis_followups"]["queue_count"] == 1
    assert result["daily_analysis_followups"]["followups"][0]["action"] == "run_jin10_daily_analysis"
    assert result["source_refs"][0]["source_ref"] == "daily_analysis_triggers:2026-06-11/run-news"


def test_build_overview_prefers_newer_triggers_over_stale_daily_market_brief(tmp_path):
    brief_path = tmp_path / "storage" / "features" / "news" / "2026-06-11" / "run-old" / "daily_market_brief.json"
    brief_path.parent.mkdir(parents=True, exist_ok=True)
    brief_path.write_text(
        json.dumps(
            {
                "daily_market_brief": {
                    "as_of": "2026-06-11T07:16:00+00:00",
                    "candidate_events": [
                        {
                            "event_id": "old:event",
                            "event_time": "2026-06-11T07:00:00+00:00",
                            "what_happened": "Old brief event",
                        }
                    ],
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    trigger_path = tmp_path / "storage" / "features" / "news" / "2026-06-12" / "run-new" / "daily_analysis_triggers.json"
    trigger_path.parent.mkdir(parents=True, exist_ok=True)
    trigger_path.write_text(
        json.dumps(
            {
                "as_of": "2026-06-12T10:07:33+00:00",
                "rule_version": "jin10-daily-analysis-trigger-v2",
                "trigger_count": 1,
                "triggers": [
                    {
                        "trigger_id": "trigger:hormuz",
                        "source_event_id": "event:hormuz",
                        "source_title": "霍尔木兹风险升温，黄金和油价进入再定价。",
                        "evidence_text": "霍尔木兹风险升温，黄金和油价进入再定价。",
                        "event_type": "hormuz_risk",
                        "priority": "high",
                        "status": "queued",
                        "source_key": "jin10_feishu",
                        "asset_tags": ["XAUUSD", "WTI", "DXY"],
                        "impact_path": "geo_risk_to_oil_to_inflation",
                        "gold_impact": "mixed",
                        "data_quality": {"verification_status": "single_source"},
                        "source_refs": [{"source_ref": "jin10_feishu:test", "label": "Jin10 Feishu"}],
                    }
                ],
                "data_quality": {"trigger_count": 1},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = build_event_flow_overview()

    assert result["source"] == "daily_analysis_triggers"
    assert result["updated_at"] == "2026-06-12T10:07:33+00:00"
    assert result["events"][0]["id"] == "trigger:hormuz"
    assert result["events"][0]["kind"] == "daily_analysis_trigger"
    assert result["events"][0]["title"] == "霍尔木兹风险升温，黄金和油价进入再定价。"
    assert result["events"][0]["affected_assets"] == ["XAUUSD", "WTI", "DXY"]
    assert result["events"][0]["verification_status"] == "single_source"
    assert result["source_refs"][0]["source_ref"] == "daily_analysis_triggers:2026-06-12/run-new"


def test_build_overview_includes_latest_jin10_article_briefs(tmp_path):
    path = tmp_path / "storage" / "features" / "news" / "2026-06-11" / "run-news" / "jin10_article_briefs.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "as_of": "2026-06-11T12:00:00+00:00",
                "rule_version": "jin10-article-briefs-v1",
                "brief_count": 1,
                "briefs": [
                    {
                        "brief_id": "jin10_brief:test",
                        "article_class": "gold_macro_market_reference",
                        "display_bucket": "重点分析",
                        "headline": "能源推升通胀数据，美联储已难兑现宽松。",
                        "asset_tags": ["XAUUSD", "DXY"],
                        "topic_tags": ["gold", "inflation"],
                        "suggested_actions": ["show_in_news_flash", "queue_daily_analysis"],
                    }
                ],
                "data_quality": {"display_bucket_counts": {"重点分析": 1}},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = build_event_flow_overview()

    assert result["status"] == "partial"
    assert result["source"] == "jin10_article_briefs"
    assert result["article_briefs"]["brief_count"] == 1
    assert result["article_briefs"]["display_bucket_counts"] == {"重点分析": 1}
    assert result["daily_analysis_followups"]["queue_count"] == 1
    assert result["daily_analysis_followups"]["followups"][0]["action"] == "queue_daily_analysis"
    assert result["source_refs"][0]["source_ref"] == "jin10_article_briefs:2026-06-11/run-news"


def test_build_overview_appends_trigger_source_ref_after_brief_refs(tmp_path):
    replay = materialize_news_replay(
        tmp_path,
        scenario="manual_news_p011_live",
        include_features=True,
        include_collectors=False,
        include_outputs=False,
    )
    trigger_path = tmp_path / "storage" / "features" / "news" / replay["feature_date"] / replay["feature_run_id"] / "daily_analysis_triggers.json"
    trigger_path.write_text(
        json.dumps(
            {
                "as_of": f"{replay['feature_date']}T12:00:00+00:00",
                "rule_version": "jin10-daily-analysis-trigger-v1",
                "trigger_count": 1,
                "triggers": [{"trigger_id": "trigger:test", "priority": "high", "source_key": "jin10_feishu"}],
                "data_quality": {"trigger_count": 1},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = build_event_flow_overview()

    assert result["source"] == "daily_market_brief"
    assert result["source_refs"][0]["source_ref"] == f"daily_market_brief:{replay['feature_date']}/{replay['feature_run_id']}"
    assert any(
        ref["source_ref"] == f"daily_analysis_triggers:{replay['feature_date']}/{replay['feature_run_id']}"
        for ref in result["source_refs"][1:]
    )


def test_build_overview_source_refs_are_valid():
    result = build_event_flow_overview()
    for ref in result["source_refs"]:
        assert isinstance(ref, dict)
        assert "source_ref" in ref
        assert "label" in ref
        assert "status" in ref


def test_build_event_flow_briefs_read_model(tmp_path):
    path = tmp_path / "storage" / "features" / "news" / "2026-06-12" / "run-news" / "jin10_article_briefs.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "date": "2026-06-12",
                "run_id": "run-news",
                "as_of": "2026-06-12T10:00:00+00:00",
                "status": "available",
                "artifact_path": "storage/features/news/2026-06-12/run-news/jin10_article_briefs.json",
                "brief_count": 1,
                "briefs": [
                    {
                        "brief_id": "brief:gold",
                        "headline": "黄金日报需要跟进",
                        "display_bucket": "重点分析",
                        "article_class": "gold_macro_market_reference",
                        "access_status": "readable",
                        "asset_tags": ["XAUUSD"],
                        "topic_tags": ["gold"],
                        "source_refs": [{"source_ref": "jin10:article:1", "label": "Jin10"}],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = build_event_flow_briefs()

    assert result["status"] == "available"
    assert result["source"] == "jin10_article_briefs"
    assert result["brief_count"] == 1
    assert result["briefs"][0]["brief_id"] == "brief:gold"
    assert result["source_refs"][0]["source_ref"] == "jin10_article_briefs:2026-06-12/run-news"


def test_build_event_flow_events_and_detail_from_overview(tmp_path):
    brief_path = tmp_path / "storage" / "features" / "news" / "2026-06-12" / "run-news" / "daily_market_brief.json"
    brief_path.parent.mkdir(parents=True, exist_ok=True)
    brief_path.write_text(
        json.dumps(
            {
                "daily_market_brief": {
                    "as_of": "2026-06-12T12:00:00+00:00",
                    "confirmed_events": [
                        {
                            "event_id": "evt:detail",
                            "event_time": "2026-06-12T11:00:00+00:00",
                            "what_happened": "Fed speaker leaned hawkish.",
                            "pricing_status": "partially_priced",
                            "affected_assets": ["XAUUSD", "DXY"],
                            "impact_path": ["rates", "dollar", "gold"],
                            "gold_impact": "bearish",
                            "market_validation": {
                                "status": "validated",
                                "market_snapshot": {"XAUUSD": {"move_pct": -0.4}},
                            },
                            "source_refs": [{"source_ref": "jin10:flash:1", "label": "Jin10 flash"}],
                        }
                    ],
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    events = build_event_flow_events()
    detail = build_event_flow_event_detail("evt:detail")
    impact = build_event_flow_impact("evt:detail")
    market_reaction = build_event_flow_market_reaction("evt:detail")

    assert events["status"] == "partial"
    assert events["event_count"] == 1
    assert events["events"][0]["id"] == "evt:detail"
    assert detail["event"]["id"] == "evt:detail"
    assert detail["source_refs"][0]["source_ref"] == "jin10:flash:1"
    assert impact["impact_path"] == ["rates", "dollar", "gold"]
    assert impact["gold_impact"] == "bearish"
    assert market_reaction["status"] == "validated"
    assert market_reaction["market_snapshot"] == {"XAUUSD": {"move_pct": -0.4}}


def test_build_event_flow_detail_returns_none_for_missing_event():
    assert build_event_flow_event_detail("missing:event") is None
    assert build_event_flow_impact("missing:event") is None
    assert build_event_flow_market_reaction("missing:event") is None


def test_build_event_flow_report_inputs_from_brief_summary(tmp_path):
    brief_path = tmp_path / "storage" / "features" / "news" / "2026-06-12" / "run-news" / "daily_market_brief.json"
    brief_path.parent.mkdir(parents=True, exist_ok=True)
    brief_path.write_text(
        json.dumps(
            {
                "daily_market_brief": {
                    "as_of": "2026-06-12T12:00:00+00:00",
                    "report_inputs": {
                        "news_highlights": ["Fed hawkish"],
                        "watchlist": ["DXY"],
                        "risk_points": ["single source"],
                    },
                    "source_refs": [{"source_ref": "fed:rss", "label": "Fed RSS"}],
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = build_event_flow_report_inputs()

    assert result["status"] == "partial"
    assert result["report_inputs"]["news_highlights"] == ["Fed hawkish"]
    assert result["source_refs"][0]["source_ref"] == "daily_market_brief:2026-06-12/run-news"
    assert [item["group"] for item in result["actionable_inputs"]] == ["新闻重点", "观察清单", "风险提示"]
    assert result["actionable_inputs"][0]["input_id"].startswith("summary:news_highlights:")
    assert result["actionable_inputs"][0]["title"] == "Fed hawkish"


def test_api_event_flow_split_read_models(tmp_path):
    brief_path = tmp_path / "storage" / "features" / "news" / "2026-06-12" / "run-news" / "daily_market_brief.json"
    brief_path.parent.mkdir(parents=True, exist_ok=True)
    brief_path.write_text(
        json.dumps(
            {
                "daily_market_brief": {
                    "as_of": "2026-06-12T12:00:00+00:00",
                    "report_inputs": {
                        "news_highlights": ["Fed hawkish"],
                        "watchlist": ["DXY"],
                    },
                    "confirmed_events": [
                        {
                            "event_id": "evt:detail",
                            "event_time": "2026-06-12T11:00:00+00:00",
                            "what_happened": "Fed speaker leaned hawkish.",
                            "pricing_status": "partially_priced",
                            "affected_assets": ["XAUUSD", "DXY"],
                            "impact_path": ["rates", "dollar", "gold"],
                            "gold_impact": "bearish",
                            "market_validation": {
                                "status": "validated",
                                "market_snapshot": {"XAUUSD": {"move_pct": -0.4}},
                            },
                            "source_refs": [{"source_ref": "jin10:flash:1", "label": "Jin10 flash"}],
                        }
                    ],
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    article_path = tmp_path / "storage" / "features" / "news" / "2026-06-12" / "run-news" / "jin10_article_briefs.json"
    article_path.write_text(
        json.dumps(
            {
                "date": "2026-06-12",
                "run_id": "run-news",
                "as_of": "2026-06-12T12:00:00+00:00",
                "status": "available",
                "artifact_path": "storage/features/news/2026-06-12/run-news/jin10_article_briefs.json",
                "brief_count": 1,
                "briefs": [
                    {
                        "brief_id": "brief:gold",
                        "headline": "黄金日报需要跟进",
                        "display_bucket": "重点分析",
                        "article_class": "gold_macro_market_reference",
                        "access_status": "readable",
                        "asset_tags": ["XAUUSD"],
                        "topic_tags": ["gold"],
                        "source_refs": [{"source_ref": "jin10:article:1", "label": "Jin10"}],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    briefs_resp = client.get("/api/events/briefs")
    events_resp = client.get("/api/events")
    detail_resp = client.get("/api/events/evt:detail")
    impact_resp = client.get("/api/events/evt:detail/impact")
    reaction_resp = client.get("/api/events/evt:detail/market-reaction")
    inputs_resp = client.get("/api/events/report-inputs")

    assert briefs_resp.status_code == 200
    assert briefs_resp.json()["brief_count"] == 1
    assert events_resp.status_code == 200
    assert events_resp.json()["event_count"] == 1
    assert detail_resp.status_code == 200
    assert detail_resp.json()["event"]["id"] == "evt:detail"
    assert impact_resp.status_code == 200
    assert impact_resp.json()["impact_path"] == ["rates", "dollar", "gold"]
    assert reaction_resp.status_code == 200
    assert reaction_resp.json()["market_snapshot"] == {"XAUUSD": {"move_pct": -0.4}}
    assert inputs_resp.status_code == 200
    assert inputs_resp.json()["report_inputs"]["news_highlights"] == ["Fed hawkish"]
    assert inputs_resp.json()["actionable_inputs"][0]["title"] == "Fed hawkish"


def test_api_event_flow_split_routes_404_for_missing_event():
    detail_resp = client.get("/api/events/missing:event")
    impact_resp = client.get("/api/events/missing:event/impact")
    reaction_resp = client.get("/api/events/missing:event/market-reaction")

    assert detail_resp.status_code == 404
    assert impact_resp.status_code == 404
    assert reaction_resp.status_code == 404


def test_build_overview_when_no_data_shows_warning():
    result = build_event_flow_overview()
    if result["events"] == []:
        assert len(result["warnings"]) > 0
        assert any("mock" in w.lower() or "不可用" in w for w in result["warnings"])


def test_normalized_flash_without_source_id_uses_stable_content_id():
    events = _normalize_flashes([{"content": "Fed CPI shock", "time": "2026-05-29T00:00:00Z"}])

    assert events[0]["id"] == "flash:95f3962a5ee9"


@pytest.mark.integration
def test_api_event_flow_overview_200():
    """Smoke: /api/events/flow/overview returns 200."""
    import os
    import urllib.request
    import json

    for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
        os.environ.pop(k, None)

    try:
        resp = urllib.request.urlopen("http://localhost:8000/api/events/flow/overview", timeout=5)
    except Exception:
        pytest.skip("API not running on localhost:8000")

    assert resp.status == 200
    data = json.loads(resp.read())
    assert "events" in data
    assert "flash_count" in data
    assert "calendar_count" in data
    assert "daily_analysis_triggers" in data
    assert "daily_analysis_followups" in data
