from __future__ import annotations

from apps.collectors.jin10 import kline, quotes
from apps.collectors.news.collector import _make_ref


def test_news_mcp_refs_carry_lane_source_keys() -> None:
    calendar_ref = _make_ref(
        "jin10_mcp",
        "list_calendar",
        "raw/news/jin10_mcp/2026-06-13/calendar.json",
        source_key="jin10_mcp_calendar",
    )
    flash_ref = _make_ref(
        "jin10_mcp",
        "list_flash",
        "raw/news/jin10_mcp/2026-06-13/flash_latest.json",
        source_key="jin10_mcp_flash",
    )

    assert calendar_ref["source_key"] == "jin10_mcp_calendar"
    assert flash_ref["source_key"] == "jin10_mcp_flash"


def test_market_mcp_quote_and_kline_refs_carry_market_source_key(tmp_path) -> None:
    quote_refs: list[dict] = []
    quotes._archive_and_ref(
        {"status": 200, "data": {"price": "4463.04"}},
        "2026-06-13",
        "XAUUSD",
        tmp_path,
        quote_refs,
    )

    kline_refs: list[dict] = []
    kline._archive_and_ref(
        {"status": 200, "data": {"klines": []}},
        "2026-06-13",
        "XAUUSD",
        tmp_path,
        kline_refs,
    )

    assert quote_refs[0]["source_key"] == "jin10_mcp_market"
    assert quote_refs[0]["source"] == "jin10_mcp"
    assert kline_refs[0]["source_key"] == "jin10_mcp_market"
    assert kline_refs[0]["source"] == "jin10_mcp"


def test_kline_collector_extracts_mcp_klines_shape() -> None:
    points = kline._extract_kline_points(
        {
            "data": {
                "klines": [
                    {
                        "time": 1780645680,
                        "open": "4462.82",
                        "high": "4463.11",
                        "low": "4461.90",
                        "close": "4463.04",
                    }
                ]
            }
        },
        "XAUUSD",
        "raw/news/jin10_mcp/2026-06-13/kline_XAUUSD.json",
        "2026-06-13T00:00:00+00:00",
        "2026-06-13",
    )

    assert len(points) == 1
    assert points[0].symbol == "KLINE:XAUUSD:1780645680"
    assert points[0].value == 4463.04
