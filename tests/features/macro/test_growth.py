from __future__ import annotations

from apps.features.macro.growth import build_growth_features


def _point(symbol: str, date: str, value: float) -> dict[str, object]:
    return {
        "symbol": symbol,
        "date": date,
        "value": value,
        "source": "fixture",
        "source_url": "fixture://growth",
        "retrieved_at": "2026-09-08T12:00:00+00:00",
        "raw_path": f"raw/macro/growth/{symbol}.json",
    }


def _health(source_key: str, *, official_date: str, status: str = "success") -> dict[str, object]:
    return {
        "source_key": source_key,
        "collector_status": status,
        "staleness": "fresh",
        "expected_freshness": "monthly",
        "expected_release_time": "2026-10-01T10:00:00-04:00",
        "actual_latest_date": official_date,
        "official_latest_date": official_date,
        "source": "fixture",
        "source_url": "fixture://growth",
        "raw_path": "raw/macro/growth/fixture.html",
        "retrieved_at": "2026-09-08T12:00:00+00:00",
    }


def test_growth_features_expose_period_change_and_health_contract() -> None:
    refs = [
        {
            "symbol": "GDP_NOW",
            "source_key": "gdp_now",
            "reference_period": "2026-Q3",
            "previous_reference_period": "2026-Q3",
            "previous_value": 4.8,
            "metadata": {"unit": "% q/q saar"},
        },
        {
            "symbol": "ISM_MANUFACTURING",
            "source_key": "ism_manufacturing",
            "reference_period": "2026-08",
            "previous_reference_period": "2026-07",
            "previous_value": 55.6,
            "metadata": {"unit": "index"},
        },
        {
            "symbol": "ISM_SERVICES",
            "source_key": "ism_services",
            "reference_period": "2026-08",
            "previous_reference_period": "2026-07",
            "previous_value": 54.1,
            "metadata": {"unit": "index"},
        },
        {
            "symbol": "ISM_SERVICES_PRICES",
            "source_key": "ism_services",
            "reference_period": "2026-08",
            "previous_reference_period": "2026-07",
            "previous_value": 70.3,
            "metadata": {"unit": "index"},
        },
    ]
    health = {
        "gdp_now": _health("gdp_now", official_date="2026-09-03"),
        "ism_manufacturing": _health("ism_manufacturing", official_date="2026-08-01"),
        "ism_services": _health("ism_services", official_date="2026-08-01"),
    }

    snapshot = build_growth_features(
        [
            _point("GDP_NOW", "2026-09-03", 4.7),
            _point("ISM_MANUFACTURING", "2026-08-01", 54.6),
            _point("ISM_SERVICES", "2026-08-01", 55.4),
            _point("ISM_SERVICES_PRICES", "2026-08-01", 72.6),
        ],
        as_of="2026-09-08",
        source_refs=refs,
        collector_health=health,
    )

    assert snapshot.status == "ready"
    assert snapshot.metrics["GDP_NOW"].change == -0.1
    assert snapshot.metrics["GDP_NOW"].reference_period == "2026-Q3"
    assert snapshot.metrics["ISM_SERVICES_PRICES"].change == 2.3
    assert snapshot.collector_health["ism_services"]["official_latest_date"] == "2026-08-01"


def test_growth_features_reject_local_value_when_official_source_is_newer() -> None:
    snapshot = build_growth_features(
        [_point("ISM_SERVICES", "2026-07-01", 54.1)],
        as_of="2026-09-08",
        source_refs=[
            {
                "symbol": "ISM_SERVICES",
                "source_key": "ism_services",
                "reference_period": "2026-07",
                "metadata": {"unit": "index"},
            }
        ],
        collector_health={"ism_services": _health("ism_services", official_date="2026-08-01")},
    )

    metric = snapshot.metrics["ISM_SERVICES"]
    assert metric.status == "stale"
    assert "ISM_SERVICES" in snapshot.unavailable_symbols
    assert snapshot.collector_health["ism_services"]["collector_status"] == "stale"
    assert snapshot.collector_health["ism_services"]["staleness"] == "local_old_value"
    assert snapshot.warnings == ["ISM_SERVICES: local date 2026-07-01 trails official date 2026-08-01"]


def test_growth_features_preserve_auth_and_unpublished_states() -> None:
    snapshot = build_growth_features(
        [],
        as_of="2026-09-08",
        unavailable_symbols=["GDP_NOW", "ISM_MANUFACTURING", "ISM_SERVICES", "ISM_SERVICES_PRICES"],
        collector_health={
            "gdp_now": _health("gdp_now", official_date="2026-09-03", status="auth_failed"),
            "ism_manufacturing": {
                **_health("ism_manufacturing", official_date="2026-08-01", status="not_published"),
                "staleness": "not_published",
            },
        },
    )

    assert snapshot.metrics["GDP_NOW"].status == "auth_failed"
    assert snapshot.metrics["ISM_MANUFACTURING"].status == "not_published"
    assert snapshot.metrics["ISM_SERVICES"].status == "unavailable"
    assert snapshot.collector_health["ism_manufacturing"]["staleness"] == "not_published"


def test_growth_features_reject_future_points_at_cutoff() -> None:
    snapshot = build_growth_features(
        [_point("GDP_NOW", "2026-09-09", 5.0)],
        as_of="2026-09-08",
        source_refs=[{"symbol": "GDP_NOW", "source_key": "gdp_now", "reference_period": "2026-Q3"}],
        collector_health={"gdp_now": _health("gdp_now", official_date="2026-09-09")},
    )

    assert snapshot.metrics["GDP_NOW"].status == "unavailable"
    assert "future observation rejected" in snapshot.warnings[0]


def test_growth_features_rejects_official_future_date_even_when_local_point_is_old() -> None:
    snapshot = build_growth_features(
        [_point("GDP_NOW", "2026-09-03", 4.7)],
        as_of="2026-09-08",
        source_refs=[{"symbol": "GDP_NOW", "source_key": "gdp_now", "reference_period": "2026-Q3"}],
        collector_health={"gdp_now": _health("gdp_now", official_date="2026-09-09")},
    )

    assert snapshot.metrics["GDP_NOW"].status == "unavailable"
    assert snapshot.collector_health["gdp_now"]["collector_status"] == "future_observation"
