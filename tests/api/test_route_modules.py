"""Regression tests for API route modularization."""

from __future__ import annotations

from fastapi.routing import APIRoute


def _route_endpoint_map():
    from apps.api.main import app

    return {
        route.path: route.endpoint
        for route in app.routes
        if isinstance(route, APIRoute)
    }


def _route_method_endpoint_map():
    from apps.api.main import app

    return {
        (route.path, method): route.endpoint
        for route in app.routes
        if isinstance(route, APIRoute)
        for method in route.methods
    }


def test_main_reexports_execution_and_source_trace_handlers() -> None:
    from apps.api.main import (
        api_artifact_detail,
        api_run_artifacts,
        api_run_detail,
        api_run_events,
        api_run_logs,
        api_run_steps,
        api_runs,
        api_source_trace_by_artifact,
        api_source_trace_by_report,
        api_source_trace_by_strategy,
        api_source_trace_detail,
    )
    from apps.api.routes.execution_read_routes import (
        api_artifact_detail as modular_api_artifact_detail,
        api_run_artifacts as modular_api_run_artifacts,
        api_run_detail as modular_api_run_detail,
        api_run_events as modular_api_run_events,
        api_run_logs as modular_api_run_logs,
        api_run_steps as modular_api_run_steps,
        api_runs as modular_api_runs,
    )
    from apps.api.routes.source_trace_routes import (
        api_source_trace_by_artifact as modular_api_source_trace_by_artifact,
        api_source_trace_by_report as modular_api_source_trace_by_report,
        api_source_trace_by_strategy as modular_api_source_trace_by_strategy,
        api_source_trace_detail as modular_api_source_trace_detail,
    )

    assert api_runs is modular_api_runs
    assert api_run_detail is modular_api_run_detail
    assert api_run_steps is modular_api_run_steps
    assert api_run_logs is modular_api_run_logs
    assert api_run_artifacts is modular_api_run_artifacts
    assert api_artifact_detail is modular_api_artifact_detail
    assert api_run_events is modular_api_run_events
    assert api_source_trace_by_report is modular_api_source_trace_by_report
    assert api_source_trace_by_strategy is modular_api_source_trace_by_strategy
    assert api_source_trace_by_artifact is modular_api_source_trace_by_artifact
    assert api_source_trace_detail is modular_api_source_trace_detail


def test_main_reexports_data_source_and_ingestion_handlers() -> None:
    from apps.api.main import (
        api_data_source_health,
        api_data_source_health_latest,
        api_data_source_history,
        api_data_sources_registry,
        api_data_sources_status,
        api_data_status_summary,
        api_ingestion_manual_upload,
        api_ingestion_source_retry,
        api_ingestion_source_test,
    )
    from apps.api.routes.data_source_routes import (
        api_data_source_health as modular_api_data_source_health,
        api_data_source_health_latest as modular_api_data_source_health_latest,
        api_data_source_history as modular_api_data_source_history,
        api_data_sources_registry as modular_api_data_sources_registry,
        api_data_sources_status as modular_api_data_sources_status,
        api_data_status_summary as modular_api_data_status_summary,
        api_ingestion_manual_upload as modular_api_ingestion_manual_upload,
        api_ingestion_source_retry as modular_api_ingestion_source_retry,
        api_ingestion_source_test as modular_api_ingestion_source_test,
    )

    assert api_data_sources_status is modular_api_data_sources_status
    assert api_data_sources_registry is modular_api_data_sources_registry
    assert api_data_status_summary is modular_api_data_status_summary
    assert api_data_source_health_latest is modular_api_data_source_health_latest
    assert api_data_source_health is modular_api_data_source_health
    assert api_data_source_history is modular_api_data_source_history
    assert api_ingestion_source_retry is modular_api_ingestion_source_retry
    assert api_ingestion_source_test is modular_api_ingestion_source_test
    assert api_ingestion_manual_upload is modular_api_ingestion_manual_upload


def test_main_reexports_review_handlers() -> None:
    from apps.api.main import (
        api_review_approve,
        api_review_detail,
        api_review_reject,
        api_review_rerun,
        api_review_use_fallback,
        api_reviews,
    )
    from apps.api.routes.review_routes import (
        api_review_approve as modular_api_review_approve,
        api_review_detail as modular_api_review_detail,
        api_review_reject as modular_api_review_reject,
        api_review_rerun as modular_api_review_rerun,
        api_review_use_fallback as modular_api_review_use_fallback,
        api_reviews as modular_api_reviews,
    )

    assert api_reviews is modular_api_reviews
    assert api_review_detail is modular_api_review_detail
    assert api_review_approve is modular_api_review_approve
    assert api_review_reject is modular_api_review_reject
    assert api_review_rerun is modular_api_review_rerun
    assert api_review_use_fallback is modular_api_review_use_fallback


def test_main_reexports_system_evolution_handlers() -> None:
    from apps.api.main import api_system_evolution_latest, api_system_evolution_proposal_action
    from apps.api.routes.system_evolution_routes import (
        api_system_evolution_latest as modular_api_system_evolution_latest,
        api_system_evolution_proposal_action as modular_api_system_evolution_proposal_action,
    )

    assert api_system_evolution_latest is modular_api_system_evolution_latest
    assert api_system_evolution_proposal_action is modular_api_system_evolution_proposal_action


def test_main_reexports_strategy_report_handlers() -> None:
    from apps.api.main import (
        api_final_report,
        api_final_report_latest,
        api_strategy_card,
        api_strategy_card_assets,
        api_strategy_card_detail,
        api_strategy_card_latest,
        api_strategy_cards,
        api_strategy_cards_latest,
    )
    from apps.api.routes.strategy_report_routes import (
        api_final_report as modular_api_final_report,
        api_final_report_latest as modular_api_final_report_latest,
        api_strategy_card as modular_api_strategy_card,
        api_strategy_card_assets as modular_api_strategy_card_assets,
        api_strategy_card_detail as modular_api_strategy_card_detail,
        api_strategy_card_latest as modular_api_strategy_card_latest,
        api_strategy_cards as modular_api_strategy_cards,
        api_strategy_cards_latest as modular_api_strategy_cards_latest,
    )

    assert api_final_report_latest is modular_api_final_report_latest
    assert api_final_report is modular_api_final_report
    assert api_strategy_card_latest is modular_api_strategy_card_latest
    assert api_strategy_card is modular_api_strategy_card
    assert api_strategy_cards is modular_api_strategy_cards
    assert api_strategy_card_assets is modular_api_strategy_card_assets
    assert api_strategy_cards_latest is modular_api_strategy_cards_latest
    assert api_strategy_card_detail is modular_api_strategy_card_detail


def test_main_reexports_market_monitor_handlers() -> None:
    from apps.api.main import (
        api_market_monitor,
        api_market_monitor_history,
        api_market_tickers,
    )
    from apps.api.routes.market_monitor_routes import (
        api_market_monitor as modular_api_market_monitor,
        api_market_monitor_history as modular_api_market_monitor_history,
        api_market_tickers as modular_api_market_tickers,
    )

    assert api_market_tickers is modular_api_market_tickers
    assert api_market_monitor is modular_api_market_monitor
    assert api_market_monitor_history is modular_api_market_monitor_history


def test_main_reexports_report_handlers() -> None:
    from apps.api.main import (
        api_report_analysis,
        api_report_analysis_inputs,
        api_report_artifact_asset,
        api_report_artifacts,
        api_report_detail,
        api_report_evidence,
        api_report_source,
        api_report_visual,
        api_reports_dates,
        api_reports_index,
    )
    from apps.api.routes.reports_routes import (
        api_report_analysis as modular_api_report_analysis,
        api_report_analysis_inputs as modular_api_report_analysis_inputs,
        api_report_artifact_asset as modular_api_report_artifact_asset,
        api_report_artifacts as modular_api_report_artifacts,
        api_report_detail as modular_api_report_detail,
        api_report_evidence as modular_api_report_evidence,
        api_report_source as modular_api_report_source,
        api_report_visual as modular_api_report_visual,
        api_reports_dates as modular_api_reports_dates,
        api_reports_index as modular_api_reports_index,
    )

    assert api_reports_index is modular_api_reports_index
    assert api_reports_dates is modular_api_reports_dates
    assert api_report_detail is modular_api_report_detail
    assert api_report_artifacts is modular_api_report_artifacts
    assert api_report_source is modular_api_report_source
    assert api_report_analysis is modular_api_report_analysis
    assert api_report_artifact_asset is modular_api_report_artifact_asset
    assert api_report_visual is modular_api_report_visual
    assert api_report_evidence is modular_api_report_evidence
    assert api_report_analysis_inputs is modular_api_report_analysis_inputs


def test_main_reexports_market_odds_handlers() -> None:
    from apps.api.main import (
        api_market_odds_report,
        api_market_odds_snapshot,
    )
    from apps.api.routes.market_odds_routes import (
        api_market_odds_report as modular_api_market_odds_report,
        api_market_odds_snapshot as modular_api_market_odds_snapshot,
    )

    assert api_market_odds_snapshot is modular_api_market_odds_snapshot
    assert api_market_odds_report is modular_api_market_odds_report


def test_main_reexports_operations_handlers() -> None:
    from apps.api.main import (
        api_dashboard_summary,
        api_run_all_collectors,
        api_scheduler_overview,
        api_tasks,
    )
    from apps.api.routes.operations_routes import (
        api_dashboard_summary as modular_api_dashboard_summary,
        api_run_all_collectors as modular_api_run_all_collectors,
        api_scheduler_overview as modular_api_scheduler_overview,
        api_tasks as modular_api_tasks,
    )

    assert api_tasks is modular_api_tasks
    assert api_scheduler_overview is modular_api_scheduler_overview
    assert api_run_all_collectors is modular_api_run_all_collectors
    assert api_dashboard_summary is modular_api_dashboard_summary


def test_main_reexports_macro_handlers() -> None:
    from apps.api.main import (
        api_macro_latest,
        api_macro_report,
    )
    from apps.api.routes.macro_routes import (
        api_macro_latest as modular_api_macro_latest,
        api_macro_report as modular_api_macro_report,
    )

    assert api_macro_latest is modular_api_macro_latest
    assert api_macro_report is modular_api_macro_report


def test_main_reexports_options_handlers() -> None:
    from apps.api.main import (
        api_options_dates,
        api_options_report,
        api_options_snapshot,
        api_options_visual_report,
        api_options_visual_report_latest,
    )
    from apps.api.routes.options_routes import (
        api_options_dates as modular_api_options_dates,
        api_options_report as modular_api_options_report,
        api_options_snapshot as modular_api_options_snapshot,
        api_options_visual_report as modular_api_options_visual_report,
        api_options_visual_report_latest as modular_api_options_visual_report_latest,
    )

    assert api_options_snapshot is modular_api_options_snapshot
    assert api_options_report is modular_api_options_report
    assert api_options_dates is modular_api_options_dates
    assert api_options_visual_report_latest is modular_api_options_visual_report_latest
    assert api_options_visual_report is modular_api_options_visual_report


def test_main_reexports_event_flow_handlers() -> None:
    from apps.api.main import (
        api_event_flow_brief_ignore,
        api_event_flow_brief_link,
        api_event_flow_briefs,
        api_event_flow_event_detail,
        api_event_flow_event_impact,
        api_event_flow_event_market_reaction,
        api_event_flow_event_review,
        api_event_flow_events,
        api_event_flow_overview,
        api_event_flow_report_input_exclude,
        api_event_flow_report_input_include,
        api_event_flow_report_inputs,
    )
    from apps.api.routes.event_flow_routes import (
        api_event_flow_brief_ignore as modular_api_event_flow_brief_ignore,
        api_event_flow_brief_link as modular_api_event_flow_brief_link,
        api_event_flow_briefs as modular_api_event_flow_briefs,
        api_event_flow_event_detail as modular_api_event_flow_event_detail,
        api_event_flow_event_impact as modular_api_event_flow_event_impact,
        api_event_flow_event_market_reaction as modular_api_event_flow_event_market_reaction,
        api_event_flow_event_review as modular_api_event_flow_event_review,
        api_event_flow_events as modular_api_event_flow_events,
        api_event_flow_overview as modular_api_event_flow_overview,
        api_event_flow_report_input_exclude as modular_api_event_flow_report_input_exclude,
        api_event_flow_report_input_include as modular_api_event_flow_report_input_include,
        api_event_flow_report_inputs as modular_api_event_flow_report_inputs,
    )

    assert api_event_flow_overview is modular_api_event_flow_overview
    assert api_event_flow_briefs is modular_api_event_flow_briefs
    assert api_event_flow_events is modular_api_event_flow_events
    assert api_event_flow_report_inputs is modular_api_event_flow_report_inputs
    assert api_event_flow_event_detail is modular_api_event_flow_event_detail
    assert api_event_flow_event_impact is modular_api_event_flow_event_impact
    assert api_event_flow_event_market_reaction is modular_api_event_flow_event_market_reaction
    assert api_event_flow_brief_link is modular_api_event_flow_brief_link
    assert api_event_flow_brief_ignore is modular_api_event_flow_brief_ignore
    assert api_event_flow_report_input_include is modular_api_event_flow_report_input_include
    assert api_event_flow_report_input_exclude is modular_api_event_flow_report_input_exclude
    assert api_event_flow_event_review is modular_api_event_flow_event_review


def test_main_reexports_playbook_handlers() -> None:
    from apps.api.main import (
        api_create_playbook,
        api_playbook_detail,
        api_playbook_versions,
        api_playbooks,
    )
    from apps.api.routes.playbook_routes import (
        api_create_playbook as modular_api_create_playbook,
        api_playbook_detail as modular_api_playbook_detail,
        api_playbook_versions as modular_api_playbook_versions,
        api_playbooks as modular_api_playbooks,
    )

    assert api_create_playbook is modular_api_create_playbook
    assert api_playbooks is modular_api_playbooks
    assert api_playbook_detail is modular_api_playbook_detail
    assert api_playbook_versions is modular_api_playbook_versions


def test_main_reexports_knowledge_handlers() -> None:
    from apps.api.main import (
        api_knowledge_item,
        api_knowledge_items,
    )
    from apps.api.routes.knowledge_routes import (
        api_knowledge_item as modular_api_knowledge_item,
        api_knowledge_items as modular_api_knowledge_items,
    )

    assert api_knowledge_items is modular_api_knowledge_items
    assert api_knowledge_item is modular_api_knowledge_item


def test_main_reexports_settings_read_handlers() -> None:
    from apps.api.main import (
        api_settings_history,
        api_settings_status,
    )
    from apps.api.routes.settings_read_routes import (
        api_settings_history as modular_api_settings_history,
        api_settings_status as modular_api_settings_status,
    )

    assert api_settings_status is modular_api_settings_status
    assert api_settings_history is modular_api_settings_history


def test_main_reexports_settings_write_handlers() -> None:
    from apps.api.main import (
        api_settings_reset_preferences,
        api_settings_reset_secret,
        api_settings_reset_source,
        api_settings_rollback_history_event,
        api_settings_update_preferences,
        api_settings_update_secret,
        api_settings_update_source,
    )
    from apps.api.routes.settings_write_routes import (
        api_settings_reset_preferences as modular_api_settings_reset_preferences,
        api_settings_reset_secret as modular_api_settings_reset_secret,
        api_settings_reset_source as modular_api_settings_reset_source,
        api_settings_rollback_history_event as modular_api_settings_rollback_history_event,
        api_settings_update_preferences as modular_api_settings_update_preferences,
        api_settings_update_secret as modular_api_settings_update_secret,
        api_settings_update_source as modular_api_settings_update_source,
    )

    assert api_settings_update_preferences is modular_api_settings_update_preferences
    assert api_settings_reset_preferences is modular_api_settings_reset_preferences
    assert api_settings_update_source is modular_api_settings_update_source
    assert api_settings_reset_source is modular_api_settings_reset_source
    assert api_settings_update_secret is modular_api_settings_update_secret
    assert api_settings_reset_secret is modular_api_settings_reset_secret
    assert api_settings_rollback_history_event is modular_api_settings_rollback_history_event


def test_main_reexports_jin10_report_handlers() -> None:
    from apps.api.main import (
        api_jin10_article_briefs,
        api_jin10_article_briefs_latest,
        api_jin10_daily_report,
        api_jin10_daily_report_latest,
        api_jin10_report_bundle,
        api_jin10_report_bundle_asset,
        api_jin10_report_bundle_latest,
        api_jin10_web_flash_briefs,
        api_jin10_web_flash_briefs_latest,
        api_jin10_weekly_report,
        api_jin10_weekly_report_latest,
    )
    from apps.api.routes.jin10_report_routes import (
        api_jin10_article_briefs as modular_api_jin10_article_briefs,
        api_jin10_article_briefs_latest as modular_api_jin10_article_briefs_latest,
        api_jin10_daily_report as modular_api_jin10_daily_report,
        api_jin10_daily_report_latest as modular_api_jin10_daily_report_latest,
        api_jin10_report_bundle as modular_api_jin10_report_bundle,
        api_jin10_report_bundle_asset as modular_api_jin10_report_bundle_asset,
        api_jin10_report_bundle_latest as modular_api_jin10_report_bundle_latest,
        api_jin10_web_flash_briefs as modular_api_jin10_web_flash_briefs,
        api_jin10_web_flash_briefs_latest as modular_api_jin10_web_flash_briefs_latest,
        api_jin10_weekly_report as modular_api_jin10_weekly_report,
        api_jin10_weekly_report_latest as modular_api_jin10_weekly_report_latest,
    )

    assert api_jin10_daily_report_latest is modular_api_jin10_daily_report_latest
    assert api_jin10_daily_report is modular_api_jin10_daily_report
    assert api_jin10_weekly_report_latest is modular_api_jin10_weekly_report_latest
    assert api_jin10_weekly_report is modular_api_jin10_weekly_report
    assert api_jin10_report_bundle_latest is modular_api_jin10_report_bundle_latest
    assert api_jin10_report_bundle is modular_api_jin10_report_bundle
    assert api_jin10_report_bundle_asset is modular_api_jin10_report_bundle_asset
    assert api_jin10_article_briefs_latest is modular_api_jin10_article_briefs_latest
    assert api_jin10_article_briefs is modular_api_jin10_article_briefs
    assert api_jin10_web_flash_briefs_latest is modular_api_jin10_web_flash_briefs_latest
    assert api_jin10_web_flash_briefs is modular_api_jin10_web_flash_briefs


def test_main_reexports_news_handlers() -> None:
    from apps.api.main import (
        api_create_daily_analysis_followup_tasks,
        api_daily_analysis_followups,
        api_daily_analysis_followups_latest,
        api_daily_analysis_triggers,
        api_daily_analysis_triggers_latest,
        api_daily_brief,
        api_daily_brief_latest,
        api_feishu_jin10_message_monitor,
        api_feishu_jin10_message_monitor_dates,
        api_feishu_jin10_message_monitor_latest,
    )
    from apps.api.routes.news_routes import (
        api_create_daily_analysis_followup_tasks as modular_api_create_daily_analysis_followup_tasks,
        api_daily_analysis_followups as modular_api_daily_analysis_followups,
        api_daily_analysis_followups_latest as modular_api_daily_analysis_followups_latest,
        api_daily_analysis_triggers as modular_api_daily_analysis_triggers,
        api_daily_analysis_triggers_latest as modular_api_daily_analysis_triggers_latest,
        api_daily_brief as modular_api_daily_brief,
        api_daily_brief_latest as modular_api_daily_brief_latest,
        api_feishu_jin10_message_monitor as modular_api_feishu_jin10_message_monitor,
        api_feishu_jin10_message_monitor_dates as modular_api_feishu_jin10_message_monitor_dates,
        api_feishu_jin10_message_monitor_latest as modular_api_feishu_jin10_message_monitor_latest,
    )

    assert api_daily_analysis_triggers_latest is modular_api_daily_analysis_triggers_latest
    assert api_daily_analysis_triggers is modular_api_daily_analysis_triggers
    assert api_daily_brief_latest is modular_api_daily_brief_latest
    assert api_daily_brief is modular_api_daily_brief
    assert api_daily_analysis_followups_latest is modular_api_daily_analysis_followups_latest
    assert api_daily_analysis_followups is modular_api_daily_analysis_followups
    assert api_create_daily_analysis_followup_tasks is modular_api_create_daily_analysis_followup_tasks
    assert api_feishu_jin10_message_monitor_latest is modular_api_feishu_jin10_message_monitor_latest
    assert api_feishu_jin10_message_monitor_dates is modular_api_feishu_jin10_message_monitor_dates
    assert api_feishu_jin10_message_monitor is modular_api_feishu_jin10_message_monitor


def test_main_reexports_jin10_market_handlers() -> None:
    from apps.api.main import (
        api_jin10_calendar,
        api_jin10_flash,
        api_jin10_kline,
        api_jin10_quotes_latest,
    )
    from apps.api.routes.jin10_market_routes import (
        api_jin10_calendar as modular_api_jin10_calendar,
        api_jin10_flash as modular_api_jin10_flash,
        api_jin10_kline as modular_api_jin10_kline,
        api_jin10_quotes_latest as modular_api_jin10_quotes_latest,
    )

    assert api_jin10_quotes_latest is modular_api_jin10_quotes_latest
    assert api_jin10_calendar is modular_api_jin10_calendar
    assert api_jin10_flash is modular_api_jin10_flash
    assert api_jin10_kline is modular_api_jin10_kline


def test_jin10_market_routes_do_not_depend_on_fastapi_main_helpers() -> None:
    from pathlib import Path

    source = Path("apps/api/routes/jin10_market_routes.py").read_text(encoding="utf-8")

    assert "from apps.api import main as api_main" not in source
    assert "from apps.api.services import jin10_market_service" in source


def test_market_monitor_routes_depend_on_data_service_not_fastapi_main() -> None:
    from pathlib import Path

    source = Path("apps/api/routes/market_monitor_routes.py").read_text(encoding="utf-8")

    assert "from apps.api import main as api_main" not in source
    assert "from apps.api.data_service import" in source


def test_macro_routes_depend_on_data_service_not_fastapi_main() -> None:
    from pathlib import Path

    source = Path("apps/api/routes/macro_routes.py").read_text(encoding="utf-8")

    assert "from apps.api import main as api_main" not in source
    assert "from apps.api.data_service import" in source


def test_options_routes_depend_on_data_service_not_fastapi_main() -> None:
    from pathlib import Path

    source = Path("apps/api/routes/options_routes.py").read_text(encoding="utf-8")

    assert "from apps.api import main as api_main" not in source
    assert "from apps.api.data_service import" in source


def test_gold_mainline_routes_depend_on_service_not_fastapi_main() -> None:
    from pathlib import Path

    source = Path("apps/api/routes/gold_mainline_routes.py").read_text(encoding="utf-8")

    assert "from apps.api import main as api_main" not in source
    assert "from apps.api.services.gold_mainline_service import" in source


def test_pure_service_routes_do_not_depend_on_fastapi_main() -> None:
    from pathlib import Path

    route_files = (
        "data_source_routes.py",
        "event_flow_routes.py",
        "jin10_report_routes.py",
        "market_odds_routes.py",
        "news_routes.py",
        "operations_routes.py",
        "playbook_routes.py",
        "reports_routes.py",
        "settings_read_routes.py",
        "settings_write_routes.py",
        "strategy_report_routes.py",
    )
    for route_file in route_files:
        source = Path("apps/api/routes", route_file).read_text(encoding="utf-8")
        assert "from apps.api import main as api_main" not in source, route_file


def test_main_reexports_premarket_handlers() -> None:
    from apps.api.main import (
        api_premarket_launch_preflight,
        api_premarket_pipeline_contract,
        api_premarket_pipeline_readiness,
        get_task,
        get_task_logs,
        trigger_premarket,
    )
    from apps.api.routes.premarket_routes import (
        api_premarket_launch_preflight as modular_api_premarket_launch_preflight,
        api_premarket_pipeline_contract as modular_api_premarket_pipeline_contract,
        api_premarket_pipeline_readiness as modular_api_premarket_pipeline_readiness,
        get_task as modular_get_task,
        get_task_logs as modular_get_task_logs,
        trigger_premarket as modular_trigger_premarket,
    )

    assert api_premarket_pipeline_contract is modular_api_premarket_pipeline_contract
    assert api_premarket_pipeline_readiness is modular_api_premarket_pipeline_readiness
    assert api_premarket_launch_preflight is modular_api_premarket_launch_preflight
    assert trigger_premarket is modular_trigger_premarket
    assert get_task is modular_get_task
    assert get_task_logs is modular_get_task_logs


def test_main_reexports_health_handlers() -> None:
    from apps.api.main import health
    from apps.api.routes.health_routes import health as modular_health

    assert health is modular_health


def test_main_reexports_gold_mainline_handlers() -> None:
    from apps.api.main import (
        api_gold_mainlines,
        api_gold_mainlines_latest,
        api_gold_runtime_orchestration_contract,
        api_gold_runtime_summary_preview,
    )
    from apps.api.routes.gold_mainline_routes import (
        api_gold_mainlines as modular_api_gold_mainlines,
        api_gold_mainlines_latest as modular_api_gold_mainlines_latest,
        api_gold_runtime_orchestration_contract as modular_api_gold_runtime_orchestration_contract,
        api_gold_runtime_summary_preview as modular_api_gold_runtime_summary_preview,
    )

    assert api_gold_mainlines_latest is modular_api_gold_mainlines_latest
    assert api_gold_mainlines is modular_api_gold_mainlines
    assert api_gold_runtime_orchestration_contract is modular_api_gold_runtime_orchestration_contract
    assert api_gold_runtime_summary_preview is modular_api_gold_runtime_summary_preview


def test_main_reexports_agent_governance_read_handlers() -> None:
    from apps.api.main import (
        api_agent_registry_detail,
        api_agents_registry,
        api_prompt_evolution_latest,
        api_prompt_evolution_proposal,
        api_prompt_versions_active,
        api_prompt_versions_by_agent,
        api_prompt_versions_list,
    )
    from apps.api.routes.agent_governance_read_routes import (
        api_agent_registry_detail as modular_api_agent_registry_detail,
        api_agents_registry as modular_api_agents_registry,
        api_prompt_evolution_latest as modular_api_prompt_evolution_latest,
        api_prompt_evolution_proposal as modular_api_prompt_evolution_proposal,
        api_prompt_versions_active as modular_api_prompt_versions_active,
        api_prompt_versions_by_agent as modular_api_prompt_versions_by_agent,
        api_prompt_versions_list as modular_api_prompt_versions_list,
    )

    assert api_agents_registry is modular_api_agents_registry
    assert api_agent_registry_detail is modular_api_agent_registry_detail
    assert api_prompt_versions_list is modular_api_prompt_versions_list
    assert api_prompt_versions_by_agent is modular_api_prompt_versions_by_agent
    assert api_prompt_versions_active is modular_api_prompt_versions_active
    assert api_prompt_evolution_proposal is modular_api_prompt_evolution_proposal
    assert api_prompt_evolution_latest is modular_api_prompt_evolution_latest


def test_main_reexports_agent_governance_write_handlers() -> None:
    from apps.api.main import (
        api_prompt_evolution_release_action,
        api_prompt_feedback_by_agent,
        api_prompt_feedback_create,
        api_prompt_feedback_list,
        api_prompt_versions_activate,
        api_prompt_versions_create,
    )
    from apps.api.routes.agent_governance_write_routes import (
        api_prompt_evolution_release_action as modular_api_prompt_evolution_release_action,
        api_prompt_feedback_by_agent as modular_api_prompt_feedback_by_agent,
        api_prompt_feedback_create as modular_api_prompt_feedback_create,
        api_prompt_feedback_list as modular_api_prompt_feedback_list,
        api_prompt_versions_activate as modular_api_prompt_versions_activate,
        api_prompt_versions_create as modular_api_prompt_versions_create,
    )

    assert api_prompt_versions_create is modular_api_prompt_versions_create
    assert api_prompt_versions_activate is modular_api_prompt_versions_activate
    assert api_prompt_feedback_create is modular_api_prompt_feedback_create
    assert api_prompt_feedback_by_agent is modular_api_prompt_feedback_by_agent
    assert api_prompt_feedback_list is modular_api_prompt_feedback_list
    assert api_prompt_evolution_release_action is modular_api_prompt_evolution_release_action


def test_main_reexports_agent_analysis_read_handlers() -> None:
    from apps.api.main import (
        api_agent_analysis_by_date,
        api_agent_analysis_inspect,
        api_agent_analysis_latest,
        api_agent_analysis_synthesis_latest,
    )
    from apps.api.routes.agent_analysis_read_routes import (
        api_agent_analysis_by_date as modular_api_agent_analysis_by_date,
        api_agent_analysis_inspect as modular_api_agent_analysis_inspect,
        api_agent_analysis_latest as modular_api_agent_analysis_latest,
        api_agent_analysis_synthesis_latest as modular_api_agent_analysis_synthesis_latest,
    )

    assert api_agent_analysis_latest is modular_api_agent_analysis_latest
    assert api_agent_analysis_by_date is modular_api_agent_analysis_by_date
    assert api_agent_analysis_inspect is modular_api_agent_analysis_inspect
    assert api_agent_analysis_synthesis_latest is modular_api_agent_analysis_synthesis_latest


def test_main_reexports_agent_analysis_run_handler() -> None:
    from apps.api.main import api_run_agent_analysis
    from apps.api.routes.agent_analysis_run_routes import (
        api_run_agent_analysis as modular_api_run_agent_analysis,
    )

    assert api_run_agent_analysis is modular_api_run_agent_analysis


def test_main_reexports_frontend_compat_handlers() -> None:
    from apps.api.main import (
        serve_agent_tasks,
        serve_agent_tasks_subpath,
        serve_cme_options,
        serve_dashboard,
        serve_dashboard_analysis,
        serve_data_ingestion,
        serve_data_sources_subpath,
        serve_event_flow,
        serve_event_flow_subpath,
        serve_frontend_asset,
        serve_frontend_favicon,
        serve_knowledge_base,
        serve_market_monitor,
        serve_reports,
        serve_reports_subpath,
        serve_review_center,
        serve_scheduler,
        serve_scheduler_subpath,
        serve_settings,
        serve_settings_audit,
    )
    from apps.api.routes.frontend_compat_routes import (
        serve_agent_tasks as modular_serve_agent_tasks,
        serve_agent_tasks_subpath as modular_serve_agent_tasks_subpath,
        serve_cme_options as modular_serve_cme_options,
        serve_dashboard as modular_serve_dashboard,
        serve_dashboard_analysis as modular_serve_dashboard_analysis,
        serve_data_ingestion as modular_serve_data_ingestion,
        serve_data_sources_subpath as modular_serve_data_sources_subpath,
        serve_event_flow as modular_serve_event_flow,
        serve_event_flow_subpath as modular_serve_event_flow_subpath,
        serve_frontend_asset as modular_serve_frontend_asset,
        serve_frontend_favicon as modular_serve_frontend_favicon,
        serve_knowledge_base as modular_serve_knowledge_base,
        serve_market_monitor as modular_serve_market_monitor,
        serve_reports as modular_serve_reports,
        serve_reports_subpath as modular_serve_reports_subpath,
        serve_review_center as modular_serve_review_center,
        serve_scheduler as modular_serve_scheduler,
        serve_scheduler_subpath as modular_serve_scheduler_subpath,
        serve_settings as modular_serve_settings,
        serve_settings_audit as modular_serve_settings_audit,
    )

    assert serve_frontend_asset is modular_serve_frontend_asset
    assert serve_frontend_favicon is modular_serve_frontend_favicon
    assert serve_dashboard is modular_serve_dashboard
    assert serve_dashboard_analysis is modular_serve_dashboard_analysis
    assert serve_data_ingestion is modular_serve_data_ingestion
    assert serve_data_sources_subpath is modular_serve_data_sources_subpath
    assert serve_market_monitor is modular_serve_market_monitor
    assert serve_cme_options is modular_serve_cme_options
    assert serve_reports is modular_serve_reports
    assert serve_reports_subpath is modular_serve_reports_subpath
    assert serve_event_flow is modular_serve_event_flow
    assert serve_event_flow_subpath is modular_serve_event_flow_subpath
    assert serve_knowledge_base is modular_serve_knowledge_base
    assert serve_agent_tasks is modular_serve_agent_tasks
    assert serve_scheduler is modular_serve_scheduler
    assert serve_scheduler_subpath is modular_serve_scheduler_subpath
    assert serve_agent_tasks_subpath is modular_serve_agent_tasks_subpath
    assert serve_review_center is modular_serve_review_center
    assert serve_settings is modular_serve_settings
    assert serve_settings_audit is modular_serve_settings_audit


def test_main_reexports_system_status_handler() -> None:
    from apps.api.main import system_status
    from apps.api.routes.system_status_routes import system_status as modular_system_status

    assert system_status is modular_system_status


def test_app_registers_modular_execution_and_source_trace_routes() -> None:
    from apps.api.routes.execution_read_routes import (
        api_artifact_detail as modular_api_artifact_detail,
        api_run_artifacts as modular_api_run_artifacts,
        api_run_detail as modular_api_run_detail,
        api_run_events as modular_api_run_events,
        api_run_logs as modular_api_run_logs,
        api_run_steps as modular_api_run_steps,
        api_runs as modular_api_runs,
    )
    from apps.api.routes.source_trace_routes import (
        api_source_trace_by_artifact as modular_api_source_trace_by_artifact,
        api_source_trace_by_report as modular_api_source_trace_by_report,
        api_source_trace_by_strategy as modular_api_source_trace_by_strategy,
        api_source_trace_detail as modular_api_source_trace_detail,
    )

    route_map = _route_endpoint_map()

    assert route_map["/api/runs"] is modular_api_runs
    assert route_map["/api/runs/{run_id}"] is modular_api_run_detail
    assert route_map["/api/runs/{run_id}/steps"] is modular_api_run_steps
    assert route_map["/api/runs/{run_id}/logs"] is modular_api_run_logs
    assert route_map["/api/runs/{run_id}/artifacts"] is modular_api_run_artifacts
    assert route_map["/api/artifacts/{artifact_id}"] is modular_api_artifact_detail
    assert route_map["/api/runs/{run_id}/events"] is modular_api_run_events
    assert route_map["/api/source-trace/by-report/{report_id}"] is modular_api_source_trace_by_report
    assert route_map["/api/source-trace/by-strategy/{strategy_card_id}"] is modular_api_source_trace_by_strategy
    assert route_map["/api/source-trace/by-artifact/{artifact_id}"] is modular_api_source_trace_by_artifact
    assert route_map["/api/source-trace/{snapshot_id}"] is modular_api_source_trace_detail


def test_app_registers_modular_data_source_and_ingestion_routes() -> None:
    from apps.api.routes.data_source_routes import (
        api_data_source_health as modular_api_data_source_health,
        api_data_source_health_latest as modular_api_data_source_health_latest,
        api_data_source_history as modular_api_data_source_history,
        api_data_sources_registry as modular_api_data_sources_registry,
        api_data_sources_status as modular_api_data_sources_status,
        api_data_status_summary as modular_api_data_status_summary,
        api_ingestion_manual_upload as modular_api_ingestion_manual_upload,
        api_ingestion_source_retry as modular_api_ingestion_source_retry,
        api_ingestion_source_test as modular_api_ingestion_source_test,
    )

    route_map = _route_endpoint_map()

    assert route_map["/api/data-sources/status"] is modular_api_data_sources_status
    assert route_map["/api/data-sources/registry"] is modular_api_data_sources_registry
    assert route_map["/api/data-status/summary"] is modular_api_data_status_summary
    assert route_map["/api/data-sources/health/latest"] is modular_api_data_source_health_latest
    assert route_map["/api/data-sources/health"] is modular_api_data_source_health
    assert route_map["/api/data-sources/{source_key}/history"] is modular_api_data_source_history
    assert route_map["/api/ingestion/sources/{source_key}/retry"] is modular_api_ingestion_source_retry
    assert route_map["/api/ingestion/sources/{source_key}/test"] is modular_api_ingestion_source_test
    assert route_map["/api/ingestion/manual-upload"] is modular_api_ingestion_manual_upload


def test_app_registers_modular_review_routes() -> None:
    from apps.api.routes.review_routes import (
        api_review_approve as modular_api_review_approve,
        api_review_detail as modular_api_review_detail,
        api_review_reject as modular_api_review_reject,
        api_review_rerun as modular_api_review_rerun,
        api_review_use_fallback as modular_api_review_use_fallback,
        api_reviews as modular_api_reviews,
    )

    route_map = _route_endpoint_map()

    assert route_map["/api/reviews"] is modular_api_reviews
    assert route_map["/api/reviews/{review_id}"] is modular_api_review_detail
    assert route_map["/api/reviews/{review_id}/approve"] is modular_api_review_approve
    assert route_map["/api/reviews/{review_id}/reject"] is modular_api_review_reject
    assert route_map["/api/reviews/{review_id}/rerun"] is modular_api_review_rerun
    assert route_map["/api/reviews/{review_id}/use-fallback"] is modular_api_review_use_fallback


def test_app_registers_modular_strategy_report_routes() -> None:
    from apps.api.routes.strategy_report_routes import (
        api_final_report as modular_api_final_report,
        api_final_report_latest as modular_api_final_report_latest,
        api_strategy_card as modular_api_strategy_card,
        api_strategy_card_assets as modular_api_strategy_card_assets,
        api_strategy_card_detail as modular_api_strategy_card_detail,
        api_strategy_card_latest as modular_api_strategy_card_latest,
        api_strategy_cards as modular_api_strategy_cards,
        api_strategy_cards_latest as modular_api_strategy_cards_latest,
    )

    route_map = _route_endpoint_map()

    assert route_map["/api/final-report/latest"] is modular_api_final_report_latest
    assert route_map["/api/final-report"] is modular_api_final_report
    assert route_map["/api/strategy-card/latest"] is modular_api_strategy_card_latest
    assert route_map["/api/strategy-card"] is modular_api_strategy_card
    assert route_map["/api/strategy-cards"] is modular_api_strategy_cards
    assert route_map["/api/strategy-cards/assets"] is modular_api_strategy_card_assets
    assert route_map["/api/strategy-cards/latest"] is modular_api_strategy_cards_latest
    assert route_map["/api/strategy-cards/{strategy_card_id}"] is modular_api_strategy_card_detail


def test_app_registers_modular_live_strategy_routes() -> None:
    from apps.api.routes.live_strategy_routes import (
        api_live_strategy_latest as modular_api_live_strategy_latest,
        api_live_strategy_recompute_preview as modular_api_live_strategy_recompute_preview,
    )

    route_map = _route_endpoint_map()

    assert route_map["/api/live-strategy/latest"] is modular_api_live_strategy_latest
    assert (
        route_map["/api/live-strategy/recompute-preview"]
        is modular_api_live_strategy_recompute_preview
    )


def test_app_registers_modular_market_monitor_routes() -> None:
    from apps.api.routes.market_monitor_routes import (
        api_market_monitor as modular_api_market_monitor,
        api_market_monitor_history as modular_api_market_monitor_history,
        api_market_tickers as modular_api_market_tickers,
    )

    route_map = _route_endpoint_map()

    assert route_map["/api/market/tickers"] is modular_api_market_tickers
    assert route_map["/api/market/monitor"] is modular_api_market_monitor
    assert route_map["/api/market/monitor/history"] is modular_api_market_monitor_history


def test_app_registers_modular_report_routes() -> None:
    from apps.api.routes.reports_routes import (
        api_report_analysis as modular_api_report_analysis,
        api_report_analysis_inputs as modular_api_report_analysis_inputs,
        api_report_artifact_asset as modular_api_report_artifact_asset,
        api_report_artifacts as modular_api_report_artifacts,
        api_report_detail as modular_api_report_detail,
        api_report_evidence as modular_api_report_evidence,
        api_report_source as modular_api_report_source,
        api_report_visual as modular_api_report_visual,
        api_reports_dates as modular_api_reports_dates,
        api_reports_index as modular_api_reports_index,
    )

    route_map = _route_endpoint_map()

    assert route_map["/api/reports/index"] is modular_api_reports_index
    assert route_map["/api/reports/dates"] is modular_api_reports_dates
    assert route_map["/api/reports/{report_id}"] is modular_api_report_detail
    assert route_map["/api/reports/{report_id}/artifacts"] is modular_api_report_artifacts
    assert route_map["/api/reports/{report_id}/source"] is modular_api_report_source
    assert route_map["/api/reports/{report_id}/analysis"] is modular_api_report_analysis
    assert route_map["/api/reports/{report_id}/asset/{artifact_type}/{asset_path:path}"] is modular_api_report_artifact_asset
    assert route_map["/api/reports/{report_id}/visual"] is modular_api_report_visual
    assert route_map["/api/reports/{report_id}/evidence"] is modular_api_report_evidence
    assert route_map["/api/reports/{report_id}/analysis-inputs"] is modular_api_report_analysis_inputs


def test_app_registers_modular_market_odds_routes() -> None:
    from apps.api.routes.market_odds_routes import (
        api_market_odds_report as modular_api_market_odds_report,
        api_market_odds_snapshot as modular_api_market_odds_snapshot,
    )

    route_map = _route_endpoint_map()

    assert route_map["/api/market-odds/snapshot"] is modular_api_market_odds_snapshot
    assert route_map["/api/market-odds/report"] is modular_api_market_odds_report


def test_app_registers_modular_operations_routes() -> None:
    from apps.api.routes.operations_routes import (
        api_dashboard_summary as modular_api_dashboard_summary,
        api_run_all_collectors as modular_api_run_all_collectors,
        api_scheduler_overview as modular_api_scheduler_overview,
        api_tasks as modular_api_tasks,
    )

    route_map = _route_endpoint_map()

    assert route_map["/api/tasks"] is modular_api_tasks
    assert route_map["/api/scheduler/overview"] is modular_api_scheduler_overview
    assert route_map["/api/scheduler/run-all-collectors"] is modular_api_run_all_collectors
    assert route_map["/api/dashboard/summary"] is modular_api_dashboard_summary


def test_app_registers_modular_orchestration_routes() -> None:
    from apps.api.routes.orchestration_routes import (
        api_orchestration_latest as modular_api_orchestration_latest,
        api_orchestration_manual_review_action as modular_api_orchestration_manual_review_action,
        api_orchestration_manual_review as modular_api_orchestration_manual_review,
        api_orchestration_notification_plan as modular_api_orchestration_notification_plan,
    )

    route_map = _route_endpoint_map()
    method_route_map = _route_method_endpoint_map()

    assert route_map["/api/orchestration/latest"] is modular_api_orchestration_latest
    assert route_map["/api/orchestration/notification-plan"] is modular_api_orchestration_notification_plan
    assert route_map["/api/orchestration/manual-review"] is modular_api_orchestration_manual_review
    assert method_route_map[("/api/orchestration/manual-review/action", "POST")] is modular_api_orchestration_manual_review_action


def test_main_reexports_orchestration_handlers() -> None:
    from apps.api.main import (
        api_orchestration_latest,
        api_orchestration_manual_review_action,
        api_orchestration_manual_review,
        api_orchestration_notification_plan,
    )
    from apps.api.routes.orchestration_routes import (
        api_orchestration_latest as modular_api_orchestration_latest,
        api_orchestration_manual_review_action as modular_api_orchestration_manual_review_action,
        api_orchestration_manual_review as modular_api_orchestration_manual_review,
        api_orchestration_notification_plan as modular_api_orchestration_notification_plan,
    )

    assert api_orchestration_latest is modular_api_orchestration_latest
    assert api_orchestration_notification_plan is modular_api_orchestration_notification_plan
    assert api_orchestration_manual_review is modular_api_orchestration_manual_review
    assert api_orchestration_manual_review_action is modular_api_orchestration_manual_review_action


def test_app_registers_modular_macro_routes() -> None:
    from apps.api.routes.macro_routes import (
        api_macro_latest as modular_api_macro_latest,
        api_macro_report as modular_api_macro_report,
    )

    route_map = _route_endpoint_map()

    assert route_map["/api/macro/latest"] is modular_api_macro_latest
    assert route_map["/api/macro/report"] is modular_api_macro_report


def test_app_registers_modular_options_routes() -> None:
    from apps.api.routes.options_routes import (
        api_options_dates as modular_api_options_dates,
        api_options_report as modular_api_options_report,
        api_options_snapshot as modular_api_options_snapshot,
        api_options_visual_report as modular_api_options_visual_report,
        api_options_visual_report_latest as modular_api_options_visual_report_latest,
    )

    route_map = _route_endpoint_map()

    assert route_map["/api/options/snapshot"] is modular_api_options_snapshot
    assert route_map["/api/options/report"] is modular_api_options_report
    assert route_map["/api/options/dates"] is modular_api_options_dates
    assert route_map["/api/options/visual-report/latest"] is modular_api_options_visual_report_latest
    assert route_map["/api/options/visual-report"] is modular_api_options_visual_report


def test_app_registers_modular_event_flow_routes() -> None:
    from apps.api.routes.event_flow_routes import (
        api_event_flow_brief_ignore as modular_api_event_flow_brief_ignore,
        api_event_flow_brief_link as modular_api_event_flow_brief_link,
        api_event_flow_briefs as modular_api_event_flow_briefs,
        api_event_flow_event_detail as modular_api_event_flow_event_detail,
        api_event_flow_event_impact as modular_api_event_flow_event_impact,
        api_event_flow_event_market_reaction as modular_api_event_flow_event_market_reaction,
        api_event_flow_event_review as modular_api_event_flow_event_review,
        api_event_flow_events as modular_api_event_flow_events,
        api_event_flow_overview as modular_api_event_flow_overview,
        api_event_flow_report_input_exclude as modular_api_event_flow_report_input_exclude,
        api_event_flow_report_input_include as modular_api_event_flow_report_input_include,
        api_event_flow_report_inputs as modular_api_event_flow_report_inputs,
    )

    route_map = _route_endpoint_map()

    assert route_map["/api/events/flow/overview"] is modular_api_event_flow_overview
    assert route_map["/api/events/briefs"] is modular_api_event_flow_briefs
    assert route_map["/api/events"] is modular_api_event_flow_events
    assert route_map["/api/events/report-inputs"] is modular_api_event_flow_report_inputs
    assert route_map["/api/events/{event_id}"] is modular_api_event_flow_event_detail
    assert route_map["/api/events/{event_id}/impact"] is modular_api_event_flow_event_impact
    assert route_map["/api/events/{event_id}/market-reaction"] is modular_api_event_flow_event_market_reaction
    assert route_map["/api/events/briefs/{brief_id}/link"] is modular_api_event_flow_brief_link
    assert route_map["/api/events/briefs/{brief_id}/ignore"] is modular_api_event_flow_brief_ignore
    assert route_map["/api/events/report-inputs/{input_id}/include"] is modular_api_event_flow_report_input_include
    assert route_map["/api/events/report-inputs/{input_id}/exclude"] is modular_api_event_flow_report_input_exclude
    assert route_map["/api/events/{event_id}/review"] is modular_api_event_flow_event_review


def test_app_registers_modular_playbook_routes() -> None:
    from apps.api.routes.playbook_routes import (
        api_create_playbook as modular_api_create_playbook,
        api_playbook_detail as modular_api_playbook_detail,
        api_playbook_versions as modular_api_playbook_versions,
        api_playbooks as modular_api_playbooks,
    )

    route_map = _route_method_endpoint_map()

    assert route_map[("/api/playbooks", "POST")] is modular_api_create_playbook
    assert route_map[("/api/playbooks", "GET")] is modular_api_playbooks
    assert route_map[("/api/playbooks/{playbook_id}", "GET")] is modular_api_playbook_detail
    assert route_map[("/api/playbooks/{playbook_id}/versions", "GET")] is modular_api_playbook_versions


def test_app_registers_modular_knowledge_routes() -> None:
    from apps.api.routes.knowledge_routes import (
        api_knowledge_item as modular_api_knowledge_item,
        api_knowledge_items as modular_api_knowledge_items,
    )

    route_map = _route_endpoint_map()

    assert route_map["/api/knowledge/items"] is modular_api_knowledge_items
    assert route_map["/api/knowledge/items/{item_id}"] is modular_api_knowledge_item


def test_app_registers_modular_settings_read_routes() -> None:
    from apps.api.routes.settings_read_routes import (
        api_settings_history as modular_api_settings_history,
        api_settings_status as modular_api_settings_status,
    )

    route_map = _route_endpoint_map()

    assert route_map["/api/settings/status"] is modular_api_settings_status
    assert route_map["/api/settings/history"] is modular_api_settings_history


def test_app_registers_modular_settings_write_routes() -> None:
    from apps.api.routes.settings_write_routes import (
        api_settings_reset_preferences as modular_api_settings_reset_preferences,
        api_settings_reset_secret as modular_api_settings_reset_secret,
        api_settings_reset_source as modular_api_settings_reset_source,
        api_settings_rollback_history_event as modular_api_settings_rollback_history_event,
        api_settings_update_preferences as modular_api_settings_update_preferences,
        api_settings_update_secret as modular_api_settings_update_secret,
        api_settings_update_source as modular_api_settings_update_source,
    )

    route_map = _route_method_endpoint_map()

    assert route_map[("/api/settings/preferences", "POST")] is modular_api_settings_update_preferences
    assert route_map[("/api/settings/preferences/reset", "POST")] is modular_api_settings_reset_preferences
    assert route_map[("/api/settings/sources/{source_key}", "POST")] is modular_api_settings_update_source
    assert route_map[("/api/settings/sources/{source_key}/reset", "POST")] is modular_api_settings_reset_source
    assert route_map[("/api/settings/secrets/{source_key}", "POST")] is modular_api_settings_update_secret
    assert route_map[("/api/settings/secrets/{source_key}/reset", "POST")] is modular_api_settings_reset_secret
    assert route_map[("/api/settings/history/{audit_id}/rollback", "POST")] is modular_api_settings_rollback_history_event


def test_app_registers_modular_jin10_report_routes() -> None:
    from apps.api.routes.jin10_report_routes import (
        api_jin10_article_briefs as modular_api_jin10_article_briefs,
        api_jin10_article_briefs_latest as modular_api_jin10_article_briefs_latest,
        api_jin10_daily_report as modular_api_jin10_daily_report,
        api_jin10_daily_report_latest as modular_api_jin10_daily_report_latest,
        api_jin10_report_bundle as modular_api_jin10_report_bundle,
        api_jin10_report_bundle_asset as modular_api_jin10_report_bundle_asset,
        api_jin10_report_bundle_latest as modular_api_jin10_report_bundle_latest,
        api_jin10_web_flash_briefs as modular_api_jin10_web_flash_briefs,
        api_jin10_web_flash_briefs_latest as modular_api_jin10_web_flash_briefs_latest,
        api_jin10_weekly_report as modular_api_jin10_weekly_report,
        api_jin10_weekly_report_latest as modular_api_jin10_weekly_report_latest,
    )

    route_map = _route_endpoint_map()

    assert route_map["/api/jin10/daily-report/latest"] is modular_api_jin10_daily_report_latest
    assert route_map["/api/jin10/daily-report"] is modular_api_jin10_daily_report
    assert route_map["/api/jin10/weekly-report/latest"] is modular_api_jin10_weekly_report_latest
    assert route_map["/api/jin10/weekly-report"] is modular_api_jin10_weekly_report
    assert route_map["/api/jin10/report-bundle/latest"] is modular_api_jin10_report_bundle_latest
    assert route_map["/api/jin10/report-bundle"] is modular_api_jin10_report_bundle
    assert route_map["/api/jin10/report-bundle/{date}/{run_id}/asset/{asset_path:path}"] is modular_api_jin10_report_bundle_asset
    assert route_map["/api/jin10/article-briefs/latest"] is modular_api_jin10_article_briefs_latest
    assert route_map["/api/jin10/article-briefs"] is modular_api_jin10_article_briefs
    assert route_map["/api/jin10/web-flash-briefs/latest"] is modular_api_jin10_web_flash_briefs_latest
    assert route_map["/api/jin10/web-flash-briefs"] is modular_api_jin10_web_flash_briefs


def test_app_registers_modular_news_routes() -> None:
    from apps.api.routes.news_routes import (
        api_create_daily_analysis_followup_tasks as modular_api_create_daily_analysis_followup_tasks,
        api_daily_analysis_followups as modular_api_daily_analysis_followups,
        api_daily_analysis_followups_latest as modular_api_daily_analysis_followups_latest,
        api_daily_analysis_triggers as modular_api_daily_analysis_triggers,
        api_daily_analysis_triggers_latest as modular_api_daily_analysis_triggers_latest,
        api_daily_brief as modular_api_daily_brief,
        api_daily_brief_latest as modular_api_daily_brief_latest,
        api_feishu_jin10_message_monitor as modular_api_feishu_jin10_message_monitor,
        api_feishu_jin10_message_monitor_dates as modular_api_feishu_jin10_message_monitor_dates,
        api_feishu_jin10_message_monitor_latest as modular_api_feishu_jin10_message_monitor_latest,
    )

    route_map = _route_endpoint_map()
    route_method_map = _route_method_endpoint_map()

    assert route_map["/api/news/daily-analysis-triggers/latest"] is modular_api_daily_analysis_triggers_latest
    assert route_map["/api/news/daily-analysis-triggers"] is modular_api_daily_analysis_triggers
    assert route_map["/api/news/daily-brief/latest"] is modular_api_daily_brief_latest
    assert route_map["/api/news/daily-brief"] is modular_api_daily_brief
    assert route_map["/api/news/daily-analysis-followups/latest"] is modular_api_daily_analysis_followups_latest
    assert route_map["/api/news/daily-analysis-followups"] is modular_api_daily_analysis_followups
    assert route_method_map[("/api/news/daily-analysis-followups/tasks", "POST")] is modular_api_create_daily_analysis_followup_tasks
    assert route_map["/api/news/feishu-jin10/messages/latest"] is modular_api_feishu_jin10_message_monitor_latest
    assert route_map["/api/news/feishu-jin10/dates"] is modular_api_feishu_jin10_message_monitor_dates
    assert route_map["/api/news/feishu-jin10/messages"] is modular_api_feishu_jin10_message_monitor


def test_app_registers_modular_jin10_market_routes() -> None:
    from apps.api.routes.jin10_market_routes import (
        api_jin10_calendar as modular_api_jin10_calendar,
        api_jin10_flash as modular_api_jin10_flash,
        api_jin10_kline as modular_api_jin10_kline,
        api_jin10_quotes_latest as modular_api_jin10_quotes_latest,
    )

    route_map = _route_endpoint_map()

    assert route_map["/api/jin10/quotes/latest"] is modular_api_jin10_quotes_latest
    assert route_map["/api/jin10/calendar"] is modular_api_jin10_calendar
    assert route_map["/api/jin10/flash"] is modular_api_jin10_flash
    assert route_map["/api/jin10/kline"] is modular_api_jin10_kline


def test_app_registers_modular_premarket_routes() -> None:
    from apps.api.routes.premarket_routes import (
        api_premarket_launch_preflight as modular_api_premarket_launch_preflight,
        api_premarket_pipeline_contract as modular_api_premarket_pipeline_contract,
        api_premarket_pipeline_readiness as modular_api_premarket_pipeline_readiness,
        get_task as modular_get_task,
        get_task_logs as modular_get_task_logs,
        trigger_premarket as modular_trigger_premarket,
    )

    route_map = _route_endpoint_map()
    route_method_map = _route_method_endpoint_map()

    assert route_map["/api/pipelines/premarket/contract"] is modular_api_premarket_pipeline_contract
    assert route_map["/api/pipelines/premarket/readiness"] is modular_api_premarket_pipeline_readiness
    assert route_map["/api/tasks/premarket/preflight"] is modular_api_premarket_launch_preflight
    assert route_method_map[("/tasks/premarket", "POST")] is modular_trigger_premarket
    assert route_method_map[("/api/tasks/premarket", "POST")] is modular_trigger_premarket
    assert route_map["/tasks/{task_id}"] is modular_get_task
    assert route_map["/api/tasks/{task_id}"] is modular_get_task
    assert route_map["/tasks/{task_id}/logs"] is modular_get_task_logs
    assert route_map["/api/tasks/{task_id}/logs"] is modular_get_task_logs


def test_app_registers_modular_gold_mainline_routes() -> None:
    from apps.api.routes.gold_mainline_routes import (
        api_gold_mainlines as modular_api_gold_mainlines,
        api_gold_mainlines_latest as modular_api_gold_mainlines_latest,
        api_gold_runtime_orchestration_contract as modular_api_gold_runtime_orchestration_contract,
        api_gold_runtime_summary_preview as modular_api_gold_runtime_summary_preview,
    )

    route_map = _route_endpoint_map()

    assert route_map["/api/gold/mainlines/latest"] is modular_api_gold_mainlines_latest
    assert route_map["/api/gold/mainlines"] is modular_api_gold_mainlines
    assert route_map["/api/gold/runtime-orchestration/contract"] is modular_api_gold_runtime_orchestration_contract
    assert route_map["/api/gold/runtime-orchestration/summary-preview"] is modular_api_gold_runtime_summary_preview


def test_app_registers_modular_health_routes() -> None:
    from apps.api.routes.health_routes import health as modular_health

    route_map = _route_endpoint_map()

    assert route_map["/health"] is modular_health
    assert route_map["/api/health"] is modular_health
    assert "/api/memory/context" not in route_map


def test_app_registers_modular_agent_governance_read_routes() -> None:
    from apps.api.routes.agent_governance_read_routes import (
        api_agent_registry_detail as modular_api_agent_registry_detail,
        api_agents_registry as modular_api_agents_registry,
        api_prompt_evolution_latest as modular_api_prompt_evolution_latest,
        api_prompt_evolution_proposal as modular_api_prompt_evolution_proposal,
        api_prompt_versions_active as modular_api_prompt_versions_active,
        api_prompt_versions_by_agent as modular_api_prompt_versions_by_agent,
        api_prompt_versions_list as modular_api_prompt_versions_list,
    )

    route_map = _route_endpoint_map()
    route_method_map = _route_method_endpoint_map()

    assert route_map["/api/agents/registry"] is modular_api_agents_registry
    assert route_map["/api/agents/registry/{agent_id}"] is modular_api_agent_registry_detail
    assert route_map["/api/agents/prompts"] is modular_api_prompt_versions_list
    assert route_method_map[("/api/agents/prompts/{agent_id}", "GET")] is modular_api_prompt_versions_by_agent
    assert route_map["/api/agents/prompts/{agent_id}/active"] is modular_api_prompt_versions_active
    assert route_map["/api/agents/prompt-evolution/proposal/{agent_id}"] is modular_api_prompt_evolution_proposal
    assert route_map["/api/governance/prompt-evolution/latest"] is modular_api_prompt_evolution_latest


def test_app_registers_modular_system_evolution_routes() -> None:
    from apps.api.routes.system_evolution_routes import (
        api_system_evolution_latest as modular_api_system_evolution_latest,
        api_system_evolution_proposal_action as modular_api_system_evolution_proposal_action,
    )

    route_map = _route_endpoint_map()
    route_method_map = _route_method_endpoint_map()

    assert route_map["/api/governance/system-evolution/latest"] is modular_api_system_evolution_latest
    assert (
        route_method_map[("/api/governance/system-evolution/proposal/action", "POST")]
        is modular_api_system_evolution_proposal_action
    )


def test_app_registers_modular_processing_monitor_routes() -> None:
    from apps.api.routes.processing_monitor_routes import (
        api_processing_overview as modular_api_processing_overview,
        api_processing_trace as modular_api_processing_trace,
        api_processing_trace_by_event as modular_api_processing_trace_by_event,
        api_processing_trace_by_input as modular_api_processing_trace_by_input,
        api_processing_trace_by_mainline as modular_api_processing_trace_by_mainline,
        api_processing_trace_by_source_ref as modular_api_processing_trace_by_source_ref,
        api_processing_trace_by_transmission_chain as modular_api_processing_trace_by_transmission_chain,
    )

    route_map = _route_endpoint_map()

    assert route_map["/api/processing/overview"] is modular_api_processing_overview
    assert route_map["/api/processing/trace/{trace_id}"] is modular_api_processing_trace
    assert route_map["/api/processing/trace-by-event/{event_id}"] is modular_api_processing_trace_by_event
    assert route_map["/api/processing/trace-by-input/{input_id}"] is modular_api_processing_trace_by_input
    assert route_map["/api/processing/trace-by-source-ref/{source_ref}"] is modular_api_processing_trace_by_source_ref
    assert route_map["/api/processing/trace-by-mainline/{mainline}"] is modular_api_processing_trace_by_mainline
    assert route_map["/api/processing/trace-by-chain/{chain_id}"] is modular_api_processing_trace_by_transmission_chain


def test_app_registers_modular_agent_governance_write_routes() -> None:
    from apps.api.routes.agent_governance_write_routes import (
        api_prompt_evolution_release_action as modular_api_prompt_evolution_release_action,
        api_prompt_feedback_by_agent as modular_api_prompt_feedback_by_agent,
        api_prompt_feedback_create as modular_api_prompt_feedback_create,
        api_prompt_feedback_list as modular_api_prompt_feedback_list,
        api_prompt_versions_activate as modular_api_prompt_versions_activate,
        api_prompt_versions_create as modular_api_prompt_versions_create,
    )

    route_map = _route_endpoint_map()
    route_method_map = _route_method_endpoint_map()

    assert route_method_map[("/api/agents/prompts/{agent_id}", "POST")] is modular_api_prompt_versions_create
    assert route_method_map[("/api/agents/prompts/{agent_id}/activate", "PATCH")] is modular_api_prompt_versions_activate
    assert route_method_map[("/api/agents/feedback", "POST")] is modular_api_prompt_feedback_create
    assert route_map["/api/agents/feedback/{agent_id}"] is modular_api_prompt_feedback_by_agent
    assert route_map["/api/agents/feedback"] is modular_api_prompt_feedback_list
    assert (
        route_method_map[("/api/governance/prompt-evolution/release/action", "POST")]
        is modular_api_prompt_evolution_release_action
    )


def test_app_registers_modular_agent_analysis_read_routes() -> None:
    from apps.api.routes.agent_analysis_read_routes import (
        api_agent_analysis_by_date as modular_api_agent_analysis_by_date,
        api_agent_analysis_inspect as modular_api_agent_analysis_inspect,
        api_agent_analysis_latest as modular_api_agent_analysis_latest,
        api_agent_analysis_synthesis_latest as modular_api_agent_analysis_synthesis_latest,
    )

    route_map = _route_endpoint_map()

    assert route_map["/api/agent-analysis/latest"] is modular_api_agent_analysis_latest
    assert route_map["/api/agent-analysis"] is modular_api_agent_analysis_by_date
    assert route_map["/api/agent-analysis/inspect"] is modular_api_agent_analysis_inspect
    assert route_map["/api/agent-analysis/synthesis/latest"] is modular_api_agent_analysis_synthesis_latest


def test_app_registers_modular_agent_analysis_run_route() -> None:
    from apps.api.routes.agent_analysis_run_routes import (
        api_run_agent_analysis as modular_api_run_agent_analysis,
    )

    route_method_map = _route_method_endpoint_map()

    assert route_method_map[("/api/agent-analysis/run", "POST")] is modular_api_run_agent_analysis


def test_app_registers_modular_frontend_compat_routes() -> None:
    from apps.api.routes.frontend_compat_routes import (
        serve_agent_tasks as modular_serve_agent_tasks,
        serve_agent_tasks_subpath as modular_serve_agent_tasks_subpath,
        serve_cme_options as modular_serve_cme_options,
        serve_dashboard as modular_serve_dashboard,
        serve_dashboard_analysis as modular_serve_dashboard_analysis,
        serve_data_ingestion as modular_serve_data_ingestion,
        serve_data_sources_subpath as modular_serve_data_sources_subpath,
        serve_event_flow as modular_serve_event_flow,
        serve_event_flow_subpath as modular_serve_event_flow_subpath,
        serve_frontend_asset as modular_serve_frontend_asset,
        serve_frontend_favicon as modular_serve_frontend_favicon,
        serve_knowledge_base as modular_serve_knowledge_base,
        serve_market_monitor as modular_serve_market_monitor,
        serve_reports as modular_serve_reports,
        serve_reports_subpath as modular_serve_reports_subpath,
        serve_review_center as modular_serve_review_center,
        serve_scheduler as modular_serve_scheduler,
        serve_scheduler_subpath as modular_serve_scheduler_subpath,
        serve_settings as modular_serve_settings,
        serve_settings_audit as modular_serve_settings_audit,
    )

    route_map = _route_endpoint_map()

    assert route_map["/assets/{asset_path:path}"] is modular_serve_frontend_asset
    assert route_map["/favicon.svg"] is modular_serve_frontend_favicon
    assert route_map["/dashboard"] is modular_serve_dashboard
    assert route_map["/dashboard/analysis"] is modular_serve_dashboard_analysis
    assert route_map["/data-ingestion"] is modular_serve_data_ingestion
    assert route_map["/data-sources/{path:path}"] is modular_serve_data_sources_subpath
    assert route_map["/market-monitor"] is modular_serve_market_monitor
    assert route_map["/cme-options"] is modular_serve_cme_options
    assert route_map["/reports"] is modular_serve_reports
    assert route_map["/reports/{path:path}"] is modular_serve_reports_subpath
    assert route_map["/event-flow"] is modular_serve_event_flow
    assert route_map["/event-flow/{path:path}"] is modular_serve_event_flow_subpath
    assert route_map["/knowledge-base"] is modular_serve_knowledge_base
    assert route_map["/agent-tasks"] is modular_serve_agent_tasks
    assert route_map["/scheduler"] is modular_serve_scheduler
    assert route_map["/scheduler/{path:path}"] is modular_serve_scheduler_subpath
    assert route_map["/agent-tasks/{path:path}"] is modular_serve_agent_tasks_subpath
    assert route_map["/review-center"] is modular_serve_review_center
    assert route_map["/settings"] is modular_serve_settings
    assert route_map["/settings/audit"] is modular_serve_settings_audit


def test_app_registers_modular_system_status_route() -> None:
    from apps.api.routes.system_status_routes import system_status as modular_system_status

    route_map = _route_endpoint_map()

    assert route_map["/dashboard/system-status"] is modular_system_status
