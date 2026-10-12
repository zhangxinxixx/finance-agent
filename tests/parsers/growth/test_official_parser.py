from __future__ import annotations

import json
from pathlib import Path

import pytest

from apps.parsers.growth.official import (
    parse_gdpnow_commentary,
    parse_gdpnow_payload,
    parse_ism_report_html,
    parse_ism_prnewswire_index,
    parse_ism_prnewswire_release,
)


FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "macro" / "growth"


def test_parse_gdpnow_normalizes_value_period_and_official_update_date() -> None:
    payload = json.loads((FIXTURES / "gdpnow_research_data.json").read_text(encoding="utf-8"))

    result = parse_gdpnow_payload(payload)

    assert result.symbol == "GDP_NOW"
    assert result.value == 4.7
    assert result.observation_date == "2026-09-03"
    assert result.reference_period == "2026-Q3"
    assert result.metadata["date_semantics"] == "provider_update_date"


def test_parse_gdpnow_commentary_keeps_next_date_without_inventing_time() -> None:
    result = parse_gdpnow_commentary(
        (FIXTURES / "gdpnow_commentary.html").read_text(encoding="utf-8"),
        latest_observation_date="2026-09-03",
    )

    assert result.expected_release_date == "2026-09-10"
    assert result.expected_release_time is None
    assert result.previous_value == 4.8
    assert "time is not published" in (result.source_note or "")


def test_parse_ism_pages_emits_manufacturing_services_and_prices_with_prior_month() -> None:
    manufacturing, manufacturing_schedule = parse_ism_report_html(
        (FIXTURES / "ism_manufacturing_august.html").read_text(encoding="utf-8"),
        report_kind="manufacturing",
        source_url="fixture://ism/manufacturing/august",
    )
    services, services_schedule = parse_ism_report_html(
        (FIXTURES / "ism_services_august.html").read_text(encoding="utf-8"),
        report_kind="services",
        source_url="fixture://ism/services/august",
    )

    assert [(item.symbol, item.value, item.reference_period, item.previous_value) for item in manufacturing] == [
        ("ISM_MANUFACTURING", 54.6, "2026-08", 55.6),
    ]
    assert [(item.symbol, item.value, item.previous_value) for item in services] == [
        ("ISM_SERVICES", 55.4, 54.1),
        ("ISM_SERVICES_PRICES", 72.6, 70.3),
    ]
    assert manufacturing_schedule.expected_release_time == "2026-10-01T10:00:00-04:00"
    assert services_schedule.expected_release_time == "2026-10-05T10:00:00-04:00"
    assert services[1].metadata["index_role"] == "inflation_input"


def test_parse_ism_january_rolls_prior_reference_period_into_previous_year() -> None:
    records, schedule = parse_ism_report_html(
        (FIXTURES / "ism_january.html").read_text(encoding="utf-8"),
        report_kind="services",
        source_url="fixture://ism/services/january",
    )

    assert records[0].reference_period == "2027-01"
    assert records[0].previous_reference_period == "2026-12"
    assert records[1].previous_reference_period == "2026-12"
    assert schedule.expected_release_time == "2027-02-04T10:00:00-05:00"


def test_parse_gdpnow_missing_indicator_is_explicitly_unpublished() -> None:
    payload = json.loads((FIXTURES / "gdpnow_empty.json").read_text(encoding="utf-8"))

    with pytest.raises(ValueError, match="not published"):
        parse_gdpnow_payload(payload)


def test_parse_ism_requires_report_period_and_does_not_accept_napm_shape() -> None:
    with pytest.raises(ValueError, match="reference period"):
        parse_ism_report_html(
            "<html><body><p>NAPM 54.0</p></body></html>",
            report_kind="manufacturing",
            source_url="fixture://legacy/napm",
        )


def test_parse_ism_prnewswire_index_and_release_validates_issuer_period_and_release_time() -> None:
    candidate = parse_ism_prnewswire_index(
        (FIXTURES / "ism_prnewswire_index.html").read_text(encoding="utf-8"),
        report_kind="manufacturing",
        reference_period="2026-08",
    )
    assert candidate is not None
    assert candidate.url.endswith("302865127.html")
    assert candidate.reference_period == "2026-08"
    assert candidate.listing_release_date == "2026-09-01"

    records, _schedule = parse_ism_prnewswire_release(
        (FIXTURES / "ism_prnewswire_manufacturing_august.html").read_text(encoding="utf-8"),
        report_kind="manufacturing",
        source_url=candidate.url,
        expected_period="2026-08",
    )
    assert records[0].value == 54.6
    assert records[0].previous_value == 55.6
    assert records[0].release_date == "2026-09-01"
    assert records[0].release_time == "2026-09-01T10:00:00-04:00"
    assert records[0].source == "ism_prnewswire"
    assert records[0].metadata["issuer_verified"] is True
    assert records[0].metadata["distribution_channel"] == "prnewswire"


def test_parse_ism_prnewswire_release_rejects_unverified_issuer() -> None:
    payload = (FIXTURES / "ism_prnewswire_manufacturing_august.html").read_text(encoding="utf-8").replace(
        "SOURCE Institute for Supply Management", "SOURCE Unknown Publisher"
    )
    with pytest.raises(ValueError, match="issuer is not verified"):
        parse_ism_prnewswire_release(
            payload,
            report_kind="manufacturing",
            source_url="https://www.prnewswire.com/news-releases/example.html",
            expected_period="2026-08",
        )
