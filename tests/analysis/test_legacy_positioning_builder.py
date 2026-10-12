from __future__ import annotations

from apps.analysis.snapshots.builder import _build_positioning_section


FUTURES_URL = "https://www.cftc.gov/files/dea/history/fut_disagg_txt_2026.zip"
COMBINED_URL = "https://www.cftc.gov/files/dea/history/com_disagg_txt_2026.zip"


def _point(symbol: str, value: float, *, source_url: str, raw_path: str) -> dict[str, object]:
    return {
        "symbol": symbol,
        "date": "2026-09-01",
        "value": value,
        "source": "cftc",
        "source_url": source_url,
        "raw_path": raw_path,
    }


def test_legacy_positioning_keeps_combined_points_out_of_futures_history_and_refs() -> None:
    futures_values = (-500.0, -450.0, -400.0, -350.0, -100.0)
    futures_points = [
        _point(
            "COT_GOLD_commercial_net",
            value,
            source_url=FUTURES_URL,
            raw_path=f"raw/cot/futures-{index}.json",
        )
        for index, value in enumerate(futures_values)
    ]
    futures_points.append(
        _point(
            "COT_GOLD_noncomm_net",
            50.0,
            source_url=FUTURES_URL,
            raw_path="raw/cot/futures-latest.json",
        )
    )
    combined_points = [
        _point(
            "COT_GOLD_combined_commercial_net",
            1_000.0 + index,
            source_url=COMBINED_URL,
            raw_path=f"raw/cot/combined-{index}.json",
        )
        for index in range(5)
    ]

    result = _build_positioning_section([*futures_points, *combined_points])

    assert result["status"] == "available"
    data = result["data"]
    assert data["commercial_net"] == -100.0
    assert data["extreme_reading"] is True
    assert all(ref["source_url"] == FUTURES_URL for ref in data["source_refs"])
    assert all("combined" not in ref["raw_path"] for ref in data["source_refs"])
