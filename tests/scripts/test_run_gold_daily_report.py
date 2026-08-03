from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

from apps.analysis.gold_policy.feature_snapshot import build_feature_snapshot
from apps.analysis.gold_policy.daily_close_store import (
    load_gold_daily_close_head,
    verify_gold_daily_close_bundle,
)
from scripts import run_gold_daily_report as report
from tests.analysis.test_gold_strategy_policy import _snapshot
from tests.analysis.test_gold_cme_options_regime import _options_output


def _write_snapshot(root: Path, trade_date: str) -> Path:
    path = root / "features" / "snapshots" / "XAUUSD" / trade_date / "premarket" / "premarket_snapshot.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"trade_date": trade_date, "legacy_context": "ignored"}), encoding="utf-8")
    return path


def _runtime(current, previous):
    return SimpleNamespace(current=current, previous=previous)


def test_no_jin10_entrypoint_writes_complete_observe_package_idempotently(
    tmp_path: Path,
    monkeypatch,
) -> None:
    previous = _snapshot("feature_snapshot_v1_bullish_2025-01-17.json")
    current = _snapshot("feature_snapshot_v1_bearish_2025-01-21.json")
    _write_snapshot(tmp_path, "2025-01-21")
    monkeypatch.setenv("FINANCE_AGENT_DISABLE_JIN10", "true")
    monkeypatch.setattr(
        report,
        "prepare_gold_policy_runtime_inputs",
        lambda **kwargs: _runtime(current, previous),
    )

    first = report.run_gold_daily_report(
        trade_date="2025-01-21",
        storage_root=tmp_path,
    )
    second = report.run_gold_daily_report(
        trade_date="2025-01-21",
        storage_root=tmp_path,
    )

    assert first["status"] == "completed"
    assert first["jin10"] == "not_used"
    assert first["report_status"] == "observe"
    assert len(first["report_paths"]) == 9
    assert all(Path(path).is_file() for path in first["report_paths"])
    assert second == first
    assert "apps.analysis.jin10" not in Path(report.__file__).read_text(encoding="utf-8")


def test_same_day_formal_options_are_rendered_without_releasing_directional_trigger(
    tmp_path: Path,
    monkeypatch,
) -> None:
    previous = _snapshot("feature_snapshot_v1_bullish_2025-01-17.json")
    current = _snapshot("feature_snapshot_v1_bearish_2025-01-21.json")
    _write_snapshot(tmp_path, "2025-01-21")
    options_payload = json.loads(json.dumps(_options_output()).replace("2026-07-29", "2025-01-21"))
    options_path = tmp_path / "features/cme/2025-01-21/formal-options/options_analysis.json"
    options_path.parent.mkdir(parents=True)
    options_path.write_text(json.dumps(options_payload), encoding="utf-8")
    monkeypatch.setattr(
        report,
        "prepare_gold_policy_runtime_inputs",
        lambda **kwargs: _runtime(current, previous),
    )

    result = report.run_gold_daily_report(
        trade_date="2025-01-21",
        storage_root=tmp_path,
    )

    assert result["status"] == "completed"
    assert result["report_status"] == "observe"
    analysis = next(
        Path(path).read_text(encoding="utf-8") for path in result["report_paths"] if path.endswith("analysis.md")
    )
    structured = json.loads(
        next(
            Path(path).read_text(encoding="utf-8")
            for path in result["report_paths"]
            if path.endswith("report_structured.json")
        )
    )
    data_quality = json.loads(
        next(
            Path(path).read_text(encoding="utf-8")
            for path in result["report_paths"]
            if path.endswith("data_quality.json")
        )
    )
    strategy = json.loads(Path(result["strategy_card_paths"][0]).read_text(encoding="utf-8"))
    verification = verify_gold_daily_close_bundle(
        storage_root=tmp_path,
        bundle_path=Path(result["report_paths"][0]).parent,
    )
    assert "## 策略与原因" in analysis
    assert "CME GC Gamma Flip 参考：4110.0" in analysis
    assert "触发位：unavailable" in analysis
    assert any(fact["fact_id"] == "options.net_gex" for section in structured["sections"] for fact in section["facts"])
    assert verification.status == "valid"
    assert data_quality["domain_status"]["options"] == "observe"
    assert "OPTIONS_CONFIRMATION" in data_quality["prohibited_outputs"]
    assert "TRIGGERED_STRATEGY" in data_quality["prohibited_outputs"]
    assert strategy["status"] not in {
        "LONG_RESEARCH_TRIGGERED",
        "SHORT_RESEARCH_TRIGGERED",
    }


def test_existing_tampered_report_never_returns_completed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    previous = _snapshot("feature_snapshot_v1_bullish_2025-01-17.json")
    current = _snapshot("feature_snapshot_v1_bearish_2025-01-21.json")
    _write_snapshot(tmp_path, "2025-01-21")
    monkeypatch.setattr(
        report,
        "prepare_gold_policy_runtime_inputs",
        lambda **kwargs: _runtime(current, previous),
    )

    first = report.run_gold_daily_report(
        trade_date="2025-01-21",
        storage_root=tmp_path,
    )
    analysis_path = next(Path(path) for path in first["report_paths"] if path.endswith("analysis.md"))
    analysis_path.write_text(
        analysis_path.read_text(encoding="utf-8") + "\nTAMPERED\n",
        encoding="utf-8",
    )

    second = report.run_gold_daily_report(
        trade_date="2025-01-21",
        storage_root=tmp_path,
    )

    assert first["status"] == "completed"
    assert second["status"] == "blocked"
    assert "TAMPERED" in analysis_path.read_text(encoding="utf-8")


def test_no_jin10_entrypoint_publishes_degraded_no_trade_for_blocked_feature(
    tmp_path: Path,
    monkeypatch,
) -> None:
    previous = _snapshot("feature_snapshot_v1_bearish_2025-01-21.json")
    current = _snapshot("feature_snapshot_v1_blocked_2025-01-22.json")
    _write_snapshot(tmp_path, "2025-01-22")
    monkeypatch.setattr(
        report,
        "prepare_gold_policy_runtime_inputs",
        lambda **kwargs: _runtime(current, previous),
    )

    result = report.run_gold_daily_report(
        trade_date="2025-01-22",
        storage_root=tmp_path,
    )

    assert result["status"] == "completed"
    assert result["canonical_action"] == "hold"
    assert result["report_status"] == "degraded"
    strategy = json.loads(Path(result["strategy_card_paths"][0]).read_text(encoding="utf-8"))
    assert strategy["status"] == "NO_TRADE"


def test_dry_run_validates_formal_inputs_without_writing(tmp_path: Path, monkeypatch) -> None:
    previous = _snapshot("feature_snapshot_v1_bullish_2025-01-17.json")
    current = _snapshot("feature_snapshot_v1_bearish_2025-01-21.json")
    _write_snapshot(tmp_path, "2025-01-21")
    monkeypatch.setattr(
        report,
        "prepare_gold_policy_runtime_inputs",
        lambda **kwargs: _runtime(current, previous),
    )

    result = report.run_gold_daily_report(
        trade_date="2025-01-21",
        storage_root=tmp_path,
        dry_run=True,
    )

    assert result["status"] == "dry_run"
    assert result["jin10"] == "not_used"
    assert not (tmp_path / "analysis").exists()


def test_confirmatory_gaps_publish_observe_package(tmp_path: Path, monkeypatch) -> None:
    fixture_dir = Path(__file__).parents[1] / "fixtures" / "gold_policy" / "readiness_v2"
    ready = json.loads((fixture_dir / "ready.json").read_text(encoding="utf-8"))["input"]
    case = json.loads((fixture_dir / "confirmatory_missing.json").read_text(encoding="utf-8"))
    current_payload = json.loads(json.dumps(ready))
    for name, updates in case["patch"].items():
        current_payload[name].update(updates)
    previous_payload = json.loads(json.dumps(ready).replace("2025-01-17", "2025-01-16"))
    oldest_payload = json.loads(json.dumps(ready).replace("2025-01-17", "2025-01-15"))
    previous = build_feature_snapshot(previous_payload)
    oldest = build_feature_snapshot(oldest_payload)
    current = build_feature_snapshot(current_payload)
    _write_snapshot(tmp_path, "2025-01-16")
    _write_snapshot(tmp_path, "2025-01-17")
    monkeypatch.setattr(
        report,
        "prepare_gold_policy_runtime_inputs",
        lambda **kwargs: (
            _runtime(previous, oldest)
            if kwargs["snapshot"]["trade_date"] == "2025-01-16"
            else _runtime(current, previous)
        ),
    )

    bootstrap = report.run_gold_daily_report(
        trade_date="2025-01-16",
        storage_root=tmp_path,
    )

    result = report.run_gold_daily_report(
        trade_date="2025-01-17",
        storage_root=tmp_path,
    )

    assert bootstrap["status"] == "completed"
    assert result["status"] == "completed"
    assert result["report_status"] == "observe"


def test_newer_same_session_snapshot_creates_linked_revision(tmp_path: Path, monkeypatch) -> None:
    previous = _snapshot("feature_snapshot_v1_bullish_2025-01-17.json")
    first_feature = _snapshot("feature_snapshot_v1_bearish_2025-01-21.json")
    revised_payload = first_feature.model_dump(
        mode="json",
        exclude={"data_quality", "payload_hash", "snapshot_id"},
    )
    revised_as_of = first_feature.as_of + timedelta(hours=1)
    revised_payload["as_of"] = revised_as_of.isoformat()
    revised_payload["xauusd_spot"]["value"] += 1.0
    revised_payload["xauusd_spot"]["as_of"] = revised_as_of.isoformat()
    revised_feature = build_feature_snapshot(revised_payload)
    _write_snapshot(tmp_path, "2025-01-21")
    current = first_feature
    monkeypatch.setattr(
        report,
        "prepare_gold_policy_runtime_inputs",
        lambda **kwargs: _runtime(current, previous),
    )

    first = report.run_gold_daily_report(
        trade_date="2025-01-21",
        storage_root=tmp_path,
    )
    current = revised_feature
    second = report.run_gold_daily_report(
        trade_date="2025-01-21",
        storage_root=tmp_path,
    )

    assert first["status"] == second["status"] == "completed"
    assert first["run_id"] != second["run_id"]
    latest = load_gold_daily_close_head(storage_root=tmp_path)
    assert latest.latest_receipt is not None
    assert latest.latest_receipt.revision_no == 2
    assert latest.latest_receipt.supersedes_receipt_id


def test_snapshot_and_run_id_fail_closed(tmp_path: Path) -> None:
    missing = report.run_gold_daily_report(
        trade_date="2025-01-21",
        storage_root=tmp_path,
    )
    outside = report.run_gold_daily_report(
        trade_date="2025-01-21",
        storage_root=tmp_path,
        snapshot_path=tmp_path.parent / "outside.json",
    )

    assert missing["reason"] == "premarket_snapshot_missing"
    assert outside["reason"] == "snapshot_path_outside_storage_root"
