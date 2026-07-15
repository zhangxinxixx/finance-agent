from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.analysis.agents.fact_review import build_fact_review_agent_output_payload
from apps.analysis.agents.synthesis import persist_synthesis_agent_output
from database.models.analysis import AgentOutput, AnalysisBase
from database.models.report import ensure_report_tables
from database.queries.analysis import upsert_agent_output, upsert_analysis_snapshot
from database.queries.analysis import upsert_final_analysis_result
from database.queries.review import upsert_review_item
from database.queries.report import upsert_report_artifact, upsert_report_item


def _make_session_factory() -> sessionmaker:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    AnalysisBase.metadata.create_all(engine)
    ensure_report_tables(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _make_tree(root: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def _seed_standard_report(session: Session) -> None:
    upsert_report_item(
        session,
        {
            "report_id": "report-std-001",
            "family": "macro",
            "report_type": "daily_macro",
            "title": "Macro Daily Report",
            "asset": "XAUUSD",
            "trade_date": "2026-05-26",
            "run_id": "run-std-001",
            "snapshot_id": "snap-std-001",
            "data_status": "live",
            "lifecycle_status": "generated",
            "source_refs": [{"source_id": "src-report", "source_name": "Report Feed", "source_type": "api", "status": "available"}],
        },
    )
    for suffix, artifact_type, name, content_type, is_primary in (
        ("source", "source_md", "source.md", "text/markdown", True),
        ("analysis", "analysis_md", "analysis.md", "text/markdown", False),
        ("visual", "visual_html", "visual.html", "text/html", False),
        ("structured", "structured_json", "report_structured.json", "application/json", False),
    ):
        upsert_report_artifact(
            session,
            {
                "artifact_id": f"report-std-001:{suffix}",
                "report_id": "report-std-001",
                "artifact_type": artifact_type,
                "file_path": f"storage/outputs/reports/2026-05-26/report-std-001/{name}",
                "version": "1",
                "status": "generated",
                "content_type": content_type,
                "is_primary": is_primary,
            },
        )


def _seed_standard_snapshot(session: Session) -> None:
    upsert_analysis_snapshot(
        session,
        payload={
            "snapshot_id": "snap-std-001",
            "asset": "XAUUSD",
            "trade_date": "2026-05-26",
            "run_id": "run-std-001",
            "status": "success",
            "input_snapshot_ids": {"macro": "macro-raw-001", "options": "options-raw-001"},
            "source_refs": [{"source_id": "src-snapshot", "source_name": "Snapshot Feed", "source_type": "api", "status": "available"}],
            "macro": {"regime": "tightening"},
            "options": {"gamma_zero": 3325},
            "payload": {
                "snapshot_id": "snap-std-001",
                "trade_date": "2026-05-26",
                "macro": {"regime": "tightening"},
                "options": {"gamma_zero": 3325},
            },
        },
        artifact_path="storage/features/2026-05-26/snap-std-001/analysis_snapshot.json",
    )


def _seed_agent_outputs(session: Session) -> None:
    upsert_agent_output(
        session,
        {
            "snapshot_id": "snap-std-001",
            "analysis_snapshot_db_id": None,
            "asset": "XAUUSD",
            "trade_date": "2026-05-26",
            "run_id": "run-std-001",
            "agent_name": "jin10_report_analysis_agent",
            "module": "jin10",
            "version": "1.0",
            "status": "success",
            "bias": "bullish",
            "confidence": 0.74,
            "input_snapshot_ids": {"jin10": "article-218330"},
            "source_refs": [{"source_id": "src-jin10", "source_name": "Jin10", "source_type": "article", "status": "available"}],
            "key_findings": ["地缘风险抬升"],
            "risk_points": ["消息驱动波动放大"],
            "watchlist": ["3330"],
            "invalid_conditions": ["美元快速走强"],
            "summary": "Jin10 agent summary.",
            "payload": {
                "generated_by": "llm",
                "prompt_version": "jin10_report_v1",
                "artifact_refs": ["storage/outputs/jin10/2026-05-26/run-std-001/agent_analysis_report.md"],
                "claims": [{"claim_id": "claim-jin10-1", "text": "金价短线偏强"}],
            },
            "llm_model": "gpt-5.6-luna",
            "token_usage": {"input": 1200, "output": 680},
        },
    )
    upsert_agent_output(
        session,
        {
            "snapshot_id": "snap-std-001",
            "analysis_snapshot_db_id": None,
            "asset": "XAUUSD",
            "trade_date": "2026-05-26",
            "run_id": "run-std-001",
            "agent_name": "cme_options_agent",
            "module": "options",
            "version": "1.0",
            "status": "success",
            "bias": "neutral",
            "confidence": 0.68,
            "input_snapshot_ids": {"options": "options-raw-001"},
            "source_refs": [{"source_id": "src-cme", "source_name": "CME", "source_type": "pdf", "status": "available"}],
            "key_findings": ["Gamma Zero 3325"],
            "risk_points": ["初版 bulletin 可能修订"],
            "watchlist": ["3325", "3350"],
            "invalid_conditions": ["失守 3300"],
            "summary": "Options agent summary.",
            "payload": {
                "generated_by": "hybrid",
                "prompt_version": "cme_options_agent_v1",
                "artifact_refs": ["storage/outputs/cme/2026-05-26/run-std-001/options_analysis_agent_report.md"],
                "claims": [{"claim_id": "claim-cme-1", "text": "Gamma Zero 位于 3325"}],
            },
            "llm_model": "gpt-5.4-mini",
            "token_usage": {"input": 900, "output": 420},
        },
    )


def _seed_fact_review_output(session: Session) -> None:
    rows = session.scalars(select(AgentOutput).where(AgentOutput.snapshot_id == "snap-std-001")).all()
    upsert_agent_output(session, build_fact_review_agent_output_payload(rows, snapshot_id="snap-std-001"))


def _seed_legacy_final_report(session: Session) -> None:
    upsert_final_analysis_result(
        session,
        payload={
            "asset": "XAUUSD",
            "trade_date": "2026-05-26",
            "run_id": "run-legacy-001",
            "snapshot_id": "snap-legacy-001",
            "analysis_snapshot_db_id": None,
            "final_bias": "bullish",
            "confidence": 0.82,
            "market_state": "trend_up",
            "scenario_summary": "Legacy report",
            "is_trade_instruction": False,
            "input_snapshot_ids": {"analysis": "snap-legacy-001"},
            "source_refs": [
                {
                    "source_id": "src-legacy-001",
                    "source_name": "Coordinator",
                    "source_type": "agent_output",
                    "status": "generated",
                }
            ],
            "source_agent_outputs": ["macro", "options"],
            "risk_points": [],
            "watchlist": [],
            "invalid_conditions": [],
            "strategy_card": None,
            "run_summaries": {},
            "payload": {"final": "report"},
        },
        paths={
            "final_report_path": "storage/outputs/final_report/XAUUSD/2026-05-26/run-legacy-001/final_report.md",
            "strategy_card_json_path": None,
            "strategy_card_md_path": None,
            "run_summary_path": "storage/outputs/run/2026-05-26/run-legacy-001/step_summaries.json",
            "final_report_sha256": "legacysha",
            "strategy_card_sha256": None,
        },
    )


def test_report_analysis_inputs_returns_snapshot_and_agent_outputs(tmp_path: Path, monkeypatch) -> None:
    from apps.api import main as api_main
    from apps.api.services import report_service

    factory = _make_session_factory()
    with factory() as session:
        _seed_standard_report(session)
        _seed_standard_snapshot(session)
        _seed_agent_outputs(session)
        session.commit()

    _make_tree(
        tmp_path,
        {
            "storage/outputs/reports/2026-05-26/report-std-001/source.md": "# Source",
            "storage/outputs/reports/2026-05-26/report-std-001/analysis.md": "# Analysis",
            "storage/outputs/reports/2026-05-26/report-std-001/visual.html": "<html></html>",
            "storage/outputs/reports/2026-05-26/report-std-001/report_structured.json": json.dumps({"sections": []}),
            "storage/features/2026-05-26/snap-std-001/analysis_snapshot.json": json.dumps({"snapshot_id": "snap-std-001"}),
        },
    )
    monkeypatch.setattr(report_service, "_PROJECT_ROOT", tmp_path)

    with factory() as db:
        payload = api_main.api_report_analysis_inputs("report-std-001", db=db).model_dump(mode="json")

    assert payload["report_id"] == "report-std-001"
    assert payload["data_status"] == "live"
    assert payload["snapshot_id"] == "snap-std-001"
    assert {item["agent_name"] for item in payload["agent_outputs"]} == {"jin10_report_analysis_agent", "cme_options_agent"}
    assert payload["fact_reviews"] == []
    assert payload["synthesis_outputs"] == []
    jin10_output = next(item for item in payload["agent_outputs"] if item["agent_name"] == "jin10_report_analysis_agent")
    assert jin10_output["claims"][0]["claim_id"] == "claim-jin10-1"
    assert jin10_output["llm_model"] == "gpt-5.6-luna"
    assert jin10_output["claims"][0]["claim_type"] == "market_view"
    assert jin10_output["claim_reviews"] == []
    assert jin10_output["artifact_refs"][0]["artifact_type"] == "analysis_md"
    snapshot_input = next(item for item in payload["deterministic_inputs"] if item["input_type"] == "analysis_snapshot")
    assert snapshot_input["sections"] == ["macro", "options"]
    assert snapshot_input["snapshot"]["snapshot_id"] == "snap-std-001"
    assert any(item["artifact_type"] == "feature_json" for item in snapshot_input["artifact_refs"])


def test_report_analysis_inputs_groups_fact_review_outputs_separately(tmp_path: Path, monkeypatch) -> None:
    from apps.api import main as api_main
    from apps.api.services import report_service

    factory = _make_session_factory()
    with factory() as session:
        _seed_standard_report(session)
        _seed_standard_snapshot(session)
        _seed_agent_outputs(session)
        _seed_fact_review_output(session)
        session.commit()

    _make_tree(
        tmp_path,
        {
            "storage/outputs/reports/2026-05-26/report-std-001/source.md": "# Source",
            "storage/outputs/reports/2026-05-26/report-std-001/analysis.md": "# Analysis",
            "storage/outputs/reports/2026-05-26/report-std-001/visual.html": "<html></html>",
            "storage/outputs/reports/2026-05-26/report-std-001/report_structured.json": json.dumps({"sections": []}),
            "storage/features/2026-05-26/snap-std-001/analysis_snapshot.json": json.dumps({"snapshot_id": "snap-std-001"}),
        },
    )
    monkeypatch.setattr(report_service, "_PROJECT_ROOT", tmp_path)

    with factory() as db:
        payload = api_main.api_report_analysis_inputs("report-std-001", db=db).model_dump(mode="json")

    assert {item["agent_name"] for item in payload["agent_outputs"]} == {"jin10_report_analysis_agent", "cme_options_agent"}
    assert len(payload["fact_reviews"]) == 1
    assert payload["fact_reviews"][0]["agent_name"] == "fact_review_agent"
    assert payload["fact_reviews"][0]["fact_review_status"] == "partial"


def test_report_analysis_inputs_groups_synthesis_outputs_separately(tmp_path: Path, monkeypatch) -> None:
    from apps.api import main as api_main
    from apps.api.services import report_service

    factory = _make_session_factory()
    with factory() as session:
        _seed_standard_report(session)
        _seed_standard_snapshot(session)
        _seed_agent_outputs(session)
        _seed_fact_review_output(session)
        upsert_review_item(
            session,
            {
                "review_id": "review-cme-1",
                "run_id": "run-std-001",
                "source_module": "options",
                "agent_output_id": "cme_options_agent",
                "claim_id": "claim-cme-1",
                "severity": "warning",
                "reason": "期权结论待人工复核",
                "impact_modules": ["reports"],
                "impact_report_ids": ["report-std-001"],
                "status": "pending",
            },
        )
        persist_synthesis_agent_output(session, snapshot_id="snap-std-001")
        session.commit()

    _make_tree(
        tmp_path,
        {
            "storage/outputs/reports/2026-05-26/report-std-001/source.md": "# Source",
            "storage/outputs/reports/2026-05-26/report-std-001/analysis.md": "# Analysis",
            "storage/outputs/reports/2026-05-26/report-std-001/visual.html": "<html></html>",
            "storage/outputs/reports/2026-05-26/report-std-001/report_structured.json": json.dumps({"sections": []}),
            "storage/features/2026-05-26/snap-std-001/analysis_snapshot.json": json.dumps({"snapshot_id": "snap-std-001"}),
        },
    )
    monkeypatch.setattr(report_service, "_PROJECT_ROOT", tmp_path)

    with factory() as db:
        payload = api_main.api_report_analysis_inputs("report-std-001", db=db).model_dump(mode="json")

    assert len(payload["synthesis_outputs"]) == 1
    assert payload["synthesis_outputs"][0]["agent_name"] == "synthesis_agent"
    assert payload["synthesis_outputs"][0]["fact_review_status"] == "needs_review"


def test_report_analysis_inputs_falls_back_to_agent_inputs_for_legacy_cme_report(tmp_path: Path, monkeypatch) -> None:
    from apps.api import main as api_main
    from apps.api.services import report_service

    factory = _make_session_factory()
    with factory() as session:
        upsert_agent_output(
            session,
            {
                "snapshot_id": "options:2026-05-06:OG:options-sample",
                "analysis_snapshot_db_id": None,
                "asset": "XAUUSD",
                "trade_date": "2026-05-06",
                "run_id": "options-sample",
                "agent_name": "cme_options_agent",
                "module": "options",
                "version": "1.0",
                "status": "success",
                "bias": "bullish",
                "confidence": 0.77,
                "input_snapshot_ids": {"raw_file_sha256": "abc123"},
                "source_refs": [{"source_id": "src-cme", "source_name": "CME", "source_type": "pdf", "status": "available"}],
                "key_findings": ["Call wall 上移"],
                "risk_points": ["需确认终版 bulletin"],
                "watchlist": ["3340"],
                "invalid_conditions": ["跌破 Gamma Zero"],
                "summary": "Options agent summary.",
                "payload": {
                    "generated_by": "hybrid",
                    "prompt_version": "cme_options_agent_v1",
                    "input_payload": {"options_snapshot": {"trade_date": "2026-05-06", "intent": {"type": "call_buying"}}},
                    "artifact_refs": [
                        "storage/outputs/cme/2026-05-06/options-sample/options_analysis_agent_report.md",
                        "storage/outputs/cme/2026-05-06/options-sample/options_visual_report.json",
                    ],
                    "claims": [{"claim_id": "claim-cme-1", "text": "Call wall 上移"}],
                },
            },
        )
        session.commit()

    _make_tree(
        tmp_path,
        {
            "storage/outputs/cme/2026-05-06/options-sample/options_analysis_agent_report.md": "# Options Agent",
            "storage/outputs/cme/2026-05-06/options-sample/options_analysis.md": "# Options",
            "storage/outputs/cme/2026-05-06/options-sample/options_visual_report.html": "<html></html>",
            "storage/outputs/cme/2026-05-06/options-sample/options_visual_report.json": json.dumps({"summary": "ok"}),
            "storage/outputs/cme/2026-05-06/options-sample/options_analysis.json": json.dumps({"intent": {"type": "call_buying"}}),
        },
    )
    monkeypatch.setattr(report_service, "_PROJECT_ROOT", tmp_path)

    with factory() as db:
        payload = api_main.api_report_analysis_inputs("options-sample", db=db).model_dump(mode="json")

    assert payload["report_id"] == "options-sample"
    assert {item["agent_name"] for item in payload["agent_outputs"]} == {"cme_options_agent"}
    assert any(warning["code"] == "analysis-inputs-agent-fallback" for warning in payload["warnings"])
    fallback_input = payload["deterministic_inputs"][0]
    assert fallback_input["input_type"] == "agent_input_payload"
    assert fallback_input["payload"]["options_snapshot"]["intent"]["type"] == "call_buying"
    assert payload["agent_outputs"][0]["claims"][0]["claim_id"] == "claim-cme-1"
    assert payload["agent_outputs"][0]["claims"][0]["claim_type"] == "market_view"


def test_report_analysis_inputs_marks_missing_agent_outputs_as_partial(tmp_path: Path, monkeypatch) -> None:
    from apps.api import main as api_main
    from apps.api.services import report_service

    factory = _make_session_factory()
    with factory() as session:
        _seed_standard_report(session)
        _seed_standard_snapshot(session)
        session.commit()

    _make_tree(
        tmp_path,
        {
            "storage/outputs/reports/2026-05-26/report-std-001/source.md": "# Source",
            "storage/outputs/reports/2026-05-26/report-std-001/analysis.md": "# Analysis",
            "storage/outputs/reports/2026-05-26/report-std-001/visual.html": "<html></html>",
            "storage/outputs/reports/2026-05-26/report-std-001/report_structured.json": json.dumps({"sections": []}),
            "storage/features/2026-05-26/snap-std-001/analysis_snapshot.json": json.dumps({"snapshot_id": "snap-std-001"}),
        },
    )
    monkeypatch.setattr(report_service, "_PROJECT_ROOT", tmp_path)

    with factory() as db:
        payload = api_main.api_report_analysis_inputs("report-std-001", db=db).model_dump(mode="json")

    assert payload["data_status"] == "partial"
    assert payload["agent_outputs"] == []
    assert payload["fact_reviews"] == []
    assert payload["synthesis_outputs"] == []
    assert any(warning["code"] == "agent-outputs-unavailable" for warning in payload["warnings"])


def test_report_analysis_inputs_uses_detail_lineage_when_snapshot_row_is_missing(tmp_path: Path, monkeypatch) -> None:
    from apps.api import main as api_main
    from apps.api.services import report_service

    factory = _make_session_factory()
    with factory() as session:
        _seed_legacy_final_report(session)
        session.commit()

    _make_tree(
        tmp_path,
        {
            "storage/outputs/final_report/XAUUSD/2026-05-26/run-legacy-001/final_report.md": "# Final Report",
            "storage/outputs/run/2026-05-26/run-legacy-001/step_summaries.json": json.dumps({"steps": []}),
        },
    )
    monkeypatch.setattr(report_service, "_PROJECT_ROOT", tmp_path)

    with factory() as db:
        payload = api_main.api_report_analysis_inputs("run-legacy-001", db=db).model_dump(mode="json")

    assert payload["report_id"] == "run-legacy-001"
    assert any(item["input_type"] == "input_snapshot" for item in payload["deterministic_inputs"])
    assert not any(warning["code"] == "analysis-inputs-unavailable" for warning in payload["warnings"])


def test_report_analysis_inputs_prefers_snapshot_matched_agent_output_over_same_run_fallback(
    tmp_path: Path, monkeypatch
) -> None:
    from apps.api import main as api_main
    from apps.api.services import report_service
    from database.queries.analysis import upsert_agent_output

    factory = _make_session_factory()
    with factory() as session:
        _seed_standard_report(session)
        _seed_standard_snapshot(session)
        _seed_agent_outputs(session)
        conflicting = upsert_agent_output(
            session,
            {
                "snapshot_id": "snap-other-001",
                "analysis_snapshot_db_id": None,
                "asset": "XAUUSD",
                "trade_date": "2026-05-26",
                "run_id": "run-std-001",
                "agent_name": "jin10_report_analysis_agent",
                "module": "jin10",
                "version": "1.0",
                "status": "success",
                "bias": "bearish",
                "confidence": 0.11,
                "input_snapshot_ids": {"jin10": "article-999999"},
                "source_refs": [{"source_id": "src-jin10-wrong", "source_name": "Wrong Jin10", "source_type": "article", "status": "available"}],
                "key_findings": ["错误 lineage"],
                "risk_points": ["不应串入当前报告"],
                "watchlist": ["3290"],
                "invalid_conditions": ["与报告快照不一致"],
                "summary": "Wrong fallback row.",
                "payload": {"artifact_refs": ["storage/outputs/jin10/2026-05-26/run-std-001/wrong.md"]},
            },
        )
        conflicting.created_at = datetime.now(timezone.utc) + timedelta(minutes=5)
        session.commit()

    _make_tree(
        tmp_path,
        {
            "storage/outputs/reports/2026-05-26/report-std-001/source.md": "# Source",
            "storage/outputs/reports/2026-05-26/report-std-001/analysis.md": "# Analysis",
            "storage/outputs/reports/2026-05-26/report-std-001/visual.html": "<html></html>",
            "storage/outputs/reports/2026-05-26/report-std-001/report_structured.json": json.dumps({"sections": []}),
            "storage/features/2026-05-26/snap-std-001/analysis_snapshot.json": json.dumps({"snapshot_id": "snap-std-001"}),
        },
    )
    monkeypatch.setattr(report_service, "_PROJECT_ROOT", tmp_path)

    with factory() as db:
        payload = api_main.api_report_analysis_inputs("report-std-001", db=db).model_dump(mode="json")

    jin10_output = next(item for item in payload["agent_outputs"] if item["agent_name"] == "jin10_report_analysis_agent")
    assert jin10_output["snapshot_id"] == "snap-std-001"
    assert jin10_output["summary"] == "Jin10 agent summary."
    assert {item["source_id"] for item in jin10_output["source_refs"]} == {"src-jin10"}
    assert not any(warning["code"] == "agent-outputs-lineage-fallback" for warning in payload["warnings"])


def test_report_analysis_inputs_warns_when_agent_output_uses_run_id_lineage_fallback(
    tmp_path: Path, monkeypatch
) -> None:
    from apps.api import main as api_main
    from apps.api.services import report_service
    from database.queries.analysis import upsert_agent_output

    factory = _make_session_factory()
    with factory() as session:
        _seed_standard_report(session)
        _seed_standard_snapshot(session)
        upsert_agent_output(
            session,
            {
                "snapshot_id": "snap-fallback-001",
                "analysis_snapshot_db_id": None,
                "asset": "XAUUSD",
                "trade_date": "2026-05-26",
                "run_id": "run-std-001",
                "agent_name": "macro_fallback_agent",
                "module": "macro",
                "version": "1.0",
                "status": "success",
                "bias": "neutral",
                "confidence": 0.42,
                "input_snapshot_ids": {"macro": "macro-raw-001"},
                "source_refs": [{"source_id": "src-fallback", "source_name": "Fallback Macro", "source_type": "api", "status": "available"}],
                "key_findings": ["只有 run_id 对得上"],
                "risk_points": [],
                "watchlist": [],
                "invalid_conditions": [],
                "summary": "Fallback output.",
                "payload": {"artifact_refs": ["storage/outputs/macro/2026-05-26/run-std-001/fallback.md"]},
            },
        )
        session.commit()

    _make_tree(
        tmp_path,
        {
            "storage/outputs/reports/2026-05-26/report-std-001/source.md": "# Source",
            "storage/outputs/reports/2026-05-26/report-std-001/analysis.md": "# Analysis",
            "storage/outputs/reports/2026-05-26/report-std-001/visual.html": "<html></html>",
            "storage/outputs/reports/2026-05-26/report-std-001/report_structured.json": json.dumps({"sections": []}),
            "storage/features/2026-05-26/snap-std-001/analysis_snapshot.json": json.dumps({"snapshot_id": "snap-std-001"}),
        },
    )
    monkeypatch.setattr(report_service, "_PROJECT_ROOT", tmp_path)

    with factory() as db:
        payload = api_main.api_report_analysis_inputs("report-std-001", db=db).model_dump(mode="json")

    assert {item["agent_name"] for item in payload["agent_outputs"]} == {"macro_fallback_agent"}
    assert payload["agent_outputs"][0]["snapshot_id"] == "snap-fallback-001"
    assert any(warning["code"] == "agent-outputs-lineage-fallback" for warning in payload["warnings"])


def test_report_analysis_inputs_warns_when_report_declared_snapshot_drifted(tmp_path: Path, monkeypatch) -> None:
    from apps.api import main as api_main
    from apps.api.services import report_service
    from database.models.report import ReportItem

    factory = _make_session_factory()
    with factory() as session:
        _seed_standard_report(session)
        _seed_standard_snapshot(session)
        _seed_agent_outputs(session)
        report_item = session.get(ReportItem, "report-std-001")
        report_item.snapshot_id = "snap-declared-999"
        session.commit()

    _make_tree(
        tmp_path,
        {
            "storage/outputs/reports/2026-05-26/report-std-001/source.md": "# Source",
            "storage/outputs/reports/2026-05-26/report-std-001/analysis.md": "# Analysis",
            "storage/outputs/reports/2026-05-26/report-std-001/visual.html": "<html></html>",
            "storage/outputs/reports/2026-05-26/report-std-001/report_structured.json": json.dumps({"sections": []}),
            "storage/features/2026-05-26/snap-std-001/analysis_snapshot.json": json.dumps({"snapshot_id": "snap-std-001"}),
        },
    )
    monkeypatch.setattr(report_service, "_PROJECT_ROOT", tmp_path)

    with factory() as db:
        payload = api_main.api_report_analysis_inputs("report-std-001", db=db).model_dump(mode="json")

    warning_codes = {item["code"] for item in payload["warnings"]}
    assert "report-lineage-snapshot-mismatch" in warning_codes
    assert payload["snapshot_id"] == "snap-std-001"
    assert any(item["snapshot"]["snapshot_id"] == "snap-std-001" for item in payload["deterministic_inputs"] if item["snapshot"])
