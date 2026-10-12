from __future__ import annotations

import json
from datetime import datetime, timezone

from apps.analysis.agents.research_synthesis import enrich_research_coordinator
from apps.analysis.agents.schemas import AgentBias, AgentOutput, AgentStatus, DataCategory

def test_context_compaction_preserves_numbers_dates_and_source_urls():
    from copy import deepcopy
    from apps.analysis.agents.research_synthesis import _compact_json

    value = {'price': 4383.12, 'observation_date': '2026-09-10', 'status': 'partial',
             'source_refs': [{'source_url': 'https://fred.stlouisfed.org/series/DFII10', 'raw_path': 'raw/large.json'}],
             'nested': {'value': 2.46, 'method': 'official_TIPS'}}
    before = deepcopy(value)
    compact = _compact_json(value)
    assert value == before
    assert compact['price'] == value['price']
    assert compact['nested'] == value['nested']
    assert compact['observation_date'] == value['observation_date']
    assert compact['status'] == 'partial'
    assert compact['source_urls'] == ['https://fred.stlouisfed.org/series/DFII10']
    assert 'source_refs' not in compact


def _output(*, payload: dict | None = None) -> AgentOutput:
    output = AgentOutput(
        version="1.0",
        agent_name="coordinator_agent",
        module="coordinator",
        snapshot_id="snapshot-v2",
        input_snapshot_ids={"analysis_snapshot": "snapshot-v2"},
        bias=AgentBias.MIXED,
        confidence=0.35,
        key_findings=["规则综合结论"],
        risk_points=["规则风险"],
        watchlist=["后续数据"],
        invalid_conditions=["正式状态链未确认"],
        summary="规则摘要",
        source_refs=[{"source": "fixture", "reference": "fixture:research"}],
        status=AgentStatus.PARTIAL,
        created_at=datetime(2026, 9, 8, tzinfo=timezone.utc),
        data_category=DataCategory.SYSTEM_INFERENCE,
        evidence_items=[
            {
                "factor_id": "real_yield",
                "family": "rates",
                "rationale": "实际利率代理仍是主要机会成本证据",
            },
            {
                "factor_id": "spot_confirmation",
                "family": "price",
                "rationale": "现货结构需要同窗口确认",
            },
        ],
        input_payload=payload
        or {
            "daily_research_assessment": {
                "adjudication": {
                    "factors": [
                        {
                            "factor_id": "real_yield",
                            "family": "rates",
                            "role": "primary",
                            "bias": "bearish",
                            "rationale": "实际利率代理仍是主要机会成本证据",
                        },
                        {
                            "factor_id": "spot_confirmation",
                            "family": "price",
                            "role": "context",
                            "bias": "neutral",
                            "rationale": "现货结构需要同窗口确认",
                        },
                    ]
                }
            }
        },
    )
    from apps.analysis.snapshots.input_validation import prepare_analysis_inputs
    return output.model_copy(update={"input_payload": {**output.input_payload,
        "input_validation": prepare_analysis_inputs(_snapshot())["input_validation"]}})


def _hard_fields(output: AgentOutput) -> dict:
    return {
        "bias": output.bias,
        "confidence": output.confidence,
        "status": output.status,
        "accepted_state_conclusion": output.accepted_state_conclusion,
        "source_refs": output.source_refs,
    }


class _FakeGateway:
    def __init__(self, content: str | None = None, error: Exception | None = None) -> None:
        self.content = content
        self.error = error
        self.calls: list[dict] = []

    def chat_sync(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return {
            "content": self.content,
            "model": "fake-model",
            "provider": "fake-provider",
            "usage": {"total_tokens": 12},
            "latency_ms": 4,
            "audit_id": "audit-fixture",
        }


def _snapshot() -> dict:
    from tests.analysis.test_input_validation import valid_snapshot
    snapshot = valid_snapshot()
    snapshot["gold_workflow"]["evidence_catalog"] = []
    return snapshot


def test_v4_reviewer_downgrades_without_changing_accepted():
    from apps.features.research.macro_causal import QUESTIONS
    snapshot = _snapshot()
    snapshot['gold_workflow']['macro_causal'] = {'schema_version':'gold_macro_causal.v4'}
    response = {'dominant_factor':'利率压力尚需检验', 'counter_evidence':[], 'state_limitations':[],
                'convergence_transition':[], 'evidence_ids':['macro_causal_v4'],
                'macro_answers':{k:'证据不足，保留缺口' for k,_ in QUESTIONS},
                'macro_narrative':{k:'unavailable' for k in ('growth','inflation','labor','fed','treasury','term_premium','fiscal','dollar','liquidity','credit','oil')},
                'dominant_shocks':{'primary':'unavailable','secondary':'unavailable','counter':'unavailable'}}
    calls=[]
    def gateway(**kwargs):
        calls.append(kwargs)
        content = {'checks':[{'id':i,'passed':i!=0,'reason':'test evidence'} for i in range(14)]} if len(calls)==2 else response
        return {'content':json.dumps(content),'audit_id':'v4-test'}
    original=_output()
    result=enrich_research_coordinator(snapshot, original, gateway=gateway)
    assert len(calls)==2
    assert result.confidence == original.confidence*.7
    assert result.accepted_state_conclusion == original.accepted_state_conclusion
    assert result.input_payload['research_synthesis']['macro_review']['status']=='needs_revision'


def _snapshot_with_catalog(*evidence_ids: str) -> dict:
    snapshot = _snapshot()
    snapshot["gold_workflow"]["evidence_catalog"] = [
        {"evidence_id": evidence_id, "family": "research", "rationale": "已校验证据"} for evidence_id in evidence_ids
    ]
    from tests.analysis.test_input_validation import row
    snapshot["daily_research"]["passport"] = [row(symbol=identifier, unit="index") for identifier in evidence_ids]
    return snapshot


def test_disabled_marker_does_not_call_gateway_or_change_output() -> None:
    gateway = _FakeGateway(error=RuntimeError("must not be called"))
    output = _output()

    result = enrich_research_coordinator({}, output, gateway)

    assert result == output
    assert gateway.calls == []


def test_multiple_independent_limitations_are_retained_with_a_bounded_output():
    limitations = [
        "正式状态尚未确认",
        "利率窗口早于现货窗口",
        "美元前收日期缺失",
        "资金披露频率不同",
        "融资价格等待更新",
        "期权到期仍需核验",
        "新闻仅摘要的部分保留限制",
        "市场赔率数据不可用",
    ]
    for values, expected in ((limitations, "success"), (limitations + ["额外限制"] * 5, "rule_fallback")):
        content = json.dumps(
            {
                "dominant_factor": "实际利率是主要机会成本",
                "counter_evidence": [],
                "state_limitations": values,
                "convergence_transition": [],
                "evidence_ids": ["real_yield"],
            }
        )
        result = enrich_research_coordinator(_snapshot(), _output(), _FakeGateway(content))
        assert result.input_payload["research_synthesis"]["status"] == expected
        if expected == "success":
            assert result.input_payload["research_synthesis"]["analysis"]["state_limitations"] == limitations


def test_conditional_migration_observations_are_preserved() -> None:
    conditions = [
        "若实际利率与美元继续分化，ETF 单日与周度资金也未统一，且现货仍缺乏完整结构确认，则继续观察区间内消化，而不完成状态迁移。",
        "流动性相关判断需要准备金与财政账户的数量变化、融资利差以及信用价格在较新共同窗口内共同验证；任何单项变化都不足以触发状态迁移。",
    ]
    content = json.dumps(
        {
            "dominant_factor": "实际利率是主要机会成本",
            "counter_evidence": [],
            "state_limitations": [],
            "convergence_transition": conditions,
            "evidence_ids": ["real_yield"],
        }
    )
    result = enrich_research_coordinator(_snapshot(), _output(), _FakeGateway(content))
    assert result.input_payload["research_synthesis"]["status"] == "success"


def test_single_constrained_repair_preserves_hard_fields_and_audits_second_attempt():
    valid = {
        "dominant_factor": "实际利率是主要机会成本",
        "counter_evidence": [],
        "state_limitations": [],
        "convergence_transition": [],
        "evidence_ids": ["real_yield"],
    }
    calls = []

    def gateway(**kwargs):
        calls.append(kwargs)
        value = valid if len(calls) == 2 else {**valid, "evidence_ids": ["unknown"]}
        return {"content": json.dumps(value), "model": "fixture", "provider": "fixture"}

    before = _output()
    result = enrich_research_coordinator(_snapshot(), before, gateway)
    assert len(calls) == 2
    assert calls[1]["audit_context"]["validation_attempt"] == 2
    assert result.input_payload["research_synthesis"]["status"] == "success"
    assert _hard_fields(result) == _hard_fields(before)
    failed = _FakeGateway(json.dumps({**valid, "evidence_ids": ["unknown"]}))
    fallback = enrich_research_coordinator(_snapshot(), before, failed)
    assert len(failed.calls) == 2
    assert fallback.input_payload["research_synthesis"]["status"] == "rule_fallback"


def test_valid_language_layer_preserves_hard_fields_and_uses_default_gateway_config() -> None:
    gateway = _FakeGateway(
        '{"dominant_factor":"实际利率机会成本仍是主导解释",'
        '"counter_evidence":["现货结构尚未与利率窗口对齐"],'
        '"state_limitations":["正式状态依赖已验证前序链"],'
        '"convergence_transition":["等待利率、美元与现货共同确认"],'
        '"evidence_ids":["real_yield","spot_confirmation"]}'
    )
    output = _output()

    result = enrich_research_coordinator(_snapshot(), output, gateway)

    assert _hard_fields(result) == _hard_fields(output)
    assert result.llm_model == "fake-model"
    assert result.input_payload["research_synthesis"]["status"] == "success"
    assert "[MODEL] 主导因素解释：实际利率机会成本仍是主导解释" in result.key_findings
    assert gateway.calls[0]["request_timeout"] == 360
    assert gateway.calls[0]["max_tokens"] == 7800
    assert gateway.calls[0]["max_retries"] == 0
    assert "model" not in gateway.calls[0]
    assert gateway.calls[0]["json_mode"] is True


def test_unknown_evidence_id_falls_back_without_changing_direction() -> None:
    gateway = _FakeGateway(
        '{"dominant_factor":"实际利率是主导解释", "counter_evidence":[], '
        '"state_limitations":[], "convergence_transition":[], '
        '"evidence_ids":["invented_factor"]}'
    )
    output = _output()

    result = enrich_research_coordinator(_snapshot(), output, gateway)

    assert _hard_fields(result) == _hard_fields(output)
    assert result.input_payload["research_synthesis"]["status"] == "rule_fallback"
    assert "rule_fallback" in result.data_quality


def test_unknown_json_field_falls_back_after_one_bounded_repair() -> None:
    content = json.dumps(
        {
            "dominant_factor": "实际利率是主导解释",
            "counter_evidence": [],
            "state_limitations": [],
            "convergence_transition": [],
            "evidence_ids": ["real_yield"],
            "unexpected_field": "不属于研究合成协议",
        },
        ensure_ascii=False,
    )
    gateway = _FakeGateway(content)
    before = _output()
    result = enrich_research_coordinator(_snapshot(), before, gateway)
    assert len(gateway.calls) == 2
    assert result.input_payload["research_synthesis"]["status"] == "rule_fallback"
    assert _hard_fields(result) == _hard_fields(before)


def test_unknown_number_and_independent_model_opinion_are_preserved_with_review_metadata() -> None:
    gateway = _FakeGateway(
        json.dumps(
            {
                "dominant_factor": "我独立判断当前状态 S6 已确认，价格目标 9999 美元仍只是模型假设。",
                "counter_evidence": ["实际利率与美元尚未形成同向确认"],
                "state_limitations": ["候选目标 9999 需要新的市场数据核验"],
                "convergence_transition": ["若现货结构和资金证据共同改善，再重新评估该假设"],
                "evidence_ids": ["real_yield"],
                "independent_assessment": "模型判断可以与系统当前候选状态不同，但不改变正式决策。",
                "module_challenges": ["价格模块的窗口尚未覆盖该独立判断。"],
                "alternative_hypotheses": ["也可能是实际利率压力下的高位再平衡。"],
                "what_would_change_my_mind": ["获得同窗口的价格、美元和资金共振证据。"],
            },
            ensure_ascii=False,
        )
    )
    before = _output()
    result = enrich_research_coordinator(_snapshot(), before, gateway)
    metadata = result.input_payload["research_synthesis"]
    assert metadata["status"] == "success"
    assert metadata["schema_version"] == "research_synthesis.v2"
    assert metadata["proposal_scope"] == "model_inference_not_canonical_decision"
    assert _hard_fields(result) == _hard_fields(before)
    assert metadata["numeric_review"]["status"] == "requires_verification"
    assert any("9999" in mention for mention in metadata["numeric_review"]["unverified_mentions"])
    assert metadata["numeric_review"]["promoted_to_facts"] is False
    assert metadata["analysis"]["independent_assessment"].startswith("模型判断")
    assert metadata["analysis"]["module_challenges"] == ["价格模块的窗口尚未覆盖该独立判断。"]
    assert metadata["analysis"]["alternative_hypotheses"] == ["也可能是实际利率压力下的高位再平衡。"]
    assert metadata["analysis"]["what_would_change_my_mind"] == ["获得同窗口的价格、美元和资金共振证据。"]


def test_valid_catalog_evidence_ids_are_not_limited_by_narrative_list_bound() -> None:
    evidence_ids = ["real_yield", "spot_confirmation", *[f"factor_{index}" for index in range(30)]]
    gateway = _FakeGateway(
        json.dumps(
            {
                "dominant_factor": "实际利率机会成本仍是主导解释",
                "counter_evidence": [],
                "state_limitations": [],
                "convergence_transition": [],
                "evidence_ids": evidence_ids,
            },
            ensure_ascii=False,
        )
    )

    result = enrich_research_coordinator(_snapshot_with_catalog(*evidence_ids), _output(), gateway)

    assert result.input_payload["research_synthesis"]["status"] == "success"
    assert result.input_payload["research_synthesis"]["analysis"]["evidence_ids"] == evidence_ids

    too_many_ids = [f"factor_{index}" for index in range(33)]
    too_many = _FakeGateway(
        json.dumps(
            {
                "dominant_factor": "实际利率机会成本仍是主导解释",
                "counter_evidence": [],
                "state_limitations": [],
                "convergence_transition": [],
                "evidence_ids": too_many_ids,
            },
            ensure_ascii=False,
        )
    )
    rejected = enrich_research_coordinator(_snapshot_with_catalog(*too_many_ids), _output(), too_many)
    assert rejected.input_payload["research_synthesis"]["status"] == "rule_fallback"


def test_state_and_target_hypotheses_are_model_inference_only() -> None:
    before = _output()
    gateway = _FakeGateway(
        json.dumps(
            {
                "dominant_factor": "当前状态 S6 已确认，价格向上",
                "counter_evidence": [],
                "state_limitations": [],
                "convergence_transition": [],
                "evidence_ids": ["real_yield"],
            },
            ensure_ascii=False,
        )
    )

    result = enrich_research_coordinator(_snapshot(), before, gateway)

    assert result.input_payload["research_synthesis"]["status"] == "success"
    assert result.input_payload["research_synthesis"]["proposal_scope"] == "model_inference_not_canonical_decision"
    assert _hard_fields(result) == _hard_fields(before)

    prediction_gateway = _FakeGateway(
        json.dumps(
            {
                "dominant_factor": "价格将上涨",
                "counter_evidence": [],
                "state_limitations": [],
                "convergence_transition": [],
                "evidence_ids": ["real_yield"],
            },
            ensure_ascii=False,
        )
    )
    prediction = enrich_research_coordinator(_snapshot(), before, prediction_gateway)
    assert prediction.input_payload["research_synthesis"]["status"] == "success"
    assert _hard_fields(prediction) == _hard_fields(before)


def test_known_price_target_and_negative_conditional_text_are_model_inference() -> None:
    snapshot = _snapshot_with_catalog("price_structure", "real_yield")
    snapshot["gold_workflow"]["evidence_catalog"][0]["rationale"] = "关键位 4514 已在规则层留痕"
    gateway = _FakeGateway(
        json.dumps(
            {
                "dominant_factor": "价格目标 4514",
                "counter_evidence": [],
                "state_limitations": [],
                "convergence_transition": [],
                "evidence_ids": ["price_structure"],
            },
            ensure_ascii=False,
        )
    )
    result = enrich_research_coordinator(snapshot, _output(), gateway)
    assert result.input_payload["research_synthesis"]["status"] == "success"
    assert result.input_payload["research_synthesis"]["proposal_scope"] == "model_inference_not_canonical_decision"
    assert result.input_payload["research_synthesis"]["analysis"]["dominant_factor"] == "价格目标 4514"

    allowed_gateway = _FakeGateway(
        json.dumps(
            {
                "dominant_factor": "实际利率证据仍是主要解释",
                "counter_evidence": [],
                "state_limitations": ["S6 尚未确认"],
                "convergence_transition": ["若价格与实际利率共同确认，才观察下一状态"],
                "evidence_ids": ["real_yield"],
            },
            ensure_ascii=False,
        )
    )
    allowed = enrich_research_coordinator(_snapshot(), _output(), allowed_gateway)
    assert allowed.input_payload["research_synthesis"]["status"] == "success"


def test_same_clause_condition_prefixes_allow_state_migration_observations() -> None:
    conditions = [
        "若实际利率与美元停止上升，同时价格改善并获得资金回归确认，才观察修复方向的状态迁移。",
        "若实际利率与美元在同一窗口形成压力，价格结构同步转弱并伴随多头继续收缩，才观察压力方向的状态迁移。",
    ]
    for condition in conditions:
        gateway = _FakeGateway(
            json.dumps(
                {
                    "dominant_factor": "实际利率证据仍是主要解释",
                    "counter_evidence": [],
                    "state_limitations": [],
                    "convergence_transition": [condition],
                    "evidence_ids": ["real_yield"],
                },
                ensure_ascii=False,
            )
        )
        result = enrich_research_coordinator(_snapshot(), _output(), gateway)
        assert result.input_payload["research_synthesis"]["status"] == "success"


def test_model_state_opinion_is_retained_even_when_it_disagrees_with_system() -> None:
    claims = [
        "不能确认趋势。当前状态 S6 已确认",
        "当前状态 S6 已确认，但无法预测价格",
    ]
    for claim in claims:
        gateway = _FakeGateway(
            json.dumps(
                {
                    "dominant_factor": claim,
                    "counter_evidence": [],
                    "state_limitations": [],
                    "convergence_transition": [],
                    "evidence_ids": ["real_yield"],
                },
                ensure_ascii=False,
            )
        )
        before = _output()
        result = enrich_research_coordinator(_snapshot(), before, gateway)
        assert result.input_payload["research_synthesis"]["status"] == "success"
        assert result.input_payload["research_synthesis"]["proposal_scope"] == "model_inference_not_canonical_decision"
        assert _hard_fields(result) == _hard_fields(before)


def test_gateway_failure_is_explicit_rule_fallback_and_does_not_expose_error_text() -> None:
    gateway = _FakeGateway(error=RuntimeError("secret-key=do-not-persist"))
    result = enrich_research_coordinator(_snapshot(), _output(), gateway)

    metadata = result.input_payload["research_synthesis"]
    assert metadata["status"] == "rule_fallback"
    assert metadata["failure_reason"] == "RuntimeError"
    assert "secret-key" not in str(result.model_dump(mode="json"))
