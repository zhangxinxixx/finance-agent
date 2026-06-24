from __future__ import annotations

from pathlib import Path

from apps.features.news.event_candidates import build_event_candidates
from apps.features.news.report_event_extractor import (
    archive_jin10_report_events,
    extract_jin10_report_events,
)


RAW_REPORT = {
    "article_id": "221446",
    "document_id": "jin10-2026-06-09-221446",
    "run_id": "221446",
    "title": "黄金ETF资金观望等待催化剂，白银或已进入低估区间-金十数据VIP",
    "trade_date": "2026-06-09",
    "source_url": "https://svip.jin10.com/news/221446",
    "article_markdown": (
        "# 黄金ETF资金观望等待催化剂，白银或已进入低估区间\n\n"
        "2026年06月09日\n\n"
        "5月黄金ETF资金表现平稳，资金进入观望状态，本周三大关键催化剂可能改变日内走势。"
        "而白银存在两大宏观支撑，公允价格已提升至更高位。"
    ),
    "generated_from": {
        "article_context": {
            "key_sentences": [
                "5月黄金ETF资金表现平稳，资金进入观望状态，本周三大关键催化剂可能改变日内走势。",
                "白银存在两大宏观支撑，公允价格已提升至更高位。",
            ],
            "level_snippets": [
                "黄金ETF资金观望等待催化剂，白银或已进入低估区间",
            ],
        },
        "external_report_dir": "/tmp/finance-agent-test/jin10-reports/2026-06-09/daily/221446",
    },
    "quality_audit": {
        "status": "needs_review",
        "reasons": [{"code": "evidence_insufficient", "message": "limited evidence"}],
    },
    "source_refs": [
        {
            "source": "jin10_external",
            "asset_type": "report_md",
            "path": "/tmp/finance-agent-test/jin10-reports/2026-06-09/daily/221446/report.md",
            "source_url": "https://svip.jin10.com/news/221446",
        }
    ],
}

DAILY_ANALYSIS = {
    "article_id": "221446",
    "run_id": "221446",
    "title": "黄金ETF资金观望等待催化剂，白银或已进入低估区间-金十数据VIP",
    "trade_date": "2026-06-09",
    "core_conclusion": "解析已完成，但正文与图表证据仍不足以形成稳定结论。",
    "quality_audit": RAW_REPORT["quality_audit"],
    "source_refs": RAW_REPORT["source_refs"],
}

AGENT_ANALYSIS = {
    "article_id": "221446",
    "run_id": "221446",
    "data_category": "external_opinion",
    "one_line_conclusion": "黄金ETF资金观望，白银估值线索升温。",
    "evidence_basis": {
        "author_views": [
            "报告明确提到：5月黄金ETF资金表现平稳，资金进入观望状态。",
            "白银存在两大宏观支撑，或已进入低估区间。",
        ]
    },
    "quality_audit": RAW_REPORT["quality_audit"],
}


def test_extract_jin10_report_events_marks_report_opinion_as_single_source() -> None:
    result = extract_jin10_report_events(
        raw_article_report=RAW_REPORT,
        daily_analysis=DAILY_ANALYSIS,
        agent_analysis_report=AGENT_ANALYSIS,
        artifact_paths={
            "raw_article_report": "storage/outputs/jin10/2026-06-09/221446/raw_article_report.json",
            "daily_analysis": "storage/outputs/jin10/2026-06-09/221446/daily_analysis.json",
            "agent_analysis_report": "storage/outputs/jin10/2026-06-09/221446/agent_analysis_report.json",
        },
        fetched_at="2026-06-10T01:00:00+00:00",
    )

    data = result.to_dict()
    event_types = {item["event_type"] for item in data["items"]}

    assert data["status"] == "partial"
    assert data["data_quality"]["quality_audit_status"] == "needs_review"
    assert {"gold_fund_flow", "silver_industrial_demand", "macro_watchlist"} <= event_types
    assert data["source_refs"]
    assert data["warnings"] == ["Jin10 report quality_audit.status=needs_review."]

    for item in data["items"]:
        assert item["source_key"] == "jin10_report_events"
        assert item["source_type"] == "supplemental"
        assert item["verification_status"] == "single_source"
        assert item["raw_payload"]["report_run_id"] == "221446"
        assert item["raw_payload"]["quality_audit_status"] == "needs_review"
        assert item["raw_payload"]["source_refs"]


def test_report_events_feed_existing_event_candidate_builder() -> None:
    result = extract_jin10_report_events(
        raw_article_report=RAW_REPORT,
        daily_analysis=DAILY_ANALYSIS,
        agent_analysis_report=AGENT_ANALYSIS,
        fetched_at="2026-06-10T01:00:00+00:00",
    )

    bundle = build_event_candidates(result.items, as_of="2026-06-10T01:00:00+00:00")
    data = bundle.to_dict()

    assert data["source_mix"]["supplemental"] == len(result.items)
    assert data["top_market_events"] == []
    assert data["data_quality"]["single_source_count"] == len(result.items)
    assert all(event["verification_status"] == "single_source" for event in data["event_candidates"])
    assert all(event["need_verification"] is True for event in data["event_candidates"])
    assert any(ref.get("asset_type") == "report_md" for event in data["event_candidates"] for ref in event["source_refs"])


def test_archive_jin10_report_events_writes_feature_artifact(tmp_path: Path) -> None:
    result = extract_jin10_report_events(
        raw_article_report=RAW_REPORT,
        daily_analysis=DAILY_ANALYSIS,
        fetched_at="2026-06-10T01:00:00+00:00",
    )

    artifact_path = archive_jin10_report_events(
        storage_root=tmp_path,
        retrieved_date="2026-06-10",
        run_id="221446",
        extraction=result,
    )

    assert artifact_path == "features/news/2026-06-10/221446/report_events.json"
    assert (tmp_path / artifact_path).exists()
    assert '"jin10_report_events"' in (tmp_path / artifact_path).read_text(encoding="utf-8")
