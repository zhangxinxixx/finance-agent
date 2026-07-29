from __future__ import annotations

import copy
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from apps.analysis.snapshots.builder import build_analysis_snapshot, write_analysis_snapshot
from apps.analysis.gold_policy.feature_adapter import (
    build_feature_snapshot_from_analysis_snapshot,
)
from apps.features.market_data.formal_snapshots import (
    build_market_price_snapshot,
    build_oil_snapshot,
)
from apps.features.news.formal_events import build_official_event_snapshot


_FORMAL_AS_OF = datetime(2026, 5, 14, 10, 0, tzinfo=UTC)


def _formal_bar(
    *, asset: str, timeframe: str, source: str, source_ref: dict[str, str], open_time: datetime, price: float
) -> dict[str, object]:
    duration = timedelta(minutes=5) if timeframe == "5m" else timedelta(days=1)
    return {
        "asset": asset,
        "timeframe": timeframe,
        "source": source,
        "source_ref": source_ref,
        "open_time": open_time,
        "close_time": open_time + duration,
        "open": price,
        "high": price + 2,
        "low": price - 1,
        "close": price + 1,
        "retrieved_at": (open_time + duration).isoformat(),
        "raw_path": f"raw/{asset}/{source}.json",
    }


def _formal_market_snapshots():
    market = build_market_price_snapshot(
        candidates=[
            _formal_bar(
                asset="XAUUSD", timeframe="5m", source="jin10_mcp_derived_5m",
                source_ref={"provider_symbol": "XAUUSD", "instrument_type": "otc_spot_quote_proxy", "source_role": "market_primary", "reference": "market://xau"},
                open_time=_FORMAL_AS_OF - timedelta(minutes=10), price=2400,
            ),
            _formal_bar(
                asset="GC", timeframe="1d", source="yahoo_finance_gc_f",
                source_ref={"provider_symbol": "GC=F", "instrument_type": "futures_continuous_proxy", "source_role": "market_primary", "reference": "market://gc"},
                open_time=_FORMAL_AS_OF - timedelta(days=2), price=2410,
            ),
        ],
        as_of=_FORMAL_AS_OF,
    )
    oil = build_oil_snapshot(
        candidates=[
            _formal_bar(
                asset=asset, timeframe="1d", source="ice_settlement",
                source_ref={"provider_symbol": asset, "instrument_type": "spot", "source_role": "oil_primary", "reference": f"market://{asset.lower()}"},
                open_time=_FORMAL_AS_OF - timedelta(days=2), price=75,
            )
            for asset in ("WTI", "BRENT")
        ],
        as_of=_FORMAL_AS_OF,
    )
    return market, oil


def _cot_point(**overrides: object) -> dict[str, object]:
    point: dict[str, object] = {
        "symbol": "COT_GOLD_noncomm_net",
        "date": "2026-05-12",
        "value": 178_500,
        "source": "cftc",
        "source_url": "https://www.cftc.gov/files/dea/history/fut_disagg_txt_2026.zip",
        "raw_path": "raw/cftc/2026/fut_disagg_txt_2026.zip",
        "retrieved_at": "2026-05-14T09:30:00+00:00",
    }
    point.update(overrides)
    return point


def _official_news_snapshot(*, as_of: datetime = _FORMAL_AS_OF) -> dict[str, object]:
    event_time = as_of - timedelta(hours=1)
    official_ref = {
        "source": "federal_reserve",
        "source_type": "official",
        "reference": "https://www.federalreserve.gov/release",
        "raw_path": "raw/news/fed-release.json",
        "retrieved_at": (event_time + timedelta(minutes=1)).isoformat(),
    }
    baseline_time = event_time - timedelta(minutes=1)
    after_time = event_time + timedelta(minutes=30)
    candle_refs = {
        role: {
            "role": role,
            "asset": "XAUUSD",
            "timeframe": "1m",
            "open_time": open_time.isoformat(),
            "source": "twelve_data",
            "reference": f"market://xauusd/{role}",
            "retrieved_at": (event_time + timedelta(minutes=31)).isoformat(),
            "retrieval_basis": "source_ref.retrieved_at",
        }
        for role, open_time in (("baseline", baseline_time), ("after", after_time))
    }
    formal = build_official_event_snapshot(
        candidates=[
            {
                "event_id": "fed-release",
                "event_type": "fomc_statement",
                "event_time": event_time.isoformat(),
                "event_status": "occurred",
                "verification_status": "official_confirmed",
                "source_refs": [official_ref],
            }
        ],
        reactions=[
            {
                "event_id": "fed-release",
                "status": "available",
                "windows": {
                    "30m": {
                        "XAUUSD": {
                            "baseline_time": baseline_time.isoformat(),
                            "after_time": after_time.isoformat(),
                            "pct_change": 0.42,
                            "threshold_hit": True,
                            "baseline_candle_refs": [candle_refs["baseline"]],
                            "after_candle_refs": [candle_refs["after"]],
                        }
                    }
                },
            }
        ],
        as_of=as_of,
    )
    return {
        "official_events": {
            "status": "available",
            "data": formal.model_dump(mode="json"),
        }
    }


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
    assert snapshot["market_prices"] == {
        "status": "unavailable", "reason": "market_prices_not_provided"
    }
    assert snapshot["oil"] == {"status": "unavailable", "reason": "oil_not_provided"}
    assert snapshot["official_events"] == {
        "status": "unavailable",
        "reason": "official_event_snapshot_not_provided",
    }


def test_build_materializes_exact_official_event_contract_with_content_lineage() -> None:
    news_snapshot = _official_news_snapshot()
    before = copy.deepcopy(news_snapshot)

    snapshot = build_analysis_snapshot(
        asset="XAUUSD",
        trade_date="2026-05-14",
        run_id="formal-events",
        macro_snapshot=None,
        options_snapshot=None,
        snapshot_time=_FORMAL_AS_OF.isoformat(),
        news_snapshot=news_snapshot,
    )

    assert snapshot["official_events"] == news_snapshot["official_events"]
    assert snapshot["input_snapshot_ids"]["official_events"].startswith(
        "official_event_snapshot.v1:"
    )
    assert any(
        ref.get("reference") == "https://www.federalreserve.gov/release"
        for ref in snapshot["source_refs"]
    )
    feature_snapshot = build_feature_snapshot_from_analysis_snapshot(snapshot)
    assert feature_snapshot.official_events.events[0].reaction_status == "confirmed"
    assert feature_snapshot.official_events.events[0].reaction_asset == "XAUUSD"
    assert news_snapshot == before


def test_formal_official_event_wrong_version_or_future_lineage_is_unavailable() -> None:
    wrong_version = _official_news_snapshot()
    wrong_version["official_events"]["data"]["schema_version"] = "official_event_snapshot.v0"  # type: ignore[index]
    future_lineage = _official_news_snapshot()
    future_lineage["official_events"]["data"]["source_refs"][0]["retrieved_at"] = (  # type: ignore[index]
        _FORMAL_AS_OF + timedelta(minutes=1)
    ).isoformat()

    wrong = build_analysis_snapshot(
        asset="XAUUSD", trade_date="2026-05-14", run_id="wrong-events",
        macro_snapshot=None, options_snapshot=None, snapshot_time=_FORMAL_AS_OF.isoformat(),
        news_snapshot=wrong_version,
    )
    future = build_analysis_snapshot(
        asset="XAUUSD", trade_date="2026-05-14", run_id="future-events",
        macro_snapshot=None, options_snapshot=None, snapshot_time=_FORMAL_AS_OF.isoformat(),
        news_snapshot=future_lineage,
    )

    assert wrong["official_events"]["reason"] == "official_event_snapshot_invalid_or_unsupported"
    assert "official_events" not in wrong["input_snapshot_ids"]
    assert future["official_events"]["reason"] == "official_event_snapshot_future_or_misaligned"
    assert future["official_events"]["alignment_status"] == "misaligned"


def test_build_materializes_formal_market_and_oil_sections_with_content_addressed_lineage() -> None:
    market, oil = _formal_market_snapshots()
    snapshot = build_analysis_snapshot(
        asset="XAUUSD", trade_date="2026-05-14", run_id="formal-sections",
        macro_snapshot=None, options_snapshot=None,
        snapshot_time=_FORMAL_AS_OF.isoformat(), market_price_snapshot=market, oil_snapshot=oil,
    )

    assert snapshot["market_prices"]["status"] == "available"
    assert snapshot["market_prices"]["data"] == market.model_dump(mode="json")
    assert snapshot["oil"]["data"] == oil.model_dump(mode="json")
    assert snapshot["input_snapshot_ids"]["market_prices"].startswith("market_price_snapshot.v1:")
    assert snapshot["input_snapshot_ids"]["oil"].startswith("oil_snapshot.v1:")
    assert {ref["reference"] for ref in snapshot["source_refs"] if "reference" in ref} >= {
        "market://xau", "market://gc", "market://wti", "market://brent"
    }


def test_formal_snapshot_missing_query_refs_are_kept_in_lineage() -> None:
    oil = build_oil_snapshot(candidates=[], as_of=_FORMAL_AS_OF)
    snapshot = build_analysis_snapshot(
        asset="XAUUSD", trade_date="2026-05-14", run_id="missing-oil",
        macro_snapshot=None, options_snapshot=None, snapshot_time=_FORMAL_AS_OF.isoformat(), oil_snapshot=oil,
    )
    assert snapshot["oil"]["status"] == "available"
    assert {ref["reference"] for ref in snapshot["source_refs"] if "reference" in ref} >= {
        "query://WTI/1d", "query://BRENT/1d"
    }


def test_formal_snapshot_future_as_of_or_retrieval_is_misaligned() -> None:
    market, oil = _formal_market_snapshots()
    future_market = market.model_copy(update={"as_of": _FORMAL_AS_OF + timedelta(minutes=1)})
    future_ref = oil.wti.source_refs[0].model_copy(update={"retrieved_at": _FORMAL_AS_OF + timedelta(minutes=1)})
    future_wti = oil.wti.model_copy(update={"source_refs": (future_ref,)})
    future_oil = oil.model_copy(update={"wti": future_wti})
    snapshot = build_analysis_snapshot(
        asset="XAUUSD", trade_date="2026-05-14", run_id="future-formal",
        macro_snapshot=None, options_snapshot=None, snapshot_time=_FORMAL_AS_OF.isoformat(),
        market_price_snapshot=future_market, oil_snapshot=future_oil,
    )
    assert snapshot["market_prices"]["status"] == "unavailable"
    assert snapshot["market_prices"]["alignment_status"] == "misaligned"
    assert snapshot["oil"]["status"] == "unavailable"
    assert any(item["field"].endswith("retrieved_at") for item in snapshot["oil"]["future_observations"])


def test_formal_content_ids_are_stable_sensitive_and_inputs_immutable() -> None:
    market, oil = _formal_market_snapshots()
    before_market = market.model_dump(mode="json")
    before_oil = oil.model_dump(mode="json")
    snapshots = [
        build_analysis_snapshot(
            asset="XAUUSD", trade_date="2026-05-14", run_id="stable-formal",
            macro_snapshot=None, options_snapshot=None, snapshot_time=_FORMAL_AS_OF.isoformat(),
            market_price_snapshot=market, oil_snapshot=oil,
        )
        for _ in range(100)
    ]
    ids = [item["input_snapshot_ids"] for item in snapshots]
    assert len({json.dumps(item, sort_keys=True) for item in ids}) == 1
    changed_market = market.model_copy(
        update={"xauusd_spot": market.xauusd_spot.model_copy(update={"value": 2402.0, "close": 2402.0})}
    )
    changed = build_analysis_snapshot(
        asset="XAUUSD", trade_date="2026-05-14", run_id="stable-formal",
        macro_snapshot=None, options_snapshot=None, snapshot_time=_FORMAL_AS_OF.isoformat(),
        market_price_snapshot=changed_market, oil_snapshot=oil,
    )
    assert changed["input_snapshot_ids"]["market_prices"] != ids[0]["market_prices"]
    changed_oil = oil.model_copy(
        update={"brent": oil.brent.model_copy(update={"value": 77.0, "close": 77.0})}
    )
    changed = build_analysis_snapshot(
        asset="XAUUSD", trade_date="2026-05-14", run_id="stable-formal",
        macro_snapshot=None, options_snapshot=None, snapshot_time=_FORMAL_AS_OF.isoformat(),
        market_price_snapshot=market, oil_snapshot=changed_oil,
    )
    assert changed["input_snapshot_ids"]["oil"] != ids[0]["oil"]
    assert market.model_dump(mode="json") == before_market
    assert oil.model_dump(mode="json") == before_oil


def test_build_materializes_formal_cot_without_replacing_legacy_positioning() -> None:
    snapshot = build_analysis_snapshot(
        asset="XAUUSD", trade_date="2026-05-14", run_id="formal-cot",
        macro_snapshot=None, options_snapshot=None, snapshot_time=_FORMAL_AS_OF.isoformat(),
        collected_points=[_cot_point()],
    )

    assert snapshot["cot"]["status"] == "available"
    cot = snapshot["cot"]["data"]
    assert cot["schema_version"] == "cot_snapshot.v1"
    assert cot["readiness"] == "ready"
    assert cot["managed_money_net"]["value"] == 178_500.0
    assert snapshot["input_snapshot_ids"]["cot"].startswith("cot_snapshot.v1:")
    # The legacy builder keeps its prior component requirements; formal COT
    # must not replace or reinterpret that independent section.
    assert snapshot["positioning"]["status"] == "unavailable"
    assert snapshot["positioning"]["data"].get("schema_version") != "cot_snapshot.v1"
    assert any(
        ref.get("reference") == "https://www.cftc.gov/files/dea/history/fut_disagg_txt_2026.zip"
        for ref in snapshot["source_refs"]
    )


def test_formal_cot_keeps_future_retrieval_candidate_as_blocked_lineage() -> None:
    snapshot = build_analysis_snapshot(
        asset="XAUUSD", trade_date="2026-05-14", run_id="future-cot",
        macro_snapshot=None, options_snapshot=None, snapshot_time=_FORMAL_AS_OF.isoformat(),
        collected_points=[_cot_point(retrieved_at="2026-05-14T10:01:00+00:00")],
    )

    assert snapshot["cot"]["status"] == "available"
    cot = snapshot["cot"]["data"]
    assert cot["readiness"] == "blocked"
    ref = cot["managed_money_net"]["source_refs"][0]
    assert ref["qualification_reason"] == "retrieval_time_after_as_of"
    assert ref["reference"] == "https://www.cftc.gov/files/dea/history/fut_disagg_txt_2026.zip"
    assert snapshot["input_snapshot_ids"]["cot"].startswith("cot_snapshot.v1:")


def test_formal_cot_empty_input_is_blocked_with_query_lineage() -> None:
    snapshot = build_analysis_snapshot(
        asset="XAUUSD", trade_date="2026-05-14", run_id="empty-cot",
        macro_snapshot=None, options_snapshot=None, snapshot_time=_FORMAL_AS_OF.isoformat(),
    )

    assert snapshot["cot"]["status"] == "available"
    cot = snapshot["cot"]["data"]
    assert cot["readiness"] == "blocked"
    assert cot["managed_money_net"]["source_refs"][0]["reference"] == "query://COT_GOLD/noncomm_net"
    assert any(ref.get("reference") == "query://COT_GOLD/noncomm_net" for ref in snapshot["source_refs"])


def test_formal_cot_content_id_is_stable_sensitive_and_inputs_immutable() -> None:
    points = [_cot_point()]
    before = copy.deepcopy(points)
    snapshots = [
        build_analysis_snapshot(
            asset="XAUUSD", trade_date="2026-05-14", run_id="stable-cot",
            macro_snapshot=None, options_snapshot=None, snapshot_time=_FORMAL_AS_OF.isoformat(),
            collected_points=points,
        )
        for _ in range(100)
    ]
    assert len({item["input_snapshot_ids"]["cot"] for item in snapshots}) == 1
    changed = build_analysis_snapshot(
        asset="XAUUSD", trade_date="2026-05-14", run_id="stable-cot",
        macro_snapshot=None, options_snapshot=None, snapshot_time=_FORMAL_AS_OF.isoformat(),
        collected_points=[_cot_point(value=178_501)],
    )
    assert changed["input_snapshot_ids"]["cot"] != snapshots[0]["input_snapshot_ids"]["cot"]
    assert points == before


def test_formal_cot_invalid_snapshot_time_is_unavailable_and_misaligned() -> None:
    snapshot = build_analysis_snapshot(
        asset="XAUUSD", trade_date="2026-05-14", run_id="invalid-cot-time",
        macro_snapshot=None, options_snapshot=None, snapshot_time="not-a-time",
        collected_points=[_cot_point()],
    )

    assert snapshot["cot"] == {
        "status": "unavailable",
        "reason": "snapshot_time_invalid",
        "alignment_status": "misaligned",
    }
    assert "cot" not in snapshot["input_snapshot_ids"]


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

    assert len(snapshot["source_refs"]) == 3
    assert {tuple(sorted(ref.items())) for ref in snapshot["source_refs"]} == {
        tuple(sorted({
            "source": "cot_snapshot_query",
            "reference": "query://COT_GOLD/noncomm_net",
            "retrieved_at": "2026-05-14T02:00:00Z",
            "raw_path": None,
            "qualification_reason": "no_eligible_cot_candidate",
        }.items())),
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
