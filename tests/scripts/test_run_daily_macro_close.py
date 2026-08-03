from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from scripts import run_daily_macro_close as close


def test_runtime_controls_include_current_session_head_for_new_bundle(tmp_path: Path, monkeypatch) -> None:
    from apps.analysis.gold_policy.daily_close_runtime import (
        GoldDailyCloseRuntimeControls,
        execute_gold_daily_close_runtime,
    )
    from tests.analysis.test_gold_daily_close_store import _bootstrap_pair

    bootstrap_input, _ = _bootstrap_pair()
    first = execute_gold_daily_close_runtime(
        storage_root=tmp_path,
        run_id="same-session-first",
        current_feature=bootstrap_input.current_feature,
        controls=GoldDailyCloseRuntimeControls(
            decision_as_of=bootstrap_input.decision_as_of,
            transition_evidence=bootstrap_input.transition_evidence,
            options_regime=bootstrap_input.options_regime,
            event_risk=bootstrap_input.event_risk,
            key_levels=bootstrap_input.key_levels,
            key_level_decisions=bootstrap_input.key_level_decisions,
            key_level_proof=bootstrap_input.key_level_proof,
        ),
        bootstrap_previous_feature=bootstrap_input.previous_feature,
    )
    expected_current = bootstrap_input.current_feature
    monkeypatch.setattr(
        "apps.analysis.gold_policy.runtime_inputs.prepare_gold_policy_runtime_inputs",
        lambda **kwargs: SimpleNamespace(
            current=expected_current, previous=None, lookup=SimpleNamespace(summary=lambda: {})
        ),
    )
    monkeypatch.setattr(
        "apps.analysis.gold_policy.runtime_controls.build_gold_daily_close_runtime_controls",
        lambda **kwargs: SimpleNamespace(reason_codes=()),
    )

    _, summary = close._gold_policy_runtime_kwargs(
        storage_root=tmp_path,
        snapshot={},
        decision_as_of=bootstrap_input.decision_as_of,
        run_id="same-session-second",
    )

    assert summary["status"] == "ready"
    assert summary["canonical_lookup"]["status"] == "found"
    assert first.write_result.revision_no == 1


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
            "analysis_baseline": {
                "source_kind": "final_analysis_report",
                "trade_date": "2026-07-13",
                "run_id": "final-0713",
            },
            "freshness": {"market": {"status": "current"}},
            "input_snapshot_ids": {
                "previous_analysis_report": "outputs/final_report/XAUUSD/2026-07-13/final-0713/structured_report.json"
            },
            "source_refs": [],
        },
    )
    captured: dict = {}

    def fake_pipeline(**kwargs):
        captured.update(kwargs)
        return (
            {"final_report": {"status": "success"}},
            {
                "report_result": {"paths": ["outputs/final_report/XAUUSD/2026-07-14/close/final_report.md"]},
                "card_result": {"paths": []},
            },
        )

    monkeypatch.setattr(close, "run_composite_analysis_pipeline", fake_pipeline)
    monkeypatch.setattr(
        close,
        "_gold_policy_runtime_kwargs",
        lambda **kwargs: (
            {
                "gold_feature_snapshot_prebuilt": {"snapshot_id": "current"},
                "gold_daily_close_controls_prebuilt": {"schema_version": "controls"},
                "gold_policy_execution_mode": "authoritative",
            },
            {"status": "ready", "execution_mode": "authoritative"},
        ),
    )
    result = close.run_daily_macro_close(trade_date="2026-07-14", storage_root=tmp_path, run_id="close-test")

    assert result["status"] == "completed"
    assert captured["snapshot"]["gold_analysis_context"]["data"]["baseline_kind"] == "previous_analysis_report"
    assert captured["snapshot"]["input_snapshot_ids"]["gold_analysis_context"]["previous_analysis_report"]
    manifest = tmp_path / "outputs/daily_macro_close/XAUUSD/2026-07-14/close-test/close_manifest.json"
    assert manifest.exists()


def test_close_prepares_authoritative_runtime_from_original_premarket(tmp_path: Path, monkeypatch) -> None:
    premarket_path = tmp_path / "features/snapshots/XAUUSD/2026-07-14/premarket/premarket_snapshot.json"
    _write(
        premarket_path,
        {
            "snapshot_id": "premarket-id",
            "trade_date": "2026-07-14",
            "snapshot_time": "2026-07-14T12:00:00+00:00",
            "source_refs": [],
        },
    )
    monkeypatch.setattr(close, "build_daily_analysis_context", lambda **kwargs: {"status": "ready"})
    captured: dict = {}
    runtime_snapshot: dict = {}

    def fake_runtime(**kwargs):
        runtime_snapshot.update(kwargs["snapshot"])
        return (
            {
                "gold_feature_snapshot_prebuilt": {"snapshot_id": "current"},
                "previous_gold_feature_snapshot_prebuilt": None,
                "gold_daily_close_controls_prebuilt": {"schema_version": "controls"},
                "gold_policy_execution_mode": "authoritative",
            },
            {
                "status": "ready",
                "execution_mode": "authoritative",
                "lookup": {"current": "found", "previous": "missing"},
            },
        )

    monkeypatch.setattr(close, "_gold_policy_runtime_kwargs", fake_runtime)
    monkeypatch.setattr(
        close,
        "run_composite_analysis_pipeline",
        lambda **kwargs: (
            captured.update(kwargs) or {"final_report": {}},
            {
                "report_result": {},
                "card_result": {},
                "gold_policy_artifact_paths": {"feature": "analysis/feature.json"},
            },
        ),
    )
    result = close.run_daily_macro_close(trade_date="2026-07-14", storage_root=tmp_path, run_id="runtime-current-only")

    assert runtime_snapshot["snapshot_id"] == "premarket-id"
    assert runtime_snapshot["snapshot_time"] == "2026-07-14T12:00:00+00:00"
    assert captured["gold_feature_snapshot_prebuilt"] == {"snapshot_id": "current"}
    assert captured["previous_gold_feature_snapshot_prebuilt"] is None
    assert captured["gold_daily_close_controls_prebuilt"] == {"schema_version": "controls"}
    assert captured["gold_policy_execution_mode"] == "authoritative"
    assert result["gold_policy_runtime"]["lookup"]["previous"] == "missing"
    assert result["gold_policy_artifact_paths"] == {"feature": "analysis/feature.json"}


def test_close_blocks_when_authoritative_runtime_prepare_fails(tmp_path: Path, monkeypatch) -> None:
    _write(
        tmp_path / "features/snapshots/XAUUSD/2026-07-14/premarket/premarket_snapshot.json",
        {"snapshot_id": "premarket-id", "trade_date": "2026-07-14", "source_refs": []},
    )
    monkeypatch.setattr(close, "build_daily_analysis_context", lambda **kwargs: {"status": "ready"})
    monkeypatch.setattr(
        close,
        "_gold_policy_runtime_kwargs",
        lambda **kwargs: ({}, {"status": "failed", "reason_code": "gold_policy_runtime_prepare_failed", "lookup": {}}),
    )
    captured: dict = {}
    monkeypatch.setattr(
        close,
        "run_composite_analysis_pipeline",
        lambda **kwargs: (captured.update(kwargs) or {"final_report": {}}, {"report_result": {}, "card_result": {}}),
    )

    result = close.run_daily_macro_close(trade_date="2026-07-14", storage_root=tmp_path, run_id="runtime-failure")

    assert captured == {}
    assert result["status"] == "blocked"
    assert result["reason"] == "gold_policy_runtime_prepare_failed"
    assert result["gold_policy_runtime"]["status"] == "failed"


def test_close_blocks_without_market_snapshot(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(close, "build_daily_analysis_context", lambda **kwargs: {"status": "degraded"})
    result = close.run_daily_macro_close(trade_date="2026-07-14", storage_root=tmp_path)
    assert result["status"] == "blocked"
    assert result["reason"] == "premarket_snapshot_missing"


def test_authoritative_output_paths_require_a_complete_package_and_keep_degraded_card(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "analysis/gold_mainlines/2026-07-14/run/daily_close"
    bundle.mkdir(parents=True)
    outputs = {"gold_daily_close_execution": SimpleNamespace(write_result=SimpleNamespace(bundle_path=bundle))}

    reports, cards = close._authoritative_output_paths(
        storage_root=tmp_path,
        outputs=outputs,
    )
    assert reports == []
    assert cards == []

    for name in (
        "source.md",
        "analysis.md",
        "visual.html",
        "report_structured.json",
        "evidence.json",
        "data_quality.json",
        "report_manifest.json",
        "strategy_card.json",
        "strategy_card.md",
    ):
        (bundle / name).write_text("{}" if name.endswith(".json") else "# report\n", encoding="utf-8")

    reports, cards = close._authoritative_output_paths(
        storage_root=tmp_path,
        outputs=outputs,
    )
    assert len(reports) == 9
    assert {Path(path).name for path in cards} == {"strategy_card.json", "strategy_card.md"}
