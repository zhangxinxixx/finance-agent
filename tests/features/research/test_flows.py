from __future__ import annotations

from copy import deepcopy

import pytest

from apps.features.research.flows import build_flow_diagnostics


TECH_SOURCE = {
    "source": "twelvedata_xauusd_daily",
    "raw_path": "raw/technical/twelvedata/2026-09-08/XAUUSD.json",
    "source_url": "https://api.twelvedata.com/time_series",
}
COT_SOURCE = {
    "source": "cftc",
    "raw_path": "raw/cot/2026-09-08/gold.json",
    "reference": "https://www.cftc.gov/files/dea/history/fut_disagg_txt_2026.zip",
}
ETF_SOURCE = {
    "source": "ssga_gld",
    "raw_path": "raw/etf/2026-09-08/gld.json",
    "source_url": "https://www.ssga.com/us/en/individual/etfs/spdr-gold-shares-gld",
}


def _report(
    *,
    report_date: str = "2026-09-08",
    previous_report_date: str = "2026-09-01",
    mm_long: tuple[float, float] = (110.0, 100.0),
    mm_short: tuple[float, float] = (50.0, 50.0),
    oi: tuple[float, float] = (1_100.0, 1_000.0),
) -> dict:
    other_current = {"long": 220.0, "short": 180.0, "net": 40.0}
    other_previous = {"long": 210.0, "short": 175.0, "net": 35.0}
    return {
        "readiness": "ready",
        "quality_status": "accepted",
        "alignment_status": "aligned",
        "report_date": report_date,
        "previous_report_date": previous_report_date,
        "source_refs": [deepcopy(COT_SOURCE)],
        "managed_money": {
            "latest": {"long": mm_long[0], "short": mm_short[0], "net": mm_long[0] - mm_short[0]},
            "previous": {"long": mm_long[1], "short": mm_short[1], "net": mm_long[1] - mm_short[1]},
            "delta": {"long": mm_long[0] - mm_long[1], "short": mm_short[0] - mm_short[1], "net": (mm_long[0] - mm_short[0]) - (mm_long[1] - mm_short[1])},
            "spreading": {"latest": 130.0, "previous": 120.0, "delta": 10.0},
        },
        "other_reportables": {
            "latest": other_current,
            "previous": other_previous,
            "delta": {"long": 10.0, "short": 5.0, "net": 5.0},
        },
        "open_interest": {"value": oi[0], "previous": oi[1], "delta": oi[0] - oi[1]},
    }


def _snapshot(
    *,
    current_price: float = 110.0,
    previous_price: float = 100.0,
    reports: dict | None = None,
    notes_dates: list[str] | None = None,
    notes_closes: list[float] | None = None,
    source_ref: dict | None = None,
    official_etf: dict | None = None,
) -> dict:
    source_ref = deepcopy(source_ref or TECH_SOURCE)
    source_ref["notes"] = {
        "dates": notes_dates or ["2026-09-01", "2026-09-08"],
        "closes": notes_closes or [previous_price, current_price],
    }
    report_map = reports or {"combined": _report(), "futures_only": _report()}
    return {
        "snapshot_id": "XAUUSD:2026-09-08:flow-test",
        "trade_date": "2026-09-08",
        "snapshot_time": "2026-09-08T12:00:00+00:00",
        "input_snapshot_ids": {"macro": "macro:flow-test"},
        "source_refs": [source_ref, deepcopy(COT_SOURCE), deepcopy(ETF_SOURCE)],
        "technical": {
            "status": "available",
            "data": {"source_refs": [{"source": source_ref["source"], "raw_path": source_ref["raw_path"]}]},
        },
        "daily_research": {
            "input_snapshot_ids": {"cot": "cot:flow-test"},
            "cot_reports": report_map,
            "official_etf": official_etf or _etf(),
        },
    }


def _etf() -> dict:
    return {
        "status": "available",
        "source_refs": [deepcopy(ETF_SOURCE)],
        "shares_outstanding": 1_000.0,
        "shares_delta": 100.0,
        "shares_weekly_delta": -200.0,
        "shares_reported_on": "2026-09-08",
        "gold_holdings_tonnes": 500.0,
        "gold_holdings_tonnes_delta": 1.0,
        "gold_holdings_tonnes_weekly_delta": 2.0,
        "gold_holdings_tonnes_reported_on": "2026-09-08",
        "total_net_assets_usd": 150_000_000_000.0,
        "missing_data": [],
    }


@pytest.mark.parametrize(
    ("expected", "current_price", "previous_price", "mm_long", "mm_short", "oi"),
    [
        ("new_longs", 110.0, 100.0, (110.0, 100.0), (50.0, 50.0), (1_100.0, 1_000.0)),
        ("short_covering", 110.0, 100.0, (100.0, 100.0), (40.0, 50.0), (1_000.0, 1_000.0)),
        ("long_liquidation", 90.0, 100.0, (90.0, 100.0), (50.0, 50.0), (900.0, 1_000.0)),
        ("new_shorts", 90.0, 100.0, (100.0, 100.0), (60.0, 50.0), (1_100.0, 1_000.0)),
    ],
)
def test_approved_cot_price_oi_classifications(
    expected: str,
    current_price: float,
    previous_price: float,
    mm_long: tuple[float, float],
    mm_short: tuple[float, float],
    oi: tuple[float, float],
) -> None:
    report = _report(mm_long=mm_long, mm_short=mm_short, oi=oi)
    result = build_flow_diagnostics(
        _snapshot(
            current_price=current_price,
            previous_price=previous_price,
            reports={"combined": report, "futures_only": deepcopy(report)},
        )
    )
    combined = result["reports"]["combined"]
    assert combined["classification"] == expected
    assert combined["classification_status"] == "confirmed"
    assert combined["window"]["status"] == "verified"


def test_flow_keeps_spreading_other_reportables_oi_delta_and_lineage() -> None:
    result = build_flow_diagnostics(_snapshot())
    combined = result["reports"]["combined"]
    assert combined["delta"]["managed_money"]["long"] == 10.0
    assert combined["delta"]["managed_money"]["short"] == 0.0
    assert combined["delta"]["managed_money_spreading"] == 10.0
    assert combined["delta"]["other_reportables"]["long"] == 10.0
    assert combined["delta"]["open_interest"] == 100.0
    assert result["snapshot_id"] == "XAUUSD:2026-09-08:flow-test"
    assert result["input_snapshot_ids"] == {"macro": "macro:flow-test", "cot": "cot:flow-test"}
    assert any(ref.get("source") == "cftc" for ref in result["source_refs"])
    assert any(ref.get("source") == "twelvedata_xauusd_daily" for ref in result["source_refs"])


def test_wrong_source_or_missing_exact_endpoint_never_uses_nearest_price() -> None:
    wrong_source = {
        **TECH_SOURCE,
        "source": "other_price_provider",
        "raw_path": "raw/other/price.json",
    }
    wrong_snapshot = _snapshot()
    wrong_snapshot["source_refs"][0] = wrong_source
    result = build_flow_diagnostics(wrong_snapshot)
    combined = result["reports"]["combined"]
    assert combined["window"]["status"] == "unavailable"
    assert combined["classification"] == "unconfirmed"
    assert combined["positioning"]["delta"]["managed_money"]["long"] == 10.0

    no_exact_endpoint = build_flow_diagnostics(
        _snapshot(notes_dates=["2026-09-02", "2026-09-07"], notes_closes=[101.0, 109.0])
    )
    assert no_exact_endpoint["reports"]["combined"]["window"]["status"] == "unavailable"
    assert no_exact_endpoint["reports"]["combined"]["classification"] == "unconfirmed"

    future_price = build_flow_diagnostics(
        _snapshot(notes_dates=["2026-09-01", "2026-09-09"], notes_closes=[100.0, 111.0])
    )
    assert future_price["reports"]["combined"]["window"]["status"] == "unavailable"


def test_future_cot_window_is_rejected_and_contraction_is_position_only() -> None:
    report = _report(
        report_date="2026-09-09",
        previous_report_date="2026-09-01",
        mm_long=(90.0, 100.0),
        mm_short=(50.0, 50.0),
        oi=(900.0, 1_000.0),
    )
    result = build_flow_diagnostics(_snapshot(reports={"combined": report, "futures_only": deepcopy(report)}))
    combined = result["reports"]["combined"]
    assert combined["window"]["status"] == "unavailable"
    assert combined["classification"] == "unconfirmed"
    assert combined["position_contraction"]["regime"] == "position_contraction"
    assert combined["position_contraction"]["price_attribution"] is False
    assert result["event_attribution"]["status"] == "not_performed"


def test_etf_prefers_shares_and_holdings_and_exposes_daily_weekly_divergence() -> None:
    result = build_flow_diagnostics(_snapshot())
    etf = result["etf"]
    assert etf["daily"] == {"shares": 100.0, "holdings_tonnes": 1.0}
    assert etf["weekly"] == {"shares": -200.0, "holdings_tonnes": 2.0}
    assert etf["daily_vs_weekly"]["shares"] == "divergent"
    assert etf["daily_vs_weekly"]["holdings_tonnes"] == "aligned"
    assert etf["levels"]["aum_flow_used"] is False
    assert etf["auxiliary"]["IAU"]["status"] == "unavailable"
    assert etf["auxiliary"]["WGC"]["status"] == "unavailable"
