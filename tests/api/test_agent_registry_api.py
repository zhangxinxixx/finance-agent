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


def test_api_agent_registry_detail_404_for_unknown_agent() -> None:
    with pytest.raises(Exception) as exc:
        api_agent_registry_detail("missing_agent")

    assert getattr(exc.value, "status_code", None) == 404
