from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from apps.analysis.agents.fact_review import build_fact_review_prompt_template
from apps.analysis.agents.gold_v3_prompts import list_gold_v3_agent_registry_entries
from apps.analysis.agents.macro_event_followup_prompt import build_macro_event_followup_prompt_template
from apps.analysis.agents.macro_liquidity_prompt import build_macro_liquidity_prompt_template
from apps.analysis.agents.jin10_flash_semantic_filter import (
    AGENT_ID as JIN10_FLASH_SEMANTIC_FILTER_AGENT_ID,
    PROMPT_SOURCE as JIN10_FLASH_SEMANTIC_FILTER_PROMPT_SOURCE,
    build_jin10_flash_semantic_filter_prompt_template,
)
from apps.analysis.agents.synthesis import build_synthesis_prompt_template
from apps.analysis.jin10.agent_analysis import build_agent_analysis_prompt
from apps.analysis.options.llm_conclusion import build_conclusion_prompt
from apps.parsers.jin10.qwen_vl_markdown import (
    _build_page_layout_prompt,
    _build_page_markdown_prompt,
    _build_page_unified_prompt,
    _build_title_band_prompt,
)

_RUNTIME_AGENT_META: dict[str, dict[str, Any]] = {
    "jin10_vlm_parser": {
        "display_name": "金十 VLM 解析",
        "role": "parser_agent",
        "registry_id": "jin10_vlm_parser",
    },
    "macro_liquidity_agent": {
        "display_name": "宏观流动性",
        "role": "domain_agent",
        "registry_id": "macro_liquidity_agent",
    },
    "macro_event_followup_agent": {
        "display_name": "宏观事件跟进补充",
        "role": "report_agent",
        "registry_id": "macro_event_followup_agent",
    },
    "cme_options_agent": {
        "display_name": "期权结构",
        "role": "domain_agent",
        "registry_id": "cme_options_agent",
    },
    "risk_agent": {
        "display_name": "风险评估",
        "role": "domain_agent",
    },
    "technical_agent": {
        "display_name": "技术面",
        "role": "domain_agent",
    },
    "positioning_agent": {
        "display_name": "持仓",
        "role": "domain_agent",
    },
    "news_agent": {
        "display_name": "新闻事件",
        "role": "domain_agent",
    },
    "market_odds_agent": {
        "display_name": "市场赔率",
        "role": "domain_agent",
    },
    "market_regime": {
        "display_name": "市场状态",
        "role": "domain_agent",
    },
    "event_impact": {
        "display_name": "事件影响",
        "role": "domain_agent",
    },
    "jin10_daily": {
        "display_name": "金十日报",
        "role": "report_agent",
    },
    "jin10_report_analysis_agent": {
        "display_name": "金十报告分析",
        "role": "report_agent",
        "registry_id": "jin10_report_analysis_agent",
    },
    "jin10_flash_semantic_filter_agent": {
        "display_name": "金十快讯重点筛选",
        "role": "filter_agent",
        "registry_id": "jin10_flash_semantic_filter_agent",
    },
    "coordinator": {
        "display_name": "协调汇总",
        "role": "coordinator_agent",
    },
    "coordinator_agent": {
        "display_name": "协调汇总",
        "role": "coordinator_agent",
    },
    "fact_review_agent": {
        "display_name": "事实审查",
        "role": "review_agent",
        "registry_id": "fact_review_agent",
    },
    "synthesis_agent": {
        "display_name": "综合分析",
        "role": "synthesis_agent",
        "registry_id": "synthesis_agent",
    },
    "source_health_agent": {
        "display_name": "SourceHealthAgent",
        "role": "health_agent",
        "registry_id": "source_health_agent",
    },
    "event_attribution_agent": {
        "display_name": "EventAttributionAgent",
        "role": "attribution_agent",
        "registry_id": "event_attribution_agent",
    },
    "transmission_chain_agent": {
        "display_name": "TransmissionChainAgent",
        "role": "chain_agent",
        "registry_id": "transmission_chain_agent",
    },
    "driver_decomposition_agent": {
        "display_name": "DriverDecompositionAgent",
        "role": "decomposition_agent",
        "registry_id": "driver_decomposition_agent",
    },
    "mainline_ranking_agent": {
        "display_name": "MainlineRankingAgent",
        "role": "ranking_agent",
        "registry_id": "mainline_ranking_agent",
    },
    "gold_macro_overview_agent": {
        "display_name": "GoldMacroOverviewAgent",
        "role": "overview_agent",
        "registry_id": "gold_macro_overview_agent",
    },
    "review_gate_agent": {
        "display_name": "ReviewGateAgent",
        "role": "review_agent",
        "registry_id": "review_gate_agent",
    },
    "report_render_agent": {
        "display_name": "ReportRenderAgent",
        "role": "report_agent",
        "registry_id": "report_render_agent",
    },
    "system_evolution_agent": {
        "display_name": "SystemEvolutionAgent",
        "role": "development_governance_agent",
        "registry_id": "system_evolution_agent",
    },
    "prompt_evolution_agent": {
        "display_name": "PromptEvolutionAgent",
        "role": "development_governance_agent",
        "registry_id": "prompt_evolution_agent",
    },
    "architecture_agent": {
        "display_name": "ArchitectureAgent",
        "role": "development_governance_agent",
        "registry_id": "architecture_agent",
    },
    "schema_agent": {
        "display_name": "SchemaAgent",
        "role": "development_governance_agent",
        "registry_id": "schema_agent",
    },
    "dag_lineage_agent": {
        "display_name": "DagLineageAgent",
        "role": "development_governance_agent",
        "registry_id": "dag_lineage_agent",
    },
    "test_validation_agent": {
        "display_name": "TestValidationAgent",
        "role": "development_governance_agent",
        "registry_id": "test_validation_agent",
    },
}


_JIN10_TEMPLATE_RAW: dict[str, Any] = {
    "family": "jin10_raw_article",
    "document_id": "{{document_id}}",
    "trade_date": "{{trade_date}}",
    "run_id": "{{run_id}}",
    "article_id": "{{article_id}}",
    "title": "{{title}}",
    "source_url": "{{source_url}}",
    "article_markdown": "{{article_markdown}}",
    "charts": [
        {
            "seq": "{{chart_seq}}",
            "title": "{{chart_title}}",
            "caption": "{{chart_caption}}",
            "image_path": "{{chart_image_path}}",
        }
    ],
    "source_refs": [{"source": "jin10_external", "article_id": "{{article_id}}"}],
}

_JIN10_TEMPLATE_DAILY: dict[str, Any] = {
    "family": "jin10_daily_visual",
    "core_conclusion": "{{core_conclusion}}",
    "market_prices": "{{market_prices}}",
    "logic_chains": "{{logic_chains}}",
    "watch_variables": "{{watch_variables}}",
    "key_levels": "{{key_levels}}",
    "scenario_matrix": "{{scenario_matrix}}",
    "risks": "{{risks}}",
    "source_refs": [{"source": "jin10_daily_visual", "article_id": "{{article_id}}"}],
}

_OPTIONS_TEMPLATE_SNAPSHOT: dict[str, Any] = {
    "trade_date": "{{trade_date}}",
    "product": "OG",
    "data_source_status": "{{FINAL_or_PRELIM}}",
    "data_source_url": "{{cme_daily_bulletin_url_or_path}}",
    "p0": "{{live_or_report_p0}}",
    "forward_price": "{{forward_price}}",
    "f_source": "{{forward_source}}",
    "used_real_gex": "{{true_or_false}}",
    "expiries": ["{{near_expiry}}", "{{next_expiry}}"],
    "normalization": {
        "total_input_rows": "{{total_input_rows}}",
        "duplicates_merged": "{{duplicates_merged}}",
        "rows_missing_settlement": "{{rows_missing_settlement}}",
        "rows_missing_delta": "{{rows_missing_delta}}",
        "rows_filtered_by_strike": "{{rows_filtered_by_strike}}",
    },
    "data_quality": {
        "zero_oi_count": "{{zero_oi_count}}",
        "low_oi_count": "{{low_oi_count}}",
        "proxy_strike_count": "{{proxy_strike_count}}",
        "prelim_data_count": "{{prelim_data_count}}",
        "warnings": ["{{data_quality_warning}}"],
    },
    "gex": {
        "netgex_aggregate": {
            "gamma_zero": {
                "price": "{{gamma_zero_price}}",
                "method": "{{gamma_zero_method}}",
            },
            "warnings": ["{{gex_warning}}"],
        },
        "by_expiry": {
            "{{near_expiry}}": {
                "summary": "{{near_month_gex_summary}}",
                "gex_top": ["{{near_month_top_gex_rows}}"],
                "iv_skew": "{{near_month_iv_skew}}",
            },
            "{{next_expiry}}": {
                "summary": "{{next_month_gex_summary}}",
                "gex_top": ["{{next_month_top_gex_rows}}"],
                "iv_skew": "{{next_month_iv_skew}}",
            },
        },
    },
    "exposure": {
        "by_expiry": {
            "{{near_expiry}}": {"summary": "{{near_month_exposure_summary}}"},
            "{{next_expiry}}": {"summary": "{{next_month_exposure_summary}}"},
        }
    },
    "wall_scores": ["{{wall_score_rows}}"],
    "roll_signals": ["{{roll_signals}}"],
    "intent": {
        "primary_intent": {
            "intent_type": "{{intent_type}}",
            "score": "{{intent_score}}",
            "confidence": "{{intent_confidence}}",
            "evidence": ["{{intent_evidence}}"],
        },
        "all_scores": "{{intent_score_table}}",
    },
    "audit": {
        "data_audit": "{{data_audit}}",
        "black76_audit": "{{black76_audit}}",
        "gex_audit": "{{gex_audit}}",
        "wallscore_audit": "{{wallscore_audit}}",
        "intent_audit": "{{intent_audit}}",
    },
}


def list_agent_registry() -> list[dict[str, Any]]:
    """Return the current read-only Agent registry for governance and prompt review."""

    return [
        *list_gold_v3_agent_registry_entries(),
        {
            "agent_id": JIN10_FLASH_SEMANTIC_FILTER_AGENT_ID,
            "name": "金十快讯重点筛选 Agent",
            "agent_type": "filter_agent",
            "priority": "P0",
            "status": "active_prompt",
            "status_label": "已接入",
            "description": "在 Jin10 快讯采集缓存阶段，用 MiMo 语义判断是否进入实时重点事件播报。",
            "input_sections": ["jin10_flash_items"],
            "output_targets": ["storage/outputs/jin10/flash_cache.json", "Dashboard 实时重点事件播报"],
            "source_module": "apps.scheduler.jin10_refresh / apps.analysis.agents.jin10_flash_semantic_filter",
            "runtime_agent_names": ["jin10_flash_semantic_filter_agent"],
            "prompt": {
                "kind": "llm",
                "source": JIN10_FLASH_SEMANTIC_FILTER_PROMPT_SOURCE,
                "template": build_jin10_flash_semantic_filter_prompt_template(),
            },
        },
        {
            "agent_id": "jin10_report_analysis_agent",
            "name": "金十报告分析 Agent",
            "agent_type": "report_agent",
            "priority": "P0",
            "status": "active_prompt",
            "status_label": "优先重建",
            "description": "基于金十原文识别结果与 daily_analysis 结构化摘要生成二次分析报告。",
            "input_sections": ["jin10_raw_article", "jin10_daily_visual"],
            "output_targets": ["Report Detail 分析输入", "Reports 综合摘要", "Agent Tasks 输入输出"],
            "source_module": "apps.analysis.jin10.agent_analysis",
            "runtime_agent_names": ["jin10_report_analysis_agent"],
            "prompt": {
                "kind": "llm",
                "source": "apps/analysis/jin10/agent_analysis.py::build_agent_analysis_prompt",
                "template": build_agent_analysis_prompt(
                    deepcopy(_JIN10_TEMPLATE_RAW),
                    deepcopy(_JIN10_TEMPLATE_DAILY),
                ),
            },
        },
        {
            "agent_id": "macro_liquidity_agent",
            "name": "宏观流动性 Agent",
            "agent_type": "domain_agent",
            "priority": "P0",
            "status": "active_prompt",
            "status_label": "可调提示词",
            "description": "基于已加载的宏观快照，生成面向人阅读的流动性研究结论。",
            "input_sections": ["macro"],
            "output_targets": ["Report Detail 分析输入", "Dashboard 宏观流动性摘要"],
            "source_module": "apps.analysis.agents.macro_liquidity",
            "runtime_agent_names": ["macro_liquidity_agent"],
            "prompt": {
                "kind": "llm",
                "source": "apps/analysis/agents/macro_liquidity_prompt.py::build_macro_liquidity_prompt_template",
                "template": build_macro_liquidity_prompt_template(),
            },
        },
        {
            "agent_id": "cme_options_agent",
            "name": "期权结构分析 Agent",
            "agent_type": "domain_agent",
            "priority": "P0",
            "status": "active_prompt",
            "status_label": "优先重建",
            "description": "先用确定性 cme_options Agent 产出结构判断，再用期权报告 Prompt 生成可发布分析稿。",
            "input_sections": ["options", "options_analysis"],
            "output_targets": ["CME Options 解释层", "Report Detail 分析输入", "StrategyCard 证据输入"],
            "source_module": "apps.analysis.agents.cme_options / apps.analysis.options.llm_conclusion",
            "runtime_agent_names": ["cme_options_agent"],
            "prompt": {
                "kind": "hybrid",
                "source": "apps/analysis/options/llm_conclusion.py::build_conclusion_prompt",
                "template": build_conclusion_prompt(deepcopy(_OPTIONS_TEMPLATE_SNAPSHOT)),
            },
        },
        {
            "agent_id": "fact_review_agent",
            "name": "事实审查 Agent",
            "agent_type": "review_agent",
            "priority": "P1",
            "status": "active_rules",
            "status_label": "规则已接入",
            "description": "逐条审查专项 Agent claims 是否有来源支撑、是否冲突或使用过期数据。",
            "input_sections": ["agent_outputs", "source_refs", "snapshot_refs"],
            "output_targets": ["Review Center", "Report Detail 审查结果", "Dashboard review badge"],
            "source_module": "apps.analysis.agents.fact_review",
            "runtime_agent_names": ["fact_review_agent"],
            "prompt": {
                "kind": "rule",
                "source": "apps/analysis/agents/fact_review.py::build_fact_review_prompt_template",
                "template": build_fact_review_prompt_template(),
            },
        },
        {
            "agent_id": "macro_event_followup_agent",
            "name": "宏观事件跟进补充 Agent",
            "agent_type": "report_agent",
            "priority": "P1",
            "status": "active_prompt",
            "status_label": "可调提示词",
            "description": "基于非交易日跟进结构化输入，生成面向人阅读的补充分析报告。",
            "input_sections": ["macro_event_followup"],
            "output_targets": ["Report Detail 补充分析", "Reports 综合摘要"],
            "source_module": "apps.analysis.agents.macro_event_followup",
            "runtime_agent_names": ["macro_event_followup_agent"],
            "prompt": {
                "kind": "llm",
                "source": "apps.analysis.agents.macro_event_followup::build_macro_event_followup_prompt",
                "template": build_macro_event_followup_prompt_template(),
            },
        },
        {
            "agent_id": "synthesis_agent",
            "name": "综合分析 Agent",
            "agent_type": "synthesis_agent",
            "priority": "P1",
            "status": "active_rules",
            "status_label": "规则已接入",
            "description": "汇总来源数据、专项 Agent 输出和事实审查结果，生成页面级 read model 的综合结论。",
            "input_sections": ["domain_agent_outputs", "fact_review_output", "data_status"],
            "output_targets": ["DashboardSummary", "Report synthesis", "Strategy context"],
            "source_module": "apps.analysis.agents.synthesis",
            "runtime_agent_names": ["synthesis_agent"],
            "prompt": {
                "kind": "rule",
                "source": "apps/analysis/agents/synthesis.py::build_synthesis_prompt_template",
                "template": build_synthesis_prompt_template(),
            },
        },
        {
            "agent_id": "jin10_vlm_parser",
            "name": "金十 VLM 解析 Agent",
            "agent_type": "parser_agent",
            "priority": "P0",
            "status": "active_prompt",
            "status_label": "优先重建",
            "description": "基于 qwen3-vl-flash 对金十报告图片逐页做 OCR 转写、版面定位和图表识别。",
            "input_sections": ["jin10_report_images", "figure_crops"],
            "output_targets": ["Jin10 报告解析层", "raw_article_report.md"],
            "source_module": "apps.parsers.jin10.qwen_vl_markdown",
            "runtime_agent_names": ["jin10_vlm_parser"],
            "prompt": {
                "kind": "llm",
                "source": "apps/parsers/jin10/qwen_vl_markdown.py",
                "template": {
                    "unified_markdown_layout": _build_page_unified_prompt(page_no=1, page_width=1200, page_height=1800, original_page_width=1200, original_page_height=1800),
                    "layout": _build_page_layout_prompt(page_no=1, page_width=1200, page_height=1800, original_page_width=1200, original_page_height=1800, expected_chart_count=1, hint_titles=["示例图表"]),
                    "markdown_only": _build_page_markdown_prompt(page_no=1, figures=[{"title": "示例图表", "chart_image_path": "figures/fig_p1_001.png"}]),
                    "title_band": _build_title_band_prompt(page_width=1200, page_height=200),
                },
            },
        },
    ]


def get_agent_registry(agent_id: str) -> dict[str, Any] | None:
    for agent in list_agent_registry():
        if agent["agent_id"] == agent_id:
            return agent
    return None


def resolve_agent_runtime_meta(agent_name: str) -> dict[str, Any]:
    runtime_meta = deepcopy(_RUNTIME_AGENT_META.get(agent_name, {}))
    if not runtime_meta:
        runtime_meta = {
            "display_name": agent_name,
            "role": "unknown_agent",
        }

    registry_id = runtime_meta.get("registry_id")
    if registry_id is None:
        for agent in list_agent_registry():
            if agent_name in (agent.get("runtime_agent_names") or []):
                registry_id = agent["agent_id"]
                break

    runtime_meta["agent_name"] = agent_name
    runtime_meta["registry_id"] = registry_id
    return runtime_meta


def build_agent_registry_response() -> dict[str, Any]:
    """Build Agent Registry response, enriched with DB prompt version info (P2-11).

    Reads prompt_versions from DB for each agent; falls back gracefully when DB
    is unavailable or the table doesn't exist yet.
    """
    agents = list_agent_registry()

    # Enrich with DB prompt version info
    try:
        from database.models.analysis import PromptVersion
        from database.models.engine import SessionLocal

        with SessionLocal() as db:
            pv_rows = (
                db.query(PromptVersion).filter(PromptVersion.status == "active", PromptVersion.enabled.is_(True)).all()
            )
            pv_by_agent: dict[str, dict[str, Any]] = {}
            for row in pv_rows:
                pv_by_agent[row.agent_id] = {
                    "id": row.id,
                    "version": row.version,
                    "prompt_kind": row.prompt_kind,
                    "status": row.status,
                    "enabled": row.enabled,
                    "model_routing": row.model_routing,
                    "change_note": row.change_note,
                    "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                }

            for agent in agents:
                pv = pv_by_agent.get(agent["agent_id"])
                if pv:
                    agent["prompt_version"] = pv
                    agent["prompt_versions_synced"] = True
                else:
                    agent["prompt_versions_synced"] = False
    except Exception:
        for agent in agents:
            agent["prompt_versions_synced"] = False

    return {
        "source": "agent_registry",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "agents": agents,
    }


def get_active_prompt_version_from_db(agent_id: str) -> dict[str, Any] | None:
    """Read the active prompt version for an agent from DB (P2-11).

    Returns None if DB unavailable or no active version exists.
    """
    try:
        from database.models.analysis import PromptVersion
        from database.models.engine import SessionLocal

        with SessionLocal() as db:
            row = (
                db.query(PromptVersion)
                .filter(
                    PromptVersion.agent_id == agent_id,
                    PromptVersion.status == "active",
                    PromptVersion.enabled.is_(True),
                )
                .order_by(PromptVersion.created_at.desc())
                .first()
            )
            if row is None:
                return None
            return {
                "id": row.id,
                "agent_id": row.agent_id,
                "version": row.version,
                "prompt_kind": row.prompt_kind,
                "prompt_source": row.prompt_source,
                "prompt_template": row.prompt_template,
                "prompt_sha256": row.prompt_sha256,
                "status": row.status,
                "enabled": row.enabled,
                "model_routing": row.model_routing,
                "change_note": row.change_note,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            }
    except Exception:
        return None
