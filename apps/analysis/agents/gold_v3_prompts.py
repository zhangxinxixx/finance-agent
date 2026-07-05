from __future__ import annotations

from copy import deepcopy
from typing import Any

GOLD_V3_MAINLINES = [
    "fed_policy_path",
    "real_rates_dollar",
    "oil_price",
    "geopolitical_war",
    "etf_flows",
    "comex_options_institutional_sentiment",
    "central_bank_monetary_credit",
    "china_asia_demand",
    "gold_technical_phase",
]

GOLD_V3_TRANSMISSION_CHAINS = [
    "rate_chain",
    "dollar_chain",
    "war_oil_rate_chain",
    "safe_haven_chain",
    "flow_chain",
    "reserve_chain",
    "asia_demand_chain",
    "technical_chain",
]


def _template(
    *,
    agent_id: str,
    dag_node_id: str,
    system: str,
    user: str,
    output_schema: dict[str, Any],
    rules: list[str],
) -> dict[str, Any]:
    return {
        "agent_id": agent_id,
        "dag_node_id": dag_node_id,
        "gold_mainlines": GOLD_V3_MAINLINES,
        "transmission_chains": GOLD_V3_TRANSMISSION_CHAINS,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "output_schema": output_schema,
        "rules": rules,
    }


def build_source_health_prompt_template() -> dict[str, Any]:
    return _template(
        agent_id="source_health_agent",
        dag_node_id="source_health_check",
        system="你是 SourceHealthAgent，负责在黄金 v3.0 主线加工前检查数据源健康度。",
        user="检查 FRED、Treasury、DXY、XAUUSD、Brent、WTI、Jin10、CME、ETF 等数据新鲜度，输出是否可构建 GoldMacroOverview。",
        output_schema={
            "status": "healthy | degraded | blocked",
            "missing_p0_data": [],
            "missing_p1_data": [],
            "missing_p2_data": [],
            "can_build_gold_macro_overview": False,
            "degrade_reason": "",
            "source_refs": [],
        },
        rules=[
            "P0 数据缺失时不得输出强结论。",
            "缺失数据必须显式列入 missing_p0_data / missing_p1_data / missing_p2_data。",
            "只读取数据状态和产物引用，不修改 raw、parsed 或 features。",
        ],
    )


def build_event_attribution_prompt_template() -> dict[str, Any]:
    return _template(
        agent_id="event_attribution_agent",
        dag_node_id="mainline_attribution",
        system="你是 EventAttributionAgent，负责把每条新闻、报告输入或事件归因到黄金九条主线。",
        user="基于事件文本、报告摘要、行情上下文和 source_refs，输出主线归因、初步多空拆解和传导链。",
        output_schema={
            "entity_id": "",
            "mainlines": [],
            "primary_mainline": "",
            "transmission_chains": [],
            "affected_assets": [],
            "initial_gold_impact": "",
            "bullish_drivers": [],
            "bearish_drivers": [],
            "net_effect": "",
            "confidence": 0.0,
            "verification_needed": [],
            "source_refs": [],
        },
        rules=[
            "不写完整报告，只做归因。",
            "如果 net_effect 为 mixed，必须拆 bullish_drivers 和 bearish_drivers。",
            "地缘战争必须同时判断 safe_haven_chain 和 war_oil_rate_chain。",
            "油价上涨不能直接判定为利多黄金，必须判断美债收益率和通胀预期。",
        ],
    )


def build_transmission_chain_prompt_template() -> dict[str, Any]:
    return _template(
        agent_id="transmission_chain_agent",
        dag_node_id="transmission_chain_detection",
        system="你是 TransmissionChainAgent，负责判断事件或主线通过哪条传导链影响黄金。",
        user="逐条检查利率链、美元链、战争-石油-利率链、避险链、资金链、储备链、亚洲需求链和技术链。",
        output_schema={
            "entity_id": "",
            "chains": [
                {
                    "chain": "",
                    "status": "active | inactive | incomplete | uncertain",
                    "direction": "",
                    "evidence": [],
                    "missing_links": [],
                    "gold_effect": "",
                    "confidence": 0.0,
                }
            ],
            "dominant_chain": "",
            "war_oil_rate_chain": {},
            "verification_needed": [],
        },
        rules=[
            "不允许只说战争利多黄金，必须拆避险链和油价通胀链。",
            "链条缺数据必须写 missing_links。",
            "若链条之间冲突，必须指出冲突点。",
        ],
    )


def build_driver_decomposition_prompt_template() -> dict[str, Any]:
    return _template(
        agent_id="driver_decomposition_agent",
        dag_node_id="driver_decomposition",
        system="你是 DriverDecompositionAgent，专门负责拆解 mixed 判断。",
        user="任何 mixed / mixed_bearish / mixed_bullish 都必须拆成多空驱动、主导驱动、净影响和待验证项。",
        output_schema={
            "entity_id": "",
            "bullish_drivers": [],
            "bearish_drivers": [],
            "dominant_driver": "",
            "net_effect": "",
            "why_not_one_sided": "",
            "verification_needed": [],
            "confidence": 0.0,
        },
        rules=[
            "不允许裸输出 mixed。",
            "dominant_driver 必须来自证据更强的一侧。",
            "证据不足时写 verification_needed，而不是补造确定性。",
        ],
    )


def build_mainline_ranking_prompt_template() -> dict[str, Any]:
    return _template(
        agent_id="mainline_ranking_agent",
        dag_node_id="gold_mainline_agent",
        system="你是 MainlineRankingAgent，负责对黄金九条主线排序。",
        user="汇总事件、市场特征、数据健康状态、传导链结果，计算九条主线方向、强度、置信度、新鲜度和综合分。",
        output_schema={
            "theme_rankings": [],
            "dominant_mainline": "",
            "net_bias": "",
            "summary": "",
            "missing_p0_data": [],
            "warnings": [],
        },
        rules=[
            "主线必须全部输出，不能遗漏。",
            "缺数据的主线也要输出，但 missing_data 必须写清楚。",
            "dominant_mainline 必须来自 score 最高且证据足够的主线。",
            "score = abs(direction_score) * impact_strength * confidence * freshness。",
        ],
    )


def build_gold_macro_overview_prompt_template() -> dict[str, Any]:
    return _template(
        agent_id="gold_macro_overview_agent",
        dag_node_id="gold_macro_overview",
        system="你是 GoldMacroOverviewAgent，负责生成 Dashboard 和主线页面共用的黄金总览模型。",
        user="消费主线排序、驱动拆解、传导链、数据健康和 source_refs，输出唯一 GoldMacroOverview read model。",
        output_schema={
            "asset": "XAUUSD",
            "as_of": "",
            "phase": "",
            "dominant_mainline": "",
            "net_bias": "",
            "risk_score": 0,
            "one_line_conclusion": "",
            "theme_rankings": [],
            "driver_conflict": {},
            "war_oil_rate_chain": {},
            "verification_matrix": [],
            "key_events": [],
            "processing_traces": [],
        },
        rules=[
            "Dashboard 只消费此对象，不重新计算主线。",
            "任何结论必须能回溯 source_refs 或 event_ids。",
            "one_line_conclusion 必须是条件式，不得绝对预测。",
            "如果 P0 数据缺失，必须降级 confidence。",
        ],
    )


def build_review_gate_prompt_template() -> dict[str, Any]:
    return _template(
        agent_id="review_gate_agent",
        dag_node_id="processing_monitor",
        system="你是 ReviewGateAgent，负责输出前的质量检查和人工复核触发。",
        user="检查 mixed 拆解、强判断证据、P0 缺失降级、战争/石油链路、策略条件式和报告事实表述。",
        output_schema={
            "review_status": "pass | needs_review | blocked",
            "blocking_issues": [],
            "warnings": [],
            "manual_review_items": [],
            "auto_fix_suggestions": [],
        },
        rules=[
            "无 source_refs 的强判断必须 needs_review 或 blocked。",
            "P0 数据缺失时仍输出强结论必须 blocked。",
            "只生成复核结论和建议，不直接改写生产产物。",
        ],
    )


def build_report_render_prompt_template() -> dict[str, Any]:
    return _template(
        agent_id="report_render_agent",
        dag_node_id="daily_report",
        system="你是 ReportRenderAgent，负责消费 GoldMacroOverview 和 EventFlow source_refs 渲染结构化日报。",
        user="把已完成的 GoldMacroOverview、事件证据和复核结果组织成日报，不重新计算主线。",
        output_schema={
            "report_markdown": "",
            "report_json": {},
            "source_refs": [],
            "processing_trace_id": "",
        },
        rules=[
            "不重新计算主线，只渲染已有 read model。",
            "报告中的推断必须标明证据或条件。",
            "保留 source_refs 和 processing_trace_id。",
        ],
    )


_GOLD_V3_AGENT_SPECS: list[dict[str, Any]] = [
    {
        "agent_id": "source_health_agent",
        "name": "SourceHealthAgent",
        "agent_type": "health_agent",
        "priority": "P0",
        "description": "检查关键数据源新鲜度、P0/P1/P2 缺失和 GoldMacroOverview 可构建性。",
        "dag_node_id": "source_health_check",
        "run_frequency": "每 15-30 分钟 / 每次任务前",
        "input_sections": ["data_source_status", "artifact_refs", "latest_outputs"],
        "output_targets": ["ProcessingMonitor 数据健康状态", "GoldMacroOverview 降级门控"],
        "prompt_builder": build_source_health_prompt_template,
    },
    {
        "agent_id": "event_attribution_agent",
        "name": "EventAttributionAgent",
        "agent_type": "attribution_agent",
        "priority": "P0",
        "description": "把新闻、快讯和报告输入归入黄金九条主线并保留 source_refs。",
        "dag_node_id": "mainline_attribution",
        "run_frequency": "有新新闻/报告输入时",
        "input_sections": ["event_flow", "jin10_reports", "market_context", "source_refs"],
        "output_targets": ["GoldMainlines 主线归因", "SourceTrace 主线证据"],
        "prompt_builder": build_event_attribution_prompt_template,
    },
    {
        "agent_id": "transmission_chain_agent",
        "name": "TransmissionChainAgent",
        "agent_type": "chain_agent",
        "priority": "P0",
        "description": "识别利率、美元、战争-石油-利率、避险、资金、储备、亚洲需求和技术传导链。",
        "dag_node_id": "transmission_chain_detection",
        "run_frequency": "有地缘/油价/利率变化时",
        "input_sections": ["mainline_attribution", "market_context", "macro_context"],
        "output_targets": ["GoldMainlines 传导链", "OilGeopolitics 链路解释"],
        "prompt_builder": build_transmission_chain_prompt_template,
    },
    {
        "agent_id": "driver_decomposition_agent",
        "name": "DriverDecompositionAgent",
        "agent_type": "decomposition_agent",
        "priority": "P0",
        "description": "统一拆解 mixed 判断，输出多空驱动、主导驱动和待验证项。",
        "dag_node_id": "driver_decomposition",
        "run_frequency": "每次出现 mixed 判断时",
        "input_sections": ["mainline_attribution", "transmission_chains", "agent_outputs"],
        "output_targets": ["GoldMacroOverview 驱动拆解", "VerificationMatrix 输入"],
        "prompt_builder": build_driver_decomposition_prompt_template,
    },
    {
        "agent_id": "mainline_ranking_agent",
        "name": "MainlineRankingAgent",
        "agent_type": "ranking_agent",
        "priority": "P0",
        "description": "汇总事件、市场特征、数据健康状态和传导链结果，对九条黄金主线排序。",
        "dag_node_id": "gold_mainline_agent",
        "run_frequency": "每日固定 + 重大事件触发",
        "input_sections": ["source_health", "mainline_attribution", "transmission_chain_detection", "market_validation"],
        "output_targets": ["theme_rankings", "dominant_mainline", "net_bias"],
        "prompt_builder": build_mainline_ranking_prompt_template,
    },
    {
        "agent_id": "gold_macro_overview_agent",
        "name": "GoldMacroOverviewAgent",
        "agent_type": "overview_agent",
        "priority": "P0",
        "description": "生成 Dashboard 和主线页面共用的 GoldMacroOverview read model。",
        "dag_node_id": "gold_macro_overview",
        "run_frequency": "每日固定 + 主线变化时",
        "input_sections": ["theme_rankings", "driver_decomposition", "transmission_chains", "source_health"],
        "output_targets": ["Dashboard 主线总览", "GoldMainlinesPage read model", "OilGeopoliticsPage read model"],
        "prompt_builder": build_gold_macro_overview_prompt_template,
    },
    {
        "agent_id": "review_gate_agent",
        "name": "ReviewGateAgent",
        "agent_type": "review_agent",
        "priority": "P0",
        "description": "检查 mixed 拆解、source_refs、P0 缺失强结论和战争/石油链路拆分。",
        "dag_node_id": "processing_monitor",
        "run_frequency": "每次输出前",
        "input_sections": ["gold_macro_overview", "source_refs", "processing_traces"],
        "output_targets": ["ProcessingMonitor 复核状态", "ReviewCenter 人工复核项"],
        "prompt_builder": build_review_gate_prompt_template,
    },
    {
        "agent_id": "report_render_agent",
        "name": "ReportRenderAgent",
        "agent_type": "report_agent",
        "priority": "P1",
        "description": "消费 GoldMacroOverview 和 EventFlow source_refs 渲染结构化日报，不重新计算主线。",
        "dag_node_id": "daily_report",
        "run_frequency": "每日收盘/盘前",
        "input_sections": ["gold_macro_overview", "event_flow", "review_gate"],
        "output_targets": ["DailyReport Markdown", "FinalReport JSON", "Report Detail"],
        "prompt_builder": build_report_render_prompt_template,
    },
]


def list_gold_v3_agent_registry_entries() -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for spec in _GOLD_V3_AGENT_SPECS:
        prompt_builder = spec["prompt_builder"]
        prompt_template = prompt_builder()
        entry = {
            key: deepcopy(value)
            for key, value in spec.items()
            if key != "prompt_builder"
        }
        entry.update(
            {
                "status": "planned_prompt",
                "status_label": "Gold v3 固定 Agent",
                "source_module": "apps.analysis.agents.gold_v3_prompts",
                "runtime_agent_names": [entry["agent_id"]],
                "prompt": {
                    "kind": "llm",
                    "source": f"apps/analysis/agents/gold_v3_prompts.py::{prompt_builder.__name__}",
                    "template": prompt_template,
                },
            }
        )
        entries.append(entry)
    return entries
