from apps.analysis.agents.registry import get_agent_registry, list_agent_registry, resolve_agent_runtime_meta


def test_agent_registry_prioritizes_jin10_and_options_prompts() -> None:
    agents = {item["agent_id"]: item for item in list_agent_registry()}

    assert agents["jin10_report_analysis_agent"]["priority"] == "P0"
    assert agents["cme_options_agent"]["priority"] == "P0"
    assert agents["jin10_report_analysis_agent"]["prompt"]["kind"] == "llm"
    assert agents["cme_options_agent"]["prompt"]["kind"] == "hybrid"


def test_jin10_registry_exposes_reviewable_prompt_template() -> None:
    agent = get_agent_registry("jin10_report_analysis_agent")

    assert agent is not None
    template = agent["prompt"]["template"]
    assert "你是一名专业的宏观市场与贵金属分析 Agent" in template
    assert "{{article_markdown}}" in template
    assert "Agent 入库字段" in template


def test_cme_options_registry_exposes_reviewable_prompt_template() -> None:
    agent = get_agent_registry("cme_options_agent")

    assert agent is not None
    template = agent["prompt"]["template"]
    assert "你是一位专业 CME / COMEX 黄金期权结构分析师" in template
    assert "{{gamma_zero_price}}" in template
    assert "WallScore 表必须包含 dominant_side" in template


def test_fact_review_registry_exposes_rule_template() -> None:
    agent = get_agent_registry("fact_review_agent")

    assert agent is not None
    assert agent["status"] == "active_rules"
    assert agent["prompt"]["kind"] == "rule"
    template = agent["prompt"]["template"]
    assert "事实审查 Agent" in template
    assert "supported / partially_supported / unsupported / contradicted / insufficient_evidence" in template


def test_agent_registry_returns_none_for_unknown_agent() -> None:
    assert get_agent_registry("unknown_agent") is None


def test_resolve_agent_runtime_meta_for_jin10_report_agent() -> None:
    meta = resolve_agent_runtime_meta("jin10_report_analysis_agent")

    assert meta["display_name"] == "金十报告分析"
    assert meta["role"] == "report_agent"
    assert meta["registry_id"] == "jin10_report_analysis_agent"
