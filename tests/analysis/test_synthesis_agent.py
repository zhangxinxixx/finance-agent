from __future__ import annotations

from datetime import date

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from apps.analysis.agents.fact_review import build_fact_review_agent_output_payload
from apps.analysis.agents.synthesis import build_synthesis_agent_output_payload, persist_synthesis_agent_output
from database.models.analysis import AgentOutput, ensure_analysis_tables
from database.models.report import ensure_report_tables, ReportItem
from database.queries.analysis import upsert_agent_output
from database.queries.review import upsert_review_item


def _session():
    engine = create_engine("sqlite:///:memory:", echo=False)
    ensure_analysis_tables(engine)
    ensure_report_tables(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _agent_output(
    *,
    agent_name: str,
    module: str,
    bias: str,
    confidence: float,
    claims: list[dict],
    source_refs: list[dict] | None = None,
    summary: str | None = None,
    snapshot_id: str = "snap-synthesis-001",
    run_id: str = "run-synthesis-001",
) -> AgentOutput:
    return AgentOutput(
        id=f"ao-{agent_name}",
        snapshot_id=snapshot_id,
        asset="XAUUSD",
        trade_date=date(2026, 5, 31),
        run_id=run_id,
        agent_name=agent_name,
        module=module,
        version="1.0",
        status="success",
        bias=bias,
        confidence=confidence,
        input_snapshot_ids={module: snapshot_id},
        source_refs=source_refs or [],
        key_findings=[summary or f"{agent_name} finding"],
        risk_points=[],
        watchlist=[],
        invalid_conditions=[],
        summary=summary or f"{agent_name} summary",
        payload={
            "claims": claims,
            "generated_by": "rule",
            "artifact_refs": [],
        },
        payload_sha256=f"sha-{agent_name}",
    )


def test_build_synthesis_agent_output_payload_excludes_review_failed_claims_and_keeps_warnings() -> None:
    jin10 = _agent_output(
        agent_name="jin10_report_analysis_agent",
        module="jin10",
        bias="bullish",
        confidence=0.74,
        summary="金十偏多",
        source_refs=[{"source_id": "src-jin10", "source_name": "Jin10", "source_type": "article", "status": "available"}],
        claims=[
            {
                "claim_id": "claim-jin10-1",
                "text": "避险升温支撑金价。",
                "claim_type": "market_view",
                "source_refs": [{"source_id": "src-jin10", "source_name": "Jin10", "source_type": "article", "status": "available"}],
                "evidence_refs": [{"artifact_path": "storage/outputs/jin10/analysis.md"}],
                "confidence": 0.74,
            }
        ],
    )
    options = _agent_output(
        agent_name="cme_options_agent",
        module="options",
        bias="bearish",
        confidence=0.7,
        summary="期权偏空",
        source_refs=[{"source_id": "src-cme", "source_name": "CME", "source_type": "pdf", "status": "available"}],
        claims=[
            {
                "claim_id": "claim-cme-1",
                "text": "结构偏空。",
                "claim_type": "market_view",
                "source_refs": [{"source_id": "src-cme", "source_name": "CME", "source_type": "pdf", "status": "available"}],
                "evidence_refs": [{"artifact_path": "storage/outputs/cme/options_analysis.md"}],
                "confidence": 0.7,
            }
        ],
    )
    fact_review_payload = build_fact_review_agent_output_payload([jin10, options], snapshot_id="snap-synthesis-001")
    fact_review_payload["payload"]["claim_reviews"] = [
        {
            "claim_id": "claim-jin10-1",
            "verdict": "supported",
            "reason": "来源可用",
            "conflicting_refs": [],
            "suggested_action": "keep",
            "reviewer_agent_id": "fact_review_agent",
        },
        {
            "claim_id": "claim-cme-1",
            "verdict": "contradicted",
            "reason": "与其他偏向冲突，需人工复核。",
            "conflicting_refs": [{"agent_name": "jin10_report_analysis_agent", "reason": "bias_conflict"}],
            "suggested_action": "manual_review",
            "reviewer_agent_id": "fact_review_agent",
        },
    ]
    fact_review_payload["payload"]["fact_review_status"] = "conflicted"
    fact_review = AgentOutput(
        id="ao-fact-review",
        snapshot_id="snap-synthesis-001",
        asset="XAUUSD",
        trade_date=date(2026, 5, 31),
        run_id="run-synthesis-001",
        agent_name="fact_review_agent",
        module="fact_review",
        version="1.0",
        status="partial",
        bias="mixed",
        confidence=0.45,
        input_snapshot_ids={"jin10": "snap-synthesis-001", "options": "snap-synthesis-001"},
        source_refs=jin10.source_refs + options.source_refs,
        key_findings=[],
        risk_points=[],
        watchlist=[],
        invalid_conditions=[],
        summary="事实审查发现冲突。",
        payload=fact_review_payload["payload"],
        payload_sha256="sha-fact",
    )

    payload = build_synthesis_agent_output_payload(
        [jin10, options, fact_review],
        review_items=[
            {
                "review_id": "fact-review:ao-cme_options_agent:claim-cme-1",
                "claim_id": "claim-cme-1",
                "status": "pending",
                "reason": "需人工复核",
            }
        ],
        snapshot_id="snap-synthesis-001",
        asset="XAUUSD",
        trade_date="2026-05-31",
        run_id="run-synthesis-001",
    )

    assert payload["agent_name"] == "synthesis_agent"
    assert payload["module"] == "synthesis"
    assert payload["payload"]["prompt_version"] == "synthesis_rules_v1"
    assert payload["payload"]["synthesis_status"] == "needs_review"
    assert payload["payload"]["included_agent_output_ids"] == ["ao-jin10_report_analysis_agent"]
    assert payload["payload"]["excluded_claim_ids"] == ["claim-cme-1"]
    assert payload["payload"]["review_item_ids"] == ["fact-review:ao-cme_options_agent:claim-cme-1"]
    assert any(item["code"] == "claim-contradicted" for item in payload["payload"]["warnings"])
    assert any("人工复核" in item for item in payload["risk_points"])


def test_persist_synthesis_agent_output_is_idempotent() -> None:
    session = _session()
    session.add(
        ReportItem(
            report_id="report-synthesis-001",
            family="macro",
            title="Macro report",
            asset="XAUUSD",
            trade_date=date(2026, 5, 31),
            run_id="run-synthesis-001",
            snapshot_id="snap-synthesis-001",
            data_status="live",
            lifecycle_status="generated",
            source_refs=[],
            report_metadata={},
        )
    )
    jin10 = _agent_output(
        agent_name="jin10_report_analysis_agent",
        module="jin10",
        bias="bullish",
        confidence=0.74,
        summary="金十偏多",
        source_refs=[{"source_id": "src-jin10", "source_name": "Jin10", "source_type": "article", "status": "available"}],
        claims=[
            {
                "claim_id": "claim-jin10-1",
                "text": "避险升温支撑金价。",
                "claim_type": "market_view",
                "source_refs": [{"source_id": "src-jin10", "source_name": "Jin10", "source_type": "article", "status": "available"}],
                "evidence_refs": [{"artifact_path": "storage/outputs/jin10/analysis.md"}],
                "confidence": 0.74,
            }
        ],
    )
    session.add(jin10)
    session.flush()
    upsert_agent_output(session, build_fact_review_agent_output_payload([jin10], snapshot_id="snap-synthesis-001"))
    upsert_review_item(
        session,
        {
            "review_id": "review-jin10-1",
            "run_id": "run-synthesis-001",
            "source_module": "jin10",
            "agent_output_id": jin10.id,
            "claim_id": "claim-jin10-1",
            "severity": "warning",
            "reason": "人工确认金十结论",
            "impact_modules": ["reports"],
            "impact_report_ids": ["report-synthesis-001"],
            "status": "pending",
        },
    )
    session.commit()

    first = persist_synthesis_agent_output(session, snapshot_id="snap-synthesis-001")
    session.commit()
    second = persist_synthesis_agent_output(session, snapshot_id="snap-synthesis-001")
    session.commit()

    assert first["agent_output_id"] == second["agent_output_id"]
    rows = session.scalars(select(AgentOutput).where(AgentOutput.agent_name == "synthesis_agent")).all()
    assert len(rows) == 1
    assert rows[0].payload["synthesis_status"] in {"success", "needs_review", "partial"}
    assert rows[0].payload["review_item_ids"] == ["review-jin10-1"]
