from __future__ import annotations

from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from apps.analysis.agents.fact_review import build_fact_review_agent_output_payload
from apps.api.main import _build_agent_analysis_response, api_agent_analysis_synthesis_latest
from database.models.analysis import AgentOutput, AnalysisBase
from database.queries.analysis import upsert_agent_output


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    AnalysisBase.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return factory()


def test_agent_analysis_response_exposes_unified_agent_output_summary() -> None:
    db = _session()
    cme = AgentOutput(
        id="ao-cme-001",
        snapshot_id="snap-contract-001",
        asset="XAUUSD",
        trade_date=date(2026, 5, 31),
        run_id="run-contract-001",
        agent_name="cme_options_agent",
        module="options",
        version="1.1",
        status="success",
        bias="bullish",
        confidence=0.73,
        input_snapshot_ids={"options": "snap-options-001"},
        source_refs=[
            {
                "source": "cme",
                "report_date": "2026-05-31",
                "source_url": "https://example.test/cme/options/2026-05-31",
            }
        ],
        key_findings=["Gamma Zero 上移"],
        risk_points=["PRELIM 数据待终稿确认"],
        watchlist=["4500"],
        invalid_conditions=["跌破 Gamma Zero"],
        summary="CME options read-only view is bullish; confidence 0.73.",
        payload={
            "artifact_refs": ["storage/outputs/options/2026-05-31/options_report.md"],
            "claims": [{"claim_id": "claim-cme-1", "text": "Gamma Zero 上移"}],
            "generated_by": "rule",
        },
        payload_sha256="cme",
    )
    coordinator = AgentOutput(
        id="ao-coord-001",
        snapshot_id="snap-contract-001",
        asset="XAUUSD",
        trade_date=date(2026, 5, 31),
        run_id="run-contract-001",
        agent_name="coordinator_agent",
        module="coordinator",
        version="1.0",
        status="partial",
        bias="neutral",
        confidence=0.55,
        input_snapshot_ids={"macro": "snap-macro-001", "options": "snap-options-001"},
        source_refs=[{"source": "analysis_snapshot"}],
        key_findings=["宏观与期权信号分化"],
        risk_points=["等待更多数据确认"],
        watchlist=["DXY"],
        invalid_conditions=["实际利率快速回落"],
        summary="Coordinator read-only view is neutral with partial inputs; confidence 0.55.",
        payload={},
        payload_sha256="coord",
    )
    db.add_all([cme, coordinator])
    db.commit()

    payload = _build_agent_analysis_response(db, date(2026, 5, 31), run_id="run-contract-001")

    assert payload["trade_date"] == "2026-05-31"
    assert len(payload["agent_outputs"]) == 2

    cme_summary = next(item for item in payload["agent_outputs"] if item["agent_name"] == "cme_options_agent")
    assert cme_summary["agent_output_id"] == "ao-cme-001"
    assert cme_summary["registry_id"] == "cme_options_agent"
    assert cme_summary["display_name"] == "期权结构"
    assert cme_summary["role"] == "domain_agent"
    assert cme_summary["summary"] == "CME options read-only view is bullish; confidence 0.73."
    assert cme_summary["summary_zh"] == "期权结构只读视图为偏多；确信度 0.73。"
    assert cme_summary["artifact_refs"][0]["artifact_type"] == "analysis_md"
    assert cme_summary["artifact_refs"][0]["file_path"] == "storage/outputs/options/2026-05-31/options_report.md"
    assert cme_summary["artifact_refs"][0]["artifact_id"].startswith(
        "storage/outputs/options/2026-05-31/options_report.md"
    )
    assert cme_summary["source_refs"][0]["data_date"] == "2026-05-31"
    assert cme_summary["source_refs"][0]["url"] == "https://example.test/cme/options/2026-05-31"
    assert cme_summary["claim_count"] == 1
    assert cme_summary["claims"][0]["claim_id"] == "claim-cme-1"
    assert cme_summary["claims"][0]["claim_type"] == "market_view"
    assert cme_summary["claims"][0]["confidence"] == 0.0
    assert cme_summary["claim_reviews"] == []

    legacy_cme = payload["agents"]["cme_options_agent"]
    assert legacy_cme["summary"] == cme_summary["summary_zh"]
    assert legacy_cme["summary_raw"] == cme_summary["summary"]

    assert payload["final"]["bias"] == "neutral"
    assert payload["final"]["confidence"] == 0.55
    assert payload["final"]["summary"] == "协调汇总只读视图为中性（输入不完整）；确信度 0.55。"
    assert payload["final"]["summary_raw"] == "Coordinator read-only view is neutral with partial inputs; confidence 0.55."


def test_agent_analysis_response_includes_fact_review_agent_output() -> None:
    db = _session()
    jin10 = AgentOutput(
        id="ao-jin10-001",
        snapshot_id="snap-contract-002",
        asset="XAUUSD",
        trade_date=date(2026, 5, 31),
        run_id="run-contract-002",
        agent_name="jin10_report_analysis_agent",
        module="jin10",
        version="1.0",
        status="success",
        bias="bullish",
        confidence=0.74,
        input_snapshot_ids={"jin10": "article-218330"},
        source_refs=[{"source_id": "src-jin10", "source_name": "Jin10", "source_type": "article", "status": "available"}],
        key_findings=["地缘风险抬升"],
        risk_points=[],
        watchlist=[],
        invalid_conditions=[],
        summary="Jin10 summary.",
        payload={
            "artifact_refs": ["storage/outputs/jin10/2026-05-31/analysis.md"],
            "claims": [
                {
                    "claim_id": "claim-jin10-1",
                    "text": "地缘风险抬升支撑金价风险溢价。",
                    "claim_type": "market_view",
                    "source_refs": [
                        {
                            "source_id": "src-jin10",
                            "source_name": "Jin10",
                            "source_type": "article",
                            "status": "available",
                            "report_date": "2026-05-31",
                            "source_url": "https://example.test/jin10/218330",
                        }
                    ],
                    "evidence_refs": [{"artifact_path": "storage/outputs/jin10/2026-05-31/analysis.md"}],
                    "confidence": 0.74,
                }
            ],
            "generated_by": "llm",
        },
        payload_sha256="jin10",
    )
    db.add(jin10)
    db.flush()
    upsert_agent_output(db, build_fact_review_agent_output_payload([jin10]))
    db.commit()

    payload = _build_agent_analysis_response(db, date(2026, 5, 31), run_id="run-contract-002")

    fact_summary = next(item for item in payload["agent_outputs"] if item["agent_name"] == "fact_review_agent")
    assert fact_summary["registry_id"] == "fact_review_agent"
    assert fact_summary["role"] == "review_agent"
    assert fact_summary["fact_review_status"] == "passed"
    assert fact_summary["claim_count"] == 0
    assert fact_summary["claim_reviews"][0]["claim_id"] == "claim-jin10-1"
    claim_source_ref = next(item for item in payload["agent_outputs"] if item["agent_name"] == "jin10_report_analysis_agent")["claims"][0]["source_refs"][0]
    assert claim_source_ref["data_date"] == "2026-05-31"
    assert claim_source_ref["url"] == "https://example.test/jin10/218330"


def test_agent_analysis_synthesis_latest_returns_latest_synthesis_output() -> None:
    db = _session()
    synthesis = AgentOutput(
        id="ao-synth-001",
        snapshot_id="snap-contract-003",
        asset="XAUUSD",
        trade_date=date(2026, 5, 31),
        run_id="run-contract-003",
        agent_name="synthesis_agent",
        module="synthesis",
        version="1.0",
        status="partial",
        bias="mixed",
        confidence=0.58,
        input_snapshot_ids={"jin10": "snap-contract-003", "options": "snap-contract-003"},
        source_refs=[{"source_id": "src-001", "source_name": "Snapshot", "source_type": "analysis"}],
        key_findings=["金十偏多，但期权结论待复核。"],
        risk_points=["存在待人工复核项。"],
        watchlist=["review-center"],
        invalid_conditions=["unsupported claim excluded"],
        summary="综合分析认为当前结论需人工复核。",
        payload={
            "generated_by": "rule",
            "prompt_version": "synthesis_rules_v1",
            "synthesis_status": "needs_review",
            "warnings": [{"code": "claim-contradicted", "message": "期权 claim 被排除"}],
            "included_agent_output_ids": ["ao-jin10-001"],
            "excluded_claim_ids": ["claim-cme-1"],
        },
        payload_sha256="synth",
    )
    db.add(synthesis)
    db.commit()

    payload = api_agent_analysis_synthesis_latest(db=db)

    assert payload["agent_name"] == "synthesis_agent"
    assert payload["registry_id"] == "synthesis_agent"
    assert payload["role"] == "synthesis_agent"
    assert payload["summary_zh"] == "综合分析认为当前结论需人工复核。"
    assert payload["fact_review_status"] == "needs_review"
