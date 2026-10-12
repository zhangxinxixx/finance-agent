from __future__ import annotations

from apps.api.routes import reports_routes
from apps.api.services import (
    report_index_service,
    report_jin10_service,
    report_service,
    report_storage_service,
    report_strategy_service,
)
from apps.api.services.report_reading import detail


def test_report_service_preserves_public_consumer_entrypoints() -> None:
    expected_owners = {
        detail: {
            "get_report_detail",
            "get_report_artifacts",
            "get_report_source",
            "get_report_analysis",
            "get_report_visual",
            "get_report_evidence",
            "get_report_analysis_inputs",
            "get_report_artifact_asset_path",
        },
        report_storage_service: {"get_final_report_latest", "get_final_report"},
        report_strategy_service: {
            "get_strategy_card_latest",
            "get_strategy_card",
            "list_strategy_cards",
            "list_strategy_assets",
            "get_strategy_card_by_id",
            "get_strategy_card_read_model_latest",
        },
        report_jin10_service: {
            "get_jin10_daily_report_latest",
            "get_jin10_agent_analysis_latest",
            "get_jin10_daily_report",
            "get_jin10_report_bundle_latest",
            "get_jin10_report_bundle",
            "get_jin10_report_bundle_asset_path",
        },
        report_index_service: {"list_reports_index", "list_unified_dates"},
    }

    for owner, names in expected_owners.items():
        for name in names:
            assert getattr(report_service, name) is getattr(owner, name)


def test_report_routes_keep_using_the_compatibility_contract() -> None:
    assert reports_routes.get_report_detail is report_service.get_report_detail
    assert reports_routes.get_report_artifacts is report_service.get_report_artifacts
    assert reports_routes.get_report_analysis_inputs is report_service.get_report_analysis_inputs
