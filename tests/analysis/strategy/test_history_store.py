from __future__ import annotations

import json
from pathlib import Path

import pytest

from apps.analysis.strategy.history_store import (
    HISTORY_SCHEMA_VERSION,
    HistoryWriteResult,
    StrategyHistoryConflictError,
    StrategyHistoryStore,
)


def _strategy(*, version: str = "live_strategy.rules.v2", updated_at: str = "2026-07-18T09:00:00+08:00") -> dict[str, object]:
    return {
        "asset": "XAUUSD",
        "strategy_id": "xauusd-live",
        "strategy_version": version,
        "updated_at": updated_at,
        "strategy_status": "WATCHING",
        "setups": [{"direction": "long", "entry_zone": [3350, 3355]}],
    }


def test_write_read_normalizes_utc_and_returns_refs(tmp_path: Path) -> None:
    store = StrategyHistoryStore(tmp_path)

    result = store.write(_strategy())

    assert isinstance(result, HistoryWriteResult)
    assert result.created is True
    assert result.schema_version == HISTORY_SCHEMA_VERSION
    assert result.artifact_ref == "strategy_history/XAUUSD/2026-07-18/xauusd-live/live_strategy.rules.v2.json"
    assert store.read(result.artifact_ref)["updated_at"] == "2026-07-18T01:00:00Z"


def test_same_content_is_idempotent_and_different_content_conflicts(tmp_path: Path) -> None:
    store = StrategyHistoryStore(tmp_path)
    first = store.write(_strategy())
    second = store.write(_strategy(updated_at="2026-07-18T01:00:00Z"))

    assert second.created is False
    assert second.path == first.path
    with pytest.raises(StrategyHistoryConflictError):
        store.write(_strategy(updated_at="2026-07-18T01:01:00Z"))


@pytest.mark.parametrize(
    "payload",
    [
        {"asset": "../XAUUSD", "strategy_id": "x", "strategy_version": "v1", "updated_at": "2026-07-18T00:00:00Z"},
        {"asset": "XAUUSD", "strategy_id": "../x", "strategy_version": "v1", "updated_at": "2026-07-18T00:00:00Z"},
        {"asset": "XAUUSD", "strategy_id": "x", "strategy_version": "../v1", "updated_at": "2026-07-18T00:00:00Z"},
    ],
)
def test_path_components_reject_traversal(tmp_path: Path, payload: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        StrategyHistoryStore(tmp_path).write(payload)


def test_list_latest_sorts_by_utc_timestamp_and_applies_limit(tmp_path: Path) -> None:
    store = StrategyHistoryStore(tmp_path)
    store.write(_strategy(version="v1", updated_at="2026-07-18T01:00:00Z"))
    store.write(_strategy(version="v2", updated_at="2026-07-18T04:00:00Z"))
    store.write(_strategy(version="v3", updated_at="2026-07-18T03:00:00Z"))

    latest = store.list_latest(asset="XAUUSD", strategy_id="xauusd-live", limit=2)

    assert [record["strategy_version"] for record in latest] == ["v2", "v3"]
    assert all(record["schema_version"] == HISTORY_SCHEMA_VERSION for record in latest)
    assert all(record["payload"]["asset"] == "XAUUSD" for record in latest)
    with pytest.raises(ValueError):
        store.list_latest(asset="XAUUSD", limit=101)


def test_read_rejects_malformed_json(tmp_path: Path) -> None:
    store = StrategyHistoryStore(tmp_path)
    ref = "strategy_history/XAUUSD/2026-07-18/xauusd-live/v1.json"
    path = tmp_path / ref
    path.parent.mkdir(parents=True)
    path.write_text("{broken", encoding="utf-8")

    with pytest.raises(ValueError, match="invalid strategy history artifact"):
        store.read(ref)


def test_read_rejects_non_object_json(tmp_path: Path) -> None:
    store = StrategyHistoryStore(tmp_path)
    ref = "strategy_history/XAUUSD/2026-07-18/xauusd-live/v1.json"
    path = tmp_path / ref
    path.parent.mkdir(parents=True)
    path.write_text("[1, 2, 3]", encoding="utf-8")

    with pytest.raises(ValueError, match="must contain a JSON object"):
        store.read(ref)


def test_read_rejects_escape_and_symlink(tmp_path: Path) -> None:
    store = StrategyHistoryStore(tmp_path)
    with pytest.raises(ValueError):
        store.read("../outside.json")

    outside = tmp_path.parent / "outside-history.json"
    outside.write_text(json.dumps(_strategy()), encoding="utf-8")
    link = tmp_path / "strategy_history" / "XAUUSD" / "2026-07-18" / "xauusd-live" / "v1.json"
    link.parent.mkdir(parents=True)
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks unavailable")
    with pytest.raises(ValueError):
        store.read(link)

    broken = link.with_name("broken.json")
    broken.symlink_to(tmp_path / "missing.json")
    with pytest.raises(ValueError):
        store.read(broken)
