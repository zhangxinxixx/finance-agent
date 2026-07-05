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
                    "DXY": {"value": 100.7, "weekly_change": -0.4},
                },
                "source_refs": {
                    "REAL_10Y": {"source": "fred", "raw_path": "raw/macro/real.json"},
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
            ]
        )

    assert exit_code == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["run_mode"] == "premarket_full_run"
    assert summary["trigger_reason"] == "daily_premarket_refresh"
    assert "source_health_agent" in summary["agents_executed"]
    assert "report_render_agent" in summary["agents_executed"]
    assert "real_rates_dollar" in summary["affected_mainlines"]
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
    assert overview["review_status"] == "needs_review"
    assert overview["input_snapshot_ids"]["gold_event_mainlines"] == summary["gold_event_mainlines_path"]
    assert overview["input_snapshot_ids"]["macro_snapshot"] == "features/macro/2026-06-30/macro-run/macro_snapshot.json"
    assert overview["input_snapshot_ids"]["market_context"] == market_context_path.as_posix()
    assert overview["war_oil_rate_chain"]["path_id"] == "geopolitics_to_oil_to_rates"
    rankings = {row["mainline_id"]: row for row in overview["theme_rankings"]}
    assert rankings["real_rates_usd"]["feature_fields"]["real_rate_level"] == 2.2
    assert rankings["gold_technical_levels"]["feature_fields"]["gold_spot_price"] == 4115.0


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
    assert summary["review_status"] == "blocked"

    overview = json.loads((tmp_path / summary["gold_macro_overview_path"]).read_text(encoding="utf-8"))
    assert overview["status"] == "blocked"
    assert overview["source_health"]["p0_missing"] == ["xauusd_price"]
    assert overview["review_status"] == "blocked"
    assert overview["review_blocking_reasons"] == [
        "P0 source gap conflicts with strong GoldMacroOverview conclusion"
    ]


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
    assert "oil_price" in summary["affected_mainlines"]
    assert "geopolitical_war" in summary["affected_mainlines"]
    assert "report_render_agent" in summary["agents_skipped"]
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
    error = json.loads(capsys.readouterr().err)
    assert error["status"] == "error"
    assert "Unknown Gold runtime mode" in error["error"]
