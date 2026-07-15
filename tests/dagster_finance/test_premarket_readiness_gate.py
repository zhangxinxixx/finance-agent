from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from dagster import build_op_context

from dagster_finance.ops.premarket_gate import (
    PremarketReadinessGateConfig,
    evaluate_premarket_readiness,
    premarket_readiness_gate_op,
)


TRADE_DATE = "2026-07-20"
NOW = datetime(2026, 7, 20, 1, 0, tzinfo=timezone.utc)


def _write_readiness(tmp_path, **overrides):
    payload = {
        "trade_date": TRADE_DATE,
        "observed_at": NOW.isoformat(),
        "readiness": "ready",
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
    )

    assert result["decision"] == "allow"
    assert result["trade_date"] == TRADE_DATE
