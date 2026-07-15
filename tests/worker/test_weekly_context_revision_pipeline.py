from __future__ import annotations

import json
from pathlib import Path

import pytest

from apps.worker.pipelines.weekly_context_revision import (
    build_weekly_context_revision_input_snapshot,
    generate_weekly_context_revision,
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_baseline(root: Path, *, quality: str = "accepted") -> None:
    _write_json(
        root / "outputs" / "jin10" / "2026-07-18" / "224965" / "agent_analysis_report.json",
        {
            "article_id": "224965",
            "trade_date": "2026-07-18",
            "run_id": "224965",
            "title": "黄金短期难破僵局，期权数据与主力动向暗示底部夯实",
            "one_line_conclusion": "期权数据与主力动向暗示底部夯实。",
            "market_stage": {"label": "利率压制态", "reason": "实际利率仍高。"},
            "gold_analysis": "期权端改善，但价格尚未完成趋势反转。",
            "scenario_paths": [
                {"path": "主路径", "summary": "等待价格和利率确认。", "trigger": "价格收复关键位。"}
            ],
            "quality_audit": {"status": quality, "reasons": []},
            "source_refs": [{"source": "jin10_external", "source_ref": "jin10:224965"}],
        },
    )


def _write_context(root: Path) -> None:
    run_id = "context-run"
    _write_json(
        root / "features" / "snapshots" / "XAUUSD" / "2026-07-19" / run_id / "premarket_snapshot.json",
        {
            "asset": "XAUUSD",
            "trade_date": "2026-07-19",
            "run_id": run_id,
            "snapshot_id": f"XAUUSD:2026-07-19:{run_id}",
            "snapshot_time": "2026-07-19T11:14:10+00:00",
            "technical": {
                "status": "available",
                "data": {"price": 4016.55, "source_refs": [{"source": "jin10_quote", "source_ref": "xau:1"}]},
            },
            "macro": {
                "status": "available",
                "data": {
                    "as_of": "2026-07-19",
                    "indicators": {
                        "US10Y": {"value": 4.57, "date": "2026-07-16", "weekly_change": 0.03},
                        "REAL_10Y": {"value": 2.35, "date": "2026-07-16", "weekly_change": 0.04},
                        "BREAKEVEN_10Y": {"value": 2.24, "date": "2026-07-17", "weekly_change": 0.0},
                        "DXY": {"value": 100.755, "date": "2026-07-19", "weekly_change": None},
                    },
                    "source_refs": {"US10Y": {"source": "fred", "source_ref": "fred:US10Y"}},
                },
            },
            "options": {
                "status": "available",
                "data": {
                    "trade_date": "2026-07-17",
                    "data_source": {"status": "PRELIM", "source_url": "https://www.cmegroup.com/test.pdf"},
                    "parameters": {"report_p0": 4019.0},
                    "gex": {"netgex_aggregate": {"gamma_zero": {"price": 4126.43}}},
                    "wall_scores": [
                        {"strike": 4000, "rank": 1, "dominant_side": "Put", "oi": 5377},
                        {"strike": 4250, "rank": 3, "dominant_side": "Call", "oi": 3420},
                    ],
                    "support_resistance": {
                        "support": [{"strike": 4015}],
                        "resistance": [{"strike": 4235}],
                    },
                },
            },
            "positioning": {
                "status": "available",
                "data": {
                    "as_of": "2026-07-14",
                    "noncomm_net": 120779.0,
                    "noncomm_net_prev": 116161.0,
                    "source_refs": [{"source": "cftc", "source_ref": "cot:2026-07-14"}],
                },
            },
            "news": {"status": "available", "data": {}},
            "input_snapshot_ids": {},
            "source_refs": [],
        },
    )
    _write_json(
        root / "features" / "news" / "2026-07-19" / run_id / "daily_market_brief.json",
        {
            "daily_market_brief": {
                "as_of": "2026-07-19T11:14:14+00:00",
                "market_mainline": {
                    "status": "available",
                    "summary": "油价上升令实际利率压力重新成为主导。",
                    "risk_level": "high",
                },
                "source_refs": [{"source": "reuters_public_news", "source_ref": "news:oil"}],
            }
        },
    )
    _write_json(
        root / "analysis" / "gold_mainlines" / "2026-07-19" / run_id / "oil_context.json",
        {
            "as_of": "2026-07-17",
            "brent_price": 88.10,
            "wti_price": 82.49,
            "brent_weekly_change": 16.0,
            "source_refs": [{"source": "market_data", "source_ref": "oil:2026-07-17"}],
        },
    )
    _write_json(
        root / "analysis" / "gold_mainlines" / "2026-07-19" / run_id / "gold_macro_overview.json",
        {
            "as_of": "2026-07-19T11:14:10+00:00",
            "war_oil_rate_chain": {
                "label": "地缘风险 -> 油价 -> 通胀预期 -> 实际利率 -> 黄金",
                "dominant_driver": "oil_inflation_rate_pressure",
                "net_effect": "mixed",
            },
            "review_status": "accepted",
            "source_refs": [{"source": "gold_mainline", "source_ref": "overview:1"}],
        },
    )


def test_build_weekly_revision_snapshot_uses_latest_archived_context_and_preserves_as_of_dates(tmp_path: Path) -> None:
    storage_root = tmp_path / "storage"
    _write_baseline(storage_root)
    _write_context(storage_root)

    snapshot = build_weekly_context_revision_input_snapshot(
        article_id="224965",
        baseline_date="2026-07-18",
        trade_date="2026-07-19",
        storage_root=storage_root,
    )

    assert snapshot["status"] == "ready"
    assert snapshot["anchor"]["baseline_quality_status"] == "accepted"
    assert snapshot["freshness"]["price"]["as_of"] == "2026-07-19T11:14:10+00:00"
    assert snapshot["freshness"]["options"]["as_of"] == "2026-07-17"
    assert snapshot["freshness"]["positioning"]["as_of"] == "2026-07-14"
    assert snapshot["freshness"]["oil"]["as_of"] == "2026-07-17"
    assert snapshot["confirmation_matrix"]["price"]["basis"] == "point_quote"
    assert snapshot["confirmation_matrix"]["rates"]["real_10y"] == 2.35
    assert snapshot["confirmation_matrix"]["options"]["primary_wall"] == 4000.0
    assert snapshot["positioning_check"]["noncomm_net"] == 120779.0


def test_generate_weekly_revision_writes_append_only_three_file_artifact(tmp_path: Path) -> None:
    storage_root = tmp_path / "storage"
    _write_baseline(storage_root)
    _write_context(storage_root)

    result = generate_weekly_context_revision(
        article_id="224965",
        baseline_date="2026-07-18",
        trade_date="2026-07-19",
        run_id="weekly-revision-run",
        storage_root=storage_root,
    )

    assert result["artifact_type"] == "weekly_context_revision"
    assert len(result["paths"]) == 3
    structured = json.loads(Path(result["paths"][2]).read_text(encoding="utf-8"))
    assert structured["report_type"] == "weekly_context_revision"
    assert structured["anchor"]["article_id"] == "224965"
    assert structured["publish_allowed"] is True

    with pytest.raises(FileExistsError, match="already exist"):
        generate_weekly_context_revision(
            article_id="224965",
            baseline_date="2026-07-18",
            trade_date="2026-07-19",
            run_id="weekly-revision-run",
            storage_root=storage_root,
        )


def test_generate_weekly_revision_keeps_fallback_baseline_observe_only(tmp_path: Path) -> None:
    storage_root = tmp_path / "storage"
    _write_baseline(storage_root, quality="needs_review")
    _write_context(storage_root)

    result = generate_weekly_context_revision(
        article_id="224965",
        baseline_date="2026-07-18",
        trade_date="2026-07-19",
        run_id="weekly-revision-observe",
        storage_root=storage_root,
    )

    structured = json.loads(Path(result["paths"][2]).read_text(encoding="utf-8"))
    assert structured["quality_status"] == "needs_review"
    assert structured["publication_status"] == "observe"
    assert structured["publish_allowed"] is False
    assert "baseline_needs_review" in structured["revision_risk"]["quality_flags"]
