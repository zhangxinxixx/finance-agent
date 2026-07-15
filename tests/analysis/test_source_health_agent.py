from __future__ import annotations

from apps.analysis.agents.gold_v3_prompts import build_source_health_prompt_template
from apps.analysis.agents.source_health import (
    build_gold_v3_source_health,
    source_statuses_from_analysis_snapshot,
)


AS_OF = "2026-07-06T09:30:00+00:00"


def _source(source_key: str, *, updated_at: str = AS_OF, status: str = "ok") -> dict[str, object]:
    return {
        "source_key": source_key,
        "status": status,
        "health_state": "healthy" if status == "ok" else status,
        "readiness_state": "ready" if status == "ok" else status,
        "latest_health_at": updated_at,
        "source_refs": [{"source_ref": f"storage/{source_key}.json"}],
    }


def _p0_sources() -> list[dict[str, object]]:
    return [
        _source("xauusd_price"),
        _source("dxy"),
        _source("treasury_2y"),
        _source("treasury_10y"),
        _source("tips_10y"),
        _source("fed_macro_events"),
        _source("brent_wti"),
        _source("geopolitical_news"),
        _source("technical_levels"),
    ]


def test_gold_v3_source_health_allows_build_with_p0_ready_and_degraded_p1_p2() -> None:
    snapshot = build_gold_v3_source_health(_p0_sources(), as_of=AS_OF).to_dict()

    assert snapshot["overall_status"] == "degraded"
    assert snapshot["can_build_gold_macro_overview"] is True
    assert snapshot["p0_missing"] == []
    assert "fedwatch_ois" in snapshot["p1_missing"]
    assert "central_bank_buying" in snapshot["p2_missing"]
    assert snapshot["mainline_impact"]["gold_technical_levels"]["status"] == "ready"
    assert snapshot["mainline_impact"]["fed_policy_path"]["status"] == "degraded"


def test_gold_v3_source_health_blocks_impacted_mainlines_when_p0_sources_missing() -> None:
    sources = [
        source
        for source in _p0_sources()
        if source["source_key"] not in {"dxy", "tips_10y", "brent_wti"}
    ]

    snapshot = build_gold_v3_source_health(sources, as_of=AS_OF).to_dict()

    assert snapshot["overall_status"] == "degraded"
    assert snapshot["can_build_gold_macro_overview"] is True
    assert snapshot["can_emit_strong_conclusion"] is False
    assert snapshot["p0_missing"] == ["dxy", "tips_10y", "brent_wti"]
    assert snapshot["mainline_impact"]["real_rates_usd"]["status"] == "blocked"
    assert snapshot["mainline_impact"]["oil_prices"]["status"] == "blocked"
    assert "real_rates_usd" in snapshot["blocked_mainlines"]
    assert "oil_prices" in snapshot["blocked_mainlines"]
    assert snapshot["blocking_reasons"] == []


def test_gold_v3_source_health_keeps_overview_buildable_when_p0_gap_is_mainline_scoped() -> None:
    sources = [source for source in _p0_sources() if source["source_key"] != "brent_wti"]

    snapshot = build_gold_v3_source_health(sources, as_of=AS_OF).to_dict()

    assert snapshot["overall_status"] == "degraded"
    assert snapshot["can_build_gold_macro_overview"] is True
    assert snapshot["can_emit_strong_conclusion"] is False
    assert "oil_prices" in snapshot["blocked_mainlines"]
    assert "geopolitical_war_risk" in snapshot["blocked_mainlines"]
    assert "P0 source missing: brent_wti" not in snapshot["blocking_reasons"]


def test_gold_v3_source_health_globally_blocks_when_core_rate_stack_is_unavailable() -> None:
    sources = [
        source
        for source in _p0_sources()
        if source["source_key"] not in {"dxy", "treasury_10y", "tips_10y"}
    ]

    snapshot = build_gold_v3_source_health(sources, as_of=AS_OF).to_dict()

    assert snapshot["overall_status"] == "blocked"
    assert snapshot["can_build_gold_macro_overview"] is False
    assert "core rate/USD stack unavailable: dxy, treasury_10y, tips_10y" in snapshot["blocking_reasons"]


def test_gold_v3_source_health_treats_available_success_enabled_as_ready() -> None:
    sources = [
        _source("xauusd_price", status="available"),
        {
            **_source("dxy"),
            "status": None,
            "health_state": "success",
            "readiness_state": None,
        },
        {
            **_source("treasury_2y"),
            "status": None,
            "health_state": None,
            "readiness_state": "enabled",
        },
    ]

    snapshot = build_gold_v3_source_health(sources, as_of=AS_OF).to_dict()

    assert snapshot["source_freshness"]["xauusd_price"]["status"] == "fresh"
    assert snapshot["source_freshness"]["dxy"]["status"] == "fresh"
    assert snapshot["source_freshness"]["treasury_2y"]["status"] == "fresh"
    assert "xauusd_price" not in snapshot["p0_missing"]
    assert "dxy" not in snapshot["p0_missing"]
    assert "treasury_2y" not in snapshot["p0_missing"]


def test_gold_v3_source_health_blocks_strong_overview_when_p0_missing() -> None:
    sources = [source for source in _p0_sources() if source["source_key"] != "xauusd_price"]
    overview = {
        "phase": "strong_uptrend",
        "net_bias": "bullish",
        "one_line_conclusion": "strong bullish breakout",
    }

    snapshot = build_gold_v3_source_health(sources, as_of=AS_OF, gold_macro_overview=overview).to_dict()

    assert snapshot["overall_status"] == "blocked"
    assert "P0 source gap conflicts with strong GoldMacroOverview conclusion" in snapshot["blocking_reasons"]


def test_source_health_prompt_schema_matches_runtime_contract() -> None:
    template = build_source_health_prompt_template()
    schema = template["output_schema"]

    assert schema["overall_status"] == "ready | degraded | blocked"
    assert "p0_missing" in schema
    assert "p1_missing" in schema
    assert "p2_missing" in schema
    assert "source_freshness" in schema
    assert "mainline_impact" in schema
    assert "blocking_reasons" in schema


def _completed_analysis_snapshot() -> dict[str, object]:
    return {
        "snapshot_time": "2026-07-21T04:54:22+00:00",
        "technical": {
            "status": "available",
            "data": {"price": 4045.9, "atr14": 51.92},
        },
        "macro": {
            "status": "available",
            "data": {
                "indicators": {
                    "DXY": {"value": 100.943, "date": "2026-07-21"},
                    "US02Y": {"value": 4.18, "date": "2026-07-17"},
                    "US10Y": {"value": 4.55, "date": "2026-07-17"},
                    "REAL_10Y": {"value": 2.31, "date": "2026-07-17"},
                    "BREAKEVEN_10Y": {"value": 2.25, "date": "2026-07-20"},
                }
            },
        },
        "news": {"status": "available", "data": {}},
        "positioning": {"status": "available", "data": {"as_of": "2026-07-14"}},
        "options": {"status": "available", "data": {}},
        "source_refs": [
            {
                "source": "jin10_quote",
                "symbol": "XAUUSD",
                "raw_path": "raw/technical/XAUUSD.json",
                "notes": {"quote_time": "2026-07-21T12:50:40+08:00"},
            },
            {"source": "tradingview", "symbol": "DXY", "raw_path": "raw/macro/DXY.json"},
            {"source": "fred", "symbol": "DGS2", "raw_path": "raw/macro/DGS2.json"},
            {"source": "fred", "symbol": "DGS10", "raw_path": "raw/macro/DGS10.json"},
            {"source": "fred", "symbol": "DFII10", "raw_path": "raw/macro/DFII10.json"},
            {"source": "fred", "symbol": "T10YIE", "raw_path": "raw/macro/T10YIE.json"},
            {"source": "fed_rss", "status": "ok", "source_ref": "fed_rss:h15"},
            {"source": "jin10_mcp", "method": "get_quote:USOIL", "raw_path": "raw/USOIL.json"},
            {
                "source": "reuters_public_news",
                "status": "available",
                "query_group": "middle_east_hormuz",
                "source_ref": "reuters:middle-east",
            },
            {"source": "cftc", "raw_path": "raw/cot.json"},
            {"source": "cme_daily_bulletin", "report_date": "2026-07-17", "raw_path": "raw/cme.pdf"},
            {"source": "eia_energy", "status": "ok", "source_ref": "eia:weekly"},
            {"source": "jin10_mcp", "method": "get_quote:USDCNH", "raw_path": "raw/USDCNH.json"},
        ],
    }


def test_completed_snapshot_rebuilds_p0_health_from_unified_evidence() -> None:
    snapshot = _completed_analysis_snapshot()

    statuses = source_statuses_from_analysis_snapshot(snapshot)
    health = build_gold_v3_source_health(
        statuses,
        as_of=str(snapshot["snapshot_time"]),
    ).to_dict()

    assert health["p0_missing"] == []
    assert not set(health["stale_sources"]) & {"treasury_2y", "treasury_10y", "tips_10y"}
    assert health["source_freshness"]["xauusd_price"]["source_ref"] == "raw/technical/XAUUSD.json"
    assert health["source_freshness"]["brent_wti"]["source_ref"] == "raw/USOIL.json"


def test_completed_snapshot_keeps_missing_price_fail_closed_without_lineage_ref() -> None:
    snapshot = _completed_analysis_snapshot()
    snapshot["source_refs"] = [
        ref
        for ref in snapshot["source_refs"]
        if not (isinstance(ref, dict) and ref.get("symbol") == "XAUUSD")
    ]

    statuses = source_statuses_from_analysis_snapshot(snapshot)
    health = build_gold_v3_source_health(
        statuses,
        as_of=str(snapshot["snapshot_time"]),
    ).to_dict()

    assert "xauusd_price" in health["p0_missing"]
    assert "global P0 source unavailable: xauusd_price" in health["blocking_reasons"]
