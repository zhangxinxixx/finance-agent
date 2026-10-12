from __future__ import annotations

from pathlib import Path

import pytest

from apps.parsers.bls.employment import BLSReleaseParseError, parse_bls_employment_release_html


FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "macro" / "bls_employment_release.html"


def test_parse_employment_release_extracts_publication_headline_revisions_and_sectors() -> None:
    release = parse_bls_employment_release_html(FIXTURE.read_text(encoding="utf-8"))

    assert release.status == "available"
    assert release.release_date == "2026-09-04"
    assert release.release_time_local == "08:30"
    assert release.release_timezone == "America/New_York"
    assert release.release_datetime == "2026-09-04T08:30:00-04:00"
    assert release.observation_month == "2026-08"
    assert release.headline_new_jobs_thousands == 123.0
    assert release.headline_unemployment_rate == 4.2
    assert release.headline_wage_mom_pct == 0.2
    assert release.headline_wage_yoy_pct == 3.0

    assert [item.to_dict() for item in release.revisions] == [
        {
            "observation_month": "2026-06",
            "previous_value_thousands": 20.0,
            "revised_value_thousands": 30.0,
            "delta_thousands": 10.0,
            "direction": "up",
            "evidence_excerpt": "change in total nonfarm payroll employment for June was revised up by 10,000, from +20,000 to +30,000,",
        },
        {
            "observation_month": "2026-07",
            "previous_value_thousands": 15.0,
            "revised_value_thousands": 10.0,
            "delta_thousands": -5.0,
            "direction": "down",
            "evidence_excerpt": "the change for July was revised down by 5,000, from +15,000 to +10,000",
        },
    ]
    sectors = {item.sector: item.change_thousands for item in release.sector_contributions}
    assert sectors["food services"] == 45.0
    assert sectors["Local government education"] == 12.0
    assert sectors["Information"] == -7.0
    assert release.evidence_excerpts["headline"].startswith("Total nonfarm payroll employment")
    assert "0.2 percent" in release.evidence_excerpts["wages"]


def test_parse_employment_release_rejects_unverified_observation_month() -> None:
    with pytest.raises(BLSReleaseParseError, match="observation month mismatch"):
        parse_bls_employment_release_html(
            FIXTURE.read_text(encoding="utf-8"),
            expected_observation_month="2026-07",
        )
