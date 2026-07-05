"""向后兼容层。优先直接从 apps.api.services.* 导入。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from apps.api.services import _storage
from apps.api.services import artifact_service, dashboard_service, macro_service, market_service, options_service, report_service, source_service, task_service

_PROJECT_ROOT = _storage._PROJECT_ROOT
_try_db_session = _storage._try_db_session


def _sync_project_root() -> None:
    _storage._PROJECT_ROOT = _PROJECT_ROOT
    options_service._PROJECT_ROOT = _PROJECT_ROOT
    macro_service._PROJECT_ROOT = _PROJECT_ROOT
    macro_service._try_db_session = _try_db_session
    artifact_service._PROJECT_ROOT = _PROJECT_ROOT
    report_service._PROJECT_ROOT = _PROJECT_ROOT
    source_service._PROJECT_ROOT = _PROJECT_ROOT
    market_service._PROJECT_ROOT = _PROJECT_ROOT
    report_service._try_db_session = _try_db_session
    source_service._try_db_session = _try_db_session


def _latest_date_dir(base: Path) -> Path | None:
    return _storage._latest_date_dir(base)


def _latest_run_file(date_dir: Path, filename: str) -> Path | None:
    return _storage._latest_run_file(date_dir, filename)


def _latest_asset_date_run(base: Path, asset: str) -> tuple[str | None, str | None, Path | None]:
    return _storage._latest_asset_date_run(base, asset)


def _collect_reports(base_rel: str, report_type: str, fmt: str, asset: str, md_filename: str | None = None) -> list[dict[str, Any]]:
    _sync_project_root()
    return report_service._collect_reports(base_rel, report_type, fmt, asset, md_filename)


def get_options_snapshot(date_str: str | None = None, db: Any | None = None) -> dict[str, Any] | None:
    _sync_project_root()
    return options_service.get_options_snapshot(date_str, db=db)


def get_options_report_md(date_str: str | None = None) -> str | None:
    _sync_project_root()
    return options_service.get_options_report_md(date_str)


def get_options_visual_report_html(date_str: str | None = None, run_id: str | None = None) -> dict[str, Any] | None:
    _sync_project_root()
    return options_service.get_options_visual_report_html(date_str, run_id)


def list_options_report_dates() -> list[str]:
    _sync_project_root()
    return options_service.list_options_report_dates()


def get_macro_latest() -> dict[str, Any] | None:
    _sync_project_root()
    return macro_service.get_macro_latest()


def get_macro_report_md(date_str: str | None = None) -> str | None:
    _sync_project_root()
    return macro_service.get_macro_report_md(date_str)


def list_recent_tasks(limit: int = 20) -> list[dict[str, Any]]:
    return task_service.list_recent_tasks(limit)


def get_final_report_latest(asset: str = "XAUUSD") -> dict[str, Any] | None:
    _sync_project_root()
    return report_service.get_final_report_latest(asset)


def get_final_report(date: str, run_id: str, asset: str = "XAUUSD") -> dict[str, Any] | None:
    _sync_project_root()
    return report_service.get_final_report(date, run_id, asset)


def get_strategy_card_latest(asset: str = "XAUUSD") -> dict[str, Any] | None:
    _sync_project_root()
    return report_service.get_strategy_card_latest(asset)


def get_strategy_card(date: str, run_id: str, asset: str = "XAUUSD") -> dict[str, Any] | None:
    _sync_project_root()
    return report_service.get_strategy_card(date, run_id, asset)


def list_strategy_cards(asset: str = "XAUUSD", limit: int = 20) -> dict[str, Any]:
    _sync_project_root()
    return report_service.list_strategy_cards(asset, limit)


def list_strategy_assets() -> dict[str, Any]:
    _sync_project_root()
    return report_service.list_strategy_assets()


def get_strategy_card_by_id(strategy_card_id: str, asset: str = "XAUUSD") -> dict[str, Any] | None:
    _sync_project_root()
    return report_service.get_strategy_card_by_id(strategy_card_id, asset)


def get_strategy_card_read_model_latest(asset: str = "XAUUSD") -> dict[str, Any] | None:
    _sync_project_root()
    return report_service.get_strategy_card_read_model_latest(asset)


def get_jin10_daily_report_latest() -> dict[str, Any] | None:
    _sync_project_root()
    return market_service.get_jin10_daily_report_latest()


def get_jin10_daily_report(date: str, run_id: str) -> dict[str, Any] | None:
    _sync_project_root()
    return market_service.get_jin10_daily_report(date, run_id)


def get_jin10_weekly_report_latest() -> dict[str, Any] | None:
    _sync_project_root()
    return market_service.get_jin10_weekly_report_latest()


def get_jin10_weekly_report(date: str, run_id: str) -> dict[str, Any] | None:
    _sync_project_root()
    return market_service.get_jin10_weekly_report(date, run_id)


def get_jin10_report_bundle_latest() -> dict[str, Any] | None:
    _sync_project_root()
    return report_service.get_jin10_report_bundle_latest()


def get_jin10_report_bundle(date: str, run_id: str) -> dict[str, Any] | None:
    _sync_project_root()
    return report_service.get_jin10_report_bundle(date, run_id)


def get_jin10_report_bundle_asset_path(date: str, run_id: str, asset_path: str) -> Path | None:
    _sync_project_root()
    return report_service.get_jin10_report_bundle_asset_path(date, run_id, asset_path)


def list_reports_index(asset: str = "XAUUSD") -> dict[str, Any]:
    _sync_project_root()
    return report_service.list_reports_index(asset)


def list_unified_dates(asset: str = "XAUUSD") -> dict[str, Any]:
    _sync_project_root()
    return report_service.list_unified_dates(asset)


def get_data_source_statuses() -> dict[str, Any]:
    _sync_project_root()
    return source_service.get_data_source_statuses()


def get_dashboard_summary() -> dict[str, Any]:
    _sync_project_root()
    return dashboard_service.get_dashboard_summary()


def get_market_odds_snapshot(date_str: str | None = None, run_id: str | None = None) -> dict[str, Any] | None:
    _sync_project_root()
    return market_service.get_market_odds_snapshot(date_str, run_id)


def get_market_odds_report(date_str: str | None = None, run_id: str | None = None) -> dict[str, Any]:
    _sync_project_root()
    return market_service.get_market_odds_report(date_str, run_id)


def get_market_tickers() -> dict[str, Any]:
    _sync_project_root()
    return market_service.get_market_tickers()


def get_market_monitor_overview() -> dict[str, Any]:
    _sync_project_root()
    return market_service.get_market_monitor_overview()


def get_market_monitor_history(limit: int = 30, timeframe: str = "1M") -> dict[str, Any]:
    _sync_project_root()
    return market_service.get_market_monitor_history(limit=limit, timeframe=timeframe)


__all__ = [
    "_PROJECT_ROOT",
    "_latest_date_dir",
    "_latest_run_file",
    "_latest_asset_date_run",
    "_try_db_session",
    "_collect_reports",
    "get_options_snapshot",
    "get_options_report_md",
    "get_options_visual_report_html",
    "list_options_report_dates",
    "get_macro_latest",
    "get_macro_report_md",
    "get_final_report_latest",
    "get_final_report",
    "get_strategy_card_latest",
    "get_strategy_card",
    "list_strategy_cards",
    "get_strategy_card_by_id",
    "get_strategy_card_read_model_latest",
    "get_jin10_daily_report_latest",
    "get_jin10_daily_report",
    "get_jin10_report_bundle_latest",
    "get_jin10_report_bundle",
    "get_jin10_report_bundle_asset_path",
    "list_reports_index",
    "list_unified_dates",
    "list_recent_tasks",
    "get_data_source_statuses",
    "get_dashboard_summary",
    "get_market_tickers",
    "get_market_monitor_overview",
    "get_market_monitor_history",
    "get_market_odds_snapshot",
    "get_market_odds_report",
]
