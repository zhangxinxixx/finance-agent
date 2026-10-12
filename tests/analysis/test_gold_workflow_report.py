import pytest
from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace

from apps.analysis.agents.coordinator import coordinate_agent_outputs
from apps.analysis.agents.research_context import build_research_assessment
from apps.analysis.agents.research_synthesis import enrich_research_coordinator
from apps.features.research.workflow import build_gold_workflow
from apps.renderer.markdown.final_report import build_structured_report, render_final_report_markdown
from tests.analysis.test_daily_research import _snapshot


def test_v2_report_preserves_legacy_and_projects_exact_same_sections():
    snapshot = _snapshot()
    now = datetime(2026, 9, 5, 16, tzinfo=UTC)
    old_assessment = build_research_assessment(snapshot)
    kwargs = dict(snapshot=snapshot, macro_output=None, options_output=None, risk_output=None, coordinator_output=None, created_at=now)
    with pytest.raises(ValueError, match="research report blocked"):
        build_structured_report(**kwargs, research_assessment=old_assessment)
    legacy_snapshot = deepcopy(snapshot)
    legacy_snapshot.pop("daily_research", None)
    legacy = build_structured_report(**{**kwargs, "snapshot": legacy_snapshot})
    assert legacy.version.report_version == "1.0.0"
    snapshot["gold_workflow"] = build_gold_workflow(snapshot)
    assessment = build_research_assessment(snapshot)
    with pytest.raises(ValueError, match="research report blocked"):
        render_final_report_markdown(**kwargs, research_assessment=assessment)
    from apps.renderer.markdown.gold_workflow import gold_workflow_sections
    from apps.renderer.markdown.daily_research import render_daily_research_report
    sections = gold_workflow_sections(snapshot, {}, assessment)
    markdown = render_daily_research_report(snapshot, sections)
    assert [x['section_id'] for x in sections] == [
        "data_passport", "research_summary", "delta_vs_previous", "unified_factor_table",
        "macro_diagnosis", "funds", "current_state", "key_level_lifecycle",
        "three_scenarios", "execution_card", "risk_list", "final_assessment", "analysis_sources",
    ]
    assert all(x['body'] in markdown for x in sections)
    assert "最新价格锚点未完全验证" in markdown
    assert "不是统计概率" in markdown
    assert "当前快照没有完整且同步" in markdown
    assert "本次 CME 输入不可用" in markdown


def test_final_agent_explanation_is_visible_and_cannot_set_direction():
    import json

    snapshot = _snapshot()
    snapshot["daily_research"]["passport"].append({"symbol": "XAUUSD_DAILY", "value": 4000, "unit": "USD/oz", "status": "fresh",
        "observation_date": "2026-09-04", "source_refs": [{"source": "twelvedata_xauusd_daily", "symbol": "XAUUSD", "instrument_type": "spot",
        "source_url": "https://example.test/spot", "raw_path": "raw/test.json", "retrieved_at": "2026-09-05T15:00:00Z"}]})
    snapshot["gold_workflow"] = build_gold_workflow(snapshot)
    original = coordinate_agent_outputs(snapshot, macro_output=None, options_output=None, risk_output=None)
    answer = {"dominant_factor": "当前输入不足以确认同向宏观冲击。", "counter_evidence": ["美元比较窗口缺失。"], "state_limitations": ["正式状态前序未确认。"], "convergence_transition": ["价格结构与利率和美元共同确认后重评。"], "evidence_ids": ["real_rate"],
              "independent_assessment": "[MODEL] 我不同意把当前规则压力排序视为趋势确认，更倾向等待区间证据。",
              "module_challenges": ["技术模块的短窗方向不等于宏观资金已确认。"],
              "alternative_hypotheses": ["[假设] 若资金回归且实际利率回落，可观察 4555 附近修复；价格跌破并无承接时失效。"],
              "what_would_change_my_mind": ["新融资价格和同窗口美元证据会改变我的判断。"]}
    gateway = SimpleNamespace(chat_sync=lambda **kwargs: SimpleNamespace(content=json.dumps(answer), model="test", provider="test"))
    enriched = enrich_research_coordinator(snapshot, original, gateway=gateway)
    assert enriched.bias == original.bias
    assert enriched.confidence == original.confidence
    assert enriched.accepted_state_conclusion == original.accepted_state_conclusion
    md = render_final_report_markdown(snapshot=snapshot, macro_output=None, options_output=None, risk_output=None, coordinator_output=enriched, research_assessment=build_research_assessment(snapshot))
    assert answer["counter_evidence"][0] in md
    assert answer["convergence_transition"][0] in md
    assert "执行方式：llm" in md
    assert answer["independent_assessment"] in md
    assert answer["module_challenges"][0] in md
    assert answer["alternative_hypotheses"][0] in md
    assert answer["what_would_change_my_mind"][0] in md
    assert "模型新增数值提及：4555" in md
    assert "未提升为系统事实" in md


def test_v3_adaptive_research_audit_shows_why_data_was_selected():
    snapshot = _snapshot()
    snapshot['adaptive_research'] = {
        'schema_version': 'adaptive_research.v3', 'status': 'partial',
        'stop_reason': 'evidence_unavailable', 'budget_used': {'collection_rounds': 1},
        'unavailable_data_needs': [{'data': 'OTC买方身份', 'reason': '能力目录不支持',
                                    'decision_impact': '限制残差归因', 'materiality': 'decisive'}],
        'rounds': [{'decision_index': 1, 'new_evidence_count': 1,
                    'decision_ref': {'path': 'analysis/research/decision.json'},
                    'plan': {'action': 'continue', 'question': '是否为避险买盘？',
                             'driver_assessment': '黄金与实际利率背离', 'hypothesis': '风险厌恶',
                             'evidence_assessment': '需要跨资产验证',
                             'data_requests': [{'provider': 'tradingview', 'key': 'CBOE:VIX',
                                                'freshness_need': 'intraday', 'claim': '检验风险厌恶',
                                                'decision_impact': '改变主导驱动'}]}}],
    }
    snapshot['gold_workflow'] = build_gold_workflow(snapshot)
    assessment = build_research_assessment(snapshot)
    with pytest.raises(ValueError, match="research report blocked"):
        render_final_report_markdown(snapshot=snapshot, macro_output=None, options_output=None, risk_output=None,
            coordinator_output=None, research_assessment=assessment, created_at=datetime(2026, 9, 5, 16, tzinfo=UTC))
    from apps.renderer.markdown.gold_workflow import gold_workflow_sections
    from apps.renderer.markdown.daily_research import render_daily_research_report
    markdown = render_daily_research_report(snapshot, gold_workflow_sections(snapshot, {}, assessment))
    assert '选择 tradingview:CBOE:VIX' in markdown
    assert '验证“检验风险厌恶”' in markdown
    assert 'OTC买方身份' in markdown
    assert '限制残差归因' in markdown
