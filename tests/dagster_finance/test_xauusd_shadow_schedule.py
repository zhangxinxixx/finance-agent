from __future__ import annotations

from datetime import UTC, datetime, time, timedelta, timezone
from pathlib import Path

import pytest
from dagster import DefaultScheduleStatus, build_op_context, build_schedule_context

from dagster_finance.jobs.xauusd_shadow_job import xauusd_shadow_summary_job
from dagster_finance.ops.xauusd_shadow import (
    XauusdLiveStrategyHistoryConfig,
    XauusdShadowEvaluationConfig,
    XauusdShadowConfig,
    xauusd_live_strategy_history_op,
    xauusd_shadow_evaluation_op,
    xauusd_shadow_summary_op,
)
from dagster_finance.schedules.xauusd_shadow_schedule import xauusd_shadow_summary_daily_schedule


@pytest.mark.parametrize(
    ("scheduled_at", "expected_trade_date"),
    [
        (datetime(2026, 7, 14, 0, 20, tzinfo=timezone.utc), "2026-07-13"),
        (datetime(2026, 7, 15, 0, 20, tzinfo=timezone.utc), "2026-07-14"),
        (datetime(2026, 7, 16, 0, 20, tzinfo=timezone.utc), "2026-07-15"),
        (datetime(2026, 7, 17, 0, 20, tzinfo=timezone.utc), "2026-07-16"),
        (datetime(2026, 7, 18, 0, 20, tzinfo=timezone.utc), "2026-07-17"),
    ],
)
def test_shadow_schedule_targets_previous_utc_date(scheduled_at: datetime, expected_trade_date: str) -> None:
    request = xauusd_shadow_summary_daily_schedule(build_schedule_context(scheduled_execution_time=scheduled_at))
    as_of = scheduled_at.isoformat()

    assert request.run_key == f"xauusd-shadow:{expected_trade_date}"
    assert request.run_config == {
        "ops": {
            "xauusd_live_strategy_history_op": {
                "config": {"as_of": as_of, "storage_root": "./storage"}
            },
            "xauusd_shadow_evaluation_op": {
                "config": {
                    "evaluated_at": as_of,
                    "storage_root": "./storage",
                    "history_limit": 20,
                }
            },
            "xauusd_shadow_summary_op": {
                "config": {"trade_date": expected_trade_date, "storage_root": "./storage"}
            }
        }
    }
    assert request.tags == {"xauusd_shadow/trade_date": expected_trade_date}


def test_shadow_schedule_contract() -> None:
    schedule_def = xauusd_shadow_summary_daily_schedule
    assert schedule_def.name == "xauusd_shadow_summary_daily"
    assert schedule_def.cron_schedule == "20 0 * * 2-6"
    assert schedule_def.execution_timezone == "UTC"
    assert schedule_def.default_status == DefaultScheduleStatus.RUNNING


def test_shadow_job_contains_history_evaluation_and_finalized_summary_ops() -> None:
    assert {node.name for node in xauusd_shadow_summary_job.all_node_defs} == {
        "xauusd_live_strategy_history_op",
        "xauusd_shadow_evaluation_op",
        "xauusd_shadow_summary_op",
    }
    dependencies = xauusd_shadow_summary_job.graph.dependency_structure.input_to_upstream_outputs_for_node(
        "xauusd_shadow_evaluation_op"
    )
    history_input = next(item for item in dependencies if item.input_name == "history_freeze")
    assert dependencies[history_input][0].node_name == "xauusd_live_strategy_history_op"


def test_shadow_evaluation_config_bounds_history_limit() -> None:
    assert XauusdShadowEvaluationConfig().history_limit == 20
    with pytest.raises(ValueError):
        XauusdShadowEvaluationConfig(history_limit=101)


def test_shadow_op_skips_unfinalized_payload(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    payload = {
        "finalization": {"finalized": False},
        "reasons": ["sample_window_not_finalized"],
    }
    monkeypatch.setattr("dagster_finance.ops.xauusd_shadow.build_xauusd_shadow_summary", lambda *args, **kwargs: payload)
    writer = pytest.MonkeyPatch()
    writer.setattr("dagster_finance.ops.xauusd_shadow.write_xauusd_shadow_summary", lambda *args, **kwargs: pytest.fail("must not write"))
    try:
        result = xauusd_shadow_summary_op(
            build_op_context(resources={"db_session": object()}),
            XauusdShadowConfig(trade_date="2026-07-17", storage_root=str(tmp_path)),
        )
    finally:
        writer.undo()

    assert result == {
        "status": "skipped",
        "trade_date": "2026-07-17",
        "finalized": False,
        "reasons": ["sample_window_not_finalized"],
    }


def test_shadow_op_writes_only_finalized_payload(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    payload = {"finalization": {"finalized": True}, "reasons": []}
    calls: list[dict[str, object]] = []
    monkeypatch.setattr("dagster_finance.ops.xauusd_shadow.build_xauusd_shadow_summary", lambda *args, **kwargs: payload)

    def write_summary(payload_arg, *, output_path):
        calls.append({"payload": payload_arg, "output_path": output_path})
        return Path(output_path), True

    monkeypatch.setattr("dagster_finance.ops.xauusd_shadow.write_xauusd_shadow_summary", write_summary)
    result = xauusd_shadow_summary_op(
        build_op_context(resources={"db_session": object()}),
        XauusdShadowConfig(trade_date="2026-07-17", storage_root=str(tmp_path)),
    )

    assert result["status"] == "written"
    assert result["created"] is True
    assert calls == [{
        "payload": payload,
        "output_path": tmp_path / "monitoring" / "market_data" / "xauusd_shadow" / "2026-07-17" / "shadow_summary.json",
    }]


def _available_live_strategy(
    *,
    strategy_status: str = "WATCHING",
    updated_at: str = "2026-07-18T00:20:00Z",
) -> dict[str, object]:
    return {
        "schema_version": "live_strategy.v1",
        "status": "available",
        "asset": "XAUUSD",
        "strategy_id": "xauusd-live",
        "strategy_version": "live_strategy.rules.v2",
        "updated_at": updated_at,
        "strategy_status": strategy_status,
        "baseline": {
            "run_id": "daily-2026-07-18",
            "trade_date": "2026-07-18",
            "bias": "bullish",
        },
        "live_market": {"status": "available", "price": 2400.0},
        "data_quality": {"canonical_candle": {"status": "available"}},
        "source_refs": [{"source": "canonical_5m", "status": "ok"}],
        "setups": [],
    }


def test_live_strategy_history_op_skips_unavailable_without_creating_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "dagster_finance.ops.xauusd_shadow.get_live_strategy_latest",
        lambda **_: {
            **_available_live_strategy(),
            "live_market": {"status": "stale"},
            "data_quality": {"canonical_candle": {"status": "stale"}},
        },
    )

    storage_root = tmp_path / "new-storage"
    result = xauusd_live_strategy_history_op(
        build_op_context(resources={"db_session": object()}),
        XauusdLiveStrategyHistoryConfig(as_of="2026-07-18T00:20:00Z", storage_root=str(storage_root)),
    )

    assert result["status"] == "skipped"
    assert "canonical_market_unavailable" in result["reasons"]
    assert "canonical_data_unavailable" in result["reasons"]
    assert not storage_root.exists()


def test_live_strategy_history_op_writes_and_replays_unchanged(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    payload = _available_live_strategy()
    monkeypatch.setattr(
        "dagster_finance.ops.xauusd_shadow.get_live_strategy_latest",
        lambda **_: payload,
    )
    config = XauusdLiveStrategyHistoryConfig(
        as_of="2026-07-18T00:20:00Z", storage_root=str(tmp_path)
    )

    first = xauusd_live_strategy_history_op(
        build_op_context(resources={"db_session": object()}), config
    )
    second = xauusd_live_strategy_history_op(
        build_op_context(resources={"db_session": object()}), config
    )

    assert first["status"] == "written"
    assert first["created"] is True
    assert second["status"] == "unchanged"
    assert second["created"] is False
    assert first["artifact_ref"] == second["artifact_ref"]
    assert (tmp_path / first["artifact_ref"]).is_file()


def test_live_strategy_history_op_conflicting_replay_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    payload = _available_live_strategy()
    monkeypatch.setattr(
        "dagster_finance.ops.xauusd_shadow.get_live_strategy_latest",
        lambda **_: payload,
    )
    config = XauusdLiveStrategyHistoryConfig(
        as_of="2026-07-18T00:20:00Z", storage_root=str(tmp_path)
    )
    xauusd_live_strategy_history_op(build_op_context(resources={"db_session": object()}), config)

    payload["strategy_status"] = "ARMED"
    with pytest.raises(ValueError, match="immutable strategy version already differs"):
        xauusd_live_strategy_history_op(
            build_op_context(resources={"db_session": object()}), config
        )


def _history_response(payload: dict[str, object]) -> dict[str, object]:
    return {"items": [{"payload": payload}], "truncated": False}


def _market_candles(as_of: datetime, *, complete: bool) -> dict[str, object]:
    points = [as_of + timedelta(minutes=5)]
    if complete:
        points.extend(
            [
                as_of + timedelta(hours=1),
                as_of + timedelta(hours=4),
                datetime.combine(as_of.date(), time.max, tzinfo=UTC),
                as_of + timedelta(hours=24),
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


def test_shadow_evaluation_op_skips_no_history_without_candles_or_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "dagster_finance.ops.xauusd_shadow.get_live_strategy_history",
        lambda **_: {"items": [], "truncated": False},
    )
    monkeypatch.setattr(
        "dagster_finance.ops.xauusd_shadow.get_market_candles",
        lambda **_: pytest.fail("must not query candles without eligible history"),
    )
    storage_root = tmp_path / "new-storage"

    result = xauusd_shadow_evaluation_op(
        build_op_context(resources={"db_session": object()}),
        {"status": "skipped"},
        XauusdShadowEvaluationConfig(
            evaluated_at="2026-07-18T00:20:00Z",
            storage_root=str(storage_root),
        ),
    )

    assert result["status"] == "skipped"
    assert result["processed"] == 0
    assert result["artifact_refs"] == []
    assert not (storage_root / "evaluation").exists()


def test_shadow_evaluation_op_writes_approved_pending_snapshot_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    payload = _available_live_strategy(updated_at="2026-07-18T01:30:00+09:00")
    history_calls: list[dict[str, object]] = []
    candle_calls: list[dict[str, object]] = []

    def read_history(**kwargs):
        history_calls.append(kwargs)
        return _history_response(payload)

    def read_candles(**kwargs):
        candle_calls.append(kwargs)
        return _market_candles(datetime(2026, 7, 17, 16, 30, tzinfo=UTC), complete=False)

    monkeypatch.setattr("dagster_finance.ops.xauusd_shadow.get_live_strategy_history", read_history)
    monkeypatch.setattr("dagster_finance.ops.xauusd_shadow.get_market_candles", read_candles)
    session = object()
    result = xauusd_shadow_evaluation_op(
        build_op_context(resources={"db_session": session}),
        {"status": "written"},
        XauusdShadowEvaluationConfig(
            evaluated_at="2026-07-17T16:30:00Z",
            storage_root=str(tmp_path),
        ),
    )

    assert history_calls == [{"asset": "XAUUSD", "storage_root": tmp_path, "limit": 20}]
    assert candle_calls == [
        {"asset": "XAUUSD", "timeframe": "5m", "limit": 2000, "session": session}
    ]
    assert result["status"] == "completed"
    assert result["processed"] == 1
    assert result["snapshot_counts"] == {"created": 1, "unchanged": 0}
    assert result["outcome_counts"] == {"created": 0, "unchanged": 0, "pending": 4}
    assert result["evaluations"][0]["trade_date"] == "2026-07-17"
    assert result["evaluations"][0]["as_of"] == "2026-07-17T16:30:00+00:00"
    assert len(result["artifact_refs"]) == 1
    assert (tmp_path / result["artifact_refs"][0]).is_file()
    assert not list((tmp_path / "evaluation").rglob("outcomes/*.json"))


def test_shadow_evaluation_op_scores_mature_history_and_replays_unchanged(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    as_of = datetime(2026, 7, 17, 12, tzinfo=UTC)
    payload = _available_live_strategy(updated_at=as_of.isoformat())
    candle_calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        "dagster_finance.ops.xauusd_shadow.get_live_strategy_history",
        lambda **_: _history_response(payload),
    )

    def read_candles(**kwargs):
        candle_calls.append(kwargs)
        return _market_candles(as_of, complete=True)

    monkeypatch.setattr("dagster_finance.ops.xauusd_shadow.get_market_candles", read_candles)
    config = XauusdShadowEvaluationConfig(
        evaluated_at="2026-07-18T13:00:00Z",
        storage_root=str(tmp_path),
    )
    context = build_op_context(resources={"db_session": object()})

    first = xauusd_shadow_evaluation_op(context, {"status": "unchanged"}, config)
    replay = xauusd_shadow_evaluation_op(context, {"status": "unchanged"}, config)

    assert len(candle_calls) == 2
    assert first["snapshot_counts"] == {"created": 1, "unchanged": 0}
    assert first["outcome_counts"] == {"created": 4, "unchanged": 0, "pending": 0}
    assert replay["snapshot_counts"] == {"created": 0, "unchanged": 1}
    assert replay["outcome_counts"] == {"created": 0, "unchanged": 4, "pending": 0}
    assert replay["artifact_refs"] == first["artifact_refs"]
    assert len(first["artifact_refs"]) == 5
    assert all((tmp_path / ref).is_file() for ref in first["artifact_refs"])


def test_shadow_evaluation_op_rejects_bad_payload_and_propagates_runner_conflict(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    payload = _available_live_strategy(updated_at="2026-07-18T00:20:00")
    monkeypatch.setattr(
        "dagster_finance.ops.xauusd_shadow.get_live_strategy_history",
        lambda **_: _history_response(payload),
    )
    monkeypatch.setattr(
        "dagster_finance.ops.xauusd_shadow.get_market_candles",
        lambda **_: {"candles": []},
    )
    config = XauusdShadowEvaluationConfig(
        evaluated_at="2026-07-18T00:20:00Z",
        storage_root=str(tmp_path),
    )

    with pytest.raises(ValueError, match="history payload updated_at must include"):
        xauusd_shadow_evaluation_op(
            build_op_context(resources={"db_session": object()}),
            {"status": "written"},
            config,
        )

    payload["updated_at"] = "2026-07-18T00:20:00Z"
    monkeypatch.setattr(
        "dagster_finance.ops.xauusd_shadow.run_shadow_evaluation",
        lambda **_: (_ for _ in ()).throw(ValueError("immutable outcome conflict")),
    )
    with pytest.raises(ValueError, match="immutable outcome conflict"):
        xauusd_shadow_evaluation_op(
            build_op_context(resources={"db_session": object()}),
            {"status": "written"},
            config,
        )
