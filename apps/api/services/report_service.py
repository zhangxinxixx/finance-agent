"""Explicit compatibility exports for the report-reading API.

Implementations own their workflows; this module only keeps known consumers'
imports stable. Storage dependencies belong to services._storage.
"""

from apps.api.services import _storage as _storage
from apps.api.services import report_index_service as _index
from apps.api.services import report_jin10_service as _jin10
from apps.api.services import report_storage_service as _report_storage
from apps.api.services import report_strategy_service as _strategy
from apps.api.services.report_reading import detail as _detail

_collect_reports = _index._collect_reports
list_reports_index = _index.list_reports_index
list_unified_dates = _index.list_unified_dates
_find_external_jin10_meta = _jin10._find_external_jin10_meta
_is_jin10_daily_storage_payload = _jin10._is_jin10_daily_storage_payload
_jin10_quality_blocks_content = _jin10._jin10_quality_blocks_content
_read_optional_json = _jin10._read_optional_json
get_jin10_agent_analysis_latest = _jin10.get_jin10_agent_analysis_latest
get_jin10_daily_report = _jin10.get_jin10_daily_report
get_jin10_daily_report_latest = _jin10.get_jin10_daily_report_latest
get_jin10_report_bundle = _jin10.get_jin10_report_bundle
get_jin10_report_bundle_asset_path = _jin10.get_jin10_report_bundle_asset_path
get_jin10_report_bundle_latest = _jin10.get_jin10_report_bundle_latest
_build_legacy_jin10_structured_payload = _detail._build_legacy_jin10_structured_payload
_enrich_report_detail_with_gold_macro_context = _detail._enrich_report_detail_with_gold_macro_context
_legacy_jin10_report_detail = _detail._legacy_jin10_report_detail
_page_report_artifact_allowed = _detail._page_report_artifact_allowed
_resolve_report_asset_path = _detail._resolve_report_asset_path
_verified_final_report = _detail._verified_final_report
get_report_analysis = _detail.get_report_analysis
get_report_analysis_inputs = _detail.get_report_analysis_inputs
get_report_artifact_asset_path = _detail.get_report_artifact_asset_path
get_report_artifacts = _detail.get_report_artifacts
get_report_detail = _detail.get_report_detail
get_report_evidence = _detail.get_report_evidence
get_report_source = _detail.get_report_source
get_report_visual = _detail.get_report_visual
get_final_report = _report_storage.get_final_report
get_final_report_latest = _report_storage.get_final_report_latest
_collect_fs_strategy_cards = _strategy._collect_fs_strategy_cards
_strategy_card_status = _strategy._strategy_card_status
get_strategy_card = _strategy.get_strategy_card
get_strategy_card_by_id = _strategy.get_strategy_card_by_id
get_strategy_card_latest = _strategy.get_strategy_card_latest
get_strategy_card_read_model_latest = _strategy.get_strategy_card_read_model_latest
list_strategy_assets = _strategy.list_strategy_assets
list_strategy_cards = _strategy.list_strategy_cards

__all__ = [
    "list_reports_index",
    "list_unified_dates",
    "get_jin10_agent_analysis_latest",
    "get_jin10_daily_report",
    "get_jin10_daily_report_latest",
    "get_jin10_report_bundle",
    "get_jin10_report_bundle_asset_path",
    "get_jin10_report_bundle_latest",
    "get_report_analysis",
    "get_report_analysis_inputs",
    "get_report_artifact_asset_path",
    "get_report_artifacts",
    "get_report_detail",
    "get_report_evidence",
    "get_report_source",
    "get_report_visual",
    "get_final_report",
    "get_final_report_latest",
    "get_strategy_card",
    "get_strategy_card_by_id",
    "get_strategy_card_latest",
    "get_strategy_card_read_model_latest",
    "list_strategy_assets",
    "list_strategy_cards",
]
