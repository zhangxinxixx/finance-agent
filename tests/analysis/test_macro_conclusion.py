from __future__ import annotations

from apps.analysis.macro.conclusion import build_macro_conclusion
from apps.analysis.macro.full_report import render_macro_full_report_markdown
from apps.features.macro.snapshot import build_macro_snapshot


def test_current_manual_macro_doc_generates_target_conclusion() -> None:
    snapshot = build_macro_snapshot(_current_doc_points(), as_of="2026-05-08")
    conclusion = build_macro_conclusion(snapshot)
    assert conclusion.bias == "中性偏多"
    assert conclusion.quantity_layer == "偏松"
    assert conclusion.price_layer == "钱仍贵"
    assert conclusion.dollar_layer == "顺风"
    assert conclusion.state == "状态 2 —— 过渡释放态"
    assert conclusion.action == "回踩接多 / 等待"
    assert "不建议在当前环境里直接追高" in conclusion.no_go_actions
    assert conclusion.missing_inputs == []
    markdown = render_macro_full_report_markdown(snapshot, conclusion)
    assert "# XAUUSD 宏观 / 流动性更新（2026-05-08）" in markdown
    assert "**结论：中性偏多。**" in markdown
    assert "状态 2 —— 过渡释放态" in markdown
    assert "回踩接多" in markdown


def _current_doc_points() -> list[dict[str, object]]:
    series = {
        "RRPONTSYD": [("2026-04-07", 15.345), ("2026-04-30", 8.261), ("2026-05-07", 0.773)],
        "RRPONTSYAWARD": [("2026-04-07", 3.50), ("2026-04-30", 3.50), ("2026-05-07", 3.50)],
        "TGA": [("2026-04-06", 775.430), ("2026-04-29", 988.100), ("2026-05-06", 862.760)],
        "WRESBAL": [("2026-04-06", 3116.659), ("2026-04-29", 2919.011), ("2026-05-06", 3033.000)],
        "SOFR": [("2026-04-06", 3.65), ("2026-04-29", 3.63), ("2026-05-06", 3.61)],
        "EFFR": [("2026-04-06", 3.64), ("2026-04-29", 3.64), ("2026-05-06", 3.64)],
        "IORB": [("2026-04-08", 3.65), ("2026-05-01", 3.65), ("2026-05-08", 3.65)],
        "DGS2": [("2026-04-07", 3.84), ("2026-04-30", 3.84), ("2026-05-07", 3.87)],
        "DGS10": [("2026-04-07", 4.34), ("2026-04-30", 4.36), ("2026-05-07", 4.36)],
        "DFII10": [("2026-04-07", 1.97), ("2026-04-30", 1.90), ("2026-05-07", 1.91)],
        "T10YIE": [("2026-04-07", 2.37), ("2026-04-30", 2.46), ("2026-05-07", 2.45)],
        "DXY": [("2026-04-08", 98.967), ("2026-05-01", 98.137), ("2026-05-08", 97.927)],
    }
    points: list[dict[str, object]] = []
    for symbol, obs in series.items():
        for d, v in obs:
            points.append({"symbol": symbol, "date": d, "value": v, "source": "fixture", "source_url": "fixture://", "retrieved_at": "2026-05-08T00:00:00+00:00", "raw_path": "fixture"})
    return points
