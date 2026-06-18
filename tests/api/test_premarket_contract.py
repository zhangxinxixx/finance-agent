from __future__ import annotations

from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.services.pipeline_contract_service import build_premarket_pipeline_contract
from apps.premarket import PREMARKET_STEP_ORDER, get_premarket_step_contracts

client = TestClient(app)


def test_premarket_contract_keeps_canonical_order() -> None:
    contract = build_premarket_pipeline_contract()
    assert contract["step_order"] == list(PREMARKET_STEP_ORDER)
    assert [step["name"] for step in contract["steps"]] == list(PREMARKET_STEP_ORDER)
    assert [step["order"] for step in contract["steps"]] == list(range(len(PREMARKET_STEP_ORDER)))


def test_premarket_contract_classifies_pipeline_groups() -> None:
    contract = build_premarket_pipeline_contract()
    assert contract["pipeline_groups"] == {
        "macro": ["macro_collect", "macro_feature", "report_render"],
        "cme": ["cme_download", "cme_parse", "cme_ingest", "option_wall"],
        "news": ["news_collect", "news_feature", "news_brief"],
        "other": ["strategy_card"],
    }


def test_premarket_contract_keeps_same_pipeline_dependencies_isolated() -> None:
    contracts = {step.name: step for step in get_premarket_step_contracts()}

    same_pipeline_steps = {
        "macro": {"macro_collect", "macro_feature", "report_render"},
        "cme": {"cme_download", "cme_parse", "cme_ingest", "option_wall"},
        "news": {"news_collect", "news_feature", "news_brief"},
    }

    for pipeline, step_names in same_pipeline_steps.items():
        for step_name in step_names:
            step = contracts[step_name]
            assert step.pipeline_group == pipeline
            assert step.blocked_scope == pipeline
            assert set(step.upstream_dependencies).issubset(step_names)

    strategy_card = contracts["strategy_card"]
    assert strategy_card.pipeline_group == "other"
    assert strategy_card.stage == "summary"
    assert strategy_card.type == "summary"
    assert strategy_card.blocked_scope == "none"
    assert strategy_card.upstream_dependencies == ("report_render", "option_wall", "news_brief")


def test_premarket_contract_api_exposes_canonical_contract() -> None:
    resp = client.get("/api/pipelines/premarket/contract")

    assert resp.status_code == 200
    body = resp.json()
    assert body["step_order"] == list(PREMARKET_STEP_ORDER)
    assert [step["name"] for step in body["steps"]] == list(PREMARKET_STEP_ORDER)
    assert body["pipeline_groups"]["cme"] == ["cme_download", "cme_parse", "cme_ingest", "option_wall"]
