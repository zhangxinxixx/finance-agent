from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from apps.worker.runner import _load_pre_analysis_gate, _pre_analysis_gate_blocks


TRADE_DATE = "2026-07-20"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _ready_payload(*, observed_at: datetime, readiness: str = "ready", can_run_full: bool = True) -> dict:
    return {
        "trade_date": TRADE_DATE,
        "observed_at": observed_at.isoformat(),
        "readiness": readiness,
        "can_run_full_analysis": can_run_full,
        "capabilities": {"full_daily_analysis": "allowed" if can_run_full else "blocked"},
        "blocked_outputs": [] if can_run_full else ["full analysis"],
    }


@pytest.mark.parametrize(
    ("readiness_payload", "reason_code"),
    [
        (None, "downstream_readiness_missing"),
        (
            _ready_payload(observed_at=datetime.now(timezone.utc) - timedelta(hours=2)),
            "downstream_readiness_stale",
        ),
        (
            _ready_payload(observed_at=datetime.now(timezone.utc), readiness="blocked", can_run_full=False),
            "downstream_readiness_not_ready",
        ),
    ],
)
def test_legacy_runner_fails_closed_before_composite_agents(
    tmp_path: Path,
    readiness_payload: dict | None,
    reason_code: str,
) -> None:
    if readiness_payload is not None:
        _write_json(
            tmp_path / "monitoring" / TRADE_DATE / "downstream_readiness.json",
            readiness_payload,
        )

    gate = _load_pre_analysis_gate(
        storage_root=tmp_path,
        analysis_snapshot={"trade_date": TRADE_DATE},
    )

    assert _pre_analysis_gate_blocks(gate) is True
    assert gate["reason_code"] == reason_code


def test_legacy_runner_allows_current_readiness_without_legacy_gate(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "monitoring" / TRADE_DATE / "downstream_readiness.json",
        _ready_payload(observed_at=datetime.now(timezone.utc)),
    )

    gate = _load_pre_analysis_gate(
        storage_root=tmp_path,
        analysis_snapshot={"trade_date": TRADE_DATE},
    )

    assert gate["decision"] == "allow"
    assert _pre_analysis_gate_blocks(gate) is False


def test_legacy_runner_reads_nested_gate_from_orchestrator_latest_pointer(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "monitoring" / TRADE_DATE / "downstream_readiness.json",
        _ready_payload(observed_at=datetime.now(timezone.utc)),
    )
    gate_ref = f"orchestration/{TRADE_DATE}/pre-analysis-run/pre_analysis_gate.json"
    _write_json(
        tmp_path / gate_ref,
        {
            "trade_date": TRADE_DATE,
            "decision": "block",
            "reason_code": "manual_pre_analysis_block",
            "blocked_outputs": ["full analysis"],
        },
    )
    _write_json(
        tmp_path / "orchestration" / TRADE_DATE / "latest.json",
        {
            "trade_date": TRADE_DATE,
            "run_id": "pre-analysis-run",
            "trigger": "pre_analysis",
            "artifacts": {"pre_analysis_gate": gate_ref},
        },
    )

    gate = _load_pre_analysis_gate(
        storage_root=tmp_path,
        analysis_snapshot={"trade_date": TRADE_DATE},
    )

    assert gate["decision"] == "block"
    assert gate["reason_code"] == "manual_pre_analysis_block"


def test_legacy_runner_blocks_snapshot_without_trade_date(tmp_path: Path) -> None:
    gate = _load_pre_analysis_gate(storage_root=tmp_path, analysis_snapshot={})

    assert gate["decision"] == "block"
    assert gate["reason_code"] == "analysis_snapshot_trade_date_missing"
