import pytest

from apps.api.main import api_agent_registry_detail, api_agents_registry


def test_api_agents_registry_returns_prompt_templates() -> None:
    response = api_agents_registry()
    agents = {item["agent_id"]: item for item in response["agents"]}

    assert response["source"] == "agent_registry"
    assert "macro_liquidity_agent" in agents
    assert "jin10_report_analysis_agent" in agents
    assert "macro_event_followup_agent" in agents
    assert "cme_options_agent" in agents
    assert "jin10_flash_semantic_filter_agent" in agents
    assert agents["macro_liquidity_agent"]["prompt"]["template"]
    assert agents["macro_liquidity_agent"]["prompt"]["kind"] == "llm"
    assert agents["jin10_report_analysis_agent"]["prompt"]["template"]
    assert agents["cme_options_agent"]["prompt"]["template"]
    assert agents["macro_event_followup_agent"]["prompt"]["template"]
    assert agents["macro_event_followup_agent"]["prompt"]["kind"] == "llm"
    flash_prompt = agents["jin10_flash_semantic_filter_agent"]["prompt"]
    assert flash_prompt["template"]["messages"]
    assert "flash_items_json" in flash_prompt["template"]["variables"]


def test_api_agents_registry_includes_gold_v3_fixed_runtime_agents() -> None:
    response = api_agents_registry()
    agents = {item["agent_id"]: item for item in response["agents"]}

    expected_agents = {
        "source_health_agent": ("source_health_check", "每 15-30 分钟 / 每次任务前"),
        "event_attribution_agent": ("mainline_attribution", "有新新闻/报告输入时"),
        "transmission_chain_agent": ("transmission_chain_detection", "有地缘/油价/利率变化时"),
        "driver_decomposition_agent": ("driver_decomposition", "每次出现 mixed 判断时"),
        "mainline_ranking_agent": ("gold_mainline_agent", "每日固定 + 重大事件触发"),
        "gold_macro_overview_agent": ("gold_macro_overview", "每日固定 + 主线变化时"),
        "review_gate_agent": ("processing_monitor", "每次输出前"),
        "report_render_agent": ("daily_report", "每日收盘/盘前"),
    }

    for agent_id, (dag_node_id, run_frequency) in expected_agents.items():
        agent = agents[agent_id]
        assert agent["status"] == "planned_prompt"
        assert agent["dag_node_id"] == dag_node_id
        assert agent["run_frequency"] == run_frequency
        assert agent["prompt"]["kind"] == "llm"
        assert agent["prompt"]["template"]["messages"]
        assert agent["prompt"]["template"]["output_schema"]
        assert agent["prompt"]["template"]["dag_node_id"] == dag_node_id
        assert agent["input_sections"]
        assert agent["output_targets"]
        assert not any(str(target).startswith(("raw/", "parsed/", "features/")) for target in agent["output_targets"])

    event_prompt = agents["event_attribution_agent"]["prompt"]["template"]
    assert "fed_policy_path" in event_prompt["gold_mainlines"]
    assert "war_oil_rate_chain" in event_prompt["transmission_chains"]
    assert "bullish_drivers" in event_prompt["output_schema"]
    assert "bearish_drivers" in event_prompt["output_schema"]

    overview_prompt = agents["gold_macro_overview_agent"]["prompt"]["template"]
    assert overview_prompt["output_schema"]["asset"] == "XAUUSD"
    assert "processing_traces" in overview_prompt["output_schema"]


def test_api_agents_registry_includes_gold_v3_development_governance_agents() -> None:
    response = api_agents_registry()
    agents = {item["agent_id"]: item for item in response["agents"]}

    expected_agents = {
        "architecture_agent": "页面职责与能力落层治理",
        "schema_agent": "TypeScript / 后端 schema 字段治理",
        "dag_lineage_agent": "DAG 和 trace mode 链路治理",
        "test_validation_agent": "schema / DAG / mixed / 页面绑定测试治理",
    }

    for agent_id, governance_scope in expected_agents.items():
        agent = agents[agent_id]
        assert agent["status"] == "planned_governance"
        assert agent["agent_type"] == "development_governance_agent"
        assert agent["governance_scope"] == governance_scope
        assert agent["proposal_only"] is True
        assert agent["prompt"]["kind"] == "llm"
        assert agent["prompt"]["template"]["messages"]
        assert agent["prompt"]["template"]["output_schema"]
        assert agent["prompt"]["template"]["proposal_only"] is True
        assert "raw" in agent["prompt"]["template"]["forbidden_mutation_layers"]
        assert "parsed" in agent["prompt"]["template"]["forbidden_mutation_layers"]
        assert "features" in agent["prompt"]["template"]["forbidden_mutation_layers"]
        assert not any(str(target).startswith(("raw/", "parsed/", "features/")) for target in agent["output_targets"])

    dag_prompt = agents["dag_lineage_agent"]["prompt"]["template"]
    assert "source_ref" in dag_prompt["output_schema"]["checks"]
    assert "frontend_slot" in dag_prompt["output_schema"]["checks"]


def test_api_agent_registry_detail_404_for_unknown_agent() -> None:
    with pytest.raises(Exception) as exc:
        api_agent_registry_detail("missing_agent")

    assert getattr(exc.value, "status_code", None) == 404
