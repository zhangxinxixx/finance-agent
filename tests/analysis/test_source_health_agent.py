from __future__ import annotations

from apps.analysis.agents.gold_v3_prompts import build_source_health_prompt_template
from apps.analysis.agents.source_health import build_gold_v3_source_health


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


def test_gold_v3_source_health_blocks_mainlines_when_p0_sources_missing() -> None:
    sources = [
        source
        for source in _p0_sources()
        if source["source_key"] not in {"dxy", "tips_10y", "brent_wti"}
    ]

    snapshot = build_gold_v3_source_health(sources, as_of=AS_OF).to_dict()

    assert snapshot["overall_status"] == "blocked"
    assert snapshot["can_build_gold_macro_overview"] is False
    assert snapshot["p0_missing"] == ["dxy", "tips_10y", "brent_wti"]
    assert snapshot["mainline_impact"]["real_rates_usd"]["status"] == "blocked"
    assert snapshot["mainline_impact"]["oil_prices"]["status"] == "blocked"
    assert "P0 source missing: dxy" in snapshot["blocking_reasons"]


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
