import json
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.services.report_market_odds_service import (
    build_market_odds_view,
    load_latest_report_market_odds_view,
    load_report_market_odds_view,
)
from apps.features.jin10.schemas.market_odds import Jin10MarketOddsEvidence


def _payload() -> dict:
    item = {
        "item_id": "223555:gold:4200",
        "panel_id": "fig_p1_001:panel_05",
        "asset": "XAUUSD",
        "event_type": "price_level",
        "predicate": "touch_above",
        "direction": "up",
        "target_value": 4200,
        "target_unit": "USD_per_oz",
        "horizon_start": "2026-07-03",
        "horizon_end": "2026-07-31",
        "timezone": "Asia/Shanghai",
        "probability": 0.94,
        "probability_raw": "94%",
        "probability_semantics": "ever_touch_before_horizon",
        "outcome_label": "黄金向上触及4200美元",
        "extraction_confidence": 0.96,
        "extraction_status": "accepted",
        "page_no": 1,
        "figure_id": "fig_p1_001",
        "bbox": [0, 0, 1080, 6120],
        "ocr_text": "黄金向上触及4200美元 94%",
        "source_refs": [],
        "evidence_refs": [],
    }
    return {
        "schema_version": "1.0",
        "feature_id": "jin10-market-odds:223555:2026-07-03T14:00:00+08:00",
        "article_id": "223555",
        "report_id": "jin10:223555",
        "report_type": "market_observation",
        "published_at": "2026-07-03T14:00:00+08:00",
        "generated_at": "2026-07-16T00:00:00+00:00",
        "source_kind": "jin10_external_market_odds",
        "data_category": "external_opinion",
        "provider_role": "supplemental_source",
        "source_verification_status": "single_source",
        "extraction_status": "accepted",
        "parser_version": "jin10-vlm-parser-v0.2",
        "panel_count": 1,
        "items": [item],
        "source_refs": [],
    }


def _accepted_agent_analysis() -> dict:
    return {
        "one_line_conclusion": "黄金近端上方触及赔率较高，但下方尾部仍在。",
        "gold_analysis": "黄金赔率只提供战术价格分布，仍需美元和实际利率确认。",
        "unresolved_items": ["当前黄金现价", "同语义内部赔率"],
        "quality_audit": {
            "status": "accepted",
            "input_quality_audit": {"status": "accepted"},
            "output_quality_audit": {"status": "accepted"},
        },
    }
def test_view_model_groups_items_and_refuses_direction_without_spot() -> None:
    view = build_market_odds_view(
        Jin10MarketOddsEvidence.model_validate(_payload()),
        now=datetime(2026, 7, 4, tzinfo=UTC),
    )
    assert view.groups[0].group_key == "precious_metals"
    assert view.panel_count == 1
    assert view.interpretation["structure_label"] == "raw_probability_distribution"
    assert view.interpretation["directional_interpretation"] == "unavailable_without_spot_reference"
    assert view.analysis_context.source == "deterministic_fallback"
    assert view.analysis_context.quality_status == "unavailable"
    assert view.internal_comparisons == []


def test_view_model_exposes_only_accepted_agent_analysis_context() -> None:
    feature = Jin10MarketOddsEvidence.model_validate(_payload())
    view = build_market_odds_view(
        feature,
        agent_analysis=_accepted_agent_analysis(),
        now=datetime(2026, 7, 4, tzinfo=UTC),
    )
    assert view.analysis_context.source == "accepted_agent_analysis"
    assert view.analysis_context.quality_status == "accepted"
    assert view.analysis_context.structure_summary == "黄金近端上方触及赔率较高，但下方尾部仍在。"
    assert view.analysis_context.gold_implication == "黄金赔率只提供战术价格分布，仍需美元和实际利率确认。"
    assert view.analysis_context.confirmation_variables == ["当前黄金现价", "同语义内部赔率"]

    rejected = _accepted_agent_analysis()
    rejected["quality_audit"]["output_quality_audit"]["status"] = "needs_review"
    fallback = build_market_odds_view(
        feature,
        agent_analysis=rejected,
        now=datetime(2026, 7, 4, tzinfo=UTC),
    )
    assert fallback.analysis_context.source == "deterministic_fallback"

def test_loader_reads_dedicated_feature_artifact(tmp_path) -> None:
    path = tmp_path / "features" / "jin10" / "2026-07-03" / "223555" / "market_odds_evidence.json"
    path.parent.mkdir(parents=True)
    path.write_text(Jin10MarketOddsEvidence.model_validate(_payload()).model_dump_json(), encoding="utf-8")
    analysis_path = tmp_path / "outputs" / "jin10" / "2026-07-03" / "223555" / "agent_analysis_report.json"
    analysis_path.parent.mkdir(parents=True)
    analysis_path.write_text(json.dumps(_accepted_agent_analysis()), encoding="utf-8")
    view = load_report_market_odds_view(storage_root=tmp_path, trade_date="2026-07-03", article_id="223555")
    assert view is not None
    assert view.article_id == "223555"
    assert view.report_id == "jin10:223555"
    assert view.trade_date == "2026-07-03"
    assert view.source_role == "supplemental_source"
    assert view.analysis_context.source == "accepted_agent_analysis"
    assert view.evidence_items[0]["figure_id"] == "fig_p1_001"
    assert view.evidence_items[0]["image_url"] == (
        "/api/jin10/report-bundle/2026-07-03/223555/asset/figures/fig_p1_001.png"
    )
    assert view.evidence_items[0]["image_kind"] == "figure_crop"


def test_loader_rejects_agent_analysis_that_did_not_pass_all_audits(tmp_path) -> None:
    feature_path = tmp_path / "features" / "jin10" / "2026-07-03" / "223555" / "market_odds_evidence.json"
    feature_path.parent.mkdir(parents=True)
    feature_path.write_text(Jin10MarketOddsEvidence.model_validate(_payload()).model_dump_json(), encoding="utf-8")
    analysis = _accepted_agent_analysis()
    analysis["quality_audit"]["output_quality_audit"]["status"] = "needs_review"
    analysis_path = tmp_path / "outputs" / "jin10" / "2026-07-03" / "223555" / "agent_analysis_report.json"
    analysis_path.parent.mkdir(parents=True)
    analysis_path.write_text(json.dumps(analysis), encoding="utf-8")

    view = load_report_market_odds_view(storage_root=tmp_path, trade_date="2026-07-03", article_id="223555")

    assert view is not None
    assert view.analysis_context.source == "deterministic_fallback"
    assert view.analysis_context.quality_status == "unavailable"


def test_view_model_only_exposes_fully_comparable_internal_odds() -> None:
    feature = Jin10MarketOddsEvidence.model_validate(_payload())
    exact = {
        "event_id": "internal:gold:4200",
        "underlying": "XAUUSD",
        "event_type": "price_level",
        "predicate": "touch_above",
        "target_value": 4200,
        "target_unit": "USD_per_oz",
        "probability_semantics": "ever_touch_before_horizon",
        "horizon_start": "2026-07-03",
        "horizon_end": "2026-07-31",
        "observed_at": "2026-07-03T15:00:00+08:00",
        "probability": 0.87,
        "source_refs": [{"source_ref": "cme:fixture"}],
    }
    mismatched = {**exact, "event_id": "internal:gold:4300", "target_value": 4300}
    view = build_market_odds_view(
        feature,
        internal_market_odds=[exact, mismatched],
        now=datetime(2026, 7, 4, tzinfo=UTC),
    )
    assert len(view.internal_comparisons) == 1
    assert view.internal_comparisons[0]["comparison_status"] == "supports"
    assert view.internal_comparisons[0]["probability_gap"] == 0.07
    assert view.internal_comparisons[0]["observation_gap_hours"] == 1.0
    assert view.internal_comparisons[0]["aggregation_allowed"] is False


def test_view_model_separates_displayable_history_from_analysis_eligibility() -> None:
    feature = Jin10MarketOddsEvidence.model_validate(_payload())
    fresh = build_market_odds_view(feature, now=datetime(2026, 7, 4, tzinfo=UTC))
    historical = build_market_odds_view(feature, now=datetime(2026, 7, 16, tzinfo=UTC))
    expired = build_market_odds_view(feature, now=datetime(2026, 8, 1, tzinfo=UTC))

    assert fresh.evidence_items[0]["freshness_status"] == "fresh"
    assert fresh.evidence_items[0]["analysis_eligible"] is True
    assert historical.evidence_items[0]["freshness_status"] == "historical"
    assert historical.evidence_items[0]["analysis_eligible"] is False
    assert historical.evidence_items[0]["analysis_block_reasons"] == ["freshness_historical"]
    assert expired.evidence_items[0]["freshness_status"] == "expired"
    assert "horizon_expired" in expired.evidence_items[0]["analysis_block_reasons"]


def test_stale_external_odds_are_not_used_for_internal_comparison() -> None:
    feature = Jin10MarketOddsEvidence.model_validate(_payload())
    internal = {
        "event_id": "internal:gold:4200",
        "underlying": "XAUUSD",
        "event_type": "price_level",
        "predicate": "touch_above",
        "target_value": 4200,
        "target_unit": "USD_per_oz",
        "probability_semantics": "ever_touch_before_horizon",
        "horizon_start": "2026-07-03",
        "horizon_end": "2026-07-31",
        "observed_at": "2026-07-03T15:00:00+08:00",
        "probability": 0.87,
    }

    view = build_market_odds_view(
        feature,
        internal_market_odds=[internal],
        now=datetime(2026, 7, 16, tzinfo=UTC),
    )

    assert view.evidence_items
    assert view.internal_comparisons == []


def test_latest_loader_selects_newest_feature_date(tmp_path) -> None:
    for trade_date, article_id in (("2026-07-01", "223267"), ("2026-07-03", "223555")):
        payload = _payload()
        payload["article_id"] = article_id
        payload["report_id"] = f"jin10:{article_id}"
        payload["feature_id"] = f"jin10-market-odds:{article_id}:{trade_date}T14:00:00+08:00"
        payload["published_at"] = f"{trade_date}T14:00:00+08:00"
        path = tmp_path / "features" / "jin10" / trade_date / article_id / "market_odds_evidence.json"
        path.parent.mkdir(parents=True)
        path.write_text(Jin10MarketOddsEvidence.model_validate(payload).model_dump_json(), encoding="utf-8")
    view = load_latest_report_market_odds_view(storage_root=tmp_path)
    assert view is not None
    assert view.article_id == "223555"
    assert view.trade_date == "2026-07-03"


def test_latest_external_odds_route_returns_dedicated_view_model(tmp_path, monkeypatch) -> None:
    storage_root = tmp_path / "storage"
    path = storage_root / "features" / "jin10" / "2026-07-03" / "223555" / "market_odds_evidence.json"
    path.parent.mkdir(parents=True)
    path.write_text(Jin10MarketOddsEvidence.model_validate(_payload()).model_dump_json(), encoding="utf-8")
    monkeypatch.setattr("apps.api.routes.market_odds_routes._PROJECT_ROOT", tmp_path)

    response = TestClient(app).get("/api/market-odds/external/latest")

    assert response.status_code == 200
    payload = response.json()
    assert payload["article_id"] == "223555"
    assert payload["report_id"] == "jin10:223555"
    assert payload["source_role"] == "supplemental_source"
    assert payload["analysis_context"]["source"] == "deterministic_fallback"
