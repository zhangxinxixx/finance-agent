from __future__ import annotations

import json
from pathlib import Path

import pytest

from apps.output.macro_event_followup import write_macro_event_followup
from apps.renderer.markdown.macro_event_followup import (
    build_macro_event_followup_structured_payload,
    render_macro_event_followup_analysis_markdown,
    render_macro_event_followup_source_markdown,
)


def _input_snapshot(*, include_optional_inputs: bool = True) -> dict:
    same_day_input_status = "available" if include_optional_inputs else "unavailable"
    return {
        "status": "ready" if include_optional_inputs else "degraded",
        "trade_date": "2026-06-21",
        "anchor_trade_date": "2026-06-20",
        "anchor_report_refs": [
            {
                "artifact_type": "final_report",
                "trade_date": "2026-06-20",
                "run_id": "run-anchor",
                "path": "outputs/final_report/XAUUSD/2026-06-20/run-anchor/final_report.md",
                "available": True,
            },
            {
                "artifact_type": "strategy_card",
                "trade_date": "2026-06-20",
                "run_id": "run-anchor",
                "path": "outputs/strategy_card/XAUUSD/2026-06-20/run-anchor/strategy_card.json",
                "available": True,
            },
        ],
        "inputs": {
            "daily_market_brief": {
                "status": same_day_input_status,
                "run_id": "run-news",
                "payload": {
                    "market_mainline": {
                        "status": "available",
                        "summary": "Weekend macro updates keep gold sensitive to Fed repricing.",
                    },
                    "confirmed_events": [
                        {
                            "event_id": "evt-fed",
                            "event_type": "fed_hawkish",
                            "what_happened": "Fed speaker signaled higher-for-longer.",
                            "source_refs": [{"source": "jin10", "source_ref": "brief:event-fed"}],
                        }
                    ],
                    "candidate_events": [],
                    "unconfirmed_risks": [],
                    "source_refs": [{"source": "jin10", "source_ref": "brief:daily-market-brief"}],
                },
            },
            "daily_analysis_followups": {
                "status": same_day_input_status,
                "run_id": "run-news",
                "queue_count": 1 if include_optional_inputs else 0,
                "payload": {
                    "followups": [
                        {
                            "title": "Weekend Fed repricing",
                            "event_type": "fed_hawkish",
                            "impact_path": "rates_to_gold",
                            "source_refs": [{"source": "jin10", "source_ref": "followup:1"}],
                        }
                    ]
                    if include_optional_inputs
                    else [],
                },
            },
            "jin10_article_briefs": {
                "status": same_day_input_status,
                "run_id": "run-news",
                "payload": {
                    "briefs": [
                        {
                            "headline": "Gold weekend brief",
                            "analysis_summary": "Weekend macro headlines reinforce the prior gold thesis.",
                            "source_refs": [{"source": "jin10", "source_ref": "brief:1"}],
                        }
                    ]
                    if include_optional_inputs
                    else [],
                },
            },
            "event_flow_overview": {"status": "unavailable", "run_id": None, "payload": None},
        },
        "availability": {
            "daily_market_brief": same_day_input_status,
            "daily_analysis_followups": same_day_input_status,
            "jin10_article_briefs": same_day_input_status,
            "event_flow_overview": "unavailable",
        },
        "quality_flags": [] if include_optional_inputs else ["missing_optional_inputs"],
        "warnings": [] if include_optional_inputs else ["daily_market_brief unavailable for 2026-06-21"],
    }


def test_render_followup_markdown_and_structured_payload_capture_anchor_and_events() -> None:
    snapshot = _input_snapshot()

    structured = build_macro_event_followup_structured_payload(snapshot)
    source_md = render_macro_event_followup_source_markdown(snapshot)
    analysis_md = render_macro_event_followup_analysis_markdown(structured.model_dump(mode="python"))

    assert structured.report_type == "macro_event_followup"
    assert structured.trade_date == "2026-06-21"
    assert structured.anchor_trade_date == "2026-06-20"
    assert structured.anchor_report_refs[0]["run_id"] == "run-anchor"
    assert structured.new_macro_events[0]["title"] == "Fed speaker signaled higher-for-longer."
    assert "2026-06-20" in source_md
    assert "Weekend Fed repricing" in source_md
    assert "开头结论" in analysis_md
    assert "相比锚点的变化" in analysis_md
    assert "开盘前观察项" in analysis_md
    assert "改判风险" in analysis_md
    assert "Fed speaker signaled higher-for-longer." in analysis_md
    assert "Weekend macro headlines reinforce the prior gold thesis." in analysis_md
    assert "风险级别：" in analysis_md
    assert "风险原因：" in analysis_md


def test_render_followup_markdown_dedupes_duplicate_watch_items() -> None:
    snapshot = _input_snapshot()
    snapshot["inputs"]["daily_analysis_followups"]["payload"]["followups"].append(
        {
            "title": "Weekend Fed repricing",
            "event_type": "fed_hawkish",
            "impact_path": "rates_to_gold",
            "source_refs": [{"source": "jin10", "source_ref": "followup:dup"}],
        }
    )

    structured = build_macro_event_followup_structured_payload(snapshot)
    analysis_md = render_macro_event_followup_analysis_markdown(structured.model_dump(mode="python"))

    watch_section = analysis_md.split("## 开盘前观察项", 1)[1].split("## 改判风险", 1)[0]
    assert watch_section.count("Weekend Fed repricing") == 1


def test_write_macro_event_followup_creates_three_artifacts_and_validates_payload(tmp_path: Path) -> None:
    snapshot = _input_snapshot()
    structured = build_macro_event_followup_structured_payload(snapshot)

    result = write_macro_event_followup(
        storage_root=tmp_path,
        asset="XAUUSD",
        trade_date="2026-06-21",
        run_id="run-followup",
        source_markdown=render_macro_event_followup_source_markdown(snapshot),
        analysis_markdown=render_macro_event_followup_analysis_markdown(structured.model_dump(mode="python")),
        structured_payload=structured.model_dump(mode="json"),
    )

    assert result["artifact_type"] == "macro_event_followup"
    assert len(result["paths"]) == 3

    source_path = Path(result["paths"][0])
    analysis_path = Path(result["paths"][1])
    structured_path = Path(result["paths"][2])
    assert source_path.name == "source.md"
    assert analysis_path.name == "analysis.md"
    assert structured_path.name == "report_structured.json"
    payload = json.loads(structured_path.read_text(encoding="utf-8"))
    assert payload["report_type"] == "macro_event_followup"
    assert payload["anchor_trade_date"] == "2026-06-20"


def test_write_macro_event_followup_default_no_overwrite(tmp_path: Path) -> None:
    snapshot = _input_snapshot(include_optional_inputs=False)
    structured = build_macro_event_followup_structured_payload(snapshot)

    write_macro_event_followup(
        storage_root=tmp_path,
        asset="XAUUSD",
        trade_date="2026-06-21",
        run_id="run-followup",
        source_markdown=render_macro_event_followup_source_markdown(snapshot),
        analysis_markdown=render_macro_event_followup_analysis_markdown(structured.model_dump(mode="python")),
        structured_payload=structured.model_dump(mode="json"),
    )

    with pytest.raises(FileExistsError, match="already exist"):
        write_macro_event_followup(
            storage_root=tmp_path,
            asset="XAUUSD",
            trade_date="2026-06-21",
            run_id="run-followup",
            source_markdown=render_macro_event_followup_source_markdown(snapshot),
            analysis_markdown=render_macro_event_followup_analysis_markdown(structured.model_dump(mode="python")),
            structured_payload=structured.model_dump(mode="json"),
        )
