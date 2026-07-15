from __future__ import annotations

import json
import os
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.services.gold_mainline_service import (
    get_gold_mainlines,
    get_gold_mainlines_latest,
)

client = TestClient(app)

_PROJECT_ROOT_PATCH = "apps.api.services.gold_mainline_service._PROJECT_ROOT"
_ALL_MAINLINES = [
    "fed_policy_path",
    "real_rates_usd",
    "oil_prices",
    "geopolitical_war_risk",
    "etf_flows",
    "institutional_sentiment",
    "central_bank_gold",
    "china_asia_demand",
    "gold_technical_levels",
]


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
                "latest_health_at": "2026-06-11T12:00:00+00:00",
                "source_refs": [{"source_ref": f"storage/{source_key}.json"}],
            }
            for source_key in p0_sources
            if source_key not in missing
        ]
    }


def _write_gold_artifacts(
    root: Path,
    *,
    date: str,
    run_id: str,
    dominant_mainline: str,
) -> tuple[Path, Path]:
    storage_root = root / "storage"
    mainlines_path = storage_root / "features" / "news" / date / run_id / "gold_event_mainlines.json"
    overview_path = storage_root / "analysis" / "gold_mainlines" / date / run_id / "gold_macro_overview.json"
    mainlines_path.parent.mkdir(parents=True, exist_ok=True)
    overview_path.parent.mkdir(parents=True, exist_ok=True)
    mainlines_path.write_text(
        json.dumps(
            {
                "schema_version": "gold-event-mainlines-v1",
                "asset": "XAUUSD",
                "as_of": f"{date}T12:00:00+00:00",
                "status": "partial",
                "mainlines": [
                    {"mainline_id": dominant_mainline, "rank": 1, "event_ids": ["event:fed"]}
                ],
                "event_links": [
                    {
                        "event_id": "event:fed",
                        "primary_mainline": dominant_mainline,
                        "mainline_ids": [dominant_mainline],
                        "transmission_path_ids": ["inflation_to_real_rates"],
                        "source_refs": [{"source": "fed_rss", "source_ref": "fed:test"}],
                    }
                ],
                "dominant_forces": [dominant_mainline],
                "source_refs": [{"source": "fed_rss", "source_ref": "fed:test"}],
                "warnings": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    theme_rankings = []
    for rank, mainline_id in enumerate(_ALL_MAINLINES, start=1):
        row: dict[str, object] = {
            "mainline_id": mainline_id,
            "label": mainline_id,
            "pricing_layer": "rate_pricing" if mainline_id in {"fed_policy_path", "real_rates_usd"} else "risk_pricing",
            "rank": rank,
            "score": round(84 - ((rank - 1) * 5.5), 1),
            "theme_score": round(84 - ((rank - 1) * 5.5), 1),
            "direction_score": -1 if mainline_id in {"fed_policy_path", "real_rates_usd", "oil_prices"} else 0,
            "impact_score": 3 if mainline_id in {"fed_policy_path", "real_rates_usd", "oil_prices"} else 1,
            "confidence_score": 3 if rank <= 3 else 2,
            "freshness_score": 2 if rank <= 3 else 1,
            "direction": "neutral_bearish" if mainline_id in {"fed_policy_path", "real_rates_usd", "oil_prices"} else "neutral",
            "confidence": 0.75 if rank <= 3 else 0.42,
            "verification_status": "multi_source" if rank <= 2 else "single_source",
            "trend": "rising" if rank <= 2 else "stable",
            "summary": f"{mainline_id} summary",
            "bullish_drivers": [],
            "bearish_drivers": [],
            "event_ids": ["event:fed"] if mainline_id in {dominant_mainline, "fed_policy_path", "real_rates_usd"} else [],
            "source_refs": [{"source": "fed_rss", "source_ref": "fed:test"}] if rank <= 3 else [],
        }
        if mainline_id == dominant_mainline:
            row["dominant"] = True
        if mainline_id == "real_rates_usd":
            row["verification_needed"] = ["real_rate_response_needed"]
            row["missing_data"] = ["real_rates"]
        if mainline_id == "oil_prices":
            row["verification_needed"] = ["oil_price_reaction_needed"]
            row["missing_data"] = ["oil_price"]
        if mainline_id == "gold_technical_levels":
            row["verification_needed"] = ["price_level_confirmation_needed"]
            row["missing_data"] = ["xauusd_price"]
        theme_rankings.append(row)

    overview_path.write_text(
        json.dumps(
            {
                "schema_version": "gold-macro-overview-v1",
                "retrieved_date": date,
                "run_id": run_id,
                "input_snapshot_ids": {
                    "gold_event_mainlines": f"features/news/{date}/{run_id}/gold_event_mainlines.json",
                },
                "status": "partial",
                "asset": "XAUUSD",
                "as_of": f"{date}T12:00:00+00:00",
                "phase": "weak_repair_watch",
                "dominant_mainline": dominant_mainline,
                "net_bias": "neutral_bearish",
                "risk_score": 68,
                "one_line_conclusion": "实际利率与美元是当前主导压力。",
                "theme_rankings": theme_rankings,
                "driver_conflict": {
                    "status": "mixed",
                    "dominant_driver": "higher_for_longer_rate_pressure",
                    "bullish_drivers": ["safe_haven_bid"],
                    "bearish_drivers": ["higher_for_longer_rate_pressure", "oil_inflation_rate_pressure"],
                    "net_effect": "neutral_bearish",
                    "explanation": "fixture",
                    "verification_needed": ["real_rate_response_needed", "oil_price_reaction_needed"],
                    "source_refs": [{"source": "fed_rss", "source_ref": "fed:test"}],
                },
                "war_oil_rate_chain": {
                    "path_id": "geopolitics_to_oil_to_rates",
                    "label": "地缘 -> 石油 -> 利率",
                    "status": "partial",
                    "conclusion_code": "B",
                    "conclusion_label": "通胀/加息主导，压制黄金",
                    "net_effect": "neutral_bearish",
                    "oil_status": "partial",
                    "real_rate_status": "partial",
                    "gold_effect": "neutral_bearish",
                    "verification_needed": ["oil_price_reaction_needed", "real_rate_response_needed"],
                    "dominant_driver": "oil_inflation_rate_pressure",
                    "summary": "地缘风险经由油价与通胀预期抬升利率压力。",
                    "steps": [
                        {"id": "war", "label": "地缘事件升温", "status": "available"},
                        {"id": "oil", "label": "油价上行", "status": "partial"},
                        {"id": "rates", "label": "实际利率承压", "status": "partial"},
                    ],
                    "source_refs": [{"source": "fed_rss", "source_ref": "fed:test"}],
                    "artifact_refs": [],
                },
                "verification_matrix": [
                    {
                        "id": "verify-real-rates",
                        "label": "确认实际利率压力",
                        "status": "pending",
                        "mainline_id": "real_rates_usd",
                        "required_source": "real_rates",
                        "reason": "需要确认实际利率是否继续上行",
                        "source_refs": [{"source": "fed_rss", "source_ref": "fed:test"}],
                    },
                    {
                        "id": "verify-oil",
                        "label": "确认油价传导",
                        "status": "pending",
                        "mainline_id": "oil_prices",
                        "required_source": "oil_price",
                        "reason": "需要确认油价对通胀与利率预期的二次传导",
                        "source_refs": [{"source": "fed_rss", "source_ref": "fed:test"}],
                    },
                    {
                        "id": "verify-technical",
                        "label": "确认金价关键位",
                        "status": "unavailable",
                        "mainline_id": "gold_technical_levels",
                        "required_source": "xauusd_price",
                        "reason": "缺少现货金价关键位验证",
                        "source_refs": [],
                    },
                ],
                "key_events": ["event:fed"],
                "source_refs": [{"source": "fed_rss", "source_ref": "fed:test"}],
                "artifact_refs": [],
                "warnings": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return overview_path, mainlines_path


def test_get_gold_mainlines_latest_loads_overview_and_event_mainlines(tmp_path: Path) -> None:
    _write_gold_artifacts(tmp_path, date="2026-06-10", run_id="run-old", dominant_mainline="fed_policy_path")
    overview_path, mainlines_path = _write_gold_artifacts(
        tmp_path,
        date="2026-06-11",
        run_id="run-new",
        dominant_mainline="real_rates_usd",
    )
    macro_dir = tmp_path / "storage" / "features" / "macro" / "2026-06-11" / "macro-run"
    macro_dir.mkdir(parents=True, exist_ok=True)
    (macro_dir / "macro_snapshot.json").write_text(
        json.dumps(
            {
                "as_of": "2026-06-11",
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

    with (
        mock.patch(_PROJECT_ROOT_PATCH, tmp_path),
        mock.patch(
            "apps.api.services.gold_mainline_service._get_market_monitor_overview",
            lambda: {
                "generated_at": "2026-06-11T12:05:00+00:00",
                "source": "api",
                "metrics": [
                    {
                        "key": "XAUUSD",
                        "latest_value": 4115.0,
                        "unit": "USD/oz",
                        "status": "ok",
                        "interpretation": "market_candles_latest",
                    }
                ],
                "source_trace": [{"source": "market_monitor", "source_ref": "api://market/monitor"}],
            },
        ),
    ):
        payload = get_gold_mainlines_latest()

    assert payload["status"] == "partial"
    assert payload["date"] == "2026-06-11"
    assert payload["run_id"] == "run-new"
    assert payload["artifact_path"] == overview_path.relative_to(tmp_path).as_posix()
    assert payload["gold_macro_overview"]["dominant_mainline"] == "real_rates_usd"
    assert len(payload["gold_macro_overview"]["theme_rankings"]) == 9
    overview_ranking = next(
        row for row in payload["gold_macro_overview"]["theme_rankings"] if row["mainline_id"] == "real_rates_usd"
    )
    assert overview_ranking["mainline"] == "real_rates_usd"
    assert overview_ranking["impact_strength"] == "high"
    assert overview_ranking["freshness"] == "fresh"
    assert overview_ranking["evidence_count"] >= 3
    assert overview_ranking["missing_data"] == []
    assert overview_ranking["feature_fields"]["real_rate_level"] == 2.2
    assert overview_ranking["feature_fields"]["yield_spread_2y_3m_level"] == -0.45
    assert overview_ranking["feature_fields"]["yield_curve_2y3m_signal"] == "pivot_window_improving"
    assert "黄金低点确认概率提高" in overview_ranking["feature_fields"]["yield_curve_2y3m_market_meaning"]
    assert overview_ranking["feature_fields"]["dxy_trend"] == "falling"
    assert overview_ranking["related_event_ids"] == ["event:fed"]
    oil_ranking = next(
        row for row in payload["gold_macro_overview"]["theme_rankings"] if row["mainline_id"] == "oil_prices"
    )
    assert oil_ranking["missing_data"] == ["oil_price"]
    verification_matrix = payload["gold_macro_overview"]["verification_matrix"]
    verification_mainlines = {item["mainline_id"] for item in verification_matrix}
    assert "oil_prices" in verification_mainlines
    assert ("real_rates_usd", "real_rates") not in {
        (item["mainline_id"], item["required_source"]) for item in verification_matrix
    }
    assert ("gold_technical_levels", "xauusd_price") not in {
        (item["mainline_id"], item["required_source"]) for item in verification_matrix
    }
    assert payload["gold_macro_overview"]["driver_conflict"]["verification_needed"] == [
        "real_rate_response_needed",
        "oil_price_reaction_needed",
    ]
    assert payload["gold_macro_overview"]["war_oil_rate_chain"]["path_id"] == "geopolitics_to_oil_to_rates"
    assert payload["gold_macro_overview"]["war_oil_rate_chain"]["dominant_driver"] == "oil_inflation_rate_pressure"
    requirements = payload["gold_macro_overview"]["mainline_requirements"]
    assert len(requirements) == 9
    assert requirements[0]["mainline_id"] == "fed_policy_path"
    assert requirements[0]["required_fields"] == [
        "fed_policy_bias",
        "rate_expectation_delta",
        "cut_hike_probability",
        "fomc_tone",
        "policy_surprise",
    ]
    assert payload["gold_macro_overview"]["analysis_readiness"]["total_count"] == 9
    real_rate_requirement = next(item for item in requirements if item["mainline_id"] == "real_rates_usd")
    assert real_rate_requirement["readiness_status"] == "ready"
    technical_ranking = next(
        row for row in payload["gold_macro_overview"]["theme_rankings"] if row["mainline_id"] == "gold_technical_levels"
    )
    assert technical_ranking["missing_data"] == []
    assert technical_ranking["feature_fields"]["gold_spot_price"] == 4115.0
    assert technical_ranking["feature_fields"]["level_4100_4120_status"] == "inside"
    technical_requirement = next(item for item in requirements if item["mainline_id"] == "gold_technical_levels")
    assert technical_requirement["readiness_status"] == "ready"
    assert payload["gold_macro_overview"]["analysis_readiness"]["missing_count"] >= 1
    assert payload["gold_macro_overview"]["architecture_gaps"]
    assert payload["gold_mainlines"]["status"] == "partial"
    assert payload["gold_mainlines"]["artifact_path"] == mainlines_path.relative_to(tmp_path).as_posix()
    mainline = payload["gold_mainlines"]["mainlines"][0]
    assert mainline["mainline"] == "real_rates_usd"
    assert mainline["impact_strength"] == "high"
    assert mainline["freshness"] == "fresh"
    assert mainline["evidence_count"] == 1
    assert mainline["missing_data"] == []
    assert mainline["related_event_ids"] == ["event:fed"]
    assert payload["gold_mainlines"]["event_links"][0]["primary_mainline"] == "real_rates_usd"
    assert payload["source_refs"] == [{"source": "fed_rss", "source_ref": "fed:test"}]


def test_get_gold_mainlines_latest_uses_artifact_time_not_run_id_order(tmp_path: Path) -> None:
    older_path, _ = _write_gold_artifacts(
        tmp_path,
        date="2026-06-11",
        run_id="z-lexically-latest",
        dominant_mainline="fed_policy_path",
    )
    newer_path, _ = _write_gold_artifacts(
        tmp_path,
        date="2026-06-11",
        run_id="a-actually-latest",
        dominant_mainline="real_rates_usd",
    )
    os.utime(older_path, ns=(1_000_000_000, 1_000_000_000))
    os.utime(newer_path, ns=(2_000_000_000, 2_000_000_000))

    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        payload = get_gold_mainlines_latest()

    assert payload["run_id"] == "a-actually-latest"
    assert payload["artifact_path"] == newer_path.relative_to(tmp_path).as_posix()


def test_get_gold_mainlines_returns_read_time_source_health_without_overriding_artifact(tmp_path: Path) -> None:
    _write_gold_artifacts(
        tmp_path,
        date="2026-06-12",
        run_id="run-source-health",
        dominant_mainline="real_rates_usd",
    )

    with (
        mock.patch(_PROJECT_ROOT_PATCH, tmp_path),
        mock.patch(
            "apps.api.services.gold_mainline_service.get_data_source_statuses",
            return_value=_gold_v3_source_status_payload(missing={"xauusd_price"}),
        ),
    ):
        payload = get_gold_mainlines_latest()

    overview = payload["gold_macro_overview"]
    source_health = payload["read_time_source_health"]
    assert payload["status"] == "partial"
    assert overview["status"] == "partial"
    assert source_health["overall_status"] == "blocked"
    assert source_health["p0_missing"] == ["xauusd_price"]
    assert source_health["can_build_gold_macro_overview"] is False
    assert overview.get("source_health") is None
    assert "source_health blocked strong GoldMacroOverview conclusion" not in payload["warnings"]


def test_get_gold_mainlines_read_time_source_health_does_not_block_historical_strong_overview(tmp_path: Path) -> None:
    overview_path, _mainlines_path = _write_gold_artifacts(
        tmp_path,
        date="2026-06-13",
        run_id="run-source-health-block",
        dominant_mainline="real_rates_usd",
    )
    overview_payload = json.loads(overview_path.read_text(encoding="utf-8"))
    overview_payload["phase"] = "strong_uptrend"
    overview_payload["one_line_conclusion"] = "strong bullish breakout"
    overview_path.write_text(json.dumps(overview_payload, ensure_ascii=False), encoding="utf-8")

    with (
        mock.patch(_PROJECT_ROOT_PATCH, tmp_path),
        mock.patch(
            "apps.api.services.gold_mainline_service.get_data_source_statuses",
            return_value=_gold_v3_source_status_payload(missing={"xauusd_price"}),
        ),
    ):
        payload = get_gold_mainlines_latest()

    overview = payload["gold_macro_overview"]
    assert payload["status"] == "partial"
    assert overview["status"] == "partial"
    assert overview.get("review_status") != "blocked"
    assert overview.get("review_blocking_reasons") is None
    assert "P0 source gap conflicts with strong GoldMacroOverview conclusion" in payload["read_time_source_health"]["blocking_reasons"]
    assert "read_time_source_health would block strong GoldMacroOverview conclusion" in payload["read_time_warnings"]


def test_get_gold_mainlines_latest_infers_overview_from_event_mainlines(tmp_path: Path) -> None:
    overview_path, _mainlines_path = _write_gold_artifacts(
        tmp_path,
        date="2026-06-14",
        run_id="run-event-only",
        dominant_mainline="fed_policy_path",
    )
    overview_path.unlink()

    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        payload = get_gold_mainlines_latest()

    assert payload["status"] == "partial"
    assert payload["date"] == "2026-06-14"
    assert payload["run_id"] == "run-event-only"
    assert payload["artifact_path"] is None
    assert payload["input_snapshot_ids"]["gold_event_mainlines"] == (
        "features/news/2026-06-14/run-event-only/gold_event_mainlines.json"
    )
    assert payload["gold_macro_overview"]["dominant_mainline"] in _ALL_MAINLINES
    assert len(payload["gold_macro_overview"]["theme_rankings"]) == 9
    assert any(
        row["mainline_id"] == "fed_policy_path"
        for row in payload["gold_macro_overview"]["theme_rankings"]
    )
    assert payload["gold_mainlines"]["mainlines"][0]["mainline_id"] == "fed_policy_path"
    assert "gold_macro_overview inferred from gold_event_mainlines artifact" in payload["warnings"]


def test_get_gold_mainlines_exact_infers_overview_from_event_mainlines(tmp_path: Path) -> None:
    overview_path, _mainlines_path = _write_gold_artifacts(
        tmp_path,
        date="2026-06-15",
        run_id="run-exact-event-only",
        dominant_mainline="oil_prices",
    )
    overview_path.unlink()

    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        payload = get_gold_mainlines(date="2026-06-15", run_id="run-exact-event-only")

    assert payload["status"] == "partial"
    assert payload["date"] == "2026-06-15"
    assert payload["run_id"] == "run-exact-event-only"
    assert payload["artifact_path"] is None
    assert payload["gold_macro_overview"]["dominant_mainline"] in _ALL_MAINLINES
    assert len(payload["gold_macro_overview"]["theme_rankings"]) == 9
    assert any(
        row["mainline_id"] == "oil_prices"
        for row in payload["gold_macro_overview"]["theme_rankings"]
    )


def test_get_gold_mainlines_uses_persisted_market_context_without_live_service(tmp_path: Path) -> None:
    overview_path, _mainlines_path = _write_gold_artifacts(
        tmp_path,
        date="2026-06-16",
        run_id="run-persisted-market",
        dominant_mainline="fed_policy_path",
    )
    market_context_path = (
        tmp_path
        / "storage"
        / "analysis"
        / "gold_mainlines"
        / "2026-06-16"
        / "run-persisted-market"
        / "market_context.json"
    )
    market_context_path.write_text(
        json.dumps(
            {
                "gold_spot_price": 4077.0,
                "source_refs": [{"source": "market_candles", "source_ref": "XAUUSD:1d"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    overview_payload = json.loads(overview_path.read_text(encoding="utf-8"))
    overview_payload["input_snapshot_ids"]["market_context"] = (
        "analysis/gold_mainlines/2026-06-16/run-persisted-market/market_context.json"
    )
    overview_path.write_text(json.dumps(overview_payload, ensure_ascii=False), encoding="utf-8")

    with (
        mock.patch(_PROJECT_ROOT_PATCH, tmp_path),
        mock.patch(
            "apps.api.services.gold_mainline_service._get_market_monitor_overview",
            side_effect=AssertionError("live market service should not be called"),
        ),
    ):
        payload = get_gold_mainlines(date="2026-06-16", run_id="run-persisted-market")

    technical_ranking = next(
        row for row in payload["gold_macro_overview"]["theme_rankings"] if row["mainline_id"] == "gold_technical_levels"
    )
    assert technical_ranking["missing_data"] == []
    assert technical_ranking["feature_fields"]["gold_spot_price"] == 4077.0
    technical_requirement = next(
        item for item in payload["gold_macro_overview"]["mainline_requirements"] if item["mainline_id"] == "gold_technical_levels"
    )
    assert technical_requirement["readiness_status"] == "ready"


def test_get_gold_mainlines_uses_persisted_oil_context_for_chain_and_oil_features(tmp_path: Path) -> None:
    overview_path, _mainlines_path = _write_gold_artifacts(
        tmp_path,
        date="2026-06-17",
        run_id="run-persisted-oil",
        dominant_mainline="oil_prices",
    )
    mainlines_path = tmp_path / "storage" / "features" / "news" / "2026-06-17" / "run-persisted-oil" / "gold_event_mainlines.json"
    mainlines_payload = json.loads(mainlines_path.read_text(encoding="utf-8"))
    mainlines_payload["event_links"][0].update(
        {
            "primary_mainline": "oil_prices",
            "mainline_ids": ["oil_prices", "geopolitical_war_risk"],
            "transmission_path_ids": ["geopolitics_to_oil_to_rates"],
            "direction_by_asset": {"XAUUSD": "mixed"},
            "verification_status": "multi_source",
            "bullish_drivers": ["safe_haven_bid"],
            "bearish_drivers": ["oil_inflation_rate_pressure"],
            "verification_needed": ["oil_price_reaction_needed", "real_rate_response_needed"],
        }
    )
    mainlines_path.write_text(json.dumps(mainlines_payload, ensure_ascii=False), encoding="utf-8")
    oil_context_path = (
        tmp_path
        / "storage"
        / "analysis"
        / "gold_mainlines"
        / "2026-06-17"
        / "run-persisted-oil"
        / "oil_context.json"
    )
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
    macro_dir = tmp_path / "storage" / "features" / "macro" / "2026-06-17" / "macro-run"
    macro_dir.mkdir(parents=True, exist_ok=True)
    (macro_dir / "macro_snapshot.json").write_text(
        json.dumps(
            {
                "as_of": "2026-06-17",
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
    overview_payload = json.loads(overview_path.read_text(encoding="utf-8"))
    overview_payload["input_snapshot_ids"]["oil_context"] = (
        "analysis/gold_mainlines/2026-06-17/run-persisted-oil/oil_context.json"
    )
    overview_path.write_text(json.dumps(overview_payload, ensure_ascii=False), encoding="utf-8")

    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        payload = get_gold_mainlines(date="2026-06-17", run_id="run-persisted-oil")

    oil_ranking = next(
        row for row in payload["gold_macro_overview"]["theme_rankings"] if row["mainline_id"] == "oil_prices"
    )
    assert oil_ranking["missing_data"] == []
    assert oil_ranking["feature_fields"]["oil_price_trend"] == "rising"
    assert oil_ranking["feature_fields"]["oil_to_fed_pressure"] == "safe_haven_offset"
    oil_requirement = next(
        item for item in payload["gold_macro_overview"]["mainline_requirements"] if item["mainline_id"] == "oil_prices"
    )
    assert oil_requirement["readiness_status"] == "ready"
    assert payload["gold_macro_overview"]["war_oil_rate_chain"]["conclusion_code"] == "A"


def test_get_gold_mainlines_uses_persisted_flow_context_for_etf_features(tmp_path: Path) -> None:
    overview_path, _mainlines_path = _write_gold_artifacts(
        tmp_path,
        date="2026-06-18",
        run_id="run-persisted-flow",
        dominant_mainline="etf_flows",
    )
    flow_context_path = (
        tmp_path
        / "storage"
        / "analysis"
        / "gold_mainlines"
        / "2026-06-18"
        / "run-persisted-flow"
        / "flow_context.json"
    )
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
    overview_payload = json.loads(overview_path.read_text(encoding="utf-8"))
    overview_payload["input_snapshot_ids"]["flow_context"] = (
        "analysis/gold_mainlines/2026-06-18/run-persisted-flow/flow_context.json"
    )
    overview_path.write_text(json.dumps(overview_payload, ensure_ascii=False), encoding="utf-8")

    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        payload = get_gold_mainlines(date="2026-06-18", run_id="run-persisted-flow")

    etf_ranking = next(
        row for row in payload["gold_macro_overview"]["theme_rankings"] if row["mainline_id"] == "etf_flows"
    )
    assert etf_ranking["missing_data"] == []
    assert etf_ranking["feature_fields"]["global_etf_flow"] == 18.4
    assert etf_ranking["feature_fields"]["etf_flow_trend"] == "inflow"
    assert etf_ranking["feature_fields"]["flow_confirmation_status"] == "confirmed_inflow"
    etf_requirement = next(
        item for item in payload["gold_macro_overview"]["mainline_requirements"] if item["mainline_id"] == "etf_flows"
    )
    assert etf_requirement["readiness_status"] == "ready"


def test_get_gold_mainlines_loads_context_from_artifact_refs_when_snapshot_id_missing(tmp_path: Path) -> None:
    overview_path, _mainlines_path = _write_gold_artifacts(
        tmp_path,
        date="2026-06-18",
        run_id="run-artifact-ref-flow",
        dominant_mainline="etf_flows",
    )
    flow_context_rel_path = "analysis/gold_mainlines/2026-06-18/run-artifact-ref-flow/flow_context.json"
    flow_context_path = tmp_path / "storage" / flow_context_rel_path
    flow_context_path.write_text(
        json.dumps(
            {
                "global_etf_flow": 22.0,
                "north_america_etf_flow": 15.5,
                "asia_etf_flow": 3.8,
                "source_refs": [{"source": "wgc", "source_ref": "gold_etf:artifact-ref"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    overview_payload = json.loads(overview_path.read_text(encoding="utf-8"))
    overview_payload["artifact_refs"] = [
        {"artifact_type": "flow_context", "path": flow_context_rel_path},
    ]
    overview_path.write_text(json.dumps(overview_payload, ensure_ascii=False), encoding="utf-8")

    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        payload = get_gold_mainlines(date="2026-06-18", run_id="run-artifact-ref-flow")

    etf_ranking = next(
        row for row in payload["gold_macro_overview"]["theme_rankings"] if row["mainline_id"] == "etf_flows"
    )
    assert etf_ranking["missing_data"] == []
    assert etf_ranking["feature_fields"]["global_etf_flow"] == 22.0
    flow_ref = next(
        ref
        for ref in etf_ranking["source_refs"]
        if ref.get("source") == "wgc" and ref.get("source_ref") == "gold_etf:artifact-ref"
    )
    assert flow_ref["source_tier"] == "official"
    assert flow_ref["evidence_role"] == "flow_context"
    assert flow_ref["lineage_type"] == "context_artifact"
    etf_requirement = next(
        item for item in payload["gold_macro_overview"]["mainline_requirements"] if item["mainline_id"] == "etf_flows"
    )
    assert etf_requirement["readiness_status"] == "ready"


def test_get_gold_mainlines_uses_persisted_reserve_and_asia_contexts(tmp_path: Path) -> None:
    overview_path, _mainlines_path = _write_gold_artifacts(
        tmp_path,
        date="2026-06-19",
        run_id="run-persisted-structural",
        dominant_mainline="central_bank_gold",
    )
    reserve_context_path = (
        tmp_path
        / "storage"
        / "analysis"
        / "gold_mainlines"
        / "2026-06-19"
        / "run-persisted-structural"
        / "reserve_context.json"
    )
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
    asia_context_path = (
        tmp_path
        / "storage"
        / "analysis"
        / "gold_mainlines"
        / "2026-06-19"
        / "run-persisted-structural"
        / "asia_context.json"
    )
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
    overview_payload = json.loads(overview_path.read_text(encoding="utf-8"))
    overview_payload["input_snapshot_ids"]["reserve_context"] = (
        "analysis/gold_mainlines/2026-06-19/run-persisted-structural/reserve_context.json"
    )
    overview_payload["input_snapshot_ids"]["asia_context"] = (
        "analysis/gold_mainlines/2026-06-19/run-persisted-structural/asia_context.json"
    )
    overview_path.write_text(json.dumps(overview_payload, ensure_ascii=False), encoding="utf-8")

    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        payload = get_gold_mainlines(date="2026-06-19", run_id="run-persisted-structural")

    central = next(
        row for row in payload["gold_macro_overview"]["theme_rankings"] if row["mainline_id"] == "central_bank_gold"
    )
    assert central["missing_data"] == []
    assert central["feature_fields"]["central_bank_net_buying"] == 61.0
    assert central["feature_fields"]["long_term_support_score"] == 8.2
    central_requirement = next(
        item for item in payload["gold_macro_overview"]["mainline_requirements"] if item["mainline_id"] == "central_bank_gold"
    )
    assert central_requirement["readiness_status"] == "ready"

    asia = next(
        row for row in payload["gold_macro_overview"]["theme_rankings"] if row["mainline_id"] == "china_asia_demand"
    )
    assert asia["missing_data"] == []
    assert asia["feature_fields"]["usdcnh_trend"] == "falling"
    assert asia["feature_fields"]["shanghai_gold_premium"] == 42.5
    assert asia["feature_fields"]["cny_gold_relative_strength"] == "supportive"
    asia_requirement = next(
        item for item in payload["gold_macro_overview"]["mainline_requirements"] if item["mainline_id"] == "china_asia_demand"
    )
    assert asia_requirement["readiness_status"] == "ready"


def test_get_gold_mainlines_uses_persisted_positioning_context(tmp_path: Path) -> None:
    overview_path, _mainlines_path = _write_gold_artifacts(
        tmp_path,
        date="2026-06-20",
        run_id="run-persisted-positioning",
        dominant_mainline="institutional_sentiment",
    )
    positioning_context_path = (
        tmp_path
        / "storage"
        / "analysis"
        / "gold_mainlines"
        / "2026-06-20"
        / "run-persisted-positioning"
        / "positioning_context.json"
    )
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
    overview_payload = json.loads(overview_path.read_text(encoding="utf-8"))
    overview_payload["input_snapshot_ids"]["positioning_context"] = (
        "analysis/gold_mainlines/2026-06-20/run-persisted-positioning/positioning_context.json"
    )
    overview_path.write_text(json.dumps(overview_payload, ensure_ascii=False), encoding="utf-8")

    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        payload = get_gold_mainlines(date="2026-06-20", run_id="run-persisted-positioning")

    positioning = next(
        row for row in payload["gold_macro_overview"]["theme_rankings"] if row["mainline_id"] == "institutional_sentiment"
    )
    assert positioning["missing_data"] == []
    assert positioning["feature_fields"]["comex_net_long"] == 185000
    assert positioning["feature_fields"]["call_put_oi_ratio"] == 0.82
    assert positioning["feature_fields"]["positioning_crowding"] == "crowded_long"
    positioning_requirement = next(
        item for item in payload["gold_macro_overview"]["mainline_requirements"] if item["mainline_id"] == "institutional_sentiment"
    )
    assert positioning_requirement["readiness_status"] == "ready"


def test_get_gold_mainlines_uses_persisted_policy_and_geopolitical_contexts(tmp_path: Path) -> None:
    overview_path, _mainlines_path = _write_gold_artifacts(
        tmp_path,
        date="2026-06-21",
        run_id="run-persisted-verification",
        dominant_mainline="fed_policy_path",
    )
    policy_context_path = (
        tmp_path
        / "storage"
        / "analysis"
        / "gold_mainlines"
        / "2026-06-21"
        / "run-persisted-verification"
        / "policy_context.json"
    )
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
    geopolitical_context_path = (
        tmp_path
        / "storage"
        / "analysis"
        / "gold_mainlines"
        / "2026-06-21"
        / "run-persisted-verification"
        / "geopolitical_context.json"
    )
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
                    {"source": "market_volatility", "source_ref": "vix:reaction"},
                    {"source": "equity_market", "source_ref": "spx:reaction"},
                    {"source": "treasury", "source_ref": "ust:reaction"},
                    {"source": "energy_market", "source_ref": "oil:reaction"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    overview_payload = json.loads(overview_path.read_text(encoding="utf-8"))
    overview_payload["input_snapshot_ids"]["policy_context"] = (
        "analysis/gold_mainlines/2026-06-21/run-persisted-verification/policy_context.json"
    )
    overview_payload["input_snapshot_ids"]["geopolitical_context"] = (
        "analysis/gold_mainlines/2026-06-21/run-persisted-verification/geopolitical_context.json"
    )
    overview_path.write_text(json.dumps(overview_payload, ensure_ascii=False), encoding="utf-8")

    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        payload = get_gold_mainlines(date="2026-06-21", run_id="run-persisted-verification")

    fed = next(
        row for row in payload["gold_macro_overview"]["theme_rankings"] if row["mainline_id"] == "fed_policy_path"
    )
    assert fed["missing_data"] == []
    assert fed["feature_fields"]["fed_policy_bias"] == "higher_for_longer"
    assert fed["feature_fields"]["fomc_tone"] == "hawkish"
    fed_requirement = next(
        item for item in payload["gold_macro_overview"]["mainline_requirements"] if item["mainline_id"] == "fed_policy_path"
    )
    assert fed_requirement["readiness_status"] == "ready"

    geo = next(
        row for row in payload["gold_macro_overview"]["theme_rankings"] if row["mainline_id"] == "geopolitical_war_risk"
    )
    assert geo["missing_data"] == []
    assert geo["feature_fields"]["geopolitical_status"] == "escalating"
    assert geo["feature_fields"]["war_oil_rate_chain_status"] == "active"
    geo_requirement = next(
        item for item in payload["gold_macro_overview"]["mainline_requirements"] if item["mainline_id"] == "geopolitical_war_risk"
    )
    assert geo_requirement["readiness_status"] == "ready"


def test_get_gold_mainlines_fills_mainline_id_alias_from_mainline_only_artifacts(tmp_path: Path) -> None:
    overview_path, _ = _write_gold_artifacts(
        tmp_path,
        date="2026-06-14",
        run_id="run-alias",
        dominant_mainline="oil_prices",
    )
    mainlines_path = tmp_path / "storage" / "features" / "news" / "2026-06-14" / "run-alias" / "gold_event_mainlines.json"

    mainlines_payload = json.loads(mainlines_path.read_text(encoding="utf-8"))
    mainlines_payload["mainlines"][0].pop("mainline_id")
    mainlines_payload["mainlines"][0]["mainline"] = "oil_prices"
    mainlines_path.write_text(json.dumps(mainlines_payload, ensure_ascii=False), encoding="utf-8")

    overview_payload = json.loads(overview_path.read_text(encoding="utf-8"))
    overview_payload["theme_rankings"][0].pop("mainline_id")
    overview_payload["theme_rankings"][0]["mainline"] = "oil_prices"
    overview_path.write_text(json.dumps(overview_payload, ensure_ascii=False), encoding="utf-8")

    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        payload = get_gold_mainlines(date="2026-06-14", run_id="run-alias")

    overview_ranking = payload["gold_macro_overview"]["theme_rankings"][0]
    assert overview_ranking["mainline_id"] == "oil_prices"
    assert overview_ranking["mainline"] == "oil_prices"
    assert overview_ranking["related_event_ids"] == ["event:fed"]
    mainline = payload["gold_mainlines"]["mainlines"][0]
    assert mainline["mainline_id"] == "oil_prices"
    assert mainline["mainline"] == "oil_prices"


def test_get_gold_mainlines_exact_missing_returns_unavailable(tmp_path: Path) -> None:
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        payload = get_gold_mainlines(date="2099-01-01", run_id="missing")

    assert payload["status"] == "unavailable"
    assert payload["date"] == "2099-01-01"
    assert payload["run_id"] == "missing"
    assert payload["gold_macro_overview"] is None
    assert payload["gold_mainlines"]["status"] == "unavailable"
    assert "gold_macro_overview artifact unavailable" in payload["warnings"]


def test_get_gold_mainlines_latest_missing_returns_unavailable(tmp_path: Path) -> None:
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        payload = get_gold_mainlines_latest()

    assert payload["status"] == "unavailable"
    assert payload["date"] is None
    assert payload["run_id"] is None
    assert payload["artifact_path"] is None
    assert payload["gold_macro_overview"] is None
    assert payload["gold_mainlines"]["status"] == "unavailable"


def test_api_gold_mainlines_latest_returns_read_model(tmp_path: Path) -> None:
    _write_gold_artifacts(
        tmp_path,
        date="2026-06-12",
        run_id="run-api",
        dominant_mainline="geopolitical_war_risk",
    )

    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        resp = client.get("/api/gold/mainlines/latest")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "partial"
    assert data["date"] == "2026-06-12"
    assert data["run_id"] == "run-api"
    assert data["gold_macro_overview"]["dominant_mainline"] == "geopolitical_war_risk"
    assert len(data["gold_macro_overview"]["theme_rankings"]) == 9
    checks = {
        (item["mainline_id"], item["required_source"])
        for item in data["gold_macro_overview"]["verification_matrix"]
    }
    assert ("oil_prices", "oil_price") in checks
    assert data["gold_macro_overview"]["war_oil_rate_chain"]["path_id"] == "geopolitics_to_oil_to_rates"
    oil_ranking = next(row for row in data["gold_macro_overview"]["theme_rankings"] if row["mainline_id"] == "oil_prices")
    assert oil_ranking["missing_data"] == ["oil_price"]
    assert data["gold_mainlines"]["event_links"][0]["primary_mainline"] == "geopolitical_war_risk"


def test_api_gold_mainlines_exact_returns_read_model(tmp_path: Path) -> None:
    _write_gold_artifacts(
        tmp_path,
        date="2026-06-13",
        run_id="run-exact",
        dominant_mainline="oil_prices",
    )

    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        resp = client.get("/api/gold/mainlines?date=2026-06-13&run_id=run-exact")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "partial"
    assert data["date"] == "2026-06-13"
    assert data["run_id"] == "run-exact"
    assert data["gold_macro_overview"]["dominant_mainline"] == "oil_prices"


def test_api_gold_mainlines_missing_returns_unavailable(tmp_path: Path) -> None:
    with mock.patch(_PROJECT_ROOT_PATCH, tmp_path):
        resp = client.get("/api/gold/mainlines?date=2099-01-01&run_id=missing")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "unavailable"
    assert data["date"] == "2099-01-01"
    assert data["run_id"] == "missing"
    assert data["gold_macro_overview"] is None
    assert data["gold_mainlines"]["status"] == "unavailable"
