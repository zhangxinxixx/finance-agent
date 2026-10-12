"""Opposite horizons, numeric baselines, and spot/futures separation."""
from copy import deepcopy
from datetime import datetime, timezone

import pytest

from apps.api.services.gold_market_evidence import cme_structure
from apps.api.services.gold_workspace_service import build_gold_workspace

NOW = datetime(2026, 10, 7, 13, 0, tzinfo=timezone.utc)


def workspace(key="US30Y", **values):
    row = {"value": 5.64, "source": "treasury_rates", "date": "2026-10-06",
           "unit": "%", "daily_change": -.02, "monthly_change": .4, **values}
    result = build_gold_workspace(macro={"indicators": {key: row}}, quotes=None, research=None, now=NOW)
    return result, next(fact for fact in result["factors"] if fact["key"] == key)


@pytest.mark.parametrize("monthly_change", [.4, -.4, 0, None])
def test_cost_level_pressure_survives_short_term_yield_relief(monthly_change):
    _, fact = workspace(monthly_change=monthly_change)
    assert fact["macro_effect"]["impact"] == "pressure"
    assert fact["macro_effect"]["basis"] == "holding_cost_level"
    assert "5.64%" in fact["macro_effect"]["summary"]
    assert fact["impact"] == "supportive" and fact["change"] == -2
    assert "日度下降" in fact["short_term_summary"] and "日内" not in fact["short_term_summary"]


def test_yield_rise_is_pressure_and_negative_real_yield_is_a_separate_level_effect():
    _, rising = workspace(daily_change=.08)
    assert rising["impact"] == rising["macro_effect"]["impact"] == "pressure"
    _, negative_real = workspace("REAL10Y", value=-.5, daily_change=.05)
    assert negative_real["macro_effect"]["impact"] == "supportive"
    assert negative_real["impact"] == "pressure"


@pytest.mark.parametrize("values", [{"date": "2020-01-01"}, {"status": "blocked"}, {"quality_status": "unverified"}, {"value": float("nan")}])
def test_unverified_facts_cannot_drive_either_horizon_or_numeric_conditions(values):
    result, fact = workspace(**values)
    assert fact["macro_effect"]["impact"] == fact["impact"] == "unconfirmed"
    assert not result["environment_watch"]["conditions"]


def test_environment_numbers_are_actual_observation_baselines_not_new_reversal_prices():
    result, _ = workspace()
    watch = result["environment_watch"]
    assert watch["basis"] == "latest_observation_comparison"
    row = watch["conditions"][0]
    assert row["value"] == 5.64 and "5.64%" in row["supportive_condition"] and "5.64%" in row["pressure_condition"]
    assert "不是已确认" in watch["note"]


def options():
    return {"status": "partial", "meta": {"current_trade_date": "2026-10-06", "product": "OG"},
            "price_context": {"structure_coordinate_space": "GC futures", "report_p0": 4187.5},
            "data_quality": {"cme_status": "PRELIM"}, "source_refs": [{"name": "CME Daily Bulletin"}],
            "key_levels": [{"strike": 4150, "role": "primary_support", "expiry_scope": "NOV26", "coordinate_space": "GC futures"},
                           {"band": {"lower": 4188, "upper": 4238}, "role": "gamma_flip", "coordinate_space": "GC futures"},
                           {"strike": 4100, "role": "primary_support", "coordinate_space": "XAUUSD spot"}]}


def test_cme_model_levels_keep_coordinates_version_and_do_not_enter_spot_ladder():
    raw = options()
    before = deepcopy(raw)
    projection = cme_structure(raw, now=NOW)
    assert projection["status"] == "reference" and projection["version_type"] == "PRELIM"
    assert len(projection["levels"]) == 2
    assert projection["levels"][0]["price"] == 4150 and projection["levels"][1]["lower"] == 4188
    result = build_gold_workspace(macro=None, quotes=None, research=None, options=raw, now=NOW)
    assert not result["research"]["key_levels"] and not result["research"]["trade_plan"]
    assert raw == before


@pytest.mark.parametrize("mutation", ["missing_refs", "wrong_coordinate", "future_date", "bad_version", "failed"])
def test_cme_unverified_context_never_becomes_a_visible_level(mutation):
    raw = options()
    if mutation == "missing_refs":
        raw["source_refs"] = []
    elif mutation == "wrong_coordinate":
        raw["price_context"]["structure_coordinate_space"] = "XAUUSD spot"
    elif mutation == "future_date":
        raw["meta"]["current_trade_date"] = "2030-01-01"
    elif mutation == "bad_version":
        raw["data_quality"]["cme_status"] = "unverified"
    else:
        raw["status"] = "failed"
    assert cme_structure(raw, now=NOW)["levels"] == []


def test_malformed_cme_rows_and_old_reports_stay_non_authoritative():
    raw = options()
    raw["meta"]["current_trade_date"] = "2020-01-01"
    raw["key_levels"].extend([
        {"strike": float("inf"), "role": "primary_support", "coordinate_space": "GC futures"},
        {"band": {"lower": 4238, "upper": 4188}, "role": "gamma_flip", "coordinate_space": "GC futures"},
        {"strike": True, "role": "primary_support", "coordinate_space": "GC futures"}])
    result = cme_structure(raw, now=NOW)
    assert result["status"] == "historical" and len(result["levels"]) == 2
