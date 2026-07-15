from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from apps.analysis.snapshots.builder import build_analysis_snapshot, write_analysis_snapshot


def _macro_snapshot() -> dict:
    return {
        "as_of": "2026-05-14",
        "indicators": {"DGS10": {"value": 4.3}},
        "source_refs": [
            {"symbol": "DGS10", "source": "fred", "source_url": "https://fred.example/DGS10"},
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


def test_analysis_snapshot_run_dir_rejects_unsafe_asset_and_trade_date(tmp_path: Path):
    from apps.analysis.snapshots.builder import analysis_snapshot_run_dir

    with pytest.raises(ValueError, match="asset"):
        analysis_snapshot_run_dir(tmp_path, asset="../XAUUSD", trade_date="2026-05-14", run_id="safe")
    with pytest.raises(ValueError, match="trade_date"):
        analysis_snapshot_run_dir(tmp_path, asset="XAUUSD", trade_date="../../escape", run_id="safe")


def test_build_available_macro_and_options_contains_required_fields():
    snapshot = build_analysis_snapshot(
        asset="XAUUSD",
        trade_date="2026-05-14",
        run_id="test-run",
        macro_snapshot=_macro_snapshot(),
        options_snapshot=_options_snapshot(),
        snapshot_time="2026-05-14T10:00:00+08:00",
    )

    assert snapshot["version"] == "1.0"
    assert snapshot["snapshot_id"] == "XAUUSD:2026-05-14:test-run"
    assert snapshot["asset"] == "XAUUSD"
    assert snapshot["trade_date"] == "2026-05-14"
    assert snapshot["snapshot_time"] == "2026-05-14T10:00:00+08:00"
    assert snapshot["run_id"] == "test-run"
    assert snapshot["macro"]["status"] == "available"
    assert snapshot["macro"]["data"]["indicators"]["DGS10"]["value"] == 4.3
    assert snapshot["options"]["status"] == "available"
    assert snapshot["options"]["data"]["wall_scores"][0]["strike"] == 3300
    assert snapshot["input_snapshot_ids"]["macro"] == "macro:2026-05-14:test-run"
    assert snapshot["input_snapshot_ids"]["options"] == "options:2026-05-14:test-run"
    assert snapshot["input_snapshot_ids"]["options_detail"] == {
        "raw_file_sha256": "abc123",
        "raw_file_id": "42",
    }
    assert snapshot["positioning"]["status"] == "unavailable"
    assert "no_cot_gold" in snapshot["positioning"].get("reason", "")
    assert snapshot["news"] == {"status": "unavailable", "reason": "no_news_collected_points"}
    assert snapshot["technical"]["status"] == "unavailable"
    assert "no_xauusd" in snapshot["technical"].get("reason", "")
    assert isinstance(snapshot["source_refs"], list)


def test_build_analysis_snapshot_carries_fixed_gold_analysis_context() -> None:
    context = {
        "status": "ready",
        "baseline_kind": "weekly_anchor",
        "analysis_baseline": {
            "source_kind": "weekly_context_revision",
            "trade_date": "2026-05-11",
            "article_id": "weekly-1",
            "executive_summary": "周报基准",
        },
        "freshness": {"analysis_baseline": {"status": "current"}, "market": {"status": "current"}},
        "input_snapshot_ids": {"analysis_baseline": "outputs/weekly.json", "premarket_snapshot": "features/pre.json"},
        "source_refs": [{"source": "jin10_external", "article_id": "weekly-1"}],
    }

    snapshot = build_analysis_snapshot(
        asset="XAUUSD",
        trade_date="2026-05-12",
        run_id="fixed-lineage",
        macro_snapshot=_macro_snapshot(),
        options_snapshot=_options_snapshot(),
        gold_analysis_context=context,
    )

    assert snapshot["gold_analysis_context"]["status"] == "available"
    assert snapshot["gold_analysis_context"]["data"]["baseline_kind"] == "weekly_anchor"
    assert snapshot["gold_analysis_context"]["data"]["analysis_baseline"]["article_id"] == "weekly-1"
    assert snapshot["input_snapshot_ids"]["gold_analysis_context"] == context["input_snapshot_ids"]
    assert any(ref.get("article_id") == "weekly-1" for ref in snapshot["source_refs"])


def test_build_technical_snapshot_uses_jin10_quote_ohlc() -> None:
    snapshot = build_analysis_snapshot(
        asset="XAUUSD",
        trade_date="2026-05-14",
        run_id="jin10-technical",
        macro_snapshot=None,
        options_snapshot=None,
        collected_points=[
            {
                "symbol": "XAUUSD",
                "date": "2026-05-14",
                "value": 3300.0,
                "source": "jin10_quote",
            }
        ],
        source_refs=[
            {
                "symbol": "XAUUSD",
                "source": "jin10_quote",
                "source_url": "https://mcp.jin10.com/mcp",
                "raw_path": "raw/technical/jin10_quote/2026-05-14/XAUUSD.json",
                "notes": {"open": 3280.0, "high": 3320.0, "low": 3270.0},
            }
        ],
    )

    assert snapshot["technical"]["status"] == "available"
    assert snapshot["technical"]["data"]["price"] == 3300.0
    assert snapshot["technical"]["data"]["atr14"] == 50.0
    assert snapshot["technical"]["data"]["source_refs"][0]["source"] == "jin10_quote"


@pytest.mark.parametrize("macro_snapshot, options_snapshot", [(None, None), (_macro_snapshot(), None), (None, _options_snapshot())])
def test_build_marks_missing_macro_or_options_unavailable(macro_snapshot, options_snapshot):
    snapshot = build_analysis_snapshot(
        asset="XAUUSD",
        trade_date="2026-05-14",
        run_id="missing-test",
        macro_snapshot=macro_snapshot,
        options_snapshot=options_snapshot,
        snapshot_time="2026-05-14T10:00:00+08:00",
    )

    expected_macro_status = "available" if macro_snapshot is not None else "unavailable"
    expected_options_status = "available" if options_snapshot is not None else "unavailable"
    assert snapshot["macro"]["status"] == expected_macro_status
    assert snapshot["options"]["status"] == expected_options_status
    if macro_snapshot is None:
        assert "data" not in snapshot["macro"]
        assert snapshot["macro"]["reason"] == "input_not_available"
    if options_snapshot is None:
        assert "data" not in snapshot["options"]
        assert snapshot["options"]["reason"] == "input_not_available"


def test_build_marks_empty_macro_snapshot_unavailable() -> None:
    snapshot = build_analysis_snapshot(
        asset="XAUUSD",
        trade_date="2026-07-21",
        run_id="empty-macro",
        macro_snapshot={
            "as_of": "2026-07-21",
            "indicators": {},
            "unavailable_symbols": ["DGS10", "DXY"],
            "source_refs": {"DGS10": {"source": "fred", "reason": "network failed"}},
        },
        options_snapshot=_options_snapshot(),
    )

    assert snapshot["macro"] == {
        "status": "unavailable",
        "reason": "no_macro_indicators",
        "analysis_context_date": "2026-07-21",
        "unavailable_symbols": ["DGS10", "DXY"],
    }


def test_build_merges_and_deduplicates_source_refs():
    snapshot = build_analysis_snapshot(
        asset="XAUUSD",
        trade_date="2026-05-14",
        run_id="source-ref-test",
        macro_snapshot=_macro_snapshot(),
        options_snapshot=None,
        source_refs=[
            {"symbol": "DGS10", "source": "fred", "source_url": "https://fred.example/DGS10"},
            {"symbol": "DXY", "source": "tradingview"},
        ],
        snapshot_time="2026-05-14T10:00:00+08:00",
    )

    assert len(snapshot["source_refs"]) == 2
    assert {tuple(sorted(ref.items())) for ref in snapshot["source_refs"]} == {
        tuple(sorted({"symbol": "DXY", "source": "tradingview"}.items())),
        tuple(sorted({"symbol": "DGS10", "source": "fred", "source_url": "https://fred.example/DGS10"}.items())),
    }


def test_write_analysis_snapshot_writes_non_empty_json_to_exact_path(tmp_path: Path):
    snapshot = build_analysis_snapshot(
        asset="XAUUSD",
        trade_date="2026-05-14",
        run_id="write-test",
        macro_snapshot=_macro_snapshot(),
        options_snapshot=_options_snapshot(),
        snapshot_time="2026-05-14T10:00:00+08:00",
    )

    path = write_analysis_snapshot(snapshot, storage_root=tmp_path)

    assert path == tmp_path / "features" / "snapshots" / "XAUUSD" / "2026-05-14" / "write-test" / "premarket_snapshot.json"
    assert path.exists()
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["snapshot_id"] == "XAUUSD:2026-05-14:write-test"


def test_write_analysis_snapshot_rejects_unsafe_run_id(tmp_path: Path):
    snapshot = build_analysis_snapshot(
        asset="XAUUSD",
        trade_date="2026-05-14",
        run_id="../escape",
        macro_snapshot=None,
        options_snapshot=None,
        snapshot_time="2026-05-14T10:00:00+08:00",
    )

    with pytest.raises(ValueError, match="run_id"):
        write_analysis_snapshot(snapshot, storage_root=tmp_path)


def test_build_does_not_mutate_input_dictionaries():
    macro = _macro_snapshot()
    options = _options_snapshot()
    source_refs = [{"symbol": "DXY", "source": "tradingview"}]
    macro_before = copy.deepcopy(macro)
    options_before = copy.deepcopy(options)
    source_refs_before = copy.deepcopy(source_refs)

    snapshot = build_analysis_snapshot(
        asset="XAUUSD",
        trade_date="2026-05-14",
        run_id="immutability-test",
        macro_snapshot=macro,
        options_snapshot=options,
        source_refs=source_refs,
        snapshot_time="2026-05-14T10:00:00+08:00",
    )

    snapshot["macro"]["data"]["indicators"]["DGS10"]["value"] = 99
    snapshot["options"]["data"]["data_source"]["input_snapshot_ids"]["raw_file_id"] = "changed"
    snapshot["source_refs"].append({"symbol": "NEW"})

    assert macro == macro_before
    assert options == options_before
    assert source_refs == source_refs_before


def test_build_rejects_macro_and_options_observations_after_trade_date():
    macro = _macro_snapshot()
    macro["indicators"]["DGS10"]["date"] = "2026-05-16"
    options = _options_snapshot()
    options["trade_date"] = "2026-05-15"

    snapshot = build_analysis_snapshot(
        asset="XAUUSD",
        trade_date="2026-05-14",
        run_id="point-in-time-test",
        macro_snapshot=macro,
        options_snapshot=options,
        snapshot_time="2026-05-16T10:00:00+08:00",
    )

    assert snapshot["macro"]["status"] == "unavailable"
    assert snapshot["macro"]["reason"] == "future_dated_input"
    assert snapshot["macro"]["analysis_context_date"] == "2026-05-14"
    assert snapshot["macro"]["future_observations"] == [
        {"field": "indicators.DGS10.date", "date": "2026-05-16"}
    ]
    assert snapshot["options"]["status"] == "unavailable"
    assert snapshot["options"]["reason"] == "future_dated_input"
    assert snapshot["market_odds"]["status"] == "unavailable"
    assert snapshot["market_odds"]["reason"] == "future_dated_input"
    assert snapshot["market_odds"]["future_observations"] == [
        {"field": "trade_date", "date": "2026-05-15"}
    ]


def test_build_excludes_future_market_points_but_keeps_upcoming_news_events():
    points = [
        {
            "symbol": "XAUUSD",
            "date": "2026-05-15",
            "value": 3300,
            "source": "yahoo_finance",
            "source_url": "https://example.test/xau",
            "raw_path": "raw/xau.json",
        },
        {
            "symbol": "COT_GOLD_commercial_net",
            "date": "2026-05-15",
            "value": -200_000,
            "source": "cftc",
            "source_url": "https://example.test/cot",
            "raw_path": "raw/cot.json",
        },
        {
            "symbol": "NEWS_EVENT:US CPI",
            "date": "2026-05-15",
            "value": 1,
            "source": "calendar",
            "source_url": "https://example.test/calendar",
            "raw_path": "raw/calendar.json",
        },
        {
            "symbol": "NEWS_FLASH",
            "date": "2026-05-13",
            "value": 1,
            "source": "jin10_mcp",
            "source_url": "https://example.test/flash-old",
            "raw_path": "raw/flash-old.json",
        },
        {
            "symbol": "NEWS_FLASH",
            "date": "2026-05-15",
            "value": 1,
            "source": "jin10_mcp",
            "source_url": "https://example.test/flash-future",
            "raw_path": "raw/flash-future.json",
        },
        {
            "symbol": "QUOTE:DXY",
            "date": "2026-05-13",
            "value": 100.5,
            "source": "jin10_mcp",
            "source_url": "https://example.test/dxy-old",
            "raw_path": "raw/dxy-old.json",
        },
        {
            "symbol": "QUOTE:XAUUSD",
            "date": "2026-05-15",
            "value": 3300,
            "source": "jin10_mcp",
            "source_url": "https://example.test/xau-future",
            "raw_path": "raw/xau-future.json",
        },
    ]

    snapshot = build_analysis_snapshot(
        asset="XAUUSD",
        trade_date="2026-05-14",
        run_id="future-points-test",
        macro_snapshot=None,
        options_snapshot=None,
        collected_points=points,
    )

    assert snapshot["technical"]["status"] == "unavailable"
    assert snapshot["positioning"]["status"] == "unavailable"
    assert snapshot["news"]["status"] == "available"
    assert [event["title"] for event in snapshot["news"]["data"]["recent_events"]] == ["US CPI"]
    assert [flash["url"] for flash in snapshot["news"]["data"]["recent_flashes"]] == [
        "https://example.test/flash-old"
    ]
    assert set(snapshot["jin10"]["quotes"]) == {"DXY"}
    assert snapshot["jin10"]["counts"]["flash_news"] == 1
    assert snapshot["jin10"]["counts"]["calendar_events"] == 1


def test_build_rejects_future_nested_news_snapshot_anchor() -> None:
    snapshot = build_analysis_snapshot(
        asset="XAUUSD",
        trade_date="2026-05-14",
        run_id="future-news-test",
        macro_snapshot=None,
        options_snapshot=None,
        news_snapshot={
            "daily_market_brief": {
                "as_of": "2026-05-15T08:00:00+00:00",
                "next_7d_calendar": [
                    {"event_time": "2026-05-20T12:00:00+00:00", "title": "FOMC"}
                ],
            }
        },
    )

    assert snapshot["news"] == {
        "status": "unavailable",
        "reason": "future_dated_input",
        "analysis_context_date": "2026-05-14",
        "future_observations": [
            {"field": "daily_market_brief.as_of", "date": "2026-05-15"}
        ],
    }
