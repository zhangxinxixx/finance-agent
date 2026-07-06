from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

from scripts import run_gold_mainline_pipeline


def _write_input_artifacts(root: Path, *, date: str, run_id: str) -> None:
    feature_dir = root / "features" / "news" / date / run_id
    feature_dir.mkdir(parents=True, exist_ok=True)
    event = {
        "event_id": "event:hormuz",
        "event_type": "hormuz_risk",
        "event_status": "developing",
        "event_time": f"{date}T08:15:00+00:00",
        "asset_tags": ["XAUUSD", "WTI"],
        "direction": "mixed",
        "confidence": 0.72,
        "verification_status": "single_source",
        "source_refs": [{"source": "fixture_news", "source_ref": "fixture:hormuz"}],
    }
    impact = {
        "event_id": "event:hormuz",
        "impact_path": "geo_risk_to_oil_to_inflation",
        "gold_impact": "mixed",
        "dollar_impact": "dollar_strength",
        "yield_impact": "yield_up",
        "oil_impact": "oil_up",
        "pricing_status": "unpriced",
    }
    (feature_dir / "event_candidates.json").write_text(
        json.dumps({"as_of": f"{date}T08:30:00+00:00", "event_candidates": [event]}, ensure_ascii=False),
        encoding="utf-8",
    )
    (feature_dir / "impact_assessments.json").write_text(
        json.dumps({"impact_assessments": [impact]}, ensure_ascii=False),
        encoding="utf-8",
    )


def _write_json(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _gold_v3_source_status_payload(*, missing: set[str] | None = None) -> dict[str, list[dict[str, object]]]:
    missing = missing or set()
    p0_sources = [
        "xauusd_price",
        "dxy",
        "treasury_2y",
        "treasury_10y",
        "tips_10y",
        "fed_macro_events",
        "brent_wti",
        "geopolitical_news",
        "technical_levels",
    ]
    return {
        "sources": [
            {
                "source_key": source_key,
                "status": "ok",
                "health_state": "healthy",
                "readiness_state": "ready",
                "latest_health_at": "2026-06-30T08:30:00+00:00",
                "source_refs": [{"source_ref": f"storage/{source_key}.json"}],
            }
            for source_key in p0_sources
            if source_key not in missing
        ]
    }


def _write_news_artifacts(root: Path, *, date: str, run_id: str, events: list[dict], impacts: list[dict]) -> None:
    feature_dir = root / "features" / "news" / date / run_id
    feature_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        feature_dir / "event_candidates.json",
        {"as_of": f"{date}T08:30:00+00:00", "event_candidates": events},
    )
    _write_json(
        feature_dir / "impact_assessments.json",
        {"impact_assessments": impacts},
    )


def test_context_payload_validator_adds_lineage_warnings() -> None:
    payload = {"gold_spot_price": 4115.0, "artifact_path": "analysis/gold_mainlines/run/market_context.json"}

    missing = run_gold_mainline_pipeline._validate_context_payload(kind="market", payload=payload)

    assert missing == ["source_refs", "provider_role", "verification_status", "as_of"]
    assert payload["warnings"] == [
        "market_context_missing_as_of",
        "market_context_missing_provider_role",
        "market_context_missing_source_refs",
        "market_context_missing_verification_status",
    ]


def test_run_gold_mainline_pipeline_rebuilds_nine_mainline_artifacts(tmp_path: Path, capsys) -> None:
    _write_input_artifacts(tmp_path, date="2026-06-30", run_id="source-run")
    macro_dir = tmp_path / "features" / "macro" / "2026-06-30" / "macro-run"
    macro_dir.mkdir(parents=True, exist_ok=True)
    (macro_dir / "macro_snapshot.json").write_text(
        json.dumps(
            {
                "as_of": "2026-06-30",
                "indicators": {
                    "REAL_10Y": {"value": 2.2, "weekly_change": -0.09},
                    "US10Y": {"value": 4.44, "weekly_change": -0.06},
                    "BREAKEVEN_10Y": {"value": 2.23, "weekly_change": 0.05},
                    "YIELD_SPREAD_2Y_3M": {"value": -0.45, "weekly_change": 0.12},
                    "DXY": {"value": 100.7, "weekly_change": -0.4},
                },
                "source_refs": {
                    "REAL_10Y": {"source": "fred", "raw_path": "raw/macro/real.json"},
                    "DGS2": {"source": "fred", "raw_path": "raw/macro/dgs2.json"},
                    "DGS3MO": {"source": "fred", "raw_path": "raw/macro/dgs3mo.json"},
                    "DXY": {"source": "cnbc", "raw_path": "raw/macro/dxy.json"},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    market_context_path = tmp_path / "market_context.json"
    market_context_path.write_text(
        json.dumps(
            {
                "gold_spot_price": 4115.0,
                "source_refs": [{"source": "market_candles", "source_ref": "XAUUSD:1d"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    oil_context_path = tmp_path / "oil_context.json"
    oil_context_path.write_text(
        json.dumps(
            {
                "brent_price": 92.4,
                "wti_price": 88.1,
                "brent_weekly_change": 4.8,
                "wti_weekly_change": 4.2,
                "inventory_weekly_change": -6.5,
                "source_refs": [{"source": "energy_context", "source_ref": "oil:weekly"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    flow_context_path = tmp_path / "flow_context.json"
    flow_context_path.write_text(
        json.dumps(
            {
                "global_etf_flow": 18.4,
                "north_america_etf_flow": 11.2,
                "asia_etf_flow": 4.6,
                "source_refs": [{"source": "wgc", "source_ref": "gold_etf:weekly"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with mock.patch(
        "scripts.run_gold_mainline_pipeline.get_data_source_statuses",
        return_value=_gold_v3_source_status_payload(),
    ):
        exit_code = run_gold_mainline_pipeline.main(
            [
                "--storage-root",
                str(tmp_path),
                "--date",
                "2026-06-30",
                "--run-id",
                "source-run",
                "--output-run-id",
                "gold-mainlines-refresh-test",
                "--market-context",
                str(market_context_path),
                "--oil-context",
                str(oil_context_path),
                "--flow-context",
                str(flow_context_path),
            ]
        )

    assert exit_code == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["run_mode"] == "premarket_full_run"
    assert summary["trigger_reason"] == "daily_premarket_refresh"
    assert "agents_executed" not in summary
    assert "agents_skipped" not in summary
    assert summary["runtime_contract_only"] is True
    assert "source_health_agent" in summary["planned_agents_executed"]
    assert "report_render_agent" in summary["planned_agents_executed"]
    assert "real_rates_usd" in summary["affected_mainlines"]
    assert "real_rates_dollar" not in summary["affected_mainlines"]
    assert "war_oil_rate_chain" in summary["affected_chains"]
    assert summary["gold_macro_overview_updated"] is True
    assert summary["retrieved_date"] == "2026-06-30"
    assert summary["source_run_id"] == "source-run"
    assert summary["output_run_id"] == "gold-mainlines-refresh-test"
    assert summary["gold_mainline_count"] == 9
    assert summary["gold_event_link_count"] == 1
    assert summary["gold_macro_theme_count"] == 9
    assert summary["gold_verification_item_count"] >= 1
    assert summary["gold_readiness"]["ready_count"] >= 2
    assert summary["runtime_steps"]["source_health_check"]["status"] == "degraded"
    assert summary["runtime_steps"]["source_health_check"]["p0_missing"] == []
    assert summary["runtime_steps"]["source_health_check"]["can_build_gold_macro_overview"] is True
    assert summary["runtime_steps"]["review_gate"]["review_status"] == "needs_review"
    assert "quality_gate_decision" in summary["runtime_steps"]["review_gate"]
    assert (
        summary["runtime_steps"]["review_gate"]["quality_gate_action"]
        == summary["runtime_steps"]["review_gate"]["quality_gate_decision"]["action"]
    )
    assert isinstance(summary["runtime_steps"]["review_gate"]["publish_allowed"], bool)
    assert summary["source_health_status"] == "degraded"
    assert summary["review_status"] == "needs_review"
    assert isinstance(summary["warnings"], list)

    mainlines_path = tmp_path / summary["gold_event_mainlines_path"]
    overview_path = tmp_path / summary["gold_macro_overview_path"]
    assert mainlines_path.exists()
    assert overview_path.exists()

    mainlines = json.loads(mainlines_path.read_text(encoding="utf-8"))
    overview = json.loads(overview_path.read_text(encoding="utf-8"))
    assert len(mainlines["mainlines"]) == 9
    assert len(overview["theme_rankings"]) == 9
    assert overview["source_health"]["overall_status"] == "degraded"
    assert overview["source_health"]["p0_missing"] == []
    assert "fedwatch_ois" in overview["source_health"]["p1_missing"]
    assert overview["review_gate"]["review_status"] == "needs_review"
    assert "quality_gate_decision" in overview["review_gate"]
    assert overview["review_gate"]["quality_gate_action"] == overview["review_gate"]["quality_gate_decision"]["action"]
    assert isinstance(overview["review_gate"]["publish_allowed"], bool)
    assert overview["review_status"] == "needs_review"
    assert overview["input_snapshot_ids"]["gold_event_mainlines"] == summary["gold_event_mainlines_path"]
    assert overview["input_snapshot_ids"]["macro_snapshot"] == "features/macro/2026-06-30/macro-run/macro_snapshot.json"
    expected_market_context_path = "analysis/gold_mainlines/2026-06-30/gold-mainlines-refresh-test/market_context.json"
    assert overview["input_snapshot_ids"]["market_context"] == expected_market_context_path
    expected_oil_context_path = "analysis/gold_mainlines/2026-06-30/gold-mainlines-refresh-test/oil_context.json"
    assert overview["input_snapshot_ids"]["oil_context"] == expected_oil_context_path
    expected_flow_context_path = "analysis/gold_mainlines/2026-06-30/gold-mainlines-refresh-test/flow_context.json"
    assert overview["input_snapshot_ids"]["flow_context"] == expected_flow_context_path
    persisted_market_context = tmp_path / expected_market_context_path
    assert persisted_market_context.exists()
    assert json.loads(persisted_market_context.read_text(encoding="utf-8"))["gold_spot_price"] == 4115.0
    persisted_oil_context = tmp_path / expected_oil_context_path
    assert persisted_oil_context.exists()
    assert json.loads(persisted_oil_context.read_text(encoding="utf-8"))["brent_price"] == 92.4
    persisted_flow_context = tmp_path / expected_flow_context_path
    assert persisted_flow_context.exists()
    assert json.loads(persisted_flow_context.read_text(encoding="utf-8"))["global_etf_flow"] == 18.4
    assert overview["war_oil_rate_chain"]["path_id"] == "geopolitics_to_oil_to_rates"
    assert overview["war_oil_rate_chain"]["conclusion_code"] == "A"
    rankings = {row["mainline_id"]: row for row in overview["theme_rankings"]}
    assert rankings["real_rates_usd"]["feature_fields"]["real_rate_level"] == 2.2
    assert rankings["real_rates_usd"]["feature_fields"]["yield_spread_2y_3m_level"] == -0.45
    assert rankings["real_rates_usd"]["feature_fields"]["yield_curve_2y3m_signal"] == "pivot_window_improving"
    assert rankings["gold_technical_levels"]["feature_fields"]["gold_spot_price"] == 4115.0
    assert rankings["oil_prices"]["feature_fields"]["oil_price_trend"] == "rising"
    assert rankings["etf_flows"]["feature_fields"]["flow_confirmation_status"] == "confirmed_inflow"


def test_run_gold_mainline_pipeline_blocks_review_gate_from_source_health_conflict(tmp_path: Path, capsys) -> None:
    _write_input_artifacts(tmp_path, date="2026-06-30", run_id="source-run")

    class Snapshot:
        def to_dict(self) -> dict[str, object]:
            return {
                "overall_status": "blocked",
                "as_of": "2026-06-30T08:30:00+00:00",
                "p0_missing": ["xauusd_price"],
                "p1_missing": [],
                "p2_missing": [],
                "stale_sources": [],
                "fresh_sources": [],
                "source_freshness": {},
                "mainline_impact": {},
                "can_build_gold_macro_overview": False,
                "blocking_reasons": ["P0 source gap conflicts with strong GoldMacroOverview conclusion"],
                "warnings": [],
            }

    with mock.patch("scripts.run_gold_mainline_pipeline.build_gold_v3_source_health", return_value=Snapshot()):
        exit_code = run_gold_mainline_pipeline.main(
            [
                "--storage-root",
                str(tmp_path),
                "--date",
                "2026-06-30",
                "--run-id",
                "source-run",
                "--output-run-id",
                "gold-mainlines-source-health-block-test",
            ]
        )

    assert exit_code == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["runtime_steps"]["source_health_check"]["status"] == "blocked"
    assert summary["runtime_steps"]["review_gate"]["review_status"] == "blocked"
    assert summary["runtime_steps"]["review_gate"]["quality_gate_action"] == "block_publish"
    assert summary["runtime_steps"]["review_gate"]["publish_allowed"] is False
    assert summary["review_status"] == "blocked"

    overview = json.loads((tmp_path / summary["gold_macro_overview_path"]).read_text(encoding="utf-8"))
    assert overview["status"] == "blocked"
    assert overview["source_health"]["p0_missing"] == ["xauusd_price"]
    assert overview["review_status"] == "blocked"
    assert overview["review_gate"]["quality_gate_action"] == "block_publish"
    assert overview["review_gate"]["quality_gate_decision"]["review_status"] == "blocked"
    assert overview["review_gate"]["publish_allowed"] is False
    assert "P0 source gap conflicts with strong GoldMacroOverview conclusion" in overview["review_blocking_reasons"]
    assert (
        "P0 source gap conflicts with a strong or high-confidence conclusion."
        in overview["review_blocking_reasons"]
    )


def test_run_gold_mainline_pipeline_emits_major_event_runtime_summary(tmp_path: Path, capsys) -> None:
    _write_input_artifacts(tmp_path, date="2026-06-30", run_id="source-run")

    with mock.patch(
        "scripts.run_gold_mainline_pipeline.get_data_source_statuses",
        return_value=_gold_v3_source_status_payload(),
    ):
        exit_code = run_gold_mainline_pipeline.main(
            [
                "--storage-root",
                str(tmp_path),
                "--date",
                "2026-06-30",
                "--run-id",
                "source-run",
                "--output-run-id",
                "gold-mainlines-major-event-test",
                "--run-mode",
                "major_event_reprice",
                "--trigger-reason",
                "hormuz_brent_shock",
            ]
        )

    assert exit_code == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["run_mode"] == "major_event_reprice"
    assert summary["trigger_reason"] == "hormuz_brent_shock"
    assert "war_oil_rate_chain" in summary["affected_chains"]
    assert "oil_prices" in summary["affected_mainlines"]
    assert "geopolitical_war_risk" in summary["affected_mainlines"]
    assert "report_render_agent" in summary["planned_agents_skipped"]
    assert summary["review_status"] == "needs_review"


def test_run_gold_mainline_pipeline_rejects_unknown_run_mode(tmp_path: Path, capsys) -> None:
    _write_input_artifacts(tmp_path, date="2026-06-30", run_id="source-run")

    exit_code = run_gold_mainline_pipeline.main(
        [
            "--storage-root",
            str(tmp_path),
            "--date",
            "2026-06-30",
            "--run-id",
            "source-run",
            "--run-mode",
            "unknown_mode",
        ]
    )

    assert exit_code == 1
    err = capsys.readouterr().err
    assert "Unknown Gold runtime mode" in err


def test_run_gold_mainline_pipeline_smoke_artifact_chain_with_all_contexts(tmp_path: Path, capsys) -> None:
    _write_input_artifacts(tmp_path, date="2026-06-30", run_id="source-run")
    macro_dir = tmp_path / "features" / "macro" / "2026-06-30" / "macro-run"
    macro_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        macro_dir / "macro_snapshot.json",
        {
            "as_of": "2026-06-30",
            "indicators": {
                "REAL_10Y": {"value": 2.2, "weekly_change": -0.09},
                "US10Y": {"value": 4.44, "weekly_change": -0.06},
                "BREAKEVEN_10Y": {"value": 2.23, "weekly_change": 0.05},
                "YIELD_SPREAD_2Y_3M": {"value": -0.45, "weekly_change": 0.12},
                "DXY": {"value": 100.7, "weekly_change": -0.4},
            },
            "source_refs": {
                "REAL_10Y": {"source": "fred", "raw_path": "raw/macro/real.json"},
                "DGS2": {"source": "fred", "raw_path": "raw/macro/dgs2.json"},
                "DGS3MO": {"source": "fred", "raw_path": "raw/macro/dgs3mo.json"},
                "DXY": {"source": "cnbc", "raw_path": "raw/macro/dxy.json"},
            },
        },
    )
    context_payloads = {
        "market": {
            "gold_spot_price": 4115.0,
            "source_refs": [{"source": "market_candles", "source_ref": "XAUUSD:1d"}],
        },
        "oil": {
            "brent_price": 92.4,
            "wti_price": 88.1,
            "brent_weekly_change": 4.8,
            "wti_weekly_change": 4.2,
            "inventory_weekly_change": -6.5,
            "source_refs": [{"source": "energy_context", "source_ref": "oil:weekly"}],
        },
        "flow": {
            "global_etf_flow": 18.4,
            "north_america_etf_flow": 11.2,
            "asia_etf_flow": 4.6,
            "source_refs": [{"source": "wgc", "source_ref": "gold_etf:weekly"}],
        },
        "reserve": {
            "central_bank_net_buying": 61.0,
            "pboc_gold_holdings_change": 2.4,
            "reserve_diversification_signal": "broadening",
            "monetary_credit_repricing": "usd_confidence_erosion",
            "long_term_support_score": 8.2,
            "source_refs": [{"source": "wgc", "source_ref": "central_bank:monthly"}],
        },
        "asia": {
            "usdcnh_weekly_change": -0.18,
            "shanghai_gold_premium": 42.5,
            "china_gold_etf_flow": 6.3,
            "asia_demand_score": 7.4,
            "india_physical_demand": 5.1,
            "source_refs": [{"source": "sge", "source_ref": "premium:weekly"}],
        },
        "positioning": {
            "comex_net_long": 185000,
            "cot_positioning": "stretched_long",
            "option_skew": 1.35,
            "call_put_oi_ratio": 0.82,
            "institutional_sentiment": "cautious_bullish",
            "positioning_crowding": "crowded_long",
            "source_refs": [{"source": "cme_cot", "source_ref": "comex:weekly"}],
        },
        "policy": {
            "fed_policy_bias": "higher_for_longer",
            "rate_expectation_delta": 0.32,
            "cut_hike_probability": 0.18,
            "fomc_tone": "hawkish",
            "policy_surprise": "hawkish_repricing",
            "treasury_2y_change": 0.11,
            "treasury_10y_change": 0.08,
            "source_refs": [{"source": "fed", "source_ref": "fomc:2026-06"}],
        },
        "geopolitical": {
            "geopolitical_status": "escalating",
            "war_escalation_level": "regional_risk",
            "safe_haven_score": 7.6,
            "energy_channel_risk": "elevated",
            "war_oil_rate_chain_status": "active",
            "vix_reaction": "risk_off",
            "equity_reaction": "selloff",
            "treasury_yield_reaction": "bull_flattening",
            "source_refs": [
                {"source": "reuters", "source_ref": "geo:1"},
                {"source": "market_volatility", "source_ref": "vix:reaction"},
                {"source": "equity_market", "source_ref": "spx:reaction"},
                {"source": "treasury", "source_ref": "ust:reaction"},
                {"source": "energy_market", "source_ref": "oil:reaction"},
            ],
        },
    }
    context_paths = {
        name: _write_json(tmp_path / f"{name}_context.json", payload)
        for name, payload in context_payloads.items()
    }

    exit_code = run_gold_mainline_pipeline.main(
        [
            "--storage-root",
            str(tmp_path),
            "--date",
            "2026-06-30",
            "--run-id",
            "source-run",
            "--output-run-id",
            "gold-mainlines-smoke-test",
            "--market-context",
            str(context_paths["market"]),
            "--oil-context",
            str(context_paths["oil"]),
            "--flow-context",
            str(context_paths["flow"]),
            "--reserve-context",
            str(context_paths["reserve"]),
            "--asia-context",
            str(context_paths["asia"]),
            "--positioning-context",
            str(context_paths["positioning"]),
            "--policy-context",
            str(context_paths["policy"]),
            "--geopolitical-context",
            str(context_paths["geopolitical"]),
        ]
    )

    assert exit_code == 0
    summary = json.loads(capsys.readouterr().out)
    overview = json.loads((tmp_path / summary["gold_macro_overview_path"]).read_text(encoding="utf-8"))

    expected_prefix = "analysis/gold_mainlines/2026-06-30/gold-mainlines-smoke-test"
    for key in [
        "market_context",
        "oil_context",
        "flow_context",
        "reserve_context",
        "asia_context",
        "positioning_context",
        "policy_context",
        "geopolitical_context",
    ]:
        assert overview["input_snapshot_ids"][key] == f"{expected_prefix}/{key}.json"
        assert (tmp_path / overview["input_snapshot_ids"][key]).exists()

    assert overview["input_snapshot_ids"]["macro_snapshot"] == "features/macro/2026-06-30/macro-run/macro_snapshot.json"
    assert overview["priority_regime"] in {"policy_event_cycle", "war_escalation", "large_capital_flow", "monetary_credit_repricing"}
    assert overview["analysis_readiness"]["ready_count"] >= 7
    rankings = {row["mainline_id"]: row for row in overview["theme_rankings"]}
    assert rankings["etf_flows"]["source_refs"][0]["source_tier"] == "official"
    assert rankings["institutional_sentiment"]["source_refs"][0]["source_tier"] == "official"
    assert rankings["geopolitical_war_risk"]["feature_fields"]["war_oil_rate_chain_status"] == "active"
    assert overview["war_oil_rate_chain"]["path_id"] == "geopolitics_to_oil_to_rates"


def test_run_gold_mainline_pipeline_persists_live_market_context_when_no_file(tmp_path: Path, capsys) -> None:
    _write_input_artifacts(tmp_path, date="2026-06-30", run_id="source-run")

    with mock.patch.object(
        run_gold_mainline_pipeline,
        "_get_market_monitor_overview",
        return_value={
            "generated_at": "2026-06-30T12:05:00+00:00",
            "source": "api",
            "metrics": [
                {
                    "key": "XAUUSD",
                    "latest_value": 4088.5,
                    "unit": "USD/oz",
                    "status": "ok",
                }
            ],
            "source_trace": [{"source": "market_monitor", "source_ref": "api://market/monitor"}],
        },
    ):
        exit_code = run_gold_mainline_pipeline.main(
            [
                "--storage-root",
                str(tmp_path),
                "--date",
                "2026-06-30",
                "--run-id",
                "source-run",
                "--output-run-id",
                "gold-mainlines-live-market-test",
            ]
        )

    assert exit_code == 0
    summary = json.loads(capsys.readouterr().out)
    overview_path = tmp_path / summary["gold_macro_overview_path"]
    overview = json.loads(overview_path.read_text(encoding="utf-8"))
    expected_market_context_path = "analysis/gold_mainlines/2026-06-30/gold-mainlines-live-market-test/market_context.json"
    assert overview["input_snapshot_ids"]["market_context"] == expected_market_context_path
    persisted_market_context = tmp_path / expected_market_context_path
    assert persisted_market_context.exists()
    assert json.loads(persisted_market_context.read_text(encoding="utf-8"))["metrics"][0]["latest_value"] == 4088.5
    rankings = {row["mainline_id"]: row for row in overview["theme_rankings"]}
    assert rankings["gold_technical_levels"]["feature_fields"]["gold_spot_price"] == 4088.5


def test_run_gold_mainline_pipeline_auto_loads_jin10_gold_etf_flow_context(tmp_path: Path, capsys) -> None:
    _write_input_artifacts(tmp_path, date="2026-06-30", run_id="source-run")
    parsed_dir = tmp_path / "parsed" / "jin10" / "datacenter" / "2026-06-30" / "dc_etf_gold"
    parsed_dir.mkdir(parents=True, exist_ok=True)
    (parsed_dir / "parsed.json").write_text(
        json.dumps(
            {
                "status": "ok",
                "slug": "dc_etf_gold",
                "report_name": "黄金ETF持仓报告",
                "as_of": "2026-06-30 08:01:03",
                "rows": [
                    {
                        "date": "2026-06-30",
                        "data_time": "2026-06-30 08:01:03",
                        "values": [
                            {"type": "黄金", "kind": "总库存(吨)", "value": "943.20"},
                            {"type": "黄金", "kind": "增持/减持(吨)", "value": "5.70"},
                            {"type": "黄金", "kind": "总价值(美元)", "value": "78500000000"},
                        ],
                    }
                ],
                "source_refs": [
                    {
                        "source": "jin10_datacenter",
                        "source_key": "jin10_datacenter_reports",
                        "slug": "dc_etf_gold",
                        "raw_js_path": "raw/jin10/datacenter/2026-06-30/dc_etf_gold/latest.js",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    exit_code = run_gold_mainline_pipeline.main(
        [
            "--storage-root",
            str(tmp_path),
            "--date",
            "2026-06-30",
            "--run-id",
            "source-run",
            "--output-run-id",
            "gold-mainlines-jin10-flow-test",
        ]
    )

    assert exit_code == 0
    summary = json.loads(capsys.readouterr().out)
    overview_path = tmp_path / summary["gold_macro_overview_path"]
    overview = json.loads(overview_path.read_text(encoding="utf-8"))

    expected_flow_context_path = "analysis/gold_mainlines/2026-06-30/gold-mainlines-jin10-flow-test/flow_context.json"
    assert overview["input_snapshot_ids"]["flow_context"] == expected_flow_context_path
    persisted_flow_context = tmp_path / expected_flow_context_path
    assert persisted_flow_context.exists()
    flow_context = json.loads(persisted_flow_context.read_text(encoding="utf-8"))
    assert flow_context["global_etf_flow"] == 5.7
    assert flow_context["north_america_etf_flow"] is None
    assert flow_context["asia_etf_flow"] is None
    assert flow_context["artifact_path"] == expected_flow_context_path
    assert "warnings" not in flow_context
    assert flow_context["source_refs"][0]["source"] == "jin10_datacenter"
    assert flow_context["source_refs"][0]["parsed_path"] == "parsed/jin10/datacenter/2026-06-30/dc_etf_gold/parsed.json"
    assert flow_context["source_refs"][0]["source_tier"] == "supplemental"
    assert flow_context["source_refs"][0]["evidence_role"] == "flow_context"
    assert flow_context["source_refs"][0]["lineage_type"] == "parsed_artifact"

    rankings = {row["mainline_id"]: row for row in overview["theme_rankings"]}
    etf = rankings["etf_flows"]
    assert etf["feature_fields"]["global_etf_flow"] == 5.7
    assert etf["feature_fields"]["flow_confirmation_status"] == "global_only"
    assert etf["source_refs"][0]["source_tier"] == "supplemental"
    assert etf["missing_data"] == ["regional_etf_flows"]


def test_run_gold_mainline_pipeline_persists_reserve_and_asia_contexts(tmp_path: Path, capsys) -> None:
    _write_input_artifacts(tmp_path, date="2026-06-30", run_id="source-run")
    reserve_context_path = tmp_path / "reserve_context.json"
    reserve_context_path.write_text(
        json.dumps(
            {
                "central_bank_net_buying": 61.0,
                "pboc_gold_holdings_change": 2.4,
                "reserve_diversification_signal": "broadening",
                "monetary_credit_repricing": "usd_confidence_erosion",
                "long_term_support_score": 8.2,
                "source_refs": [{"source": "wgc", "source_ref": "central_bank:monthly"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    asia_context_path = tmp_path / "asia_context.json"
    asia_context_path.write_text(
        json.dumps(
            {
                "usdcnh_weekly_change": -0.18,
                "shanghai_gold_premium": 42.5,
                "china_gold_etf_flow": 6.3,
                "asia_demand_score": 7.4,
                "india_physical_demand": 5.1,
                "source_refs": [{"source": "sge", "source_ref": "premium:weekly"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    exit_code = run_gold_mainline_pipeline.main(
        [
            "--storage-root",
            str(tmp_path),
            "--date",
            "2026-06-30",
            "--run-id",
            "source-run",
            "--output-run-id",
            "gold-mainlines-structural-test",
            "--reserve-context",
            str(reserve_context_path),
            "--asia-context",
            str(asia_context_path),
        ]
    )

    assert exit_code == 0
    summary = json.loads(capsys.readouterr().out)
    overview_path = tmp_path / summary["gold_macro_overview_path"]
    overview = json.loads(overview_path.read_text(encoding="utf-8"))

    expected_reserve_context_path = "analysis/gold_mainlines/2026-06-30/gold-mainlines-structural-test/reserve_context.json"
    assert overview["input_snapshot_ids"]["reserve_context"] == expected_reserve_context_path
    expected_asia_context_path = "analysis/gold_mainlines/2026-06-30/gold-mainlines-structural-test/asia_context.json"
    assert overview["input_snapshot_ids"]["asia_context"] == expected_asia_context_path
    assert (tmp_path / expected_reserve_context_path).exists()
    assert (tmp_path / expected_asia_context_path).exists()

    rankings = {row["mainline_id"]: row for row in overview["theme_rankings"]}
    assert rankings["central_bank_gold"]["feature_fields"]["central_bank_net_buying"] == 61.0
    assert rankings["china_asia_demand"]["feature_fields"]["shanghai_gold_premium"] == 42.5


def test_run_gold_mainline_pipeline_persists_positioning_context(tmp_path: Path, capsys) -> None:
    _write_input_artifacts(tmp_path, date="2026-06-30", run_id="source-run")
    positioning_context_path = tmp_path / "positioning_context.json"
    positioning_context_path.write_text(
        json.dumps(
            {
                "comex_net_long": 185000,
                "cot_positioning": "stretched_long",
                "option_skew": 1.35,
                "call_put_oi_ratio": 0.82,
                "institutional_sentiment": "cautious_bullish",
                "positioning_crowding": "crowded_long",
                "source_refs": [{"source": "cme_cot", "source_ref": "comex:weekly"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    exit_code = run_gold_mainline_pipeline.main(
        [
            "--storage-root",
            str(tmp_path),
            "--date",
            "2026-06-30",
            "--run-id",
            "source-run",
            "--output-run-id",
            "gold-mainlines-positioning-test",
            "--positioning-context",
            str(positioning_context_path),
        ]
    )

    assert exit_code == 0
    summary = json.loads(capsys.readouterr().out)
    overview_path = tmp_path / summary["gold_macro_overview_path"]
    overview = json.loads(overview_path.read_text(encoding="utf-8"))

    expected_positioning_context_path = "analysis/gold_mainlines/2026-06-30/gold-mainlines-positioning-test/positioning_context.json"
    assert overview["input_snapshot_ids"]["positioning_context"] == expected_positioning_context_path
    assert (tmp_path / expected_positioning_context_path).exists()

    rankings = {row["mainline_id"]: row for row in overview["theme_rankings"]}
    assert rankings["institutional_sentiment"]["feature_fields"]["comex_net_long"] == 185000
    assert rankings["institutional_sentiment"]["feature_fields"]["option_skew"] == 1.35


def test_run_gold_mainline_pipeline_auto_loads_cme_options_positioning_context(tmp_path: Path, capsys) -> None:
    _write_input_artifacts(tmp_path, date="2026-06-30", run_id="source-run")
    options_dir = tmp_path / "outputs" / "cme_options" / "2026-06-30"
    options_dir.mkdir(parents=True, exist_ok=True)
    (options_dir / "options_analysis.json").write_text(
        json.dumps(
            {
                "trade_date": "2026-06-30",
                "data_source": {"product": "GC", "status": "FINAL"},
                "gex": {
                    "by_expiry": {
                        "JUL26": {"iv_skew": {"skew_25d": 0.14}},
                    }
                },
                "iv_skew_by_expiry": {"JUL26": {"skew_25d": 0.14}},
                "wall_scores": [
                    {"strike": 3350, "wall_type": "Call Wall", "oi": 24000, "wall_score": 0.91},
                    {"strike": 3250, "wall_type": "Put Wall", "oi": 12000, "wall_score": 0.74},
                ],
                "intent": {"type": "call_buying", "score": 0.71, "confidence": 0.66},
                "source_trace": [
                    {"source": "cme_options", "source_ref": "cme:2026-06-30", "status": "ok"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    exit_code = run_gold_mainline_pipeline.main(
        [
            "--storage-root",
            str(tmp_path),
            "--date",
            "2026-06-30",
            "--run-id",
            "source-run",
            "--output-run-id",
            "gold-mainlines-cme-positioning-test",
        ]
    )

    assert exit_code == 0
    summary = json.loads(capsys.readouterr().out)
    overview_path = tmp_path / summary["gold_macro_overview_path"]
    overview = json.loads(overview_path.read_text(encoding="utf-8"))

    expected_positioning_context_path = "analysis/gold_mainlines/2026-06-30/gold-mainlines-cme-positioning-test/positioning_context.json"
    assert overview["input_snapshot_ids"]["positioning_context"] == expected_positioning_context_path
    positioning_context = json.loads((tmp_path / expected_positioning_context_path).read_text(encoding="utf-8"))
    assert positioning_context["option_skew"] == 0.14
    assert positioning_context["call_put_oi_ratio"] == 2.0
    assert positioning_context["institutional_sentiment"] == "call_buying"
    assert positioning_context["positioning_crowding"] == "call_wall_dominant"
    assert positioning_context["source_refs"][0]["path"] == "outputs/cme_options/2026-06-30/options_analysis.json"
    assert positioning_context["source_refs"][0]["source_tier"] == "market_derived"
    assert positioning_context["source_refs"][0]["evidence_role"] == "positioning_context"
    assert positioning_context["source_refs"][0]["lineage_type"] == "analysis_artifact"

    rankings = {row["mainline_id"]: row for row in overview["theme_rankings"]}
    positioning = rankings["institutional_sentiment"]
    assert positioning["feature_fields"]["option_skew"] == 0.14
    assert positioning["source_refs"][0]["source_tier"] == "market_derived"
    assert positioning["feature_fields"]["call_put_oi_ratio"] == 2.0
    assert positioning["missing_data"] == ["positioning_data"]


def test_run_gold_mainline_pipeline_auto_loads_cot_and_cme_positioning_context(tmp_path: Path, capsys) -> None:
    _write_input_artifacts(tmp_path, date="2026-06-30", run_id="source-run")
    raw_dir = tmp_path / "raw" / "positioning" / "2026-06-30"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "cot_gold.json").write_text(
        json.dumps(
            [
                {
                    "Market_and_Exchange_Names": "GOLD - COMMODITY EXCHANGE INC.",
                    "Report_Date_as_YYYY-MM-DD": "2026-06-23",
                    "Open_Interest_All": "400000",
                    "Prod_Merc_Positions_Long_All": "12000",
                    "Prod_Merc_Positions_Short_All": "26000",
                    "Swap_Positions_Long_All": "24000",
                    "Swap__Positions_Short_All": "210000",
                    "M_Money_Positions_Long_All": "240000",
                    "M_Money_Positions_Short_All": "10000",
                },
                {
                    "Market_and_Exchange_Names": "GOLD - COMMODITY EXCHANGE INC.",
                    "Report_Date_as_YYYY-MM-DD": "2026-06-16",
                    "Open_Interest_All": "380000",
                    "Prod_Merc_Positions_Long_All": "11000",
                    "Prod_Merc_Positions_Short_All": "25000",
                    "Swap_Positions_Long_All": "23000",
                    "Swap__Positions_Short_All": "205000",
                    "M_Money_Positions_Long_All": "200000",
                    "M_Money_Positions_Short_All": "15000",
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    options_dir = tmp_path / "outputs" / "cme_options" / "2026-06-30"
    options_dir.mkdir(parents=True, exist_ok=True)
    (options_dir / "options_analysis.json").write_text(
        json.dumps(
            {
                "trade_date": "2026-06-30",
                "data_source": {"product": "GC", "status": "FINAL"},
                "iv_skew_by_expiry": {"JUL26": {"skew_25d": 0.14}},
                "wall_scores": [
                    {"strike": 3350, "wall_type": "Call Wall", "oi": 24000},
                    {"strike": 3250, "wall_type": "Put Wall", "oi": 12000},
                ],
                "intent": {"type": "call_buying"},
                "source_trace": [{"source": "cme_options", "source_ref": "cme:2026-06-30"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    exit_code = run_gold_mainline_pipeline.main(
        [
            "--storage-root",
            str(tmp_path),
            "--date",
            "2026-06-30",
            "--run-id",
            "source-run",
            "--output-run-id",
            "gold-mainlines-cot-positioning-test",
        ]
    )

    assert exit_code == 0
    summary = json.loads(capsys.readouterr().out)
    overview = json.loads((tmp_path / summary["gold_macro_overview_path"]).read_text(encoding="utf-8"))
    expected_positioning_context_path = (
        "analysis/gold_mainlines/2026-06-30/gold-mainlines-cot-positioning-test/positioning_context.json"
    )
    assert overview["input_snapshot_ids"]["positioning_context"] == expected_positioning_context_path
    positioning_context = json.loads((tmp_path / expected_positioning_context_path).read_text(encoding="utf-8"))
    assert positioning_context["comex_net_long"] == 230000
    assert positioning_context["cot_positioning"] == "stretched_long"
    assert positioning_context["positioning_crowding"] == "crowded_long"
    assert positioning_context["option_skew"] == 0.14
    assert positioning_context["call_put_oi_ratio"] == 2.0
    assert positioning_context["institutional_sentiment"] == "call_buying"
    assert positioning_context["source_refs"][0]["source"] == "cftc_cot"
    assert positioning_context["source_refs"][0]["source_tier"] == "official"
    assert positioning_context["source_refs"][0]["lineage_type"] == "raw_artifact"
    assert positioning_context["source_refs"][1]["source_tier"] == "market_derived"

    positioning = next(
        row for row in overview["theme_rankings"] if row["mainline_id"] == "institutional_sentiment"
    )
    assert positioning["feature_fields"]["comex_net_long"] == 230000
    assert positioning["feature_fields"]["cot_positioning"] == "stretched_long"
    assert positioning["feature_fields"]["option_skew"] == 0.14
    assert positioning["missing_data"] == []
    positioning_requirement = next(
        item for item in overview["mainline_requirements"] if item["mainline_id"] == "institutional_sentiment"
    )
    assert positioning_requirement["readiness_status"] == "ready"


def test_run_gold_mainline_pipeline_persists_policy_and_geopolitical_contexts(tmp_path: Path, capsys) -> None:
    _write_input_artifacts(tmp_path, date="2026-06-30", run_id="source-run")
    policy_context_path = tmp_path / "policy_context.json"
    policy_context_path.write_text(
        json.dumps(
            {
                "fed_policy_bias": "higher_for_longer",
                "rate_expectation_delta": 0.32,
                "cut_hike_probability": 0.18,
                "fomc_tone": "hawkish",
                "policy_surprise": "hawkish_repricing",
                "treasury_2y_change": 0.11,
                "treasury_10y_change": 0.08,
                "source_refs": [{"source": "fed", "source_ref": "fomc:2026-06"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    geopolitical_context_path = tmp_path / "geopolitical_context.json"
    geopolitical_context_path.write_text(
        json.dumps(
            {
                "geopolitical_status": "escalating",
                "war_escalation_level": "regional_risk",
                "safe_haven_score": 7.6,
                "energy_channel_risk": "elevated",
                "war_oil_rate_chain_status": "active",
                "vix_reaction": "risk_off",
                "equity_reaction": "selloff",
                "treasury_yield_reaction": "bull_flattening",
                "source_refs": [
                    {"source": "reuters", "source_ref": "geo:1"},
                    {"source": "ap", "source_ref": "geo:2"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    exit_code = run_gold_mainline_pipeline.main(
        [
            "--storage-root",
            str(tmp_path),
            "--date",
            "2026-06-30",
            "--run-id",
            "source-run",
            "--output-run-id",
            "gold-mainlines-verification-test",
            "--policy-context",
            str(policy_context_path),
            "--geopolitical-context",
            str(geopolitical_context_path),
        ]
    )

    assert exit_code == 0
    summary = json.loads(capsys.readouterr().out)
    overview_path = tmp_path / summary["gold_macro_overview_path"]
    overview = json.loads(overview_path.read_text(encoding="utf-8"))

    expected_policy_context_path = "analysis/gold_mainlines/2026-06-30/gold-mainlines-verification-test/policy_context.json"
    assert overview["input_snapshot_ids"]["policy_context"] == expected_policy_context_path
    expected_geopolitical_context_path = "analysis/gold_mainlines/2026-06-30/gold-mainlines-verification-test/geopolitical_context.json"
    assert overview["input_snapshot_ids"]["geopolitical_context"] == expected_geopolitical_context_path
    assert (tmp_path / expected_policy_context_path).exists()
    assert (tmp_path / expected_geopolitical_context_path).exists()

    rankings = {row["mainline_id"]: row for row in overview["theme_rankings"]}
    assert rankings["fed_policy_path"]["feature_fields"]["fed_policy_bias"] == "higher_for_longer"
    assert rankings["geopolitical_war_risk"]["feature_fields"]["war_oil_rate_chain_status"] == "active"


def test_run_gold_mainline_pipeline_auto_loads_macro_policy_context_without_fed_funds(tmp_path: Path, capsys) -> None:
    _write_input_artifacts(tmp_path, date="2026-06-30", run_id="source-run")
    macro_dir = tmp_path / "features" / "macro" / "2026-06-30" / "macro-run"
    macro_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        macro_dir / "macro_snapshot.json",
        {
            "as_of": "2026-06-30",
            "indicators": {
                "US02Y": {"value": 4.14, "weekly_change": 0.12},
                "US10Y": {"value": 4.44, "weekly_change": 0.08},
            },
            "source_refs": {
                "US02Y": {"source": "treasury_yields", "raw_path": "raw/market/us02y.json"},
                "US10Y": {"source": "treasury_yields", "raw_path": "raw/market/us10y.json"},
            },
        },
    )

    exit_code = run_gold_mainline_pipeline.main(
        [
            "--storage-root",
            str(tmp_path),
            "--date",
            "2026-06-30",
            "--run-id",
            "source-run",
            "--output-run-id",
            "gold-mainlines-macro-policy-test",
        ]
    )

    assert exit_code == 0
    summary = json.loads(capsys.readouterr().out)
    overview = json.loads((tmp_path / summary["gold_macro_overview_path"]).read_text(encoding="utf-8"))
    expected_policy_context_path = "analysis/gold_mainlines/2026-06-30/gold-mainlines-macro-policy-test/policy_context.json"
    assert overview["input_snapshot_ids"]["policy_context"] == expected_policy_context_path
    policy_context = json.loads((tmp_path / expected_policy_context_path).read_text(encoding="utf-8"))
    assert policy_context["fed_policy_bias"] == "higher_for_longer"
    assert policy_context["fomc_tone"] is None
    assert policy_context["rate_expectation_delta"] is None
    assert policy_context["cut_hike_probability"] is None
    assert policy_context["treasury_2y_change"] == 0.12
    assert policy_context["treasury_10y_change"] == 0.08
    assert policy_context["source_refs"][0]["source_tier"] == "market_derived"
    assert policy_context["source_refs"][0]["lineage_type"] == "feature_artifact"

    fed = next(row for row in overview["theme_rankings"] if row["mainline_id"] == "fed_policy_path")
    assert fed["feature_fields"]["fed_policy_bias"] == "higher_for_longer"
    assert fed["feature_fields"]["treasury_2y_change"] == 0.12
    assert fed["missing_data"] == ["official_data", "fed_funds_futures"]
    fed_requirement = next(item for item in overview["mainline_requirements"] if item["mainline_id"] == "fed_policy_path")
    assert fed_requirement["readiness_status"] == "partial"
    assert "fed_funds_futures" in fed_requirement["missing_sources"]


def test_run_gold_mainline_pipeline_auto_loads_news_geopolitical_context(tmp_path: Path, capsys) -> None:
    _write_input_artifacts(tmp_path, date="2026-06-30", run_id="source-run")

    exit_code = run_gold_mainline_pipeline.main(
        [
            "--storage-root",
            str(tmp_path),
            "--date",
            "2026-06-30",
            "--run-id",
            "source-run",
            "--output-run-id",
            "gold-mainlines-news-geo-test",
        ]
    )

    assert exit_code == 0
    summary = json.loads(capsys.readouterr().out)
    overview = json.loads((tmp_path / summary["gold_macro_overview_path"]).read_text(encoding="utf-8"))
    expected_geopolitical_context_path = (
        "analysis/gold_mainlines/2026-06-30/gold-mainlines-news-geo-test/geopolitical_context.json"
    )
    assert overview["input_snapshot_ids"]["geopolitical_context"] == expected_geopolitical_context_path
    geopolitical_context = json.loads((tmp_path / expected_geopolitical_context_path).read_text(encoding="utf-8"))
    assert geopolitical_context["geopolitical_status"] == "escalating"
    assert geopolitical_context["war_escalation_level"] == "regional_risk"
    assert geopolitical_context["safe_haven_score"] == 7.2
    assert geopolitical_context["energy_channel_risk"] == "elevated"
    assert geopolitical_context["war_oil_rate_chain_status"] == "active"
    assert geopolitical_context["verification_status"] == "single_source"
    assert geopolitical_context["source_refs"][0]["source_tier"] == "supplemental"
    assert geopolitical_context["source_refs"][0]["lineage_type"] == "feature_artifact"

    rankings = {row["mainline_id"]: row for row in overview["theme_rankings"]}
    geo = rankings["geopolitical_war_risk"]
    assert geo["feature_fields"]["war_escalation_level"] == "regional_risk"
    assert geo["feature_fields"]["war_oil_rate_chain_status"] == "active"
    assert geo["missing_data"] == ["vix", "equity_reaction", "treasury_yields"]
    geo_context_ref = next(ref for ref in geo["source_refs"] if ref.get("evidence_role") == "geopolitical_context")
    assert geo_context_ref["source_tier"] == "supplemental"


def test_run_gold_mainline_pipeline_auto_loads_news_reserve_context_partial(tmp_path: Path, capsys) -> None:
    date = "2026-06-30"
    _write_news_artifacts(
        tmp_path,
        date=date,
        run_id="source-run",
        events=[
            {
                "event_id": "event:reserve",
                "event_type": "central_bank_gold_buying",
                "event_time": f"{date}T08:00:00+00:00",
                "direction": "bullish",
                "confidence": 0.64,
                "verification_status": "single_source",
                "source_refs": [{"source": "wgc_news", "source_ref": "reserve:watch"}],
            }
        ],
        impacts=[{"event_id": "event:reserve", "impact_path": "reserve_reallocation", "gold_impact": "bullish"}],
    )

    exit_code = run_gold_mainline_pipeline.main(
        [
            "--storage-root",
            str(tmp_path),
            "--date",
            date,
            "--run-id",
            "source-run",
            "--output-run-id",
            "gold-mainlines-news-reserve-test",
        ]
    )

    assert exit_code == 0
    summary = json.loads(capsys.readouterr().out)
    overview = json.loads((tmp_path / summary["gold_macro_overview_path"]).read_text(encoding="utf-8"))
    expected_reserve_context_path = "analysis/gold_mainlines/2026-06-30/gold-mainlines-news-reserve-test/reserve_context.json"
    assert overview["input_snapshot_ids"]["reserve_context"] == expected_reserve_context_path
    reserve_context = json.loads((tmp_path / expected_reserve_context_path).read_text(encoding="utf-8"))
    assert reserve_context["central_bank_net_buying"] is None
    assert reserve_context["pboc_gold_holdings_change"] is None
    assert reserve_context["reserve_diversification_signal"] == "central_bank_gold_buying_watch"
    assert reserve_context["long_term_support_score"] == 6.4
    assert reserve_context["source_refs"][0]["source_tier"] == "supplemental"

    reserve = next(row for row in overview["theme_rankings"] if row["mainline_id"] == "central_bank_gold")
    assert reserve["feature_fields"]["long_term_support_score"] == 6.4
    assert reserve["missing_data"] == ["central_bank_reserves"]
    reserve_requirement = next(item for item in overview["mainline_requirements"] if item["mainline_id"] == "central_bank_gold")
    assert reserve_requirement["readiness_status"] == "partial"


def test_run_gold_mainline_pipeline_auto_loads_news_asia_context_partial(tmp_path: Path, capsys) -> None:
    date = "2026-06-30"
    _write_news_artifacts(
        tmp_path,
        date=date,
        run_id="source-run",
        events=[
            {
                "event_id": "event:asia",
                "event_type": "shanghai_gold_premium",
                "event_time": f"{date}T08:00:00+00:00",
                "direction": "bullish",
                "confidence": 0.7,
                "shanghai_gold_premium": 42.5,
                "verification_status": "single_source",
                "source_refs": [{"source": "sge_news", "source_ref": "premium:watch"}],
            }
        ],
        impacts=[{"event_id": "event:asia", "impact_path": "asia_demand", "gold_impact": "bullish"}],
    )

    exit_code = run_gold_mainline_pipeline.main(
        [
            "--storage-root",
            str(tmp_path),
            "--date",
            date,
            "--run-id",
            "source-run",
            "--output-run-id",
            "gold-mainlines-news-asia-test",
        ]
    )

    assert exit_code == 0
    summary = json.loads(capsys.readouterr().out)
    overview = json.loads((tmp_path / summary["gold_macro_overview_path"]).read_text(encoding="utf-8"))
    expected_asia_context_path = "analysis/gold_mainlines/2026-06-30/gold-mainlines-news-asia-test/asia_context.json"
    assert overview["input_snapshot_ids"]["asia_context"] == expected_asia_context_path
    asia_context = json.loads((tmp_path / expected_asia_context_path).read_text(encoding="utf-8"))
    assert asia_context["shanghai_gold_premium"] == 42.5
    assert asia_context["asia_demand_score"] == 7.0
    assert asia_context["source_refs"][0]["source_tier"] == "supplemental"

    asia = next(row for row in overview["theme_rankings"] if row["mainline_id"] == "china_asia_demand")
    assert asia["feature_fields"]["shanghai_gold_premium"] == 42.5
    assert asia["feature_fields"]["asia_demand_score"] == 7.0
    assert asia["missing_data"] == ["fx_market", "china_gold_etf", "india_physical_demand"]
    asia_requirement = next(item for item in overview["mainline_requirements"] if item["mainline_id"] == "china_asia_demand")
    assert asia_requirement["readiness_status"] == "partial"
