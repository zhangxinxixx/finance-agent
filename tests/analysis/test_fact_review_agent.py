from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from apps.analysis.agents.fact_review import (
    build_fact_review_agent_output_payload,
    build_runtime_fact_review_agent_output,
    persist_fact_review_agent_output,
)
from apps.analysis.agents.schemas import AgentOutput as RuntimeAgentOutput
from database.models.analysis import AgentOutput, ensure_analysis_tables
from database.models.report import ensure_report_tables
from database.models.report import ReportItem
from database.queries.review import list_review_items


def _session():
    engine = create_engine("sqlite:///:memory:", echo=False)
    ensure_analysis_tables(engine)
    ensure_report_tables(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _agent_output(
    *,
    agent_name: str,
    bias: str,
    claims: list[dict],
    source_refs: list[dict] | None = None,
    status: str = "success",
    confidence: float = 0.72,
    snapshot_id: str = "snap-review-001",
    run_id: str = "run-review-001",
) -> AgentOutput:
    return AgentOutput(
        snapshot_id=snapshot_id,
        asset="XAUUSD",
        trade_date=date(2026, 5, 31),
        run_id=run_id,
        agent_name=agent_name,
        module="analysis",
        version="1.0",
        status=status,
        bias=bias,
        confidence=confidence,
        input_snapshot_ids={"analysis": snapshot_id},
        source_refs=source_refs or [],
        key_findings=[],
        risk_points=[],
        watchlist=[],
        invalid_conditions=[],
        summary=f"{agent_name} summary",
        payload={
            "claims": claims,
            "generated_by": "rule",
            "artifact_refs": [],
        },
        payload_sha256=f"sha-{agent_name}",
    )


def test_build_runtime_fact_review_output_uses_pydantic_contract_without_db_ids() -> None:
    runtime = RuntimeAgentOutput(
        version="1.0",
        agent_name="technical_agent",
        module="technical",
        snapshot_id="technical:snap-runtime-review",
        input_snapshot_ids={"technical": "technical:snap-runtime-review"},
        bias="neutral",
        confidence=0.64,
        key_findings=["Price remains range-bound."],
        risk_points=[],
        watchlist=[],
        invalid_conditions=[],
        summary="Price remains range-bound.",
        source_refs=[{"source": "market_candles", "status": "available"}],
        evidence_refs=[{"artifact_path": "storage/features/technical.json"}],
        status="success",
        created_at=datetime(2026, 5, 31, tzinfo=timezone.utc),
    )

    result = build_runtime_fact_review_agent_output(
        [runtime],
        snapshot_id="snap-runtime-review",
        created_at=datetime(2026, 5, 31, tzinfo=timezone.utc),
    )

    assert result.agent_name == "fact_review_agent"
    assert result.input_payload["fact_review_status"] == "passed"
    reviewed = result.input_payload["reviewed_agent_outputs"][0]
    assert "agent_output_id" not in reviewed
    assert reviewed["claims"][0]["claim_id"] == "technical_agent:summary"


def test_persisted_fact_review_synthesizes_same_summary_claim_as_runtime() -> None:
    persisted = _agent_output(
        agent_name="technical_agent",
        bias="neutral",
        claims=[],
        source_refs=[{"source": "market_candles", "status": "available"}],
    )

    result = build_fact_review_agent_output_payload([persisted])

    assert result["payload"]["fact_review_status"] == "partial"
    reviewed = result["payload"]["reviewed_agent_outputs"][0]
    assert reviewed["claims"][0]["claim_id"] == "technical_agent:summary"
    assert result["payload"]["claim_reviews"][0]["verdict"] == "partially_supported"


def test_build_fact_review_agent_output_payload_reviews_claim_evidence_chain() -> None:
    jin10 = _agent_output(
        agent_name="jin10_report_analysis_agent",
        bias="bullish",
        source_refs=[{"source_id": "src-jin10", "source_name": "Jin10", "source_type": "article", "status": "available"}],
        claims=[
            {
                "claim_id": "claim-supported",
                "text": "地缘风险抬升支撑金价风险溢价。",
                "claim_type": "market_view",
                "source_refs": [{"source_id": "src-jin10", "source_name": "Jin10", "source_type": "article", "status": "available"}],
                "evidence_refs": [{"artifact_path": "storage/outputs/jin10/analysis.md"}],
                "confidence": 0.76,
            }
        ],
    )
    options = _agent_output(
        agent_name="cme_options_agent",
        bias="neutral",
        source_refs=[{"source_id": "src-cme", "source_name": "CME", "source_type": "pdf", "status": "available"}],
        claims=[
            {
                "claim_id": "claim-partial",
                "text": "Gamma Zero 位于 3325。",
                "claim_type": "data_fact",
                "source_refs": [{"source_id": "src-cme", "source_name": "CME", "source_type": "pdf", "status": "available"}],
                "evidence_refs": [],
                "confidence": 0.81,
            },
            {
                "claim_id": "claim-unsupported",
                "text": "上破 3350 后会形成单边趋势。",
                "claim_type": "strategy_condition",
                "source_refs": [],
                "evidence_refs": [],
                "confidence": 0.64,
            },
        ],
    )

    payload = build_fact_review_agent_output_payload([jin10, options])

    assert payload["agent_name"] == "fact_review_agent"
    assert payload["payload"]["fact_review_status"] == "needs_review"
    assert payload["summary"] == "事实审查发现 1 条证据不完整、1 条缺少证据链。"
    assert payload["payload"]["prompt_version"] == "fact_review_rules_v1"
    assert payload["payload"]["prompt_messages"][0]["role"] == "system"
    assert payload["payload"]["input_payload"]["reviewed_agent_outputs"][0]["agent_name"] == "jin10_report_analysis_agent"
    assert payload["payload"]["verdict_counts"] == {
        "supported": 1,
        "partially_supported": 1,
        "unsupported": 1,
        "contradicted": 0,
        "insufficient_evidence": 0,
    }

    claim_reviews = {item["claim_id"]: item for item in payload["payload"]["claim_reviews"]}
    assert claim_reviews["claim-supported"]["verdict"] == "supported"
    assert claim_reviews["claim-partial"]["verdict"] == "partially_supported"
    assert claim_reviews["claim-unsupported"]["verdict"] == "unsupported"
    assert claim_reviews["claim-unsupported"]["reviewer_agent_id"] == "fact_review_agent"


def test_fact_review_does_not_let_one_optional_unavailable_source_poison_claim() -> None:
    output = _agent_output(
        agent_name="macro_liquidity_agent",
        bias="bullish",
        source_refs=[
            {"source_id": "fred:DGS10", "status": "available"},
            {"source_id": "optional:oil", "status": "unavailable"},
        ],
        claims=[
            {
                "claim_id": "claim-mixed-source-health",
                "text": "可用官方利率数据支持当前宏观判断。",
                "source_refs": [
                    {"source_id": "fred:DGS10", "status": "available"},
                    {"source_id": "optional:oil", "status": "unavailable"},
                ],
                "evidence_refs": [],
            }
        ],
    )

    payload = build_fact_review_agent_output_payload([output])

    assert payload["payload"]["fact_review_status"] == "partial"
    assert payload["payload"]["claim_reviews"][0]["verdict"] == "partially_supported"


def test_fact_review_marks_claim_insufficient_when_all_sources_are_unavailable() -> None:
    output = _agent_output(
        agent_name="macro_liquidity_agent",
        bias="neutral",
        source_refs=[
            {"source_id": "optional:one", "status": "unavailable"},
            {"source_id": "optional:two", "status": "failed"},
        ],
        claims=[
            {
                "claim_id": "claim-no-usable-source",
                "text": "当前没有可用来源支持该判断。",
                "source_refs": [
                    {"source_id": "optional:one", "status": "unavailable"},
                    {"source_id": "optional:two", "status": "failed"},
                ],
                "evidence_refs": [{"artifact_path": "storage/outputs/optional.json"}],
            }
        ],
    )

    payload = build_fact_review_agent_output_payload([output])

    assert payload["payload"]["fact_review_status"] == "needs_review"
    assert payload["payload"]["claim_reviews"][0]["verdict"] == "insufficient_evidence"


def test_fact_review_ignores_unavailable_status_summary_without_explicit_claims() -> None:
    supported = _agent_output(
        agent_name="macro_liquidity_agent",
        bias="neutral",
        source_refs=[{"source_id": "macro:daily", "status": "available"}],
        claims=[
            {
                "claim_id": "macro-supported",
                "text": "宏观输入保持中性。",
                "source_refs": [{"source_id": "macro:daily", "status": "available"}],
                "evidence_refs": [{"artifact_path": "storage/features/macro/daily.json"}],
            }
        ],
    )
    unavailable = _agent_output(
        agent_name="positioning_agent",
        status="unavailable",
        bias="unavailable",
        source_refs=[{"source_id": "positioning:daily", "status": "unavailable"}],
        claims=[],
    )

    payload = build_fact_review_agent_output_payload([supported, unavailable])

    assert payload["payload"]["fact_review_status"] == "passed"
    assert [item["claim_id"] for item in payload["payload"]["claim_reviews"]] == ["macro-supported"]


def test_build_fact_review_agent_output_payload_keeps_cross_variable_biases_supported() -> None:
    bullish = _agent_output(
        agent_name="macro_liquidity_agent",
        bias="bullish",
        confidence=0.83,
        source_refs=[{"source_id": "src-jin10", "source_name": "Jin10", "source_type": "article", "status": "available"}],
        claims=[
            {
                "claim_id": "claim-bull",
                "text": "实际利率回落改善黄金的宏观流动性条件。",
                "claim_type": "market_view",
                "source_refs": [{"source_id": "src-jin10", "source_name": "Jin10", "source_type": "article", "status": "available"}],
                "evidence_refs": [{"artifact_path": "storage/outputs/jin10/analysis.md"}],
                "confidence": 0.83,
            }
        ],
    )
    bearish = _agent_output(
        agent_name="technical_agent",
        bias="bearish",
        confidence=0.79,
        source_refs=[{"source_id": "src-cme", "source_name": "CME", "source_type": "pdf", "status": "available"}],
        claims=[
            {
                "claim_id": "claim-bear",
                "text": "技术形态显示 3300 下方存在短期下行风险。",
                "claim_type": "market_view",
                "source_refs": [{"source_id": "src-cme", "source_name": "CME", "source_type": "pdf", "status": "available"}],
                "evidence_refs": [{"artifact_path": "storage/outputs/technical/analysis.md"}],
                "confidence": 0.79,
            }
        ],
    )

    options_bearish = _agent_output(
        agent_name="cme_options_agent",
        bias="bearish",
        confidence=0.79,
        source_refs=[{"source_id": "src-cme", "source_name": "CME", "source_type": "pdf", "status": "available"}],
        claims=[
            {
                "claim_id": "claim-options-bear",
                "text": "期权仓位在 3300 上方形成短期上行阻力。",
                "claim_type": "market_view",
                "source_refs": [{"source_id": "src-cme", "source_name": "CME", "source_type": "pdf", "status": "available"}],
                "evidence_refs": [{"artifact_path": "storage/outputs/cme/options_analysis.md"}],
                "confidence": 0.79,
            }
        ],
    )

    payload = build_fact_review_agent_output_payload([bullish, bearish, options_bearish])

    assert payload["payload"]["fact_review_status"] == "passed"
    claim_reviews = {item["claim_id"]: item for item in payload["payload"]["claim_reviews"]}
    assert claim_reviews["claim-bull"]["verdict"] == "supported"
    assert claim_reviews["claim-bear"]["verdict"] == "supported"
    assert claim_reviews["claim-options-bear"]["verdict"] == "supported"
    assert payload["payload"]["conflicted_claim_ids"] == []


def test_persist_fact_review_agent_output_is_idempotent() -> None:
    session = _session()
    domain_output = _agent_output(
        agent_name="jin10_report_analysis_agent",
        bias="bullish",
        source_refs=[{"source_id": "src-jin10", "source_name": "Jin10", "source_type": "article", "status": "available"}],
        claims=[
            {
                "claim_id": "claim-supported",
                "text": "地缘风险抬升支撑金价风险溢价。",
                "claim_type": "market_view",
                "source_refs": [{"source_id": "src-jin10", "source_name": "Jin10", "source_type": "article", "status": "available"}],
                "evidence_refs": [{"artifact_path": "storage/outputs/jin10/analysis.md"}],
                "confidence": 0.76,
            }
        ],
    )
    session.add(domain_output)
    session.commit()

    first = persist_fact_review_agent_output(session, snapshot_id="snap-review-001")
    session.commit()
    second = persist_fact_review_agent_output(session, snapshot_id="snap-review-001")
    session.commit()

    assert first["agent_output_id"] == second["agent_output_id"]
    rows = session.scalars(select(AgentOutput).where(AgentOutput.agent_name == "fact_review_agent")).all()
    assert len(rows) == 1
    assert rows[0].payload["fact_review_status"] == "passed"
    assert rows[0].payload["reviewed_agent_outputs"][0]["agent_name"] == "jin10_report_analysis_agent"


def test_persist_fact_review_agent_output_creates_review_items_for_review_worthy_claims() -> None:
    session = _session()
    session.add(
        ReportItem(
            report_id="report-review-001",
            family="macro",
            title="Macro report",
            asset="XAUUSD",
            trade_date=date(2026, 5, 31),
            run_id="run-review-001",
            snapshot_id="snap-review-001",
            data_status="live",
            lifecycle_status="generated",
            source_refs=[],
            report_metadata={},
        )
    )
    session.add_all(
        [
            _agent_output(
                agent_name="jin10_report_analysis_agent",
                bias="bullish",
                source_refs=[
                    {
                        "source_id": "src-jin10",
                        "source_name": "Jin10",
                        "source_type": "article",
                        "status": "available",
                    }
                ],
                claims=[
                    {
                        "claim_id": "claim-unsupported",
                        "text": "地缘风险会单边推升金价。",
                        "claim_type": "market_view",
                        "source_refs": [],
                        "evidence_refs": [],
                        "confidence": 0.71,
                    }
                ],
            ),
            _agent_output(
                agent_name="cme_options_agent",
                bias="bearish",
                source_refs=[
                    {
                        "source_id": "src-cme",
                        "source_name": "CME",
                        "source_type": "pdf",
                        "status": "available",
                    }
                ],
                claims=[
                    {
                        "claim_id": "claim-contradicted",
                        "text": "结构仍偏空。",
                        "claim_type": "market_view",
                        "source_refs": [
                            {
                                "source_id": "src-cme",
                                "source_name": "CME",
                                "source_type": "pdf",
                                "status": "available",
                            }
                        ],
                        "evidence_refs": [{"artifact_path": "storage/outputs/cme/options_analysis.md"}],
                        "confidence": 0.68,
                    }
                ],
            ),
        ]
    )
    session.commit()

    persist_fact_review_agent_output(session, snapshot_id="snap-review-001")
    session.commit()

    reviews = {item.claim_id: item for item in list_review_items(session)}
    assert set(reviews) == {"claim-unsupported"}
    assert reviews["claim-unsupported"].agent_output_id is not None
    assert reviews["claim-unsupported"].source_refs[0]["source_id"] == "src-jin10"
    assert reviews["claim-unsupported"].impact_report_ids == ["report-review-001"]
    assert "report_detail" in reviews["claim-unsupported"].impact_modules
