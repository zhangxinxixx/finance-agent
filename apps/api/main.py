"""FastAPI application assembly and explicit legacy import compatibility."""
from __future__ import annotations

import logging
import os
import sys
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException as HTTPException, Request

from apps.api.routes import data_source_routes
from apps.api.routes import (
    research_state_routes,
    fedwatch_routes,
    agent_analysis_read_routes,
    agent_analysis_run_routes,
    agent_governance_read_routes,
    agent_governance_write_routes,
    event_flow_routes,
    evaluation_routes,
    execution_read_routes,
    frontend_compat_routes,
    gold_mainline_routes,
    health_routes,
    jin10_market_routes,
    jin10_report_routes,
    llm_audit_routes,
    knowledge_routes,
    live_strategy_routes,
    macro_routes,
    market_monitor_routes,
    market_odds_routes,
    news_routes,
    operations_routes,
    orchestration_routes,
    options_routes,
    premarket_routes,
    playbook_routes,
    processing_monitor_routes,
    reports_routes,
    review_routes,
    settings_read_routes,
    settings_write_routes,
    source_trace_routes,
    strategy_report_routes,
    system_evolution_routes,
    system_status_routes,
)

from apps.api.services import pipeline_contract_service as pipeline_contract_service, premarket_task_service
from apps.api.services.report_service import get_report_source as get_report_source
from apps.api.services.premarket_launch_service import (
    PremarketActiveTaskRef as PremarketActiveTaskRef,
    PremarketDagsterRunRef as PremarketDagsterRunRef,
    PremarketLaunchPreflightResponse as PremarketLaunchPreflightResponse,
    TaskCreateResponse as TaskCreateResponse,
)
from apps.api.services.premarket_task_service import (
    StepOut as StepOut,
    TaskOut as TaskOut,
)
from apps.api.services.system_status_service import database_reachable as _database_reachable
from apps.api.services.page_data_boundary import PageDataBoundaryMiddleware
from apps.api.services.jin10_cache_refresh_scheduler import (
    start_jin10_cache_refresh_scheduler,
    stop_jin10_cache_refresh_scheduler,
)
from database.migrations.runtime import run_database_migrations

_try_parse_json = premarket_task_service._parse_json
_step_to_out = premarket_task_service.step_to_out

logger = logging.getLogger(__name__)


def _should_skip_background_jobs() -> bool:
    """Keep FastAPI startup deterministic; API background refresh is opt-in."""
    if os.getenv("FINANCE_AGENT_DISABLE_BACKGROUND_JOBS") == "1":
        return True
    if os.getenv("FINANCE_AGENT_ENABLE_API_BACKGROUND_REFRESH") != "1":
        return True
    if os.getenv("PYTEST_CURRENT_TEST"):
        return True
    return "pytest" in sys.modules


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Startup / shutdown lifecycle — replaces deprecated on_event handlers."""
    # ── Startup ──
    from database.models.engine import SessionLocal

    if _database_reachable():
        try:
            bind = SessionLocal.kw.get("bind")
            database_url = None
            if bind is not None:
                database_url = bind.url.render_as_string(hide_password=False)
            run_database_migrations(database_url)
        except Exception:
            logger.exception("Startup Alembic migration failed")

        # 初始化所有已知数据源状态到 data_source_status 表（供调度中心/数据接入消费）
        try:
            from apps.api.services.ds_status_init import init_data_source_status
            init_data_source_status()
        except Exception:
            logger.exception("Failed to init data source status records")

    if not _should_skip_background_jobs():
        try:
            scheduler = start_jin10_cache_refresh_scheduler()
            logger.info("Automation orchestration scheduling handled by Dagster")
            logger.info("Premarket scheduling handled by Dagster (premarket_daily)")
            _app.state.jin10_scheduler = scheduler
        except Exception:
            logger.exception("Failed to start optional news and market refresh scheduler")

    yield

    # ── Shutdown ──
    sched = getattr(_app.state, "jin10_scheduler", None)
    if sched is not None:
        stop_jin10_cache_refresh_scheduler(sched)
        _app.state.jin10_scheduler = None


app = FastAPI(title="finance-agent", version="0.1.0", lifespan=lifespan)
app.add_middleware(PageDataBoundaryMiddleware)


app.include_router(health_routes.router)
app.include_router(execution_read_routes.router)
app.include_router(data_source_routes.router)
app.include_router(review_routes.router)
app.include_router(source_trace_routes.router)
app.include_router(strategy_report_routes.router)
app.include_router(market_monitor_routes.router)
app.include_router(reports_routes.router)
app.include_router(market_odds_routes.router)
app.include_router(operations_routes.router)
app.include_router(orchestration_routes.router)
app.include_router(macro_routes.router)
app.include_router(options_routes.router)
app.include_router(event_flow_routes.router)
app.include_router(evaluation_routes.router)
app.include_router(playbook_routes.router)
app.include_router(knowledge_routes.router)
app.include_router(live_strategy_routes.router)
app.include_router(settings_read_routes.router)
app.include_router(settings_write_routes.router)
app.include_router(jin10_report_routes.router)
app.include_router(llm_audit_routes.router)
app.include_router(news_routes.router)
app.include_router(gold_mainline_routes.router)
app.include_router(processing_monitor_routes.router)
app.include_router(jin10_market_routes.router)
app.include_router(premarket_routes.router)
app.include_router(agent_governance_read_routes.router)
app.include_router(agent_governance_write_routes.router)
app.include_router(frontend_compat_routes.router)
app.include_router(system_status_routes.router)
app.include_router(agent_analysis_read_routes.router)
app.include_router(agent_analysis_run_routes.router)
app.include_router(system_evolution_routes.router)
app.include_router(research_state_routes.router)
app.include_router(fedwatch_routes.router)



# Direct-import compatibility: each handler remains the registered route implementation.
api_runs = execution_read_routes.api_runs
api_run_detail = execution_read_routes.api_run_detail
api_run_steps = execution_read_routes.api_run_steps
api_run_logs = execution_read_routes.api_run_logs
api_run_artifacts = execution_read_routes.api_run_artifacts
api_artifact_detail = execution_read_routes.api_artifact_detail
api_run_events = execution_read_routes.api_run_events
api_system_evolution_latest = system_evolution_routes.api_system_evolution_latest
api_system_evolution_proposal_action = system_evolution_routes.api_system_evolution_proposal_action
api_source_trace_by_report = source_trace_routes.api_source_trace_by_report
api_source_trace_by_strategy = source_trace_routes.api_source_trace_by_strategy
api_source_trace_by_artifact = source_trace_routes.api_source_trace_by_artifact
api_source_trace_detail = source_trace_routes.api_source_trace_detail
api_data_sources_status = data_source_routes.api_data_sources_status
api_data_sources_registry = data_source_routes.api_data_sources_registry
api_data_status_summary = data_source_routes.api_data_status_summary
api_data_source_health_latest = data_source_routes.api_data_source_health_latest
api_data_source_health = data_source_routes.api_data_source_health
api_data_source_history = data_source_routes.api_data_source_history
api_ingestion_source_retry = data_source_routes.api_ingestion_source_retry
api_ingestion_source_test = data_source_routes.api_ingestion_source_test
api_ingestion_manual_upload = data_source_routes.api_ingestion_manual_upload
api_reviews = review_routes.api_reviews
api_review_detail = review_routes.api_review_detail
api_review_approve = review_routes.api_review_approve
api_review_reject = review_routes.api_review_reject
api_review_rerun = review_routes.api_review_rerun
api_review_use_fallback = review_routes.api_review_use_fallback
api_final_report_latest = strategy_report_routes.api_final_report_latest
api_final_report = strategy_report_routes.api_final_report
api_strategy_card_latest = strategy_report_routes.api_strategy_card_latest
api_strategy_card = strategy_report_routes.api_strategy_card
api_strategy_cards = strategy_report_routes.api_strategy_cards
api_strategy_card_assets = strategy_report_routes.api_strategy_card_assets
api_strategy_cards_latest = strategy_report_routes.api_strategy_cards_latest
api_strategy_card_detail = strategy_report_routes.api_strategy_card_detail
api_live_strategy_latest = live_strategy_routes.api_live_strategy_latest
api_shadow_evaluation_metrics = evaluation_routes.api_shadow_evaluation_metrics
api_market_tickers = market_monitor_routes.api_market_tickers
api_market_monitor = market_monitor_routes.api_market_monitor
api_market_monitor_history = market_monitor_routes.api_market_monitor_history
api_reports_index = reports_routes.api_reports_index
api_reports_dates = reports_routes.api_reports_dates
api_report_detail = reports_routes.api_report_detail
api_report_artifacts = reports_routes.api_report_artifacts
api_report_source = reports_routes.api_report_source
api_report_analysis = reports_routes.api_report_analysis
api_report_artifact_asset = reports_routes.api_report_artifact_asset
api_report_visual = reports_routes.api_report_visual
api_report_evidence = reports_routes.api_report_evidence
api_report_analysis_inputs = reports_routes.api_report_analysis_inputs
api_llm_audits = llm_audit_routes.api_llm_audits
api_llm_audit_detail = llm_audit_routes.api_llm_audit_detail
api_market_odds_snapshot = market_odds_routes.api_market_odds_snapshot
api_market_odds_report = market_odds_routes.api_market_odds_report
api_tasks = operations_routes.api_tasks
api_scheduler_overview = operations_routes.api_scheduler_overview
api_run_all_collectors = operations_routes.api_run_all_collectors
api_dashboard_summary = operations_routes.api_dashboard_summary
api_orchestration_latest = orchestration_routes.api_orchestration_latest
api_orchestration_notification_plan = orchestration_routes.api_orchestration_notification_plan
api_orchestration_manual_review = orchestration_routes.api_orchestration_manual_review
api_orchestration_manual_review_action = orchestration_routes.api_orchestration_manual_review_action
api_macro_latest = macro_routes.api_macro_latest
api_macro_report = macro_routes.api_macro_report
api_options_snapshot = options_routes.api_options_snapshot
api_options_decision = options_routes.api_options_decision
api_options_report = options_routes.api_options_report
api_options_dates = options_routes.api_options_dates
api_options_visual_report_latest = options_routes.api_options_visual_report_latest
api_options_visual_report = options_routes.api_options_visual_report
api_event_flow_overview = event_flow_routes.api_event_flow_overview
api_event_flow_briefs = event_flow_routes.api_event_flow_briefs
api_event_flow_events = event_flow_routes.api_event_flow_events
api_event_calendar_summary = event_flow_routes.api_event_calendar_summary
api_event_flow_report_inputs = event_flow_routes.api_event_flow_report_inputs
api_event_flow_event_detail = event_flow_routes.api_event_flow_event_detail
api_event_flow_event_impact = event_flow_routes.api_event_flow_event_impact
api_event_flow_event_market_reaction = event_flow_routes.api_event_flow_event_market_reaction
api_event_flow_brief_link = event_flow_routes.api_event_flow_brief_link
api_event_flow_brief_ignore = event_flow_routes.api_event_flow_brief_ignore
api_event_flow_report_input_include = event_flow_routes.api_event_flow_report_input_include
api_event_flow_report_input_exclude = event_flow_routes.api_event_flow_report_input_exclude
api_event_flow_event_review = event_flow_routes.api_event_flow_event_review
api_create_playbook = playbook_routes.api_create_playbook
api_playbooks = playbook_routes.api_playbooks
api_playbook_detail = playbook_routes.api_playbook_detail
api_playbook_versions = playbook_routes.api_playbook_versions
api_knowledge_items = knowledge_routes.api_knowledge_items
api_knowledge_item = knowledge_routes.api_knowledge_item
api_settings_status = settings_read_routes.api_settings_status
api_settings_history = settings_read_routes.api_settings_history
api_settings_update_preferences = settings_write_routes.api_settings_update_preferences
api_settings_reset_preferences = settings_write_routes.api_settings_reset_preferences
api_settings_update_source = settings_write_routes.api_settings_update_source
api_settings_reset_source = settings_write_routes.api_settings_reset_source
api_settings_update_secret = settings_write_routes.api_settings_update_secret
api_settings_reset_secret = settings_write_routes.api_settings_reset_secret
api_settings_rollback_history_event = settings_write_routes.api_settings_rollback_history_event
api_jin10_daily_report_latest = jin10_report_routes.api_jin10_daily_report_latest
api_jin10_daily_report = jin10_report_routes.api_jin10_daily_report
api_jin10_weekly_report_latest = jin10_report_routes.api_jin10_weekly_report_latest
api_jin10_weekly_report = jin10_report_routes.api_jin10_weekly_report
api_jin10_report_bundle_latest = jin10_report_routes.api_jin10_report_bundle_latest
api_jin10_report_bundle = jin10_report_routes.api_jin10_report_bundle
api_jin10_report_bundle_asset = jin10_report_routes.api_jin10_report_bundle_asset
api_jin10_article_briefs_latest = jin10_report_routes.api_jin10_article_briefs_latest
api_jin10_article_briefs = jin10_report_routes.api_jin10_article_briefs
api_jin10_web_flash_briefs_latest = jin10_report_routes.api_jin10_web_flash_briefs_latest
api_jin10_web_flash_briefs = jin10_report_routes.api_jin10_web_flash_briefs
api_daily_analysis_triggers_latest = news_routes.api_daily_analysis_triggers_latest
api_daily_analysis_triggers = news_routes.api_daily_analysis_triggers
api_daily_brief_latest = news_routes.api_daily_brief_latest
api_daily_brief = news_routes.api_daily_brief
api_daily_analysis_followups_latest = news_routes.api_daily_analysis_followups_latest
api_daily_analysis_followups = news_routes.api_daily_analysis_followups
api_create_daily_analysis_followup_tasks = news_routes.api_create_daily_analysis_followup_tasks
api_feishu_jin10_message_monitor_latest = news_routes.api_feishu_jin10_message_monitor_latest
api_feishu_jin10_message_monitor_dates = news_routes.api_feishu_jin10_message_monitor_dates
api_feishu_jin10_message_monitor = news_routes.api_feishu_jin10_message_monitor
api_gold_mainlines_latest = gold_mainline_routes.api_gold_mainlines_latest
api_gold_mainlines = gold_mainline_routes.api_gold_mainlines
api_gold_runtime_orchestration_contract = gold_mainline_routes.api_gold_runtime_orchestration_contract
api_gold_runtime_summary_preview = gold_mainline_routes.api_gold_runtime_summary_preview
api_processing_overview = processing_monitor_routes.api_processing_overview
api_processing_trace = processing_monitor_routes.api_processing_trace
api_processing_trace_by_event = processing_monitor_routes.api_processing_trace_by_event
api_processing_trace_by_input = processing_monitor_routes.api_processing_trace_by_input
api_processing_trace_by_source_ref = processing_monitor_routes.api_processing_trace_by_source_ref
api_processing_trace_by_mainline = processing_monitor_routes.api_processing_trace_by_mainline
api_processing_trace_by_transmission_chain = processing_monitor_routes.api_processing_trace_by_transmission_chain
api_jin10_quotes_latest = jin10_market_routes.api_jin10_quotes_latest
api_jin10_calendar = jin10_market_routes.api_jin10_calendar
api_jin10_flash = jin10_market_routes.api_jin10_flash
api_jin10_kline = jin10_market_routes.api_jin10_kline
api_premarket_pipeline_contract = premarket_routes.api_premarket_pipeline_contract
api_premarket_pipeline_readiness = premarket_routes.api_premarket_pipeline_readiness
api_premarket_launch_preflight = premarket_routes.api_premarket_launch_preflight
trigger_premarket = premarket_routes.trigger_premarket
get_task = premarket_routes.get_task
get_task_logs = premarket_routes.get_task_logs
health = health_routes.health
api_agents_registry = agent_governance_read_routes.api_agents_registry
api_agent_registry_detail = agent_governance_read_routes.api_agent_registry_detail
api_prompt_versions_list = agent_governance_read_routes.api_prompt_versions_list
api_prompt_versions_by_agent = agent_governance_read_routes.api_prompt_versions_by_agent
api_prompt_versions_active = agent_governance_read_routes.api_prompt_versions_active
api_prompt_evolution_proposal = agent_governance_read_routes.api_prompt_evolution_proposal
api_prompt_evolution_latest = agent_governance_read_routes.api_prompt_evolution_latest
api_prompt_versions_create = agent_governance_write_routes.api_prompt_versions_create
api_prompt_versions_activate = agent_governance_write_routes.api_prompt_versions_activate
api_prompt_feedback_create = agent_governance_write_routes.api_prompt_feedback_create
api_prompt_feedback_by_agent = agent_governance_write_routes.api_prompt_feedback_by_agent
api_prompt_feedback_list = agent_governance_write_routes.api_prompt_feedback_list
api_prompt_evolution_release_action = agent_governance_write_routes.api_prompt_evolution_release_action
api_agent_analysis_latest = agent_analysis_read_routes.api_agent_analysis_latest
api_agent_analysis_by_date = agent_analysis_read_routes.api_agent_analysis_by_date
api_agent_analysis_inspect = agent_analysis_read_routes.api_agent_analysis_inspect
api_agent_analysis_synthesis_latest = agent_analysis_read_routes.api_agent_analysis_synthesis_latest
api_run_agent_analysis = agent_analysis_run_routes.api_run_agent_analysis
serve_frontend_asset = frontend_compat_routes.serve_frontend_asset
serve_frontend_favicon = frontend_compat_routes.serve_frontend_favicon
serve_dashboard = frontend_compat_routes.serve_dashboard
serve_dashboard_analysis = frontend_compat_routes.serve_dashboard_analysis
serve_data_ingestion = frontend_compat_routes.serve_data_ingestion
serve_data_sources_subpath = frontend_compat_routes.serve_data_sources_subpath
serve_market_monitor = frontend_compat_routes.serve_market_monitor
serve_cme_options = frontend_compat_routes.serve_cme_options
serve_reports = frontend_compat_routes.serve_reports
serve_reports_subpath = frontend_compat_routes.serve_reports_subpath
serve_event_flow = frontend_compat_routes.serve_event_flow
serve_event_flow_subpath = frontend_compat_routes.serve_event_flow_subpath
serve_knowledge_base = frontend_compat_routes.serve_knowledge_base
serve_agent_tasks = frontend_compat_routes.serve_agent_tasks
serve_scheduler = frontend_compat_routes.serve_scheduler
serve_scheduler_subpath = frontend_compat_routes.serve_scheduler_subpath
serve_agent_tasks_subpath = frontend_compat_routes.serve_agent_tasks_subpath
serve_review_center = frontend_compat_routes.serve_review_center
serve_settings = frontend_compat_routes.serve_settings
serve_settings_audit = frontend_compat_routes.serve_settings_audit
system_status = system_status_routes.system_status


@app.middleware("http")
async def log_http_requests(request: Request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    logger.info(
        "HTTP request completed",
        extra={
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
        },
    )
    return response
