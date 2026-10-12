from __future__ import annotations

import json
from pathlib import Path

import pytest

from apps.parsers.bls.employment import (
    BLS_EMPLOYMENT_SERIES,
    BLS_INDUSTRY_SERIES,
    BLS_SERIES_BY_ID,
    BLSParseError,
    parse_bls_employment_payload,
    parse_bls_industry_payload,
    parse_bls_series_payload,
)

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "macro" / "bls_employment_api.json"


def test_bls_fixture_maps_months_excludes_annual_and_applies_cutoff() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))

    parsed = parse_bls_employment_payload(payload, cutoff_month="2026-09-06")

    assert tuple(parsed) == BLS_EMPLOYMENT_SERIES
    assert [item.observation_month for item in parsed["CES0000000001"]] == [
        "2025-08",
        "2025-09",
        "2026-06",
        "2026-07",
        "2026-08",
    ]
    assert parsed["CES0000000001"][-1].point_date == "2026-08-01"
    assert parsed["CES0000000001"][-1].value == 159075.0
    assert parsed["CES0000000001"][-1].footnote_codes == ("P",)
    assert all(item.observation_month <= "2026-09" for series in parsed.values() for item in series)
    assert all(item.observation_month != "2025-13" for series in parsed.values() for item in series)


def test_bls_series_specs_keep_units_and_domain_kinds_explicit() -> None:
    assert BLS_SERIES_BY_ID["CES0000000001"].unit == "thousand_persons"
    assert BLS_SERIES_BY_ID["CES0000000001"].kind == "employment_level"
    assert BLS_SERIES_BY_ID["CES0500000003"].unit == "USD_per_hour"
    assert BLS_SERIES_BY_ID["LNS14000000"].unit == "percent"
    assert BLS_SERIES_BY_ID["LNS11300000"].kind == "labor_force_participation_rate"


def test_bls_industry_parser_keeps_the_bounded_five_series_domain() -> None:
    payload = {
        "status": "REQUEST_SUCCEEDED",
        "Results": {
            "series": [
                {
                    "seriesID": series_id,
                    "data": [
                        {"year": "2026", "period": "M07", "value": "100.0"},
                        {"year": "2026", "period": "M08", "value": "101.5"},
                    ],
                }
                for series_id in BLS_INDUSTRY_SERIES
            ]
        },
    }

    parsed = parse_bls_industry_payload(payload, cutoff_month="2026-08")

    assert tuple(parsed) == BLS_INDUSTRY_SERIES
    assert [item.value for item in parsed["CES3000000001"]] == [100.0, 101.5]


def test_bls_parser_skips_missing_and_non_monthly_values() -> None:
    payload = {
        "Results": {
            "series": [
                {
                    "seriesID": "CES0000000001",
                    "data": [
                        {"year": "2026", "period": "M01", "value": "158000"},
                        {"year": "2026", "period": "M02", "value": "-"},
                        {"year": "2026", "period": "M03", "value": "."},
                        {"year": "2026", "period": "M13", "value": "159000"},
                        {"year": "2026", "period": "M04", "value": "not-a-number"},
                    ],
                }
            ]
        }
    }

    parsed = parse_bls_series_payload(payload, series_id="CES0000000001")

    assert [(item.observation_month, item.value) for item in parsed] == [("2026-01", 158000.0)]


def test_bls_parser_fails_closed_on_conflicting_duplicate_month() -> None:
    payload = {
        "status": "REQUEST_SUCCEEDED",
        "Results": {
            "series": [
                {
                    "seriesID": "CES0500000003",
                    "data": [
                        {"year": "2026", "period": "M08", "value": "33.40"},
                        {"year": "2026", "period": "M08", "value": "33.41"},
                    ],
                }
            ]
        },
    }

    with pytest.raises(BLSParseError, match="Conflicting duplicate"):
        parse_bls_series_payload(payload, series_id="CES0500000003")


def test_bls_parser_reports_api_failure() -> None:
    with pytest.raises(BLSParseError, match="REQUEST_FAILED"):
        parse_bls_series_payload(
            {"status": "REQUEST_FAILED", "message": ["invalid request"]},
            series_id="CES0000000001",
        )
