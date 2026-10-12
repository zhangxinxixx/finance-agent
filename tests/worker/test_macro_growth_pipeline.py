from __future__ import annotations

from pathlib import Path

from apps.parsers.macro.models import MacroPoint
from apps.worker.pipelines.macro import MacroPipelineState
from tests.helpers.warehouse import run_macro_feature_from_dwd


def _point(symbol: str, value: float) -> MacroPoint:
    return MacroPoint(
        symbol=symbol,
        date="2026-09-03" if symbol == "GDP_NOW" else "2026-08-01",
        value=value,
        source="official_fixture",
        source_url="https://official.example/growth",
        retrieved_at="2026-09-08T12:00:00+00:00",
        raw_path=f"raw/macro/growth/{symbol}.html",
    )


def _ref(symbol: str, source_key: str, reference_period: str, previous_value: float) -> dict[str, object]:
    return {
        "symbol": symbol,
        "source_key": source_key,
        "source": "official_fixture",
        "source_url": "https://official.example/growth",
        "raw_path": f"raw/macro/growth/{symbol}.html",
        "retrieved_at": "2026-09-08T12:00:00+00:00",
        "reference_period": reference_period,
        "previous_reference_period": "2026-Q3" if symbol == "GDP_NOW" else "2026-07",
        "previous_value": previous_value,
        "metadata": {"unit": "% q/q saar" if symbol == "GDP_NOW" else "index"},
    }


def _health(source_key: str, official_date: str, symbols: list[str]) -> dict[str, object]:
    return {
        "source_key": source_key,
        "symbols": symbols,
        "source": "official_fixture",
        "source_url": "https://official.example/growth",
        "raw_path": "raw/macro/growth/fixture.html",
        "retrieved_at": "2026-09-08T12:00:00+00:00",
        "expected_release_time": None,
        "expected_release_date": None,
        "actual_latest_date": official_date,
        "official_latest_date": official_date,
        "collector_status": "success",
        "staleness": "fresh",
        "expected_freshness": "event_driven" if source_key == "gdp_now" else "monthly",
    }


def test_research_macro_feature_attaches_growth_and_collector_health(tmp_path: Path) -> None:
    state = MacroPipelineState(as_of="2026-09-08", research_enabled=True)
    state.all_points = [
        _point("GDP_NOW", 4.7),
        _point("ISM_MANUFACTURING", 54.6),
        _point("ISM_SERVICES", 55.4),
        _point("ISM_SERVICES_PRICES", 72.6),
    ]
    state.all_source_refs = [
        _ref("GDP_NOW", "gdp_now", "2026-Q3", 4.8),
        _ref("ISM_MANUFACTURING", "ism_manufacturing", "2026-08", 55.6),
        _ref("ISM_SERVICES", "ism_services", "2026-08", 54.1),
        _ref("ISM_SERVICES_PRICES", "ism_services", "2026-08", 70.3),
    ]
    state.growth_health = {
        "gdp_now": _health("gdp_now", "2026-09-03", ["GDP_NOW"]),
        "ism_manufacturing": _health("ism_manufacturing", "2026-08-01", ["ISM_MANUFACTURING"]),
        "ism_services": _health("ism_services", "2026-08-01", ["ISM_SERVICES", "ISM_SERVICES_PRICES"]),
    }

    result = run_macro_feature_from_dwd(state, storage_root=tmp_path)

    assert result["status"] == "success"
    assert state.snapshot_dict is not None
    growth = state.snapshot_dict["growth"]
    assert growth["status"] == "ready"
    assert growth["metrics"]["GDP_NOW"]["change"] == -0.1
    assert growth["metrics"]["ISM_SERVICES_PRICES"]["change"] == 2.3
    assert state.snapshot_dict["collector_health"]["ism_services"]["symbols"] == [
        "ISM_SERVICES",
        "ISM_SERVICES_PRICES",
    ]
