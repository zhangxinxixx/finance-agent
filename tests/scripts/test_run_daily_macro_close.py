from __future__ import annotations

import json
from pathlib import Path

from scripts import run_daily_macro_close as close


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_close_uses_latest_premarket_and_serial_context(tmp_path: Path, monkeypatch) -> None:
    _write(
        tmp_path / "features/snapshots/XAUUSD/2026-07-13/premarket/premarket_snapshot.json",
        {"snapshot_id": "XAUUSD:2026-07-13:premarket", "trade_date": "2026-07-13", "source_refs": []},
    )
    monkeypatch.setattr(
        close,
        "build_daily_analysis_context",
        lambda **kwargs: {
            "status": "ready",
            "baseline_kind": "previous_analysis_report",
            "analysis_baseline": {"source_kind": "final_analysis_report", "trade_date": "2026-07-13", "run_id": "final-0713"},
            "freshness": {"market": {"status": "current"}},
            "input_snapshot_ids": {"previous_analysis_report": "outputs/final_report/XAUUSD/2026-07-13/final-0713/structured_report.json"},
            "source_refs": [],
        },
    )
    captured: dict = {}

    def fake_pipeline(**kwargs):
        captured.update(kwargs)
        return (
            {"final_report": {"status": "success"}},
            {"report_result": {"paths": ["outputs/final_report/XAUUSD/2026-07-14/close/final_report.md"]}, "card_result": {"paths": []}},
        )

    monkeypatch.setattr(close, "run_composite_analysis_pipeline", fake_pipeline)
    result = close.run_daily_macro_close(trade_date="2026-07-14", storage_root=tmp_path, run_id="close-test")

    assert result["status"] == "completed"
    assert captured["snapshot"]["gold_analysis_context"]["data"]["baseline_kind"] == "previous_analysis_report"
    assert captured["snapshot"]["input_snapshot_ids"]["gold_analysis_context"]["previous_analysis_report"]
    manifest = tmp_path / "outputs/daily_macro_close/XAUUSD/2026-07-14/close-test/close_manifest.json"
    assert manifest.exists()


def test_close_prepares_current_only_shadow_runtime_from_original_premarket(tmp_path: Path, monkeypatch) -> None:
    premarket_path = tmp_path / "features/snapshots/XAUUSD/2026-07-14/premarket/premarket_snapshot.json"
    _write(premarket_path, {"snapshot_id": "premarket-id", "trade_date": "2026-07-14", "snapshot_time": "2026-07-14T12:00:00+00:00", "source_refs": []})
    monkeypatch.setattr(close, "build_daily_analysis_context", lambda **kwargs: {"status": "ready"})
    captured: dict = {}
    runtime_snapshot: dict = {}

    def fake_runtime(**kwargs):
        runtime_snapshot.update(kwargs["snapshot"])
        return (
            {"gold_feature_snapshot_prebuilt": {"snapshot_id": "current"}, "previous_gold_feature_snapshot_prebuilt": None, "gold_policy_execution_mode": "shadow"},
            {"status": "ready", "lookup": {"current": "found", "previous": "missing"}},
        )

    monkeypatch.setattr(close, "_gold_policy_runtime_kwargs", fake_runtime)
    monkeypatch.setattr(close, "run_composite_analysis_pipeline", lambda **kwargs: (captured.update(kwargs) or {"final_report": {}}, {"report_result": {}, "card_result": {}, "gold_policy_artifact_paths": {"feature": "analysis/feature.json"}}))
    result = close.run_daily_macro_close(trade_date="2026-07-14", storage_root=tmp_path, run_id="runtime-current-only")

    assert runtime_snapshot["snapshot_id"] == "premarket-id"
    assert runtime_snapshot["snapshot_time"] == "2026-07-14T12:00:00+00:00"
    assert captured["gold_feature_snapshot_prebuilt"] == {"snapshot_id": "current"}
    assert captured["previous_gold_feature_snapshot_prebuilt"] is None
    assert captured["gold_policy_execution_mode"] == "shadow"
    assert result["gold_policy_runtime"]["lookup"]["previous"] == "missing"
    assert result["gold_policy_artifact_paths"] == {"feature": "analysis/feature.json"}


def test_close_continues_legacy_pipeline_when_runtime_prepare_fails(tmp_path: Path, monkeypatch) -> None:
    _write(tmp_path / "features/snapshots/XAUUSD/2026-07-14/premarket/premarket_snapshot.json", {"snapshot_id": "premarket-id", "trade_date": "2026-07-14", "source_refs": []})
    monkeypatch.setattr(close, "build_daily_analysis_context", lambda **kwargs: {"status": "ready"})
    monkeypatch.setattr(close, "_gold_policy_runtime_kwargs", lambda **kwargs: ({}, {"status": "failed", "reason_code": "gold_policy_runtime_prepare_failed", "lookup": {}}))
    captured: dict = {}
    monkeypatch.setattr(close, "run_composite_analysis_pipeline", lambda **kwargs: (captured.update(kwargs) or {"final_report": {}}, {"report_result": {}, "card_result": {}}))

    result = close.run_daily_macro_close(trade_date="2026-07-14", storage_root=tmp_path, run_id="runtime-failure")

    assert captured["snapshot"]["snapshot_id"].endswith("runtime-failure")
    assert "gold_policy_execution_mode" not in captured
    assert result["status"] == "completed"
    assert result["gold_policy_runtime"]["status"] == "failed"


def test_close_blocks_without_market_snapshot(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(close, "build_daily_analysis_context", lambda **kwargs: {"status": "degraded"})
    result = close.run_daily_macro_close(trade_date="2026-07-14", storage_root=tmp_path)
    assert result["status"] == "blocked"
    assert result["reason"] == "premarket_snapshot_missing"
