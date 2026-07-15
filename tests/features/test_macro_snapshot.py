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
            "DGS3MO": [("2026-04-06", 4.9), ("2026-04-29", 4.7), ("2026-05-06", 4.6)],
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
    short_curve_spread = snapshot.indicators["YIELD_SPREAD_2Y_3M"]
    us03m = snapshot.indicators["US03M"]
    us10y = snapshot.indicators["US10Y"]
    rrp_usage = snapshot.indicators["ON_RRP_USAGE"]

    assert real_10y.label == "10Y 实际利率 = US10Y - T10YIE"
    assert real_10y.value == 1.95
    assert real_10y.weekly_change == 0.05
    assert real_10y.monthly_change == -0.05
    assert yield_spread.value == 0.3
    assert yield_spread.weekly_change == 0.0
    assert short_curve_spread.label == "2Y-3M 利差"
    assert short_curve_spread.value == -0.6
    assert short_curve_spread.weekly_change == 0.2
    assert short_curve_spread.monthly_change == 0.6
    assert short_curve_spread.direction_note == "倒挂、倒挂收窄；2Y 上行、3M 下行，鹰派预期与近期价格转松并存"
    assert us03m.label == "US03M"
    assert us03m.value == 4.6
    assert us03m.weekly_change == -0.1
    assert us03m.monthly_change == -0.3
    assert us03m.direction_note == "3M 周度下行，当前政策价格出现转松信号"
    assert us10y.unit == "%"
    assert us10y.monthly_change == 0.3
    assert rrp_usage.unit == "B"
    assert rrp_usage.monthly_change == -170.0
    assert "DXY" in snapshot.unavailable_symbols
    assert "TGA" in snapshot.unavailable_symbols
    assert snapshot.source_refs["TGA"]["reason"] == "collector unavailable"

    markdown = render_macro_snapshot_markdown(snapshot)
    assert "# XAUUSD 宏观数据报告" in markdown
    assert "数据刷新时间: 2026-05-06" in markdown
    assert "## 核心宏观指标" in markdown
    assert "指标 | 最新日期 | 最新值 | 1周变化 | 1月变化 | 方向解读" in markdown
    assert "## 宏观数据限制" in markdown
    assert "## 数据来源" in markdown
    assert "明确缺失" in markdown
    assert "10Y 实际利率" in markdown
    assert "DXY" in markdown


def test_macro_snapshot_marks_real_10y_unavailable_when_t10yie_is_missing() -> None:
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
    assert "T10YIE" in snapshot.unavailable_symbols
    assert "DGS3MO" in snapshot.unavailable_symbols
    assert "US03M" not in snapshot.indicators
    assert "BREAKEVEN_10Y" not in snapshot.indicators
    assert "YIELD_SPREAD_2Y_3M" not in snapshot.indicators
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
