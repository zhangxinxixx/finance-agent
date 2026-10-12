from __future__ import annotations

import copy

import pytest

from apps.analysis.gold_policy.feature_adapter import build_feature_snapshot_from_analysis_snapshot


def _ref(symbol: str) -> dict[str, str]:
    return {"symbol": symbol, "source": "fred", "source_url": f"https://example.test/{symbol}", "retrieved_at": "2025-01-17T21:05:00Z"}


def _snapshot() -> dict:
    indicators = {key: {"value": value, "date": "2025-01-17T21:00:00Z", "source_refs": [_ref(key)]} for key, value in {"US02Y": 4.22, "US10Y": 4.61, "US30Y": 4.86, "T10YIE": 2.37, "REAL10Y": 2.24, "BROAD_DOLLAR": 121.2}.items()}
    return {
        "snapshot_id": "XAUUSD:2025-01-17:test", "asset": "XAUUSD", "snapshot_time": "2025-01-17T21:05:00Z",
        "technical": {"status": "available", "data": {"price": 2702.4, "date": "2025-01-17T21:00:00Z", "source_refs": [{"symbol": "XAUUSD", "source": "twelve_data", "source_url": "https://example.test/xau"}]}},
        "macro": {"status": "available", "data": {"indicators": indicators}},
        "official_events": _formal_official_events(),
    }


def _complete_snapshot() -> dict:
    snapshot = _snapshot()
    for section, field, value in (
        ("futures", "gc_futures", 2710.0),
        ("oil", "wti", 77.0),
        ("etf_flow", "etf_flow", 1.5),
        ("positioning", "cot", 183_000),
        ("options", "cme_options_regime", 0.7),
    ):
        snapshot[section] = {"status": "available", "data": {field: {"value": value, "date": "2025-01-17T21:00:00Z", "source_refs": [_ref(field)]}}}
    snapshot["oil"]["data"]["brent"] = {"value": 80.0, "date": "2025-01-17T21:00:00Z", "source_refs": [_ref("brent")]}
    return _with_formal_market_sections(snapshot)


def _formal_ref(name: str) -> dict[str, str]:
    return {"source": "formal_fixture", "reference": f"formal://{name}", "retrieved_at": "2025-01-17T21:00:00Z"}


def _treasury_ref(symbol: str = "DGS10") -> dict[str, str]:
    curve, curve_type = {
        "DGS2": ("nominal", "daily_treasury_yield_curve"),
        "DGS10": ("nominal", "daily_treasury_yield_curve"),
        "DGS30": ("nominal", "daily_treasury_yield_curve"),
        "DFII10": ("real", "daily_treasury_real_yield_curve"),
    }[symbol]
    return {
        "symbol": symbol,
        "source": "treasury_rates",
        "source_url": (
            "https://home.treasury.gov/resource-center/data-chart-center/"
            "interest-rates/daily-treasury-rates.csv/2025/all"
            f"?_format=csv&field_tdr_date_value=2025&page=&type={curve_type}"
        ),
        "raw_path": (
            f"raw/macro/treasury_rates/2025-01-17/{curve}-2025-"
            "20250117T210000000000Z-0123456789ab.csv"
        ),
        "retrieved_at": "2025-01-17T21:00:00Z",
    }


def _formal_official_events() -> dict:
    official_ref = {
        "source": "federal_reserve",
        "source_type": "official",
        "reference": "https://www.federalreserve.gov/release",
        "raw_path": "raw/news/fed-release.json",
        "retrieved_at": "2025-01-17T20:00:00Z",
    }
    baseline_ref = {
        "role": "baseline",
        "asset": "XAUUSD",
        "timeframe": "1m",
        "open_time": "2025-01-17T19:59:00Z",
        "source": "twelve_data",
        "reference": "market://xauusd/baseline",
        "retrieved_at": "2025-01-17T20:31:00Z",
        "retrieval_basis": "source_ref.retrieved_at",
    }
    after_ref = {
        "role": "after",
        "asset": "XAUUSD",
        "timeframe": "1m",
        "open_time": "2025-01-17T20:30:00Z",
        "source": "twelve_data",
        "reference": "market://xauusd/after",
        "retrieved_at": "2025-01-17T20:31:00Z",
        "retrieval_basis": "source_ref.retrieved_at",
    }
    return {
        "status": "available",
        "data": {
            "schema_version": "official_event_snapshot.v1",
            "as_of": "2025-01-17T20:31:00Z",
            "readiness": "ready",
            "freshness_status": "fresh",
            "quality_status": "accepted",
            "alignment_status": "aligned",
            "events": [
                {
                    "event_id": "fed-20250117",
                    "title": "Federal Reserve release",
                    "occurred_at": "2025-01-17T20:00:00Z",
                    "reaction_baseline_time": "2025-01-17T19:59:00Z",
                    "reaction_after_time": "2025-01-17T20:30:00Z",
                    "reaction_window_end": "2025-01-17T20:30:00Z",
                    "reaction_summary": "XAUUSD 30m reaction +0.4200%",
                    "reaction_asset": "XAUUSD",
                    "reaction_return_pct": 0.42,
                    "reaction_status": "confirmed",
                    "source_refs": [official_ref],
                    "reaction_source_refs": [baseline_ref, after_ref],
                }
            ],
            "source_refs": [
                official_ref,
                {
                    key: value
                    for key, value in baseline_ref.items()
                    if key in {"source", "reference", "retrieved_at"}
                },
                {
                    key: value
                    for key, value in after_ref.items()
                    if key in {"source", "reference", "retrieved_at"}
                },
            ],
        },
    }


def _formal_observation(*, series_id: str, asset: str, market_role: str, timeframe: str, value: float, close_time: str = "2025-01-17T21:00:00Z", freshness: str = "fresh", quality: str = "accepted", alignment: str = "aligned") -> dict:
    return {"series_id": series_id, "asset": asset, "market_role": market_role, "timeframe": timeframe, "value": value, "close": value, "bar_open_time": "2025-01-17T20:55:00Z", "bar_close_time": close_time, "expected_frequency": timeframe, "freshness_status": freshness, "quality_status": quality, "alignment_status": alignment, "source_refs": [_formal_ref(series_id)]}


def _with_formal_market_sections(snapshot: dict) -> dict:
    snapshot["market_prices"] = {"status": "available", "data": {"schema_version": "market_price_snapshot.v1", "xauusd_spot": _formal_observation(series_id="XAUUSD_SPOT", asset="XAUUSD", market_role="spot", timeframe="5m", value=2711.0), "gc_futures": _formal_observation(series_id="GC_FUTURES", asset="GC", market_role="futures", timeframe="1d", value=2720.0)}}
    snapshot["oil"] = {"status": "available", "data": {"schema_version": "oil_snapshot.v1", "wti": _formal_observation(series_id="WTI", asset="WTI", market_role="oil", timeframe="1d", value=77.0), "brent": _formal_observation(series_id="BRENT", asset="BRENT", market_role="oil", timeframe="1d", value=80.0)}}
    return snapshot


def _formal_cot(*, value: float | None = 116_161.0, report_date: str | None = "2025-01-16", freshness: str = "fresh", quality: str = "accepted", alignment: str = "aligned", readiness: str = "ready") -> dict:
    return {"status": "available", "data": {"schema_version": "cot_snapshot.v1", "as_of": "2025-01-17T20:00:00Z", "readiness": readiness, "managed_money_net": {"series_id": "GOLD_COT", "metric_kind": "managed_money_net_contracts", "value": value, "unit": "contracts", "report_date": report_date, "expected_frequency": "weekly", "freshness_status": freshness, "quality_status": quality, "alignment_status": alignment, "source_refs": [{"source": "cftc", "reference": "https://www.cftc.gov/files/dea/history/fut_disagg_txt_2025.zip", "raw_path": "raw/cot.json", "retrieved_at": "2025-01-17T20:00:00Z", "qualification_reason": "eligible"}]}}}


def test_adapts_complete_canonical_structured_input() -> None:
    result = build_feature_snapshot_from_analysis_snapshot(_complete_snapshot())
    assert result.schema_version == "feature_snapshot.v2"
    assert result.readiness_policy_version == "gold_readiness_policy.v1"
    assert result.data_quality.readiness_policy_version == "gold_readiness_policy.v1"
    assert result.data_quality.analysis_readiness == "ready"
    assert result.data_quality.strategy_readiness == "ready"
    assert result.data_quality.options_readiness == "ready"
    assert result.data_quality.event_attribution_readiness == "ready"
    assert result.xauusd_spot.value == 2711.0
    assert result.real10y_direct.series_id == "DFII10"
    assert result.real10y_direct.market_role == "real_yield_direct"
    assert result.real10y_estimated.value == result.us10y.value - result.t10yie.value
    assert result.broad_dollar.series_id == "DTWEXBGS"
    assert result.us10y.source_refs[0].reference == "https://example.test/US10Y"
    assert result.official_events.events[0].reaction_status == "confirmed"
    assert result.official_events.events[0].reaction_asset == "XAUUSD"


def test_legacy_gaps_are_explicitly_blocked() -> None:
    result = build_feature_snapshot_from_analysis_snapshot(_snapshot())
    assert result.gc_futures.value is None
    assert result.gc_futures.freshness_status == "missing"
    assert result.gc_futures.quality_status == "blocked"


def test_formal_market_sections_are_authoritative_and_keep_quality_axes() -> None:
    snapshot = _with_formal_market_sections(_snapshot())
    snapshot["market_prices"]["data"]["xauusd_spot"].update(freshness_status="stale", quality_status="observe", alignment_status="unknown")
    result = build_feature_snapshot_from_analysis_snapshot(snapshot)

    assert result.xauusd_spot.value == 2711.0
    assert result.gc_futures.value == 2720.0
    assert result.wti.value == 77.0
    assert result.brent.value == 80.0
    assert (result.xauusd_spot.freshness_status, result.xauusd_spot.quality_status, result.xauusd_spot.alignment_status) == ("stale", "observe", "unknown")
    assert result.xauusd_spot.source_refs[0].reference == "formal://XAUUSD_SPOT"


def test_formal_missing_blocked_or_wrong_version_never_falls_back_to_legacy() -> None:
    snapshot = _with_formal_market_sections(_complete_snapshot())
    snapshot["market_prices"]["data"]["xauusd_spot"].update(value=None, close=None, freshness_status="missing", quality_status="blocked", alignment_status="unknown")
    snapshot["oil"]["data"]["schema_version"] = "oil_snapshot.v0"
    result = build_feature_snapshot_from_analysis_snapshot(snapshot)

    assert result.xauusd_spot.value is None
    assert result.xauusd_spot.quality_status == "blocked"
    assert result.wti.value is None
    assert result.brent.value is None


def test_formal_malformed_retrieval_future_and_gc_identity_fail_closed() -> None:
    snapshot = _with_formal_market_sections(_snapshot())
    spot = snapshot["market_prices"]["data"]["xauusd_spot"]
    spot["source_refs"][0].pop("retrieved_at")
    snapshot["market_prices"]["data"]["gc_futures"]["asset"] = "XAUUSD"
    snapshot["oil"]["data"]["wti"]["bar_close_time"] = "2025-01-18T21:00:00Z"
    result = build_feature_snapshot_from_analysis_snapshot(snapshot)

    assert result.xauusd_spot.value is None
    assert result.xauusd_spot.alignment_status == "misaligned"
    assert result.gc_futures.value is None
    assert result.wti.value is None
    assert result.wti.alignment_status == "misaligned"


def test_formal_future_retrieval_time_is_not_accepted() -> None:
    snapshot = _with_formal_market_sections(_snapshot())
    snapshot["oil"]["data"]["brent"]["source_refs"][0]["retrieved_at"] = "2025-01-18T21:00:00Z"
    result = build_feature_snapshot_from_analysis_snapshot(snapshot)

    assert result.brent.value is None
    assert result.brent.quality_status == "blocked"
    assert result.brent.alignment_status == "misaligned"


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), float("-inf")])
def test_formal_non_finite_values_fail_closed(invalid: float) -> None:
    snapshot = _with_formal_market_sections(_snapshot())
    snapshot["market_prices"]["data"]["xauusd_spot"].update(value=invalid, close=invalid)

    result = build_feature_snapshot_from_analysis_snapshot(snapshot)

    assert result.xauusd_spot.value is None
    assert result.xauusd_spot.quality_status == "blocked"
    assert result.xauusd_spot.alignment_status == "misaligned"


def test_formal_sections_are_stable_and_do_not_mutate_input() -> None:
    snapshot = _with_formal_market_sections(_snapshot())
    before = copy.deepcopy(snapshot)
    results = [build_feature_snapshot_from_analysis_snapshot(snapshot) for _ in range(100)]
    assert len({result.snapshot_id for result in results}) == 1
    assert snapshot == before


def test_formal_cot_is_authoritative_and_uses_report_date_at_utc_midnight() -> None:
    snapshot = _snapshot()
    snapshot["cot"] = _formal_cot()
    result = build_feature_snapshot_from_analysis_snapshot(snapshot)

    assert result.cot.value == 116_161.0
    assert result.cot.as_of.isoformat() == "2025-01-16T00:00:00+00:00"
    assert (result.cot.series_id, result.cot.market_role, result.cot.unit, result.cot.expected_frequency) == ("GOLD_COT", "positioning", "contracts", "weekly")
    assert result.cot.source_refs[0].reference.startswith("https://www.cftc.gov/")


def test_formal_cot_observe_missing_and_malformed_do_not_fallback_to_positioning() -> None:
    snapshot = _snapshot()
    snapshot["positioning"] = {"status": "available", "data": {"cot": {"value": 999_999, "source_refs": [_ref("legacy-cot")]}}}
    snapshot["cot"] = _formal_cot(freshness="stale", quality="observe", alignment="unknown", readiness="observe")
    result = build_feature_snapshot_from_analysis_snapshot(snapshot)
    assert (result.cot.value, result.cot.freshness_status, result.cot.quality_status, result.cot.alignment_status) == (116_161.0, "stale", "observe", "unknown")

    snapshot["cot"] = _formal_cot(value=None, report_date=None, freshness="missing", quality="blocked", alignment="unknown", readiness="blocked")
    result = build_feature_snapshot_from_analysis_snapshot(snapshot)
    assert result.cot.value is None
    assert result.cot.source_refs[0].reference.startswith("https://www.cftc.gov/")

    snapshot["cot"] = {"status": "available", "data": {"schema_version": "cot_snapshot.v0", "managed_money_net": {"value": 999_999}}}
    result = build_feature_snapshot_from_analysis_snapshot(snapshot)
    assert result.cot.value is None
    assert result.cot.quality_status == "blocked"


def test_formal_cot_future_nonfinite_and_source_retrieval_fail_closed_stably() -> None:
    snapshot = _snapshot()
    snapshot["cot"] = _formal_cot()
    snapshot["cot"]["data"]["managed_money_net"]["value"] = float("nan")
    snapshot["cot"]["data"]["managed_money_net"]["report_date"] = "2025-01-18"
    snapshot["cot"]["data"]["managed_money_net"]["source_refs"][0]["retrieved_at"] = "2025-01-18T20:00:00Z"
    before = copy.deepcopy(snapshot)
    results = [build_feature_snapshot_from_analysis_snapshot(snapshot) for _ in range(100)]

    assert results[0].cot.value is None
    assert results[0].cot.alignment_status == "misaligned"
    assert len({result.snapshot_id for result in results}) == 1
    assert snapshot == before


def test_formal_cot_requires_aware_snapshot_and_reference_timestamps() -> None:
    snapshot = _snapshot()
    snapshot["cot"] = _formal_cot()
    snapshot["cot"]["data"]["as_of"] = "2025-01-17T20:00:00"
    result = build_feature_snapshot_from_analysis_snapshot(snapshot)
    assert result.cot.value is None

    snapshot["cot"] = _formal_cot()
    snapshot["cot"]["data"]["managed_money_net"]["source_refs"][0].update(
        source="jin10",
        reference="https://example.test/cot.zip",
    )
    result = build_feature_snapshot_from_analysis_snapshot(snapshot)
    assert result.cot.value is None

    snapshot["cot"] = _formal_cot()
    snapshot["cot"]["data"]["managed_money_net"]["source_refs"][0]["retrieved_at"] = "2025-01-17T20:00:00"
    result = build_feature_snapshot_from_analysis_snapshot(snapshot)
    assert result.cot.value is None


def test_real_legacy_context_shapes_cannot_bypass_formal_input_contract() -> None:
    """Existing artifacts are structured, but are not v1 passports yet."""
    snapshot = _snapshot()
    snapshot.pop("official_events")
    snapshot["positioning"] = {
        "status": "available",
        "data": {
            "as_of": "2025-01-14",
            "commercial_net": -183_000,
            "noncomm_net": 201_000,
            "source_refs": [_ref("COT_GOLD_commercial_net")],
        },
    }
    snapshot["flow_context"] = {
        "as_of": "2025-01-17",
        "global_etf_flow": 5.7,
        "provider_role": "supplemental_source",
        "verification_status": "single_source",
        "source_refs": [_ref("gold-etf")],
    }
    snapshot["features"] = {"flow_context": dict(snapshot["flow_context"])}
    snapshot["options"] = {
        "status": "available",
        "data": {
            "data_source": {"status": "FINAL"},
            "gamma_summary": {"regime": "positive_gamma"},
            "wall_scores": [{"strike": 2700.0, "wall_score": 0.8}],
            "intent": {"score": 0.4, "type": "bullish"},
        },
    }
    snapshot["event_candidates"] = {
        "as_of": "2025-01-17T21:05:00Z",
        "event_candidates": [{
            "event_id": "fed-1", "event_time": "2025-01-17T19:00:00Z",
            "event_type": "fomc_statement", "verification_status": "official_confirmed",
            "source_refs": [_ref("fed-1")],
        }],
    }
    snapshot["market_reactions"] = {
        "market_reactions": [{
            "event_id": "fed-1", "status": "available",
            "windows": {"30m": {"XAUUSD": {"pct_change": 0.4}}},
        }],
    }

    result = build_feature_snapshot_from_analysis_snapshot(snapshot)

    for observation in (result.cot, result.etf_flow, result.cme_options_regime):
        assert observation.value is None
        assert observation.freshness_status == "missing"
        assert observation.quality_status == "blocked"
    assert result.official_events.events == ()
    assert result.official_events.freshness_status == "missing"
    assert result.official_events.quality_status == "blocked"


def test_dxy_and_computed_real_10y_do_not_substitute_canonical_inputs() -> None:
    snapshot = _snapshot()
    indicators = snapshot["macro"]["data"]["indicators"]
    indicators.pop("BROAD_DOLLAR")
    indicators["DXY"] = {"value": 108.0, "source_refs": [_ref("DXY")]}
    indicators.pop("REAL10Y")
    indicators["REAL_10Y"] = {"value": 2.2, "source_refs": [_ref("REAL_10Y")]}
    result = build_feature_snapshot_from_analysis_snapshot(snapshot)
    assert result.broad_dollar.value is None
    assert result.real10y_direct.value is None


def test_real10y_uses_exact_same_date_components_and_independent_fred_lineage() -> None:
    snapshot = _snapshot()
    snapshot["snapshot_time"] = "2025-01-21T21:05:00Z"
    macro = snapshot["macro"]["data"]
    macro["indicators"]["T10YIE"].update(value=2.38, date="2025-01-18")
    macro["indicators"]["REAL_10Y"] = {
        "derivation_version": "real10y_components.v1",
        "value": 2.24,
        "date": "2025-01-17",
        "components": [
            {"source_symbol": "DGS10", "date": "2025-01-17", "value": 4.61},
            {"source_symbol": "T10YIE", "date": "2025-01-17", "value": 2.37},
        ],
    }
    macro["source_refs"] = {
        "DGS10": {
            "source": "fred",
            "source_url": "https://api.stlouisfed.org/fred/series/observations?series_id=DGS10",
            "raw_path": "raw/macro/DGS10.json",
            "retrieved_at": "2025-01-20T20:00:00Z",
        },
        "T10YIE": {
            "source": "fred",
            "source_url": "https://api.stlouisfed.org/fred/series/observations?series_id=T10YIE",
            "raw_path": "raw/macro/T10YIE.json",
            "retrieved_at": "2025-01-20T20:00:00Z",
        },
    }

    result = build_feature_snapshot_from_analysis_snapshot(snapshot)

    assert result.us10y.as_of == result.t10yie.as_of
    assert result.us10y.as_of.isoformat() == "2025-01-17T00:00:00+00:00"
    assert (result.us10y.value, result.t10yie.value, result.real10y_estimated.value) == (
        4.61,
        2.37,
        2.24,
    )
    assert [ref.reference for ref in result.real10y_estimated.source_refs] == [
        "https://api.stlouisfed.org/fred/series/observations?series_id=DGS10",
        "https://api.stlouisfed.org/fred/series/observations?series_id=T10YIE",
    ]
    assert "REAL10Y_ESTIMATED_AVAILABLE" in result.real10y_reason_codes
    assert result.real10y_estimated.freshness_status == "stale"
    assert result.data_quality.analysis_readiness == "observe"


def test_macro_top_level_fred_refs_replace_analysis_snapshot_fallback_lineage() -> None:
    snapshot = _snapshot()
    macro = snapshot["macro"]["data"]
    macro["source_refs"] = {
        symbol: {
            "source": "fred",
            "source_url": (
                "https://api.stlouisfed.org/fred/series/observations"
                f"?series_id={symbol}"
            ),
            "raw_path": f"raw/macro/{symbol}.json",
            "retrieved_at": "2025-01-17T21:00:00Z",
        }
        for symbol in ("DGS2", "DGS10", "DGS30", "T10YIE", "DFII10", "DTWEXBGS")
    }
    # Historical FRED snapshots only required a non-empty raw_path; keep that
    # compatibility contract while Treasury uses its stricter archive layout.
    macro["source_refs"]["DGS10"]["raw_path"] = "legacy/fred-record"

    result = build_feature_snapshot_from_analysis_snapshot(snapshot)

    observations = (
        result.us02y,
        result.us10y,
        result.us30y,
        result.t10yie,
        result.real10y_direct,
        result.broad_dollar,
    )
    assert all(item.source_refs[0].source == "fred" for item in observations)
    assert all("api.stlouisfed.org" in item.source_refs[0].reference for item in observations)
    assert all(item.source_refs[0].source != "analysis_snapshot" for item in observations)


def test_macro_top_level_treasury_refs_use_the_official_curve_contract() -> None:
    snapshot = _snapshot()
    macro = snapshot["macro"]["data"]
    macro["source_refs"] = {
        "DGS2": _treasury_ref("DGS2"),
        "DGS10": _treasury_ref("DGS10"),
        "DGS30": _treasury_ref("DGS30"),
        "T10YIE": {
            "source": "fred",
            "source_url": "https://api.stlouisfed.org/fred/series/observations?series_id=T10YIE",
            "raw_path": "raw/macro/fred/2025-01-17/T10YIE-0123456789.json",
            "retrieved_at": "2025-01-17T21:00:00Z",
        },
        "DFII10": _treasury_ref("DFII10"),
        "DTWEXBGS": {
            "source": "fred",
            "source_url": "https://api.stlouisfed.org/fred/series/observations?series_id=DTWEXBGS",
            "raw_path": "raw/macro/fred/2025-01-17/DTWEXBGS-0123456789.json",
            "retrieved_at": "2025-01-17T21:00:00Z",
        },
    }

    result = build_feature_snapshot_from_analysis_snapshot(snapshot)

    assert result.us02y.source_refs[0].source == "treasury_rates"
    assert result.us10y.source_refs[0].source == "treasury_rates"
    assert result.us30y.source_refs[0].source == "treasury_rates"
    assert result.real10y_direct.source_refs[0].source == "treasury_rates"
    assert result.t10yie.source_refs[0].source == "fred"


@pytest.mark.parametrize("archive_seconds,cross_midnight", ((0, False), (6, False), (6, True)))
def test_real10y_accepts_treasury_nominal_and_fred_breakeven_lineage(
    archive_seconds: int, cross_midnight: bool,
) -> None:
    snapshot = _snapshot()
    macro = snapshot["macro"]["data"]
    macro["indicators"]["REAL_10Y"] = {
        "derivation_version": "real10y_components.v1",
        "value": 2.24,
        "date": "2025-01-17",
        "components": [
            {"source_symbol": "DGS10", "date": "2025-01-17", "value": 4.61},
            {"source_symbol": "T10YIE", "date": "2025-01-17", "value": 2.37},
        ],
    }
    macro["source_refs"] = {
        "DGS10": _treasury_ref("DGS10"),
        "T10YIE": {
            "source": "fred",
            "source_url": "https://api.stlouisfed.org/fred/series/observations?series_id=T10YIE",
            "raw_path": "raw/macro/fred/2025-01-17/T10YIE-0123456789.json",
            "retrieved_at": "2025-01-17T21:00:00Z",
        },
    }
    # Production retrieved_at marks request start; archival follows the HTTP
    # response. Both must precede the snapshot, but need not be equal.
    macro["source_refs"]["DGS10"]["raw_path"] = macro["source_refs"]["DGS10"]["raw_path"].replace(
        "210000000000", f"2100{archive_seconds:02d}000000"
    )
    if cross_midnight:
        snapshot["snapshot_time"] = "2025-01-18T00:05:00Z"
        macro["source_refs"]["DGS10"]["retrieved_at"] = "2025-01-17T23:59:59Z"
        macro["source_refs"]["DGS10"]["raw_path"] = macro["source_refs"]["DGS10"]["raw_path"].replace(
            "20250117T210006", "20250118T000006"
        )

    result = build_feature_snapshot_from_analysis_snapshot(snapshot)

    assert (result.us10y.value, result.t10yie.value, result.real10y_estimated.value) == (
        4.61,
        2.37,
        2.24,
    )
    assert result.us10y.source_refs[0].source == "treasury_rates"
    assert result.us10y.source_refs[0].retrieved_at.second == archive_seconds
    assert result.t10yie.source_refs[0].source == "fred"
    assert "REAL10Y_ESTIMATED_AVAILABLE" in result.real10y_reason_codes


@pytest.mark.parametrize(
    "mutation",
    (
        "source",
        "domain",
        "port",
        "path",
        "curve",
        "series_year",
        "raw_path",
        "missing_raw_path",
        "missing_retrieved_at",
        "archived_invalid_time",
        "archived_after_snapshot",
        "archived_date_mismatch",
        "future_retrieved_at",
    ),
)
def test_treasury_lineage_tampering_blocks_real10y_components(mutation: str) -> None:
    snapshot = _snapshot()
    macro = snapshot["macro"]["data"]
    macro["indicators"]["REAL_10Y"] = {
        "derivation_version": "real10y_components.v1",
        "value": 2.24,
        "date": "2025-01-17",
        "components": [
            {"source_symbol": "DGS10", "date": "2025-01-17", "value": 4.61},
            {"source_symbol": "T10YIE", "date": "2025-01-17", "value": 2.37},
        ],
    }
    treasury = _treasury_ref("DGS10")
    if mutation == "source":
        treasury["source"] = "treasury_rates_mirror"
    elif mutation == "domain":
        treasury["source_url"] = treasury["source_url"].replace("home.treasury.gov", "mirror.treasury.gov")
    elif mutation == "port":
        treasury["source_url"] = treasury["source_url"].replace(
            "https://home.treasury.gov/", "https://home.treasury.gov:8443/"
        )
    elif mutation == "path":
        treasury["source_url"] = treasury["source_url"].replace("daily-treasury-rates.csv", "other.csv")
    elif mutation == "curve":
        treasury["source_url"] = treasury["source_url"].replace(
            "daily_treasury_yield_curve", "daily_treasury_real_yield_curve"
        )
    elif mutation == "series_year":
        treasury["source_url"] = treasury["source_url"].replace("/2025/all", "/2024/all").replace(
            "field_tdr_date_value=2025", "field_tdr_date_value=2024"
        )
    elif mutation == "raw_path":
        treasury["raw_path"] = "raw/macro/treasury_rates/2025-01-17/nominal-2025.csv"
    elif mutation == "missing_raw_path":
        treasury.pop("raw_path")
    elif mutation == "missing_retrieved_at":
        treasury.pop("retrieved_at")
    elif mutation == "archived_invalid_time":
        treasury["raw_path"] = treasury["raw_path"].replace("210000000000", "250000000000")
    elif mutation == "archived_after_snapshot":
        treasury["raw_path"] = treasury["raw_path"].replace("210000000000", "220000000000")
    elif mutation == "archived_date_mismatch":
        treasury["raw_path"] = treasury["raw_path"].replace("20250117T", "20250118T")
    else:
        treasury["retrieved_at"] = "2025-01-18T00:00:00Z"
    macro["source_refs"] = {
        "DGS10": treasury,
        "T10YIE": {
            "source": "fred",
            "source_url": "https://api.stlouisfed.org/fred/series/observations?series_id=T10YIE",
            "raw_path": "raw/macro/fred/2025-01-17/T10YIE-0123456789.json",
            "retrieved_at": "2025-01-17T21:00:00Z",
        },
    }

    result = build_feature_snapshot_from_analysis_snapshot(snapshot)

    assert result.us10y.value is None
    assert result.t10yie.value is None
    assert result.real10y_estimated.value is None
    assert "REAL10Y_ESTIMATED_CORE_INPUT_UNUSABLE" in result.real10y_reason_codes


def test_treasury_source_cannot_claim_fred_only_t10yie() -> None:
    snapshot = _snapshot()
    macro = snapshot["macro"]["data"]
    macro["indicators"]["REAL_10Y"] = {
        "derivation_version": "real10y_components.v1",
        "value": 2.24,
        "date": "2025-01-17",
        "components": [
            {"source_symbol": "DGS10", "date": "2025-01-17", "value": 4.61},
            {"source_symbol": "T10YIE", "date": "2025-01-17", "value": 2.37},
        ],
    }
    macro["source_refs"] = {
        "DGS10": _treasury_ref("DGS10"),
        "T10YIE": _treasury_ref("DGS10"),
    }

    result = build_feature_snapshot_from_analysis_snapshot(snapshot)

    assert result.us10y.value is None
    assert result.t10yie.value is None
    assert result.real10y_estimated.value is None


@pytest.mark.parametrize(
    "corruption",
    ("arithmetic", "duplicate_ref", "missing_retrieved_at", "wrong_provider"),
)
def test_real10y_advertised_components_fail_closed_when_lineage_is_invalid(
    corruption: str,
) -> None:
    snapshot = _snapshot()
    macro = snapshot["macro"]["data"]
    macro["indicators"]["REAL_10Y"] = {
        "derivation_version": "real10y_components.v1",
        "value": 2.24,
        "date": "2025-01-17T21:00:00Z",
        "components": [
            {"source_symbol": "DGS10", "date": "2025-01-17T21:00:00Z", "value": 4.61},
            {"source_symbol": "T10YIE", "date": "2025-01-17T21:00:00Z", "value": 2.37},
        ],
    }
    macro["source_refs"] = {
        "DGS10": {**_ref("DGS10"), "raw_path": "raw/macro/DGS10.json"},
        "T10YIE": {**_ref("T10YIE"), "raw_path": "raw/macro/T10YIE.json"},
    }
    if corruption == "arithmetic":
        macro["indicators"]["REAL_10Y"]["components"][1]["value"] = 2.30
    elif corruption == "duplicate_ref":
        macro["source_refs"]["T10YIE"]["source_url"] = macro["source_refs"]["DGS10"]["source_url"]
    elif corruption == "wrong_provider":
        macro["source_refs"]["T10YIE"].update(
            source="mirror",
            source_url="https://example.test/fred/series/observations?series_id=T10YIE",
        )
    else:
        macro["source_refs"]["T10YIE"].pop("retrieved_at")

    result = build_feature_snapshot_from_analysis_snapshot(snapshot)

    assert result.us10y.value is None
    assert result.t10yie.value is None
    assert result.real10y_estimated.value is None
    assert "REAL10Y_ESTIMATED_CORE_INPUT_UNUSABLE" in result.real10y_reason_codes


def test_gc_futures_yahoo_source_cannot_become_xauusd_spot() -> None:
    snapshot = _snapshot()
    snapshot["technical"]["data"]["source_refs"] = [{"symbol": "GC=F", "source": "yahoo_finance", "source_url": "https://example.test/GC=F"}]
    result = build_feature_snapshot_from_analysis_snapshot(snapshot)
    assert result.xauusd_spot.value is None
    assert result.xauusd_spot.quality_status == "blocked"


def test_future_dated_input_is_misaligned_and_blocked() -> None:
    snapshot = _snapshot()
    snapshot["macro"]["data"]["indicators"]["US10Y"]["date"] = "2025-01-18T00:00:00Z"
    result = build_feature_snapshot_from_analysis_snapshot(snapshot)
    assert result.us10y.alignment_status == "misaligned"
    assert result.us10y.quality_status == "blocked"


def test_explicit_quality_axes_remain_independent() -> None:
    snapshot = _complete_snapshot()
    observation = snapshot["macro"]["data"]["indicators"]["US10Y"]
    observation.update(freshness_status="stale", quality_status="accepted", alignment_status="unknown")
    snapshot["official_events"]["data"].update(freshness_status="stale", quality_status="accepted", alignment_status="unknown")
    snapshot["official_events"]["data"]["readiness"] = "observe"
    result = build_feature_snapshot_from_analysis_snapshot(snapshot)
    assert (result.us10y.freshness_status, result.us10y.quality_status, result.us10y.alignment_status) == ("stale", "accepted", "unknown")
    assert (result.official_events.freshness_status, result.official_events.quality_status, result.official_events.alignment_status) == ("stale", "accepted", "unknown")


def test_future_official_event_blocks_formal_snapshot_fail_closed() -> None:
    snapshot = _complete_snapshot()
    snapshot["official_events"]["data"]["events"][0]["event_id"] = "fed-future"
    snapshot["official_events"]["data"]["events"][0]["occurred_at"] = "2025-01-18T12:00:00Z"
    result = build_feature_snapshot_from_analysis_snapshot(snapshot)
    assert result.official_events.quality_status == "blocked"
    assert result.official_events.alignment_status == "misaligned"
    assert result.official_events.events == ()


def test_wrong_official_event_schema_never_falls_back_to_legacy_fields() -> None:
    snapshot = _complete_snapshot()
    snapshot["official_events"]["data"]["schema_version"] = "official_event_snapshot.v0"
    snapshot["official_events"]["data"]["events"][0]["title"] = "Legacy-looking text"

    result = build_feature_snapshot_from_analysis_snapshot(snapshot)

    assert result.official_events.events == ()
    assert result.official_events.quality_status == "blocked"


def test_blocked_formal_event_snapshot_cannot_preserve_confirmed_event() -> None:
    snapshot = _complete_snapshot()
    snapshot["official_events"]["data"].update(
        readiness="blocked",
        quality_status="blocked",
        alignment_status="misaligned",
        reason_codes=["OFFICIAL_EVENT_AFTER_AS_OF"],
    )

    result = build_feature_snapshot_from_analysis_snapshot(snapshot)

    assert result.official_events.events == ()
    assert result.official_events.quality_status == "blocked"


def test_forged_non_30m_formal_event_payload_fails_closed() -> None:
    snapshot = _complete_snapshot()
    snapshot["official_events"]["data"]["events"][0]["reaction_window_end"] = (
        "2025-01-17T20:29:00Z"
    )

    result = build_feature_snapshot_from_analysis_snapshot(snapshot)

    assert result.official_events.events == ()
    assert result.official_events.quality_status == "blocked"


def test_same_input_is_stable_and_adapter_does_not_mutate_input() -> None:
    snapshot = _snapshot()
    before = copy.deepcopy(snapshot)
    results = [build_feature_snapshot_from_analysis_snapshot(snapshot) for _ in range(100)]
    assert {result.snapshot_id for result in results} == {results[0].snapshot_id}
    assert snapshot == before


def test_rejects_wrong_asset_and_unparseable_snapshot_time() -> None:
    snapshot = _snapshot()
    snapshot["asset"] = "GC"
    with pytest.raises(ValueError, match="XAUUSD"):
        build_feature_snapshot_from_analysis_snapshot(snapshot)
    snapshot = _snapshot()
    snapshot["snapshot_time"] = "not-a-date"
    with pytest.raises(ValueError, match="parseable"):
        build_feature_snapshot_from_analysis_snapshot(snapshot)
