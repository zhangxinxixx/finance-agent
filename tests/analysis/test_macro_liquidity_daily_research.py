from __future__ import annotations

from datetime import datetime, timezone

import pytest

from apps.analysis.agents.macro_liquidity import analyze_macro_liquidity
from apps.analysis.macro.regime import classify_macro_regime


def _row(
    symbol: str,
    value: float,
    *,
    change: float | None = None,
    weekly_change: float | None = None,
    previous_value: float | None = None,
) -> dict:
    return {
        "symbol": symbol,
        "label": symbol,
        "value": value,
        "unit": "%" if symbol not in {"DXY", "HY_OAS", "VIX"} else "index",
        "observation_date": "2026-09-04",
        "previous_date": "2026-09-03" if previous_value is not None else None,
        "previous_value": previous_value,
        "change": change,
        "weekly_anchor_date": "2026-08-28" if weekly_change is not None else None,
        "weekly_change": weekly_change,
        "source_refs": [{
            "source": "test_passport",
            "source_url": "https://example.test/passport",
            "raw_path": "raw/test/passport.json",
            "retrieved_at": "2026-09-05T18:00:00+00:00",
        }],
        "status": "fresh",
        "lineage_status": "verified",
    }


def _passport() -> list[dict]:
    return [
        _row("US02Y", 4.37, change=0.03, weekly_change=0.03, previous_value=4.34),
        _row("US10Y", 4.78, change=0.01, weekly_change=0.05, previous_value=4.77),
        _row("BREAKEVEN_10Y", 2.35, change=0.0, weekly_change=0.04, previous_value=2.35),
        _row("REAL_10Y", 2.43, change=0.01, weekly_change=0.01, previous_value=2.42),
        _row("REAL10Y", 2.43, change=0.01, weekly_change=0.01, previous_value=2.42),
        _row("DXY", 99.159),
        _row("SOFR", 3.66),
        _row("EFFR", 3.63),
        _row("IORB", 3.65),
        _row("ON_RRP_USAGE", 0.675, weekly_change=-0.1),
        _row("TGA", 903.928, weekly_change=-46.876),
        _row("RESERVES", 2894.531, weekly_change=-30.405),
    ]


def _snapshot() -> dict:
    return {
        "snapshot_id": "XAUUSD:2026-09-05:passport-test",
        "input_snapshot_ids": {"macro": "macro:2026-09-05:passport-test"},
        "macro": {
            "status": "available",
            "data": {
                "as_of": "2026-09-05",
                "indicators": {
                    "US10Y": {"value": 4.78, "daily_change": 0.01, "weekly_change": 0.05},
                    "T10YIE": {"value": 2.35, "daily_change": 0.0, "weekly_change": 0.04},
                    "DXY": {"value": 99.159, "daily_change": 0.5, "weekly_change": 0.8},
                    "RRPONTSYD": {"value": 0.675, "change_1w": -0.1},
                    "TGA": {"value": 903.928, "change_1w": -46.876},
                    "WRESBAL": {"value": 2894.531, "change_1w": -30.405},
                    "SOFR": {"value": 3.66},
                    "EFFR": {"value": 3.63},
                    "IORB": {"value": 3.65},
                },
            },
        },
        "source_refs": [],
        "daily_research": {
        "schema_version": "daily_research.v1",
        "passport": _passport(),
        "source_refs": [],
        },
    }


def _v2_snapshot(*, real_rate: dict) -> dict:
    snapshot = _snapshot()
    snapshot["trade_date"] = "2026-09-05"
    snapshot["snapshot_time"] = "2026-09-05T18:00:00+00:00"
    snapshot["gold_workflow"] = {
        "schema_version": "gold_workflow.v2",
        "real_rate": real_rate,
    }
    return snapshot


def test_daily_research_passport_is_authoritative_and_bypasses_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    snapshot = _snapshot()
    legacy = snapshot["macro"]["data"]["indicators"]
    legacy["REAL_10Y"] = {"value": 2.43, "daily_change": -0.03, "weekly_change": -0.01}
    legacy["DXY"] = {"value": 99.159, "daily_change": 0.5, "weekly_change": 0.8}
    legacy["YIELD_SPREAD_2Y_3M"] = {"value": 0.45, "weekly_change": 0.09}

    def fail_if_called(*args, **kwargs):
        raise AssertionError("daily_research passport must bypass the LLM path")

    monkeypatch.setattr("apps.analysis.agents.macro_liquidity.invoke_macro_liquidity_llm", fail_if_called)

    output = analyze_macro_liquidity(
        snapshot,
        created_at=datetime(2026, 9, 5, tzinfo=timezone.utc),
    )

    assert output.llm_raw_output is None
    assert output.input_payload["indicators"]["REAL_10Y"]["change"] == pytest.approx(0.01)
    assert output.input_payload["indicators"]["DXY"]["change"] is None
    assert output.input_payload["short_curve_policy"]["spread_2y_3m"] is None
    assert output.regime_drivers["drivers"]["real_yield"]["daily_change"] == pytest.approx(0.01)
    assert output.regime_drivers["drivers"]["real_yield"]["direction"] == "rising"
    assert any("10Y 实际利率" in finding and "+1.0bp" in finding for finding in output.key_findings)
    assert not any("回落 3 个基点" in finding for finding in output.key_findings)
    assert not any("月度下跌约 0.5%" in finding for finding in output.key_findings)


def test_daily_research_missing_dxy_does_not_fallback_to_legacy_macro_value(monkeypatch: pytest.MonkeyPatch) -> None:
    snapshot = _snapshot()
    snapshot["daily_research"]["passport"] = [
        row for row in snapshot["daily_research"]["passport"] if row["symbol"] != "DXY"
    ]
    snapshot["macro"]["data"]["indicators"]["DXY"] = {
        "value": 101.5,
        "daily_change": 0.7,
        "weekly_change": 1.2,
    }
    monkeypatch.setattr(
        "apps.analysis.agents.macro_liquidity.invoke_macro_liquidity_llm",
        lambda *args, **kwargs: pytest.fail("daily_research passport must bypass the LLM path"),
    )

    output = analyze_macro_liquidity(snapshot)

    assert "DXY" not in output.input_payload["indicators"]
    assert any("DXY" in risk and "missing" in risk.lower() for risk in output.risk_points)
    assert not any("101.50" in finding or "rising" in finding.lower() and "DXY" in finding for finding in output.key_findings)


def test_gold_workflow_v2_official_real_rate_controls_score_driver_policy_and_regime() -> None:
    snapshot = _v2_snapshot(real_rate={
        "symbol": "REAL10Y",
        "method": "official_tips",
        "value": 2.43,
        "change": 0.01,
        "date": "2026-09-04",
        "previous_date": "2026-09-03",
        "source_refs": [{"source": "fred_dfii10", "raw_path": "raw/dfii10.json"}],
    })
    next(row for row in snapshot["daily_research"]["passport"] if row["symbol"] == "REAL_10Y")["change"] = -0.03
    next(row for row in snapshot["daily_research"]["passport"] if row["symbol"] == "DXY")["change"] = 0.5

    output = analyze_macro_liquidity(snapshot)

    real = output.regime_drivers["drivers"]["real_yield"]
    assert real["source"] == "gold_workflow.v2:official_tips"
    assert real["daily_change"] == pytest.approx(0.01)
    assert real["direction"] == "rising"
    assert output.market_phase == "rate_pressure"
    assert any("Rising 10Y real yields" in finding for finding in output.key_findings)
    assert not any("US10Y - T10YIE" in finding for finding in output.key_findings)
    policy = output.input_payload["real_yield_policy"]
    assert policy["main"] == "gold_workflow.v2.real_rate"
    assert policy["selected"]["symbol"] == "REAL10Y"
    assert output.input_payload["existing_frame"]["real_yield"]["value"] == pytest.approx(2.43)


def test_gold_workflow_v2_unavailable_real_rate_does_not_fallback_to_passport_derivation() -> None:
    output = analyze_macro_liquidity(_v2_snapshot(real_rate={
        "symbol": None,
        "method": "unavailable",
        "value": None,
        "change": None,
        "date": None,
        "previous_date": None,
        "source_refs": [],
    }))

    real = output.regime_drivers["drivers"]["real_yield"]
    assert real["status"] == "unavailable"
    assert real["value"] is None
    assert real["source"] == "gold_workflow.v2:unavailable"
    assert output.input_payload["existing_frame"]["real_yield"]["status"] == "unavailable"
    assert any("no legacy US10Y-T10YIE fallback" in item for item in output.invalid_conditions)
    assert not any("Falling 10Y real yields" in item or "Rising 10Y real yields" in item for item in output.key_findings)


def test_without_gold_workflow_v2_marker_legacy_real_yield_policy_remains_unchanged() -> None:
    output = analyze_macro_liquidity(_snapshot())

    assert "gold_workflow" not in output.input_payload
    assert output.input_payload["real_yield_policy"]["main"] == "US10Y - T10YIE"
    assert any("main口径 uses US10Y - T10YIE" in item for item in output.key_findings)


def test_real_rate_override_changes_only_the_real_rate_regime_driver() -> None:
    indicators = {
        "REAL_10Y": {"value": 2.40, "daily_change": -0.03},
        "US10Y": {"value": 4.78, "daily_change": 0.01},
        "T10YIE": {"value": 2.35, "daily_change": 0.04},
        "DXY": {"value": 99.1, "daily_change": 0.02},
        "ON_RRP_USAGE": {"value": 1.0, "daily_change": -0.1},
        "TGA": {"value": 900.0, "daily_change": 0.1},
        "RESERVES": {"value": 2900.0, "daily_change": -0.1},
    }
    legacy = classify_macro_regime(indicators)
    overridden = classify_macro_regime(indicators, real_yield_override={
        "status": "available",
        "source": "gold_workflow.v2:official_tips",
        "value": 2.40,
        "daily_change": 0.01,
        "direction": "rising",
    })

    for key in legacy["drivers"]:
        if key != "real_yield":
            assert overridden["drivers"][key] == legacy["drivers"][key]
    assert legacy["drivers"]["real_yield"]["daily_change"] == pytest.approx(-0.03)
    assert overridden["drivers"]["real_yield"]["daily_change"] == pytest.approx(0.01)
