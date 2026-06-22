from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from apps.analysis.options.agent_output import (
    build_options_agent_output_payload,
    persist_options_agent_output,
)
from apps.analysis.options.report import render_options_report_markdown
from apps.analysis.options.snapshot import build_options_snapshot, snapshot_to_dict
from database.models.analysis import AgentOutput, ensure_analysis_tables


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "options"
SAMPLE_ROWS_PATH = FIXTURES / "sample_option_rows.json"


def _session():
    engine = create_engine("sqlite:///:memory:", echo=False)
    ensure_analysis_tables(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _snapshot_dict():
    rows = json.loads(SAMPLE_ROWS_PATH.read_text(encoding="utf-8"))
    result = build_options_snapshot(
        rows,
        trade_date="2026-05-06",
        product="OG",
        p0=4200,
        data_source_status="FINAL",
        data_source_url="https://www.cmegroup.com/daily_bulletin/current/Section64_Metals_Option_Products.pdf",
        input_snapshot_ids={"raw_file_sha256": "abc123def456ghi789"},
    )
    return snapshot_to_dict(result), render_options_report_markdown(result)


def test_build_options_agent_output_payload_binds_prompt_artifacts_and_claims(tmp_path):
    snapshot, report_markdown = _snapshot_dict()
    (tmp_path / "options_analysis.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    (tmp_path / "options_analysis.md").write_text(report_markdown, encoding="utf-8")
    (tmp_path / "options_visual_report.json").write_text("{}", encoding="utf-8")
    (tmp_path / "options_visual_report.html").write_text("<html></html>", encoding="utf-8")
    enhanced_markdown = "# CME 黄金期权结构分析报告 — 2026-05-06\n\n## 一句话结论\n4200 上方仍是方向分水岭，结构更接近防守型再平衡。\n"
    (tmp_path / "options_analysis_agent_report.md").write_text(enhanced_markdown, encoding="utf-8")

    payload = build_options_agent_output_payload(
        snapshot,
        artifact_dir=tmp_path,
        run_id="options-sample",
        llm_markdown=enhanced_markdown,
    )

    assert payload["snapshot_id"] == "options:2026-05-06:options-sample"
    assert payload["agent_name"] == "cme_options_agent"
    assert payload["module"] == "options"
    assert payload["run_id"] == "options-sample"
    assert payload["payload"]["prompt_version"] == "cme_options_agent_v1"
    assert payload["payload"]["prompt_messages"][0]["role"] == "system"
    assert "WallScore 表必须包含 dominant_side" in payload["payload"]["prompt_messages"][1]["content"]
    assert payload["payload"]["input_payload"]["options_snapshot"]["trade_date"] == "2026-05-06"
    assert payload["payload"]["llm_raw_output"] == enhanced_markdown.strip()
    assert payload["summary"] == "4200 上方仍是方向分水岭，结构更接近防守型再平衡。"
    assert payload["payload"]["deterministic_output"]["summary"] != "CME 期权只读视图 neutral（输入不完整/临时）；确信度 0.16。"
    assert any("Gamma Zero" in item for item in payload["payload"]["deterministic_output"]["key_findings"])
    assert payload["payload"]["artifact_refs"][-1].endswith("/options_analysis_agent_report.md")
    assert payload["payload"]["claims"]
    assert payload["payload"]["data_category"] == "external_opinion"


def test_persist_options_agent_output_is_idempotent_and_allows_llm_enrichment(tmp_path):
    snapshot, report_markdown = _snapshot_dict()
    (tmp_path / "options_analysis.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    (tmp_path / "options_analysis.md").write_text(report_markdown, encoding="utf-8")
    (tmp_path / "options_visual_report.json").write_text("{}", encoding="utf-8")
    (tmp_path / "options_visual_report.html").write_text("<html></html>", encoding="utf-8")
    session = _session()

    first = persist_options_agent_output(snapshot, artifact_dir=tmp_path, run_id="options-sample", session=session)
    session.commit()

    enhanced_markdown = "# CME 黄金期权结构分析报告 — 2026-05-06\n\n## 一句话结论\nGamma Zero 附近仍是短线主战区，站稳 4200 才进入更强的 Call 结构区。\n"
    (tmp_path / "options_analysis_agent_report.md").write_text(enhanced_markdown, encoding="utf-8")
    second = persist_options_agent_output(
        snapshot,
        artifact_dir=tmp_path,
        run_id="options-sample",
        llm_markdown=enhanced_markdown,
        session=session,
    )
    session.commit()

    assert first["agent_output_id"] == second["agent_output_id"]
    assert first["fact_review_agent_output_id"] == second["fact_review_agent_output_id"]
    assert first["synthesis_agent_output_id"] == second["synthesis_agent_output_id"]
    assert second["fact_review_status"] == "passed"
    assert second["synthesis_status"] in {"success", "needs_review", "partial"}

    rows = session.scalars(select(AgentOutput).order_by(AgentOutput.agent_name)).all()
    assert len(rows) == 3
    fact_review_row = next(row for row in rows if row.agent_name == "fact_review_agent")
    synthesis_row = next(row for row in rows if row.agent_name == "synthesis_agent")
    row = next(row for row in rows if row.agent_name == "cme_options_agent")
    assert row.snapshot_id == "options:2026-05-06:options-sample"
    assert row.summary == "Gamma Zero 附近仍是短线主战区，站稳 4200 才进入更强的 Call 结构区。"
    assert row.payload["prompt_version"] == "cme_options_agent_v1"
    assert row.payload["llm_raw_output"] == enhanced_markdown.strip()
    assert row.payload["artifact_refs"][-1].endswith("/options_analysis_agent_report.md")
    assert row.payload["claims"]
    assert fact_review_row.payload["fact_review_status"] == "passed"
    assert fact_review_row.payload["claim_reviews"]
    assert synthesis_row.payload["prompt_version"] == "synthesis_rules_v1"
