from __future__ import annotations

from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.services.agent_analysis_service import build_agent_analysis_inspection
from database.models.analysis import AgentOutput, AnalysisBase, AnalysisSnapshot, PromptVersion


def _session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    AnalysisBase.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return factory()


def test_agent_analysis_inspection_exposes_prompt_input_and_output() -> None:
    db = _session()
    snapshot = AnalysisSnapshot(
        snapshot_id="snap-io-001",
        asset="XAUUSD",
        trade_date=date(2026, 5, 31),
        run_id="run-io-001",
        status="success",
        input_snapshot_ids={"macro": "macro-001"},
        source_refs=[{"source_id": "fred"}],
        macro={"indicators": {"DXY": {"value": 99.5}}},
        payload={
            "snapshot_id": "snap-io-001",
            "trade_date": "2026-05-31",
            "macro": {"indicators": {"DXY": {"value": 99.5}}},
        },
        payload_sha256="snapshot",
        artifact_path="storage/features/snap-io-001/analysis_snapshot.json",
    )
    output = AgentOutput(
        snapshot_id="snap-io-001",
        asset="XAUUSD",
        trade_date=date(2026, 5, 31),
        run_id="run-io-001",
        agent_name="market_regime",
        module="market_monitor",
        version="1.0",
        status="success",
        bias="neutral",
        confidence=0.61,
        input_snapshot_ids={"macro": "snap-io-001"},
        source_refs=[{"source_id": "fred"}],
        key_findings=["方向抉择态"],
        risk_points=["数据冲突"],
        watchlist=["DXY"],
        invalid_conditions=["利率反转"],
        summary="市场处于方向抉择态。",
        payload={
            "prompt_messages": [
                {"role": "system", "content": "你是市场状态分析师。只输出 JSON。"},
                {"role": "user", "content": "请判断 regime"},
            ],
            "input_payload": {"macro_snapshot": {"indicators": {"DXY": {"value": 99.5}}}},
            "llm_raw_output": '{"regime":"direction_choice"}',
        },
        payload_sha256="agent",
        llm_model="test-model",
        token_usage={"prompt_tokens": 10, "completion_tokens": 5},
        llm_elapsed_seconds=1.2,
    )
    db.add_all([snapshot, output])
    db.commit()

    payload = build_agent_analysis_inspection(db, date(2026, 5, 31), run_id="run-io-001")

    assert payload["trade_date"] == "2026-05-31"
    assert payload["run_id"] == "run-io-001"
    agent = payload["agents"][0]
    assert agent["agent_output_id"] == output.id
    assert agent["agent_name"] == "market_regime"
    assert agent["display_name"] == "市场状态"
    assert agent["role"] == "domain_agent"
    assert agent["prompt"]["available"] is True
    assert agent["prompt"]["messages"][1]["content"] == "请判断 regime"
    assert agent["input"]["payload"]["macro_snapshot"]["indicators"]["DXY"]["value"] == 99.5
    assert agent["output"]["summary"] == "市场处于方向抉择态。"
    assert agent["output"]["summary_zh"] == "市场处于方向抉择态。"
    assert agent["output"]["llm_raw_output"] == '{"regime":"direction_choice"}'
    assert agent["output"]["claims"] == []
    assert agent["output"]["claim_reviews"] == []


def test_agent_analysis_inspection_resolves_prompt_metadata_from_prompt_version_id() -> None:
    db = _session()
    prompt_version = PromptVersion(
        id="pv-market-regime-v1",
        agent_id="market_regime",
        version="v1",
        prompt_kind="llm",
        prompt_source="apps/analysis/agents/market_regime_prompt.py",
        prompt_template={"messages": [{"role": "user", "content": "judge regime"}]},
        prompt_sha256="1" * 64,
        status="active",
        enabled=True,
    )
    output = AgentOutput(
        snapshot_id="snap-prompt-inspect-001",
        asset="XAUUSD",
        trade_date=date(2026, 5, 31),
        run_id="run-prompt-inspect-001",
        agent_name="market_regime",
        module="market_monitor",
        version="1.0",
        status="success",
        bias="neutral",
        confidence=0.61,
        input_snapshot_ids={"macro": "snap-prompt-inspect-001"},
        source_refs=[],
        key_findings=[],
        risk_points=[],
        watchlist=[],
        invalid_conditions=[],
        summary="市场处于方向抉择态。",
        payload={"prompt_messages": [{"role": "user", "content": "judge regime"}]},
        payload_sha256="agent",
        llm_model="test-model",
        prompt_version_id=prompt_version.id,
    )
    db.add_all([prompt_version, output])
    db.commit()

    payload = build_agent_analysis_inspection(db, date(2026, 5, 31), run_id="run-prompt-inspect-001")

    agent = payload["agents"][0]
    assert agent["prompt_version_id"] == "pv-market-regime-v1"
    assert agent["prompt"]["prompt_id"] == "market_regime_prompt"
    assert agent["prompt"]["version"] == "v1"
    assert agent["prompt"]["checksum"] == "1" * 64
    assert agent["prompt"]["source_file"] == "apps/analysis/agents/market_regime_prompt.py"
    assert agent["output"]["prompt_id"] == "market_regime_prompt"
    assert agent["output"]["prompt_version"] == "v1"
    assert agent["output"]["prompt_checksum"] == "1" * 64


def test_agent_analysis_inspection_marks_rule_agent_prompt_as_not_applicable() -> None:
    db = _session()
    output = AgentOutput(
        snapshot_id="snap-rule-001",
        asset="XAUUSD",
        trade_date=date(2026, 5, 31),
        run_id="run-rule-001",
        agent_name="macro_liquidity_agent",
        module="macro",
        version="1.0",
        status="success",
        bias="bullish",
        confidence=0.72,
        input_snapshot_ids={"macro": "snap-rule-001"},
        source_refs=[],
        key_findings=[],
        risk_points=[],
        watchlist=[],
        invalid_conditions=[],
        summary="宏观流动性偏多。",
        payload={"summary": "宏观流动性偏多。"},
        payload_sha256="agent",
    )
    db.add(output)
    db.commit()

    payload = build_agent_analysis_inspection(db, date(2026, 5, 31), run_id="run-rule-001")

    agent = payload["agents"][0]
    assert agent["agent_output_id"] == output.id
    assert agent["display_name"] == "宏观流动性"
    assert agent["prompt"]["kind"] == "rule"
    assert agent["prompt"]["available"] is False
    assert agent["prompt"]["note"] == "规则型 Agent 未使用 LLM prompt。"
    assert agent["output"]["summary"] == "宏观流动性偏多。"
    assert agent["output"]["summary_zh"] == "宏观流动性偏多。"
    assert agent["output"]["claims"] == []
    assert agent["output"]["claim_reviews"] == []


def test_agent_analysis_inspection_exposes_jin10_report_agent_io() -> None:
    db = _session()
    output = AgentOutput(
        snapshot_id="jin10:2026-05-06:218330:agent_analysis",
        asset="XAUUSD",
        trade_date=date(2026, 5, 6),
        run_id="218330",
        agent_name="jin10_report_analysis_agent",
        module="jin10_reports",
        version="1.0",
        status="success",
        bias="neutral",
        confidence=0.64,
        input_snapshot_ids={
            "jin10_raw_article_report": "jin10:2026-05-06:218330:raw_article_report",
            "jin10_daily_visual": "jin10:2026-05-06:218330:daily_analysis",
        },
        source_refs=[{"source": "jin10_external", "article_id": "218330"}],
        key_findings=["市场阶段：方向抉择态"],
        risk_points=["若利率继续上行，黄金修复路径可能降级。"],
        watchlist=["10年期美债收益率"],
        invalid_conditions=["跌破关键平衡区后无法收回。"],
        summary="黄金仍处在等待确认的方向抉择阶段。",
        payload={
            "prompt_version": "jin10_agent_analysis_v2",
            "prompt_messages": [
                {"role": "system", "content": "你是一名专业的宏观市场与贵金属分析 Agent，默认使用简体中文。"},
                {"role": "user", "content": "请输出 Agent 二次分析报告。"},
            ],
            "input_payload": {
                "raw_report": {"article_id": "218330", "title": "测试金十报告"},
                "daily_report": {"family": "jin10_daily_visual", "core_conclusion": "证据不足"},
            },
            "llm_raw_output": "# 测试金十报告｜Agent 二次分析报告",
            "narrative_md": "# 测试金十报告｜Agent 二次分析报告",
            "claims": [{"claim_id": "218330:one_line_conclusion", "text": "黄金仍处在等待确认的方向抉择阶段。"}],
            "artifact_refs": ["storage/outputs/jin10/2026-05-06/218330/agent_analysis_report.md"],
        },
        payload_sha256="jin10-agent",
    )
    db.add(output)
    db.commit()

    payload = build_agent_analysis_inspection(db, date(2026, 5, 6), run_id="218330")

    agent = payload["agents"][0]
    assert agent["agent_output_id"] == output.id
    assert agent["display_name"] == "金十报告分析"
    assert agent["registry_id"] == "jin10_report_analysis_agent"
    assert agent["role"] == "report_agent"
    assert agent["prompt"]["available"] is True
    assert agent["input"]["payload"]["raw_report"]["article_id"] == "218330"
    assert agent["output"]["summary"] == "黄金仍处在等待确认的方向抉择阶段。"
    assert agent["output"]["payload"]["prompt_version"] == "jin10_agent_analysis_v2"
    assert agent["output"]["llm_raw_output"] == "# 测试金十报告｜Agent 二次分析报告"
    assert agent["output"]["claims"][0]["claim_id"] == "218330:one_line_conclusion"
    assert agent["output"]["claims"][0]["claim_type"] == "market_view"
    assert agent["output"]["claim_reviews"] == []


def test_agent_analysis_inspection_exposes_cme_options_prompt_and_artifacts() -> None:
    db = _session()
    output = AgentOutput(
        snapshot_id="options:2026-05-06:options-sample",
        asset="XAUUSD",
        trade_date=date(2026, 5, 6),
        run_id="options-sample",
        agent_name="cme_options_agent",
        module="options",
        version="1.0",
        status="success",
        bias="neutral",
        confidence=0.58,
        input_snapshot_ids={"options_analysis_snapshot": "options:2026-05-06:options-sample"},
        source_refs=[
            {
                "source": "cme_daily_bulletin",
                "report_date": "2026-05-06",
                "source_url": "https://example.test/cme/2026-05-06.pdf",
            }
        ],
        key_findings=["Aggregate gamma zero is 4195."],
        risk_points=["PRELIM 数据可能修订。"],
        watchlist=["gamma zero", "wall scores"],
        invalid_conditions=["站不稳 4200。"],
        summary="Gamma Zero 附近仍是短线主战区。",
        payload={
            "prompt_version": "cme_options_agent_v1",
            "prompt_messages": [
                {"role": "system", "content": "你是一位专业 CME / COMEX 黄金期权结构分析师。只输出 Markdown 正文。"},
                {"role": "user", "content": "请基于结构化快照输出分析报告。"},
            ],
            "input_payload": {"options_snapshot": {"trade_date": "2026-05-06", "product": "OG"}},
            "narrative_md": "# CME 黄金期权结构分析报告 — 2026-05-06",
            "llm_raw_output": "## 一句话结论\nGamma Zero 附近仍是短线主战区。",
            "artifact_refs": ["storage/outputs/cme_options/2026-05-06/options_analysis_agent_report.md"],
            "claims": [{"claim_id": "options:summary", "text": "Gamma Zero 附近仍是短线主战区。"}],
        },
        payload_sha256="cme-options-agent",
    )
    db.add(output)
    db.commit()

    payload = build_agent_analysis_inspection(db, date(2026, 5, 6), run_id="options-sample")

    agent = payload["agents"][0]
    assert agent["agent_output_id"] == output.id
    assert agent["display_name"] == "期权结构"
    assert agent["registry_id"] == "cme_options_agent"
    assert agent["role"] == "domain_agent"
    assert agent["prompt"]["available"] is True
    assert agent["input"]["source_refs"][0]["data_date"] == "2026-05-06"
    assert agent["input"]["source_refs"][0]["url"] == "https://example.test/cme/2026-05-06.pdf"
    assert agent["input"]["payload"]["options_snapshot"]["product"] == "OG"
    assert agent["output"]["summary"] == "Gamma Zero 附近仍是短线主战区。"
    assert agent["output"]["payload"]["prompt_version"] == "cme_options_agent_v1"
    assert agent["output"]["payload"]["artifact_refs"][-1].endswith("options_analysis_agent_report.md")
    assert agent["output"]["claims"][0]["claim_id"] == "options:summary"
    assert agent["output"]["claims"][0]["claim_type"] == "market_view"
    assert agent["output"]["claim_reviews"] == []
