from __future__ import annotations

from copy import deepcopy
from typing import Any

from apps.gold_mainline_contract import GOLD_MAINLINE_IDS

GOLD_V3_MAINLINES = list(GOLD_MAINLINE_IDS)

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

FORBIDDEN_MUTATION_LAYERS = ["raw", "parsed", "features"]


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


def _governance_template(
    *,
    agent_id: str,
    system: str,
    user: str,
    checks: list[str],
    output_schema: dict[str, Any],
) -> dict[str, Any]:
    return {
        "agent_id": agent_id,
        "proposal_only": True,
        "forbidden_mutation_layers": FORBIDDEN_MUTATION_LAYERS,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "checks": checks,
        "output_schema": output_schema,
        "rules": [
            "只生成检查结果、风险和改造提案，不直接修改生产数据或自动发布。",
            "不得绕过 scheduler / worker / task_runs / task_steps。",
            "不得写入 raw、parsed 或 features 层。",
            "所有建议必须指向具体文件、接口、schema 或测试。",
        ],
    }


def build_source_health_prompt_template() -> dict[str, Any]:
    return _template(
        agent_id="source_health_agent",
        dag_node_id="source_health_check",
        system="你是 SourceHealthAgent，负责在黄金 v3.0 主线加工前检查数据源健康度。",
        user="检查 FRED、Treasury、DXY、XAUUSD、Brent、WTI、Jin10、CME、ETF 等数据新鲜度，输出是否可构建 GoldMacroOverview。",
        output_schema={
            "overall_status": "ready | degraded | blocked",
            "as_of": "",
            "p0_missing": [],
            "p1_missing": [],
            "p2_missing": [],
            "stale_sources": [],
            "fresh_sources": [],
            "source_freshness": {},
            "mainline_impact": {},
            "can_build_gold_macro_overview": False,
            "can_emit_strong_conclusion": False,
            "blocked_mainlines": [],
            "degraded_mainlines": [],
            "blocking_reasons": [],
            "warnings": [],
        },
        rules=[
            "P0 数据缺失时不得输出强结论。",
            "缺失数据必须显式列入 p0_missing / p1_missing / p2_missing。",
            "每条黄金主线必须在 mainline_impact 中标记 ready / degraded / blocked。",
            "数据过期必须标记 stale，不允许当作最新数据。",
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


def build_system_evolution_governance_prompt_template() -> dict[str, Any]:
    return _governance_template(
        agent_id="system_evolution_agent",
        system="你是 SystemEvolutionAgent，负责汇总运行质量、复核结果和失败测试，生成系统演进提案。",
        user="基于最近运行、ReviewGate 结果、SourceHealth、失败测试和 issue blockers，生成只读演进提案，不直接修改生产链路。",
        checks=[
            "runtime_quality",
            "source_health_patterns",
            "review_gate_findings",
            "test_failures",
            "issue_close_blockers",
        ],
        output_schema={
            "review_status": "pass | needs_change | blocked",
            "evolution_proposals": [],
            "risk_items": [],
            "required_followups": [],
            "source_refs": [],
        },
    )


def build_architecture_governance_prompt_template() -> dict[str, Any]:
    return _governance_template(
        agent_id="architecture_agent",
        system="你是 ArchitectureAgent，负责 Gold v3.0 页面职责、能力落层和主链边界治理。",
        user="审查新增需求应落在哪一层，避免所有功能堆回 EventFlow 或绕过生产主链。",
        checks=[
            "page_responsibility",
            "module_boundary",
            "main_chain_alignment",
            "frontend_read_model_only",
        ],
        output_schema={
            "review_status": "pass | needs_change | blocked",
            "placement_decisions": [],
            "boundary_violations": [],
            "recommended_tasks": [],
            "source_refs": [],
        },
    )


def build_schema_governance_prompt_template() -> dict[str, Any]:
    return _governance_template(
        agent_id="schema_agent",
        system="你是 SchemaAgent，负责 Gold v3.0 TypeScript、后端 schema 和 JSON 字段名治理。",
        user="审查 GoldMacroOverview、主线归因、ProcessingTrace、DAG contract 和前端类型是否字段漂移。",
        checks=[
            "typescript_schema",
            "backend_schema",
            "json_contract",
            "field_name_drift",
        ],
        output_schema={
            "review_status": "pass | needs_change | blocked",
            "schema_drift": [],
            "required_migrations": [],
            "contract_updates": [],
            "source_refs": [],
        },
    )


def build_dag_lineage_governance_prompt_template() -> dict[str, Any]:
    return _governance_template(
        agent_id="dag_lineage_agent",
        system="你是 DagLineageAgent，负责 Gold v3.0 DAG、trace mode 和 source_ref 到前端槽位链路治理。",
        user="检查 DAG 节点、边、data_contract、source_ref、artifact_ref、frontend slot 是否能闭环。",
        checks=[
            "dag_node_mapping",
            "edge_data_contract",
            "source_ref",
            "artifact_ref",
            "frontend_slot",
        ],
        output_schema={
            "review_status": "pass | needs_change | blocked",
            "checks": ["dag_node_mapping", "edge_data_contract", "source_ref", "artifact_ref", "frontend_slot"],
            "missing_edges": [],
            "missing_trace_refs": [],
            "frontend_binding_gaps": [],
            "source_refs": [],
        },
    )


def build_test_validation_governance_prompt_template() -> dict[str, Any]:
    return _governance_template(
        agent_id="test_validation_agent",
        system="你是 TestValidationAgent，负责 Gold v3.0 schema、DAG、mixed 拆解、主线归因和页面绑定测试治理。",
        user="根据变更范围提出最小但可执行的测试矩阵，并标记不能关闭 issue 的缺口。",
        checks=[
            "schema_tests",
            "dag_contract_tests",
            "mixed_decomposition_tests",
            "mainline_attribution_tests",
            "frontend_binding_tests",
        ],
        output_schema={
            "review_status": "pass | needs_more_tests | blocked",
            "required_tests": [],
            "missing_coverage": [],
            "issue_close_blockers": [],
            "verification_commands": [],
        },
    )


def build_prompt_evolution_governance_prompt_template() -> dict[str, Any]:
    return _governance_template(
        agent_id="prompt_evolution_agent",
        system="你是 PromptEvolutionAgent，负责评估固定 Agent 的 Prompt 输出质量并生成可审核的 Prompt 更新提案。",
        user="分析固定 Agent 最近 N 次输入输出、ReviewGate findings、人工反馈、失败测试、当前 schema 和数据源健康状态；只生成 prompt_update proposal，不直接修改生产 Prompt。",
        checks=[
            "repeated_failure_patterns",
            "root_cause_classification",
            "prompt_update_proposal",
            "test_cases",
            "rollback_plan",
        ],
        output_schema={
            "agent_name": "",
            "problem_summary": "",
            "failure_patterns": [
                {
                    "pattern_id": "",
                    "description": "",
                    "frequency": 0,
                    "examples": [],
                    "likely_root_cause": "prompt | schema | data_missing | rule_gap | frontend_binding | dag | unknown",
                }
            ],
            "prompt_update_proposal": {
                "proposal_id": "",
                "proposal_type": "prompt_update | schema_update | data_source_change | dag_update | insufficient_evidence",
                "before_summary": "",
                "after_summary": "",
                "patch": "",
                "rationale": "",
                "risk": "",
                "rollback_plan": "",
                "test_cases": [],
            },
            "requires_schema_change": False,
            "requires_data_source_change": False,
            "requires_dag_change": False,
            "manual_review_required": True,
        },
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


_GOLD_V3_GOVERNANCE_AGENT_SPECS: list[dict[str, Any]] = [
    {
        "agent_id": "system_evolution_agent",
        "name": "SystemEvolutionAgent",
        "agent_type": "development_governance_agent",
        "priority": "P1",
        "description": "汇总运行质量、复核结果和失败测试，生成系统演进提案。",
        "governance_scope": "运行质量与系统演进治理",
        "proposal_only": True,
        "input_sections": ["recent_runs", "review_gate_findings", "source_health", "failed_tests", "issues"],
        "output_targets": ["SystemEvolutionReview 提案", "Issue close blockers"],
        "prompt_builder": build_system_evolution_governance_prompt_template,
    },
    {
        "agent_id": "architecture_agent",
        "name": "ArchitectureAgent",
        "agent_type": "development_governance_agent",
        "priority": "P1",
        "description": "维护页面职责和能力落层，避免所有功能堆回 EventFlow。",
        "governance_scope": "页面职责与能力落层治理",
        "proposal_only": True,
        "input_sections": ["issues", "architecture_docs", "route_map", "module_boundaries"],
        "output_targets": ["ArchitectureReview 提案", "Issue close blockers"],
        "prompt_builder": build_architecture_governance_prompt_template,
    },
    {
        "agent_id": "schema_agent",
        "name": "SchemaAgent",
        "agent_type": "development_governance_agent",
        "priority": "P1",
        "description": "维护 TypeScript、后端 schema 和 JSON contract，防止字段名漂移。",
        "governance_scope": "TypeScript / 后端 schema 字段治理",
        "proposal_only": True,
        "input_sections": ["types", "api_schemas", "json_artifacts", "tests"],
        "output_targets": ["SchemaReview 提案", "Contract drift report"],
        "prompt_builder": build_schema_governance_prompt_template,
    },
    {
        "agent_id": "dag_lineage_agent",
        "name": "DagLineageAgent",
        "agent_type": "development_governance_agent",
        "priority": "P1",
        "description": "维护 DAG 和 trace mode，检查 source_ref 到 frontend slot 的链路。",
        "governance_scope": "DAG 和 trace mode 链路治理",
        "proposal_only": True,
        "input_sections": ["pipeline_dag", "source_refs", "artifact_refs", "frontend_slots"],
        "output_targets": ["DAGLineageReview 提案", "Trace gap report"],
        "prompt_builder": build_dag_lineage_governance_prompt_template,
    },
    {
        "agent_id": "test_validation_agent",
        "name": "TestValidationAgent",
        "agent_type": "development_governance_agent",
        "priority": "P1",
        "description": "维护 schema、DAG、mixed、主线归因和页面绑定测试矩阵。",
        "governance_scope": "schema / DAG / mixed / 页面绑定测试治理",
        "proposal_only": True,
        "input_sections": ["issue_acceptance", "changed_files", "test_results"],
        "output_targets": ["TestValidationReview 提案", "Verification command matrix"],
        "prompt_builder": build_test_validation_governance_prompt_template,
    },
    {
        "agent_id": "prompt_evolution_agent",
        "name": "PromptEvolutionAgent",
        "agent_type": "development_governance_agent",
        "priority": "P1",
        "description": "评估固定 Agent Prompt 输出质量，生成可审核、可测试、可回滚的 Prompt 更新提案。",
        "governance_scope": "固定 Agent Prompt 质量评估与优化提案",
        "proposal_only": True,
        "input_sections": [
            "current_prompt",
            "recent_runs",
            "review_gate_findings",
            "manual_feedback",
            "failed_test_cases",
            "data_source_health",
        ],
        "output_targets": ["PromptUpdateProposal 提案", "ReviewGate 人工复核项", "Prompt regression test cases"],
        "prompt_builder": build_prompt_evolution_governance_prompt_template,
    },
]


def list_gold_v3_agent_registry_entries() -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for spec in [*_GOLD_V3_AGENT_SPECS, *_GOLD_V3_GOVERNANCE_AGENT_SPECS]:
        prompt_builder = spec["prompt_builder"]
        prompt_template = prompt_builder()
        entry = {
            key: deepcopy(value)
            for key, value in spec.items()
            if key != "prompt_builder"
        }
        entry.update(
            {
                "status": "planned_governance" if entry.get("proposal_only") else "planned_prompt",
                "status_label": "Gold v3 治理 Agent" if entry.get("proposal_only") else "Gold v3 固定 Agent",
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
