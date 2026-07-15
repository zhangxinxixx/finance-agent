from __future__ import annotations

import os
from datetime import UTC, datetime, time, timedelta
from pathlib import Path

import pytest

from apps.analysis.evaluation.runner import run_shadow_evaluation


AS_OF = datetime(2026, 7, 17, 12, tzinfo=UTC)


def _live(*, approved: bool = False) -> dict[str, object]:
    return {
        "schema_version": "live_strategy.v1",
        "status": "available" if approved else "partial",
        "strategy_id": "live-1",
        "strategy_version": "live_strategy.rules.v2",
        "asset": "XAUUSD",
        "strategy_status": "WAITING" if approved else "SUSPENDED_DATA",
        "baseline": {"run_id": "run-1", "trade_date": "2026-07-17", "bias": "bullish"},
        "live_market": {"status": "available" if approved else "stale", "price": 2400.0},
        "market_state": {"key_levels": []},
        "feasibility": {},
        "active_scenario": None,
        "setups": (
            [
                {
                    "setup_id": "setup-long",
                    "direction": "long",
                    "status": "watching",
                    "entry_zone": [2401.5, 2402.0],
                    "confirmation_conditions": ["two_canonical_5m_closes"],
                    "invalidation_level": 2398.0,
                    "stop_reference": 2398.0,
                    "targets": [{"price": 2405.0}],
                }
            ]
            if approved
            else []
        ),
        "no_trade": {},
        "source_refs": [{"source": "canonical_5m", "status": "ok"}],
        "artifact_refs": [],
        "data_quality": {
            "canonical_candle": {"status": "available" if approved else "stale"},
            "warnings": [] if approved else ["canonical_candle_stale"],
        },
    }


def _market(*, complete: bool = False) -> dict[str, object]:
    points = [AS_OF + timedelta(minutes=5)]
    if complete:
        points.extend(
            [
                AS_OF + timedelta(hours=1),
                AS_OF + timedelta(hours=4),
                datetime.combine(AS_OF.date(), time.max, tzinfo=UTC),
                AS_OF + timedelta(hours=24),
            ]
        )
    return {
        "candles": [
            {
                "time": point.isoformat(),
                "high": 2401.0,
                "low": 2399.0,
                "close": 2400.5,
                "partial": False,
            }
            for point in points
        ]
    }


def _kwargs(tmp_path: Path, *, approved: bool = False) -> dict[str, object]:
    return {
        "trade_date": "2026-07-17",
        "as_of": AS_OF,
        "evaluated_at": AS_OF,
        "storage_root": tmp_path,
        "live_output": _live(approved=approved),
        "market_candles": _market(),
        "write": False,
    }


def test_blocked_dry_run_and_write_are_stable_and_idempotent(tmp_path: Path) -> None:
    kwargs = _kwargs(tmp_path)

    dry = run_shadow_evaluation(**kwargs)
    assert dry["dry_run"] is True
    assert dry["snapshot_write_performed"] is False
    assert all(item["maturity_status"] == "persistable" for item in dry["outcomes"].values())
    assert all(item["status"] == "blocked" for item in dry["outcomes"].values())
    assert all(item["write_performed"] is False for item in dry["outcomes"].values())
    assert not (tmp_path / "evaluation").exists()

    written = run_shadow_evaluation(**(kwargs | {"write": True}))
    replay = run_shadow_evaluation(**(kwargs | {"write": True}))
    assert written["snapshot_created"] is True
    assert replay["snapshot_created"] is False
    assert replay["evaluation_id"] == written["evaluation_id"]
    assert all(item["created"] is True for item in written["outcomes"].values())
    assert all(item["created"] is False for item in replay["outcomes"].values())


def test_approved_immature_horizons_stay_pending_without_outcome_files(tmp_path: Path) -> None:
    summary = run_shadow_evaluation(**(_kwargs(tmp_path, approved=True) | {"write": True}))

    assert summary["snapshot_write_performed"] is True
    assert all(item["maturity_status"] == "pending" for item in summary["outcomes"].values())
    assert all(item["status"] is None for item in summary["outcomes"].values())
    assert all(item["path"] is None for item in summary["outcomes"].values())
    assert not list((tmp_path / "evaluation").rglob("outcomes/*.json"))


def test_retryable_gap_stays_pending_then_complete_candles_are_scored(tmp_path: Path) -> None:
    kwargs = _kwargs(tmp_path, approved=True) | {
        "evaluated_at": AS_OF + timedelta(hours=1),
        "write": True,
    }
    pending = run_shadow_evaluation(**kwargs)
    assert pending["outcomes"]["1h"]["maturity_status"] == "pending"
    assert pending["outcomes"]["1h"]["status"] == "unscorable"
    assert pending["outcomes"]["1h"]["path"] is None

    scored = run_shadow_evaluation(**(kwargs | {"market_candles": _market(complete=True)}))
    one_hour = scored["outcomes"]["1h"]
    assert scored["snapshot_created"] is False
    assert one_hour["maturity_status"] == "persistable"
    assert one_hour["status"] == "scored"
    assert one_hour["classification"] == "hold"
    assert one_hour["created"] is True
    assert one_hour["path"].endswith("/outcomes/1h.json")


def test_runner_passes_coverage_interval_for_an_off_grid_snapshot(tmp_path: Path) -> None:
    as_of = datetime(2026, 7, 18, 10, 39, 7, tzinfo=UTC)
    market = {
        "coverage": {"expected_interval_seconds": 300},
        "candles": [
            {"time": "2026-07-18T10:40:00+00:00", "high": 2401.0, "low": 2399.0, "close": 2400.5},
            {"time": "2026-07-18T11:30:00+00:00", "high": 2401.0, "low": 2399.0, "close": 2400.5},
        ],
    }

    summary = run_shadow_evaluation(
        **(_kwargs(tmp_path, approved=True) | {"as_of": as_of, "evaluated_at": as_of + timedelta(hours=1), "market_candles": market})
    )

    assert summary["outcomes"]["1h"]["maturity_status"] == "persistable"
    assert summary["outcomes"]["1h"]["status"] == "scored"


@pytest.mark.parametrize("value", ["300", True, float("nan"), float("inf"), 0, -1])
def test_runner_rejects_invalid_coverage_interval(tmp_path: Path, value: object) -> None:
    market = _market()
    market["coverage"] = {"expected_interval_seconds": value}

    with pytest.raises(ValueError, match="expected_candle_interval_seconds"):
        run_shadow_evaluation(**(_kwargs(tmp_path, approved=True) | {"market_candles": market}))


@pytest.mark.parametrize("field", ["as_of", "evaluated_at"])
def test_runner_requires_timezone_aware_timestamps(tmp_path: Path, field: str) -> None:
    kwargs = _kwargs(tmp_path)
    kwargs[field] = datetime(2026, 7, 17, 12)
    with pytest.raises(ValueError, match=f"{field} must include a timezone"):
        run_shadow_evaluation(**kwargs)


def test_runner_does_not_mutate_database_url(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://existing")

    run_shadow_evaluation(**_kwargs(tmp_path))

    assert os.environ["DATABASE_URL"] == "postgresql://existing"
