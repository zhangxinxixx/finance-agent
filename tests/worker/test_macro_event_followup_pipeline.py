from __future__ import annotations

import json
from pathlib import Path

from apps.worker.pipelines.macro_event_followup import (
    build_macro_event_followup_input_snapshot,
    generate_macro_event_followup,
    render_and_write_macro_event_followup,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_anchor_outputs(root: Path, *, trade_date: str, run_id: str) -> None:
    _write_text(
        root / "outputs" / "final_report" / "XAUUSD" / trade_date / run_id / "final_report.md",
        f"# Final Report {trade_date}\n",
    )
    _write_json(
        root / "outputs" / "strategy_card" / "XAUUSD" / trade_date / run_id / "strategy_card.json",
        {"trade_date": trade_date, "run_id": run_id, "stance": "bullish"},
    )


def _write_same_day_inputs(root: Path, *, trade_date: str, run_id: str) -> None:
    feature_root = root / "features" / "news" / trade_date / run_id
    _write_json(
        feature_root / "daily_market_brief.json",
        {
            "daily_market_brief": {
                "as_of": f"{trade_date}T09:30:00+00:00",
                "market_mainline": {
                    "status": "available",
                    "primary_event_id": "evt-1",
                    "headline": "Weekend macro headlines keep gold in focus.",
                },
                "confirmed_events": [{"event_id": "evt-1", "event_type": "fed", "what_happened": "Fed speaker stayed hawkish."}],
                "candidate_events": [],
                "unconfirmed_risks": [],
                "source_refs": [{"source": "jin10", "source_ref": "daily_market_brief:test"}],
            }
        },
    )
    _write_json(
        feature_root / "daily_analysis_triggers.json",
        {
            "as_of": f"{trade_date}T10:00:00+00:00",
            "trigger_count": 1,
            "triggers": [
                {
                    "trigger_id": "trigger-1",
                    "priority": "high",
                    "source_title": "Weekend Fed repricing",
                    "source_url": "https://xnews.jin10.com/details/trigger-1",
                    "event_type": "fed_hawkish",
                    "suggested_actions": ["run_jin10_daily_analysis"],
                    "asset_tags": ["XAUUSD"],
                    "topic_tags": ["macro"],
                    "source_refs": [{"source": "jin10", "source_ref": "trigger:test"}],
                }
            ],
        },
    )
    _write_json(
        feature_root / "jin10_article_briefs.json",
        {
            "as_of": f"{trade_date}T10:05:00+00:00",
            "brief_count": 1,
            "briefs": [
                {
                    "brief_id": "brief-1",
                    "article_class": "gold_macro_market_reference",
                    "headline": "Gold weekend brief",
                    "source_url": "https://xnews.jin10.com/details/brief-1",
                    "access_status": "readable",
                    "original_excerpt": "Weekend macro updates support the prior gold thesis.",
                    "analysis_summary": "Weekend macro updates support the prior gold thesis.",
                    "key_points": ["Fed path still restrictive"],
                    "suggested_actions": ["queue_daily_analysis"],
                    "asset_tags": ["XAUUSD"],
                    "topic_tags": ["macro"],
                    "source_refs": [{"source": "jin10", "source_ref": "brief:test"}],
                }
            ],
        },
    )


def test_build_input_snapshot_anchors_saturday_to_previous_friday_and_collects_same_day_inputs(tmp_path: Path) -> None:
    storage_root = tmp_path / "storage"
    _write_anchor_outputs(storage_root, trade_date="2026-06-19", run_id="run-friday")
    _write_same_day_inputs(storage_root, trade_date="2026-06-20", run_id="run-weekend-news")

    snapshot = build_macro_event_followup_input_snapshot(
        trade_date="2026-06-20",
        asset="XAUUSD",
        storage_root=storage_root,
    )

    assert snapshot["status"] == "ready"
    assert snapshot["trade_date"] == "2026-06-20"
    assert snapshot["anchor_trade_date"] == "2026-06-19"
    assert {ref["artifact_type"] for ref in snapshot["anchor_report_refs"]} == {"final_report", "strategy_card"}
    assert snapshot["inputs"]["daily_market_brief"]["status"] == "available"
    assert snapshot["inputs"]["daily_analysis_followups"]["status"] == "available"
    assert snapshot["inputs"]["daily_analysis_followups"]["queue_count"] == 2
    assert snapshot["inputs"]["jin10_article_briefs"]["status"] == "available"
    assert snapshot["availability"]["event_flow_overview"] == "unavailable"
    assert snapshot["quality_flags"] == []


def test_build_input_snapshot_marks_missing_same_day_news_inputs_as_degraded(tmp_path: Path) -> None:
    storage_root = tmp_path / "storage"
    _write_anchor_outputs(storage_root, trade_date="2026-06-19", run_id="run-friday")

    snapshot = build_macro_event_followup_input_snapshot(
        trade_date="2026-06-21",
        asset="XAUUSD",
        storage_root=storage_root,
    )

    assert snapshot["status"] == "degraded"
    assert snapshot["anchor_trade_date"] == "2026-06-19"
    assert snapshot["inputs"]["daily_market_brief"]["status"] == "unavailable"
    assert snapshot["inputs"]["daily_analysis_followups"]["status"] == "unavailable"
    assert snapshot["inputs"]["jin10_article_briefs"]["status"] == "unavailable"
    assert snapshot["availability"]["daily_market_brief"] == "unavailable"
    assert snapshot["quality_flags"] == ["missing_optional_inputs"]
    assert snapshot["warnings"]


def test_build_input_snapshot_returns_not_applicable_for_weekday_requests(tmp_path: Path) -> None:
    storage_root = tmp_path / "storage"
    _write_anchor_outputs(storage_root, trade_date="2026-06-19", run_id="run-friday")

    snapshot = build_macro_event_followup_input_snapshot(
        trade_date="2026-06-22",
        asset="XAUUSD",
        storage_root=storage_root,
    )

    assert snapshot["status"] == "not_applicable"
    assert snapshot["trade_date"] == "2026-06-22"
    assert snapshot["anchor_trade_date"] is None
    assert snapshot["anchor_report_refs"] == []
    assert snapshot["blocking_reason"] == "macro_event_followup v1 only supports weekend/non-trading-day requests"


def test_build_input_snapshot_uses_shared_formal_run_id_for_anchor_refs(tmp_path: Path) -> None:
    storage_root = tmp_path / "storage"
    _write_anchor_outputs(storage_root, trade_date="2026-06-19", run_id="run-shared")
    _write_text(
        storage_root / "outputs" / "final_report" / "XAUUSD" / "2026-06-19" / "run-final-only" / "final_report.md",
        "# Final Report 2026-06-19\n",
    )
    _write_json(
        storage_root / "outputs" / "strategy_card" / "XAUUSD" / "2026-06-19" / "run-strategy-only" / "strategy_card.json",
        {"trade_date": "2026-06-19", "run_id": "run-strategy-only", "stance": "neutral"},
    )

    snapshot = build_macro_event_followup_input_snapshot(
        trade_date="2026-06-20",
        asset="XAUUSD",
        storage_root=storage_root,
    )

    assert snapshot["status"] == "degraded"
    assert snapshot["anchor_trade_date"] == "2026-06-19"
    assert {ref["run_id"] for ref in snapshot["anchor_report_refs"]} == {"run-shared"}


def test_render_and_write_macro_event_followup_writes_three_artifacts(tmp_path: Path) -> None:
    storage_root = tmp_path / "storage"
    _write_anchor_outputs(storage_root, trade_date="2026-06-19", run_id="run-shared")
    _write_same_day_inputs(storage_root, trade_date="2026-06-20", run_id="run-weekend-news")

    snapshot = build_macro_event_followup_input_snapshot(
        trade_date="2026-06-20",
        asset="XAUUSD",
        storage_root=storage_root,
    )

    result = render_and_write_macro_event_followup(
        input_snapshot=snapshot,
        storage_root=storage_root,
        asset="XAUUSD",
        run_id="run-followup",
    )

    assert result["artifact_type"] == "macro_event_followup"
    assert len(result["paths"]) == 3
    structured_path = Path(result["paths"][2])
    payload = json.loads(structured_path.read_text(encoding="utf-8"))
    assert payload["report_type"] == "macro_event_followup"
    assert payload["trade_date"] == "2026-06-20"
    assert payload["anchor_trade_date"] == "2026-06-19"
    analysis_md = (Path(result["paths"][1]).read_text(encoding="utf-8"))
    assert "开头结论" in analysis_md or "宏观事件跟进补充" in analysis_md


def test_generate_macro_event_followup_builds_and_writes_artifacts_for_weekend_request(tmp_path: Path) -> None:
    storage_root = tmp_path / "storage"
    _write_anchor_outputs(storage_root, trade_date="2026-06-19", run_id="run-shared")
    _write_same_day_inputs(storage_root, trade_date="2026-06-20", run_id="run-weekend-news")

    result = generate_macro_event_followup(
        trade_date="2026-06-20",
        asset="XAUUSD",
        storage_root=storage_root,
        run_id="run-generate",
    )

    assert result["status"] == "ready"
    assert result["trade_date"] == "2026-06-20"
    assert result["artifact_type"] == "macro_event_followup"
    assert len(result["paths"]) == 3
