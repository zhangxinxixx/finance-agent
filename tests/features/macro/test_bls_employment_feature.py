from __future__ import annotations

import json
from pathlib import Path

from apps.features.macro.employment import build_employment_features
from apps.parsers.bls.employment import parse_bls_employment_payload
from apps.parsers.macro.models import MacroPoint

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "macro" / "bls_employment_api.json"
RETRIEVED_AT = "2026-09-06T12:00:00+00:00"


def test_employment_features_build_units_changes_and_source_passports() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    parsed = parse_bls_employment_payload(payload, cutoff_month="2026-09")
    points = _points_from_parsed(parsed)
    source_refs = [_source_ref(series_id) for series_id in parsed]

    snapshot = build_employment_features(
        points,
        as_of="2026-09-06",
        source_refs=source_refs,
    )

    assert snapshot.cutoff_month == "2026-09"
    assert snapshot.unavailable_series == []
    assert snapshot.release_date is None
    assert snapshot.vintage_status == "unavailable"
    assert snapshot.consensus is None

    employment = snapshot.metrics["CES0000000001"]
    assert employment.unit == "thousand_persons"
    assert employment.current_month == "2026-08"
    assert employment.current_value == 159075.0
    assert employment.previous_month == "2026-07"
    assert employment.previous_value == 158900.0
    assert employment.monthly_change == 175.0
    assert employment.new_jobs_thousands == 175.0
    assert employment.yoy_month == "2025-08"
    assert employment.yoy_value == 156000.0
    assert employment.yoy_change == 3075.0
    assert employment.current_source is not None
    assert employment.current_source.observation_month == "2026-08"
    assert employment.current_source.source_url == "https://api.bls.gov/publicAPI/v2/timeseries/data/CES0000000001"
    assert employment.current_source.raw_path == "raw/macro/bls/2026-09-06/CES0000000001.json"
    assert employment.current_source.retrieved_at == RETRIEVED_AT
    assert employment.current_source.release_date is None
    assert employment.current_source.vintage_status == "unavailable"
    assert employment.previous_source is not None
    assert employment.previous_source.observation_month == "2026-07"

    wages = snapshot.metrics["CES0500000003"]
    assert wages.unit == "USD_per_hour"
    assert wages.current_value == 33.43
    assert wages.previous_value == 32.90
    assert wages.monthly_change == 0.53
    assert wages.yoy_value == 31.50
    assert wages.yoy_change == 1.93
    assert snapshot.wage_mom == 0.53
    assert snapshot.wage_yoy == 1.93

    assert snapshot.metrics["LNS14000000"].unit == "percent"
    assert snapshot.metrics["LNS14000000"].current_value == 4.4
    assert snapshot.metrics["LNS11300000"].current_value == 62.2
    assert snapshot.new_jobs_thousands == 175.0
    assert snapshot.to_dict()["metrics"]["CES0500000003"]["current_source"]["release_date"] is None


def test_employment_features_do_not_difference_across_missing_month() -> None:
    points = [
        _point("CES0000000001", "2026-06-01", 158800.0),
        _point("CES0000000001", "2026-08-01", 159075.0),
    ]

    snapshot = build_employment_features(points, as_of="2026-09-06")

    metric = snapshot.metrics["CES0000000001"]
    assert metric.status == "available"
    assert metric.current_month == "2026-08"
    assert metric.previous_month == "2026-06"
    assert metric.previous_value == 158800.0
    assert metric.monthly_change is None
    assert metric.monthly_change_pct is None
    assert metric.new_jobs_thousands is None
    assert metric.yoy_month == "2025-08"
    assert metric.yoy_value is None
    assert metric.yoy_change is None
    assert metric.yoy_change_pct is None


def test_employment_features_accept_macro_points_and_indexed_source_refs() -> None:
    points = [
        MacroPoint(
            symbol="CES0000000001",
            date="2026-07-01",
            value=158900.0,
            source="bls_public_api_v2",
            source_url="fixture://bls/CES0000000001",
            retrieved_at=RETRIEVED_AT,
            raw_path="raw/macro/bls/CES0000000001.json",
        ),
        MacroPoint(
            symbol="CES0000000001",
            date="2026-08-01",
            value=159075.0,
            source="bls_public_api_v2",
            source_url="fixture://bls/CES0000000001",
            retrieved_at=RETRIEVED_AT,
            raw_path="raw/macro/bls/CES0000000001.json",
        ),
    ]

    snapshot = build_employment_features(
        points,
        as_of="2026-09-06",
        source_refs={"CES0000000001": {"vintage_status": "unavailable"}},
    )

    metric = snapshot.metrics["CES0000000001"]
    assert metric.current_month == "2026-08"
    assert metric.new_jobs_thousands == 175.0
    assert metric.current_source is not None
    assert metric.current_source.source_url == "fixture://bls/CES0000000001"


def test_employment_features_apply_cutoff_and_preserve_unavailable_reason() -> None:
    points = [
        _point("LNS14000000", "2026-08-01", 4.4),
        _point("LNS14000000", "2026-10-01", 4.8),
    ]
    source_ref = {
        "symbol": "LNS14000000",
        "source": "bls_public_api_v2",
        "source_url": "fixture://bls/LNS14000000",
        "raw_path": "raw/macro/bls/LNS14000000.json",
        "retrieved_at": RETRIEVED_AT,
        "release_date": "unavailable",
        "vintage_status": "unavailable",
        "reason": "upstream unavailable",
    }

    snapshot = build_employment_features(
        points,
        as_of="2026-09-06",
        unavailable_symbols=["LNS11300000"],
        source_refs=[source_ref, {"symbol": "LNS11300000", "reason": "upstream unavailable"}],
    )

    unemployment = snapshot.metrics["LNS14000000"]
    assert unemployment.current_month == "2026-08"
    assert unemployment.current_value == 4.4
    assert unemployment.yoy_value is None
    participation = snapshot.metrics["LNS11300000"]
    assert participation.status == "unavailable"
    assert participation.unavailable_reason == "upstream unavailable"
    assert "LNS11300000" in snapshot.unavailable_series
    assert "2026-10" not in snapshot.to_dict()["metrics"]["LNS14000000"].values()


def test_employment_features_ignore_unavailable_symbols_from_other_domains() -> None:
    snapshot = build_employment_features(
        [_point("CES0000000001", "2026-08-01", 159075.0)],
        as_of="2026-09-06",
        unavailable_symbols=["COT_GOLD", "DGS10", "LNS14000000"],
        source_refs=[
            {"symbol": "CES0000000001", "source": "bls_public_api_v2"},
            {"symbol": "COT_GOLD", "source": "cftc"},
        ],
    )

    assert "LNS14000000" in snapshot.unavailable_series
    assert "COT_GOLD" not in snapshot.unavailable_series
    assert "DGS10" not in snapshot.unavailable_series
    assert set(snapshot.source_refs) == {"CES0000000001"}


def test_employment_features_expose_release_context_without_reconstructing_vintage() -> None:
    snapshot = build_employment_features(
        [_point("CES0000000001", "2026-08-01", 159123.0)],
        as_of="2026-09-06",
        source_refs=[
            {
                "symbol": "CES0000000001",
                "source": "bls_public_api_v2",
            },
            {
                "symbol": "BLS_EMPLOYMENT_RELEASE",
                "source": "bls_employment_situation",
                "source_url": "https://www.bls.gov/news.release/empsit.htm",
                "raw_path": "raw/macro/bls_release/2026-09-06/empsit-fixture.html",
                "retrieved_at": RETRIEVED_AT,
                "status": "available",
                "release_context": {
                    "status": "available",
                    "release_date": "2026-09-04",
                    "release_time_local": "08:30",
                    "release_timezone": "America/New_York",
                    "release_datetime": "2026-09-04T08:30:00-04:00",
                    "observation_month": "2026-08",
                    "headline": {
                        "new_jobs_thousands": 123.0,
                        "unemployment_rate": 4.2,
                        "wage_mom_pct": 0.2,
                        "wage_yoy_pct": 3.0,
                    },
                    "revisions": [
                        {
                            "observation_month": "2026-07",
                            "previous_value_thousands": 15.0,
                            "revised_value_thousands": 10.0,
                            "delta_thousands": -5.0,
                            "direction": "down",
                        }
                    ],
                    "sector_contributions": [
                        {
                            "sector": "Information",
                            "observation_month": "2026-08",
                            "change_thousands": -7.0,
                            "direction": "decrease",
                        }
                    ],
                    "missing_fields": [],
                    "parser_notes": [],
                    "source_refs": [
                        {
                            "source": "bls_employment_situation",
                            "source_url": "https://www.bls.gov/news.release/empsit.htm",
                            "raw_path": "raw/macro/bls_release/2026-09-06/empsit-fixture.html",
                            "retrieved_at": RETRIEVED_AT,
                        }
                    ],
                },
            },
        ],
    )

    assert snapshot.release_context["status"] == "available"
    assert snapshot.release_context["release_datetime"] == "2026-09-04T08:30:00-04:00"
    assert snapshot.release_context["headline"]["new_jobs_thousands"] == 123.0
    assert snapshot.release_context["revisions"][0]["delta_thousands"] == -5.0
    assert snapshot.release_context["sector_contributions"][0]["sector"] == "Information"
    assert snapshot.release_context["source_refs"][0]["raw_path"].endswith("empsit-fixture.html")
    assert snapshot.metrics["CES0000000001"].current_value == 159123.0


def test_employment_features_preserve_fred_vintage_lineage_and_unknown_release_time() -> None:
    snapshot = build_employment_features(
        [_point("CES0000000001", "2026-08-01", 159075.0)],
        as_of="2026-09-06",
        source_refs=[
            {
                "symbol": "BLS_EMPLOYMENT_RELEASE",
                "source": "fred_vintage",
                "source_kind": "fred_vintage",
                "release_date": "2026-09-04",
                "release_date_kind": "fred_vintage_date",
                "vintage_date": "2026-09-04",
                "previous_vintage_date": "2026-08-07",
                "release_context": {
                    "status": "partial",
                    "source_kind": "fred_vintage",
                    "release_date_kind": "fred_vintage_date",
                    "release_date": "2026-09-04",
                    "vintage_date": "2026-09-04",
                    "previous_vintage_date": "2026-08-07",
                    "baseline_kind": "previous_fred_vintage",
                    "release_time_local": None,
                    "release_datetime": None,
                    "headline": {"new_jobs_thousands": 162.0},
                    "revisions": [
                        {
                            "observation_month": "2026-07",
                            "previous_value_thousands": -23.0,
                            "revised_value_thousands": 21.0,
                            "delta_thousands": 44.0,
                            "value_kind": "monthly_change",
                            "level_components": {
                                "previous_vintage": {
                                    "observation_level_thousands": 158858.0,
                                    "prior_month_level_thousands": 158881.0,
                                },
                                "current_vintage": {
                                    "observation_level_thousands": 158913.0,
                                    "prior_month_level_thousands": 158892.0,
                                },
                            },
                            "baseline_kind": "previous_fred_vintage",
                        }
                    ],
                    "sector_contributions": [],
                    "source_refs": [
                        {
                            "source": "fred_vintage",
                            "source_url": "https://api.stlouisfed.org/fred/series/observations",
                            "raw_path": "raw/macro/fred_vintage/2026-09-06/PAYEMS.json",
                        }
                    ],
                },
            }
        ],
    )

    context = snapshot.release_context
    assert context["source_kind"] == "fred_vintage"
    assert context["release_date_kind"] == "fred_vintage_date"
    assert context["vintage_date"] == "2026-09-04"
    assert context["previous_vintage_date"] == "2026-08-07"
    assert context["baseline_kind"] == "previous_fred_vintage"
    assert context["release_time_local"] is None
    assert context["revisions"][0]["baseline_kind"] == "previous_fred_vintage"
    assert context["revisions"][0]["value_kind"] == "monthly_change"
    assert context["revisions"][0]["delta_thousands"] == 44.0


def test_employment_features_expose_bounded_industry_levels_and_derived_change() -> None:
    points = [
        _industry_point("CES3000000001", "2026-07-01", 12622.0),
        _industry_point("CES3000000001", "2026-08-01", 12638.0),
        _industry_point("CES5000000001", "2026-07-01", 2768.0),
        _industry_point("CES5000000001", "2026-08-01", 2745.0),
    ]
    source_refs = [
        {
            "symbol": "CES3000000001",
            "source": "fred",
            "source_url": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=MANEMP",
            "raw_path": "raw/macro/fred/2026-09-08/bls-employment-mirror.csv",
            "retrieved_at": RETRIEVED_AT,
        },
        {
            "symbol": "CES5000000001",
            "source": "fred",
            "source_url": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=USINFO",
            "raw_path": "raw/macro/fred/2026-09-08/bls-employment-mirror.csv",
            "retrieved_at": RETRIEVED_AT,
        },
    ]

    snapshot = build_employment_features(
        points,
        as_of="2026-09-08",
        source_refs=source_refs,
    )

    manufacturing = snapshot.industry_employment["CES3000000001"]
    information = snapshot.industry_employment["CES5000000001"]
    assert manufacturing.current_month == "2026-08"
    assert manufacturing.current_value == 12638.0
    assert manufacturing.previous_month == "2026-07"
    assert manufacturing.previous_value == 12622.0
    assert manufacturing.monthly_change == 16.0
    assert manufacturing.new_jobs_thousands is None
    assert manufacturing.current_source is not None
    assert manufacturing.current_source.source == "fred"
    assert manufacturing.current_source.observation_month == "2026-08"
    assert information.monthly_change == -23.0
    assert "CES7072200001" in snapshot.industry_unavailable_series
    # Industry availability is reported separately so the legacy core
    # ``unavailable_series`` contract remains unchanged.
    assert "CES3000000001" not in snapshot.unavailable_series
    payload = snapshot.to_dict()
    assert payload["industry_employment"]["CES3000000001"]["monthly_change"] == 16.0


def _points_from_parsed(parsed: dict[str, list]) -> list[dict[str, object]]:
    points: list[dict[str, object]] = []
    for series_id, observations in parsed.items():
        for observation in observations:
            points.append(_point(series_id, observation.point_date, observation.value))
    return points


def _point(symbol: str, date_value: str, value: float) -> dict[str, object]:
    return {
        "symbol": symbol,
        "date": date_value,
        "value": value,
        "source": "bls_public_api_v2",
        "source_url": f"https://api.bls.gov/publicAPI/v2/timeseries/data/{symbol}",
        "retrieved_at": RETRIEVED_AT,
        "raw_path": f"raw/macro/bls/2026-09-06/{symbol}.json",
    }


def _industry_point(symbol: str, date_value: str, value: float) -> dict[str, object]:
    return {
        "symbol": symbol,
        "date": date_value,
        "value": value,
        "source": "fred",
        "source_url": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=MANEMP",
        "retrieved_at": RETRIEVED_AT,
        "raw_path": "raw/macro/fred/2026-09-08/bls-employment-mirror.csv",
    }


def _source_ref(symbol: str) -> dict[str, object]:
    return {
        "symbol": symbol,
        "source": "bls_public_api_v2",
        "source_url": f"https://api.bls.gov/publicAPI/v2/timeseries/data/{symbol}",
        "raw_path": f"raw/macro/bls/2026-09-06/{symbol}.json",
        "retrieved_at": RETRIEVED_AT,
        "release_date": "unavailable",
        "vintage_status": "unavailable",
    }
