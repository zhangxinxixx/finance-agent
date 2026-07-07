from __future__ import annotations

import json

from scripts.distill_jin10_research_knowledge import build_knowledge_item, build_output_payload


def _agent_report() -> dict:
    return {
        "article_id": "223556",
        "trade_date": "2026-07-07",
        "title": "非农仅增5.7万，美联储为何不能轻易转鸽？｜大师复盘",
        "asset": "黄金",
        "family": "jin10_agent_analysis",
        "source_report_family": "jin10_research_report",
        "content_access": {
            "report_type": "research",
            "series": "master_review",
            "content_scope": "full",
            "body_complete": True,
            "vip_locked": False,
        },
        "generated_from": {
            "daily_report_family": "jin10_research_report",
            "report_type": "research",
        },
        "one_line_conclusion": "弱非农线索不能直接推导为黄金趋势上行，仍需利率、美元和价格确认。",
        "final_summary": "该报告更适合作为阶段性复盘候选，不应直接晋升为长期知识。",
        "scenario_paths": [
            {
                "summary": "弱就业利多需要经过政策预期传导确认。",
                "trigger": "收益率和美元同步回落。",
                "invalid": "美联储继续维持鹰派定价。",
            }
        ],
        "trading_implications": [
            {
                "stance": "先观察，等确认",
                "trigger": "价格重新站上关键确认位。",
            }
        ],
        "key_variables": [{"name": "DXY"}, {"name": "10Y yield"}],
        "quality_audit": {"status": "needs_review", "reasons": [{"code": "evidence_insufficient"}]},
        "source_refs": [{"source": "jin10_external", "article_id": "223556"}],
    }


def test_build_knowledge_item_from_jin10_master_review_agent_output(tmp_path) -> None:
    report_path = tmp_path / "agent_analysis_report.json"
    report_path.write_text(json.dumps(_agent_report(), ensure_ascii=False), encoding="utf-8")

    item = build_knowledge_item(_agent_report(), report_path=report_path)

    assert item["id"] == "jin10-master-review-2026-07-07-223556"
    assert item["type"] == "review"
    assert item["status"] == "待复核"
    assert item["reviewQueued"] is True
    assert item["agentReady"] is False
    assert item["metadata"]["series"] == "master_review"
    assert "弱非农线索" in item["summary"]
    assert any("收益率和美元同步回落" in rule for rule in item["rules"])
    assert item["source_refs"][0]["source"] == "jin10_agent_analysis_report"


def test_build_output_payload_upserts_existing_items(tmp_path) -> None:
    report_path = tmp_path / "agent_analysis_report.json"
    report_path.write_text(json.dumps(_agent_report(), ensure_ascii=False), encoding="utf-8")
    output_path = tmp_path / "items.json"
    output_path.write_text(
        json.dumps(
            {
                "items": [
                    {"id": "old-item", "title": "旧知识", "confidence": 90, "agentReady": True, "type": "method"},
                    {"id": "jin10-master-review-2026-07-07-223556", "title": "旧候选"},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    item = build_knowledge_item(_agent_report(), report_path=report_path)

    payload = build_output_payload(item, output_path=output_path, replace=False)

    assert [entry["id"] for entry in payload["items"]] == ["jin10-master-review-2026-07-07-223556", "old-item"]
    assert payload["stats"]["total"] == 2
    assert payload["stats"]["agent_ready"] == 1
