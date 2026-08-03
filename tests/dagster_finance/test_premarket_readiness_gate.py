from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from dagster import build_op_context

from dagster_finance.ops.premarket_gate import (
    PremarketReadinessGateConfig,
    PremarketReadinessRefreshConfig,
    evaluate_premarket_readiness,
    premarket_readiness_gate_op,
    refresh_premarket_readiness_op,
)


TRADE_DATE = "2026-07-20"
NOW = datetime(2026, 7, 20, 1, 0, tzinfo=timezone.utc)


def _write_readiness(tmp_path, **overrides):
    payload = {
        "trade_date": TRADE_DATE,
        "observed_at": NOW.isoformat(),
        "readiness": "ready",
        "can_run_daily_report": True,
        "can_run_full_analysis": True,
        "capabilities": {"full_daily_analysis": "ready"},
        "blocked_outputs": [],
    }
    payload.update(overrides)
    path = tmp_path / "monitoring" / TRADE_DATE / "downstream_readiness.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_readiness_gate_allows_current_ready_artifact(tmp_path) -> None:
    _write_readiness(tmp_path)

    result = evaluate_premarket_readiness(
        storage_root=tmp_path,
        trade_date=TRADE_DATE,
        observed_at=NOW,
    )

    assert result["decision"] == "allow"
    assert result["reason_code"] is None
    assert result["source_ref"] == f"monitoring/{TRADE_DATE}/downstream_readiness.json"


def test_readiness_gate_blocks_missing_stale_and_mismatched_artifacts(tmp_path) -> None:
    missing = evaluate_premarket_readiness(
        storage_root=tmp_path,
        trade_date=TRADE_DATE,
        observed_at=NOW,
    )
    assert missing["decision"] == "block"
    assert missing["reason_code"] == "downstream_readiness_missing"

    _write_readiness(tmp_path, observed_at=(NOW - timedelta(minutes=61)).isoformat())
    stale = evaluate_premarket_readiness(
        storage_root=tmp_path,
        trade_date=TRADE_DATE,
        observed_at=NOW,
    )
    assert stale["decision"] == "block"
    assert stale["reason_code"] == "downstream_readiness_stale"

    _write_readiness(tmp_path, trade_date="2026-07-19")
    mismatch = evaluate_premarket_readiness(
        storage_root=tmp_path,
        trade_date=TRADE_DATE,
        observed_at=NOW,
    )
    assert mismatch["decision"] == "block"
    assert mismatch["reason_code"] == "downstream_readiness_trade_date_mismatch"


def test_readiness_gate_blocks_blocked_capability(tmp_path) -> None:
    _write_readiness(
        tmp_path,
        readiness="partial",
        can_run_daily_report=True,
        can_run_full_analysis=False,
        capabilities={"full_daily_analysis": "blocked"},
        blocked_outputs=["daily_report"],
    )

    result = evaluate_premarket_readiness(
        storage_root=tmp_path,
        trade_date=TRADE_DATE,
        observed_at=NOW,
    )

    assert result["decision"] == "block"
    assert result["reason_code"] == "downstream_full_analysis_blocked"
    assert result["can_run_daily_report"] is True
    assert result["can_run_full_analysis"] is False
    assert result["capabilities"] == {"full_daily_analysis": "blocked"}


def test_readiness_gate_preserves_daily_report_capability_when_overall_readiness_is_blocked(tmp_path) -> None:
    _write_readiness(
        tmp_path,
        readiness="blocked",
        can_run_daily_report=True,
        can_run_full_analysis=False,
        capabilities={"daily_market_snapshot": "blocked", "full_daily_analysis": "blocked"},
        blocked_outputs=["full analysis"],
    )

    result = evaluate_premarket_readiness(
        storage_root=tmp_path,
        trade_date=TRADE_DATE,
        observed_at=NOW,
    )

    assert result["decision"] == "block"
    assert result["reason_code"] == "downstream_readiness_not_ready"
    assert result["can_run_daily_report"] is True
    assert result["can_run_full_analysis"] is False


def test_readiness_gate_blocks_unknown_capability_contract(tmp_path) -> None:
    _write_readiness(tmp_path, capabilities={}, can_run_full_analysis=None)

    result = evaluate_premarket_readiness(
        storage_root=tmp_path,
        trade_date=TRADE_DATE,
        observed_at=NOW,
    )

    assert result["decision"] == "block"
    assert result["reason_code"] == "downstream_full_analysis_blocked"


def test_readiness_gate_op_uses_snapshot_trade_date(tmp_path) -> None:
    _write_readiness(tmp_path)
    result = premarket_readiness_gate_op(
        build_op_context(),
        PremarketReadinessGateConfig(storage_root=str(tmp_path), observed_at=NOW.isoformat()),
        {"trade_date": TRADE_DATE},
        {"trade_date": TRADE_DATE},
    )

    assert result["decision"] == "allow"
    assert result["trade_date"] == TRADE_DATE


def test_readiness_refresh_op_materializes_current_trade_date_before_gate(tmp_path, monkeypatch) -> None:
    calls = []

    def fake_monitor(**kwargs):
        calls.append(kwargs)
        _write_readiness(tmp_path)
        return {
            "downstream_readiness": {
                "trade_date": TRADE_DATE,
                "readiness": "ready",
                "can_run_daily_report": True,
                "can_run_full_analysis": True,
            },
            "artifacts": {
                "downstream_readiness": f"monitoring/{TRADE_DATE}/downstream_readiness.json",
            },
        }

    monkeypatch.setattr("apps.monitoring.run_data_quality_monitor", fake_monitor)
    refresh = refresh_premarket_readiness_op(
        build_op_context(),
        PremarketReadinessRefreshConfig(storage_root=str(tmp_path), observed_at=NOW.isoformat()),
        {"trade_date": TRADE_DATE},
    )

    assert refresh["trade_date"] == TRADE_DATE
    assert calls[0]["trade_date"] == TRADE_DATE
    assert calls[0]["record_task_run"] is False
    assert calls[0]["observed_at"] == NOW

    result = premarket_readiness_gate_op(
        build_op_context(),
        PremarketReadinessGateConfig(storage_root=str(tmp_path), observed_at=NOW.isoformat()),
        {"trade_date": TRADE_DATE},
        refresh,
    )
    assert result["decision"] == "allow"


def test_readiness_gate_blocks_refresh_trade_date_mismatch(tmp_path) -> None:
    _write_readiness(tmp_path)
    result = premarket_readiness_gate_op(
        build_op_context(),
        PremarketReadinessGateConfig(storage_root=str(tmp_path), observed_at=NOW.isoformat()),
        {"trade_date": TRADE_DATE},
        {"trade_date": "2026-07-19"},
    )

    assert result["decision"] == "block"
    assert result["reason_code"] == "downstream_readiness_refresh_trade_date_mismatch"
