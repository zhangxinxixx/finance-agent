from __future__ import annotations

from pathlib import Path

from apps.analysis.macro.summary import render_macro_snapshot_markdown
from apps.features.macro.snapshot import build_macro_snapshot


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "macro"


def test_macro_snapshot_builds_indicator_table_fields_for_available_and_unavailable_series() -> None:
    points = _build_points(
        {
            "DGS10": [("2026-04-06", 4.0), ("2026-04-29", 4.2), ("2026-05-06", 4.3)],
            "DGS2": [("2026-04-06", 3.7), ("2026-04-29", 3.9), ("2026-05-06", 4.0)],
            "DFII10": [("2026-04-06", 1.90), ("2026-04-29", 1.93), ("2026-05-06", 1.91)],
            "T10YIE": [("2026-04-06", 2.0), ("2026-04-29", 2.3), ("2026-05-06", 2.35)],
            "SOFR": [("2026-04-06", 4.35), ("2026-04-29", 4.37), ("2026-05-06", 4.40)],
            "EFFR": [("2026-04-06", 4.32), ("2026-04-29", 4.33), ("2026-05-06", 4.36)],
            "IORB": [("2026-04-06", 4.45), ("2026-04-29", 4.45), ("2026-05-06", 4.45)],
            "RRPONTSYD": [("2026-04-06", 550.0), ("2026-04-29", 420.0), ("2026-05-06", 380.0)],
            "RRPONTSYAWARD": [("2026-04-06", 4.60), ("2026-04-29", 4.58), ("2026-05-06", 4.55)],
            "WRESBAL": [("2026-04-06", 3200.0), ("2026-04-29", 3180.0), ("2026-05-06", 3150.0)],
        }
    )

    snapshot = build_macro_snapshot(
        points,
        as_of="2026-05-06",
        unavailable_symbols=["TGA"],
        source_refs=[
            {
                "symbol": "TGA",
                "source": "treasury",
                "source_url": "https://api.fiscaldata.treasury.gov/",
                "reason": "collector unavailable",
            }
        ],
    )

    real_10y = snapshot.indicators["REAL_10Y"]
    yield_spread = snapshot.indicators["YIELD_SPREAD_10Y_2Y"]
    us10y = snapshot.indicators["US10Y"]
    rrp_usage = snapshot.indicators["ON_RRP_USAGE"]

    assert real_10y.label == "10Y 实际利率（10Y TIPS）"
    assert real_10y.value == 1.91
    assert real_10y.weekly_change == -0.02
    assert real_10y.monthly_change == 0.01
    assert yield_spread.value == 0.3
    assert yield_spread.weekly_change == 0.0
    assert us10y.unit == "%"
    assert us10y.monthly_change == 0.3
    assert rrp_usage.unit == "B"
    assert rrp_usage.monthly_change == -170.0
    assert "DXY" in snapshot.unavailable_symbols
    assert "TGA" in snapshot.unavailable_symbols
    assert snapshot.source_refs["TGA"]["reason"] == "collector unavailable"

    markdown = render_macro_snapshot_markdown(snapshot)
    assert "指标 | 最新日期 | 最新值 | 1周变化 | 1月变化 | 方向解读" in markdown
    assert "明确缺失" in markdown
    assert "10Y 实际利率" in markdown
    assert "DXY" in markdown


def test_macro_snapshot_marks_real_10y_unavailable_when_dfii10_is_missing() -> None:
    points = [
        {
            "symbol": "DGS10",
            "date": "2026-05-06",
            "value": 4.3,
            "source": "fred",
            "source_url": "fixture://fred/DGS10",
            "retrieved_at": "2026-05-06T00:00:00+00:00",
            "raw_path": "storage/raw/macro/fred/2026-05-06/DGS10.json",
        }
    ]

    snapshot = build_macro_snapshot(points, as_of="2026-05-06")

    assert "REAL_10Y" not in snapshot.indicators
    assert "DFII10" in snapshot.unavailable_symbols
    assert "T10YIE" in snapshot.unavailable_symbols
    assert "BREAKEVEN_10Y" not in snapshot.indicators
    assert snapshot.indicators["US10Y"].value == 4.3
    assert snapshot.source_refs["DGS10"]["source_url"] == "fixture://fred/DGS10"


def test_macro_snapshot_keeps_source_refs_for_unavailable_collector_symbols() -> None:
    snapshot = build_macro_snapshot(
        [],
        as_of="2026-05-06",
        unavailable_symbols=["TGA"],
        source_refs=[
            {
                "symbol": "TGA",
                "source": "treasury",
                "source_url": "https://api.fiscaldata.treasury.gov/",
                "reason": "offline",
            }
        ],
    )

    assert "TGA" in snapshot.unavailable_symbols
    assert snapshot.source_refs["TGA"]["reason"] == "offline"


def _build_points(series_map: dict[str, list[tuple[str, float]]]) -> list[dict[str, object]]:
    points: list[dict[str, object]] = []
    for symbol, observations in series_map.items():
        for date_value, value in observations:
            points.append(
                {
                    "symbol": symbol,
                    "date": date_value,
                    "value": value,
                    "source": "fred",
                    "source_url": f"fixture://fred/{symbol}",
                    "retrieved_at": "2026-05-06T00:00:00+00:00",
                    "raw_path": f"storage/raw/macro/fred/2026-05-06/{symbol}.json",
                }
            )
    return points
