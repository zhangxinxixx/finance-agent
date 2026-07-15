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


def test_close_blocks_without_market_snapshot(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(close, "build_daily_analysis_context", lambda **kwargs: {"status": "degraded"})
    result = close.run_daily_macro_close(trade_date="2026-07-14", storage_root=tmp_path)
    assert result["status"] == "blocked"
    assert result["reason"] == "premarket_snapshot_missing"
