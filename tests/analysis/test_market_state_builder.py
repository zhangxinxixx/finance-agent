from __future__ import annotations

from apps.analysis.state import MarketState, build_market_state
from apps.analysis.snapshots.builder import build_analysis_snapshot


def _macro_snapshot() -> dict:
    return {
        "as_of": "2026-05-14",
        "indicators": {"DGS10": {"value": 4.3}},
        "source_refs": [
            {"symbol": "DGS10", "source": "fred", "source_url": "https://fred.example/DGS10"},
        ],
    }


def _options_snapshot() -> dict:
    return {
        "version": "1.0",
        "trade_date": "2026-05-14",
        "data_source": {
            "status": "PRELIM",
            "product": "OG",
            "input_snapshot_ids": {
                "raw_file_sha256": "abc123",
                "raw_file_id": "42",
            },
        },
        "wall_scores": [{"strike": 3300, "rank": 1}],
    }


def _full_snapshot() -> dict:
    snapshot = build_analysis_snapshot(
        asset="XAUUSD",
        trade_date="2026-05-14",
        run_id="market-state-test",
        macro_snapshot=_macro_snapshot(),
        options_snapshot=_options_snapshot(),
        source_refs=[
            {"symbol": "DXY", "source": "tradingview"},
            {"symbol": "XAUUSD", "source": "yahoo_finance"},
        ],
        news_snapshot={"items": [{"title": "Fed watch"}]},
        snapshot_time="2026-05-14T10:00:00+08:00",
    )
    snapshot["technical"] = {"status": "available", "data": {"close": 2390.5}}
    snapshot["positioning"] = {"status": "available", "data": {"net_position": 12000}}
    snapshot["market_odds"] = {"status": "available", "data": {"direction_probability": {"bullish": 0.56}}}
    return snapshot


def test_build_market_state_from_full_analysis_snapshot() -> None:
    market_state = build_market_state(_full_snapshot())

    assert isinstance(market_state, MarketState)
    assert market_state.version == "1.0"
    assert market_state.asset == "XAUUSD"
    assert market_state.trade_date == "2026-05-14"
    assert market_state.run_id == "market-state-test"
    assert market_state.snapshot_id == "XAUUSD:2026-05-14:market-state-test"
    assert market_state.macro.status == "available"
    assert market_state.options.status == "available"
    assert market_state.technical.status == "available"
    assert market_state.positioning.status == "available"
    assert market_state.news.status == "available"
    assert market_state.market_odds.status == "available"
    assert market_state.source_quality.total_refs == 3
    assert market_state.source_quality.sources == ["fred", "tradingview", "yahoo_finance"]
    assert market_state.data_completeness.coverage_ratio == 1.0
    assert market_state.data_completeness.available_modules == [
        "macro",
        "options",
        "technical",
        "positioning",
        "news",
        "market_odds",
    ]
    assert market_state.unavailable_modules == []
    assert market_state.input_snapshot_ids["analysis_snapshot"] == "XAUUSD:2026-05-14:market-state-test"
    assert market_state.input_snapshot_ids["options_detail"]["raw_file_sha256"] == "abc123"


def test_build_market_state_marks_missing_sections_unavailable() -> None:
    snapshot = build_analysis_snapshot(
        asset="XAUUSD",
        trade_date="2026-05-14",
        run_id="missing-state-test",
        macro_snapshot=_macro_snapshot(),
        options_snapshot=None,
        source_refs=[{"symbol": "DXY", "source": "tradingview"}],
        snapshot_time="2026-05-14T10:00:00+08:00",
    )
    snapshot.pop("technical")
    snapshot.pop("news")

    market_state = build_market_state(snapshot)

    assert market_state.options.status == "unavailable"
    assert market_state.options.reason == "input_not_available"
    assert market_state.technical.status == "unavailable"
    assert market_state.technical.reason == "section_missing"
    assert market_state.news.status == "unavailable"
    assert market_state.news.reason == "section_missing"
    assert market_state.data_completeness.available_count == 1
    assert market_state.data_completeness.unavailable_count == 5
    assert market_state.data_completeness.coverage_ratio == 0.167
    assert market_state.unavailable_modules == ["options", "technical", "positioning", "news", "market_odds"]


def test_build_market_state_does_not_mutate_snapshot() -> None:
    snapshot = _full_snapshot()
    market_state = build_market_state(snapshot)

    market_state.macro.data["indicators"]["DGS10"]["value"] = 99
    market_state.source_refs.append({"source": "new"})

    assert snapshot["macro"]["data"]["indicators"]["DGS10"]["value"] == 4.3
    assert {"source": "new"} not in snapshot["source_refs"]
