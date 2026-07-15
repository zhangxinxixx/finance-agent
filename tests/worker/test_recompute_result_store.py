from __future__ import annotations

import json
import math

import pytest

from apps.worker.recompute_result_store import (
    RecomputeResultStore,
    RecomputeResultStoreConflictError,
    validate_recompute_result,
)


def _result(**overrides):
    value = {
        "schema_name": "live_strategy_recompute_result",
        "schema_version": "live_strategy_recompute_result.v1",
        "result_id": "attempt-1",
        "request_id": "request-1",
        "event_id": "event-1",
        "trade_date": "2026-07-18",
        "attempted_at": "2026-07-18T09:00:00+00:00",
        "attempt_status": "unavailable",
        "resolution_status": "eligible",
        "reason_codes": ["market_reaction_unavailable"],
        "input_snapshot_ids": {"event_snapshot": "snapshot-1"},
        "source_refs": [{"source_ref": "event:event-1"}],
    }
    value.update(overrides)
    return value


def test_writes_canonical_result_to_versioned_attempt_partition(tmp_path) -> None:
    store = RecomputeResultStore(tmp_path / "storage")
    result = store.write(_result())

    assert result.created is True
    assert result.path == (
        tmp_path
        / "storage/event_sla/2026-07-18/event-1/recompute_results/request-1/attempt-1/live_strategy_recompute_result.json"
    )
    assert result.artifact_ref == result.path.relative_to(tmp_path / "storage").as_posix()
    assert result.path.read_bytes() == (
        b'{"attempt_status":"unavailable","attempted_at":"2026-07-18T09:00:00Z","event_id":"event-1",'
        b'"input_snapshot_ids":{"event_snapshot":"snapshot-1"},"reason_codes":["market_reaction_unavailable"],'
        b'"request_id":"request-1","resolution_status":"eligible","result_id":"attempt-1",'
        b'"schema_name":"live_strategy_recompute_result","schema_version":"live_strategy_recompute_result.v1",'
        b'"source_refs":[{"source_ref":"event:event-1"}],"trade_date":"2026-07-18"}\n'
    )
    assert store.read(_result())["attempted_at"] == "2026-07-18T09:00:00Z"


def test_replay_is_idempotent_conflict_is_rejected_and_later_attempt_is_allowed(tmp_path) -> None:
    store = RecomputeResultStore(tmp_path)
    first = store.write(_result())

    assert store.write(_result()).created is False
    with pytest.raises(RecomputeResultStoreConflictError):
        store.write(_result(attempt_status="blocked"))

    later = store.write(
        _result(
            result_id="attempt-2",
            attempted_at="2026-07-18T10:00:00Z",
            attempt_status="accepted",
            reason_codes=["market_reaction_observed"],
        )
    )
    assert first.path != later.path
    assert later.created is True


def test_event_sla_max_length_event_id_is_a_safe_partition(tmp_path) -> None:
    event_id = "e" * 160
    written = RecomputeResultStore(tmp_path).write(_result(event_id=event_id))

    assert written.created is True
    assert written.path.parts[-5] == event_id


@pytest.mark.parametrize(
    "field,value",
    [
        ("event_id", "../escape"),
        ("result_id", "attempt/other"),
        ("trade_date", "not-a-date"),
        ("attempted_at", "2026-07-18T09:00:00"),
        ("attempt_status", "completed"),
        ("input_snapshot_ids", []),
        ("source_refs", [{}]),
        ("reason_codes", ["ok", math.nan]),
    ],
)
def test_invalid_components_and_non_json_data_are_rejected(tmp_path, field: str, value: object) -> None:
    store = RecomputeResultStore(tmp_path)
    with pytest.raises(ValueError):
        store.write(_result(**{field: value}))


def test_existing_noncanonical_but_semantically_identical_json_is_a_replay(tmp_path) -> None:
    store = RecomputeResultStore(tmp_path)
    path = store.result_path(_result())
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(validate_recompute_result(_result()), indent=2), encoding="utf-8")

    assert store.write(_result()).created is False
