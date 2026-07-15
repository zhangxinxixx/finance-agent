from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json

import pytest

from apps.analysis.evaluation import build_strategy_snapshot, evaluate_strategy_outcome
from apps.analysis.evaluation.store import EvaluationStore, EvaluationStoreConflictError


AS_OF = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)


def _snapshot(**overrides):
    values = {
        "asset": "XAUUSD",
        "trade_date": "2026-07-17",
        "run_id": "run-1",
        "strategy_id": "live-1",
        "strategy_version": "strategy.rules.v1",
        "as_of": AS_OF,
        "reference_price": 100.0,
        "bias": "bullish",
        "confidence": 0.8,
        "evaluation_id": "eval-fixed",
        "publish_allowed": True,
        "quality_gate": {"status": "approved"},
        "entry_conditions": [{"trigger_price": 100.5, "direction": "above"}],
        "invalidation": {"invalidation_level": 99.0},
        "source_refs": [{"source": "canonical_5m", "status": "ok"}],
        "artifact_refs": ["storage/outputs/strategy_card/run-1.json"],
    }
    values.update(overrides)
    return build_strategy_snapshot(**values)


def _candles() -> list[dict[str, object]]:
    rows = []
    for index in range(1, 13):
        close = 100.6 + (index * 0.1)
        rows.append(
            {
                "time": (AS_OF + timedelta(minutes=5 * index)).isoformat(),
                "high": close + 0.2,
                "low": close - 0.2,
                "close": close,
                "partial": False,
            }
        )
    rows.append(
        {
            "time": (AS_OF + timedelta(hours=1)).isoformat(),
            "high": 102.0,
            "low": 100.0,
            "close": 101.8,
            "partial": False,
        }
    )
    return rows


def test_snapshot_write_is_partitioned_and_readable(tmp_path) -> None:
    store = EvaluationStore(tmp_path / "storage")
    snapshot = _snapshot()

    result = store.write_snapshot(snapshot)

    assert result.created is True
    assert result.path == tmp_path / "storage/evaluation/codex-xauusd-shadow/XAUUSD/2026-07-17/eval-fixed/strategy_snapshot.json"
    assert result.path.is_file()
    assert store.read_snapshot(snapshot) == snapshot.to_dict()
    assert result.path.read_bytes().endswith(b"\n")


def test_snapshot_replay_is_idempotent_but_content_conflict_is_rejected(tmp_path) -> None:
    store = EvaluationStore(tmp_path)
    snapshot = _snapshot()

    first = store.write_snapshot(snapshot)
    replay = store.write_snapshot(snapshot)
    assert replay.path == first.path
    assert replay.created is False

    conflicting = _snapshot(bias="bearish")
    with pytest.raises(EvaluationStoreConflictError):
        store.write_snapshot(conflicting)
    assert store.read_snapshot(snapshot)["bias"] == "bullish"


def test_semantically_same_existing_json_is_idempotent(tmp_path) -> None:
    store = EvaluationStore(tmp_path)
    snapshot = _snapshot()
    path = store.snapshot_path(snapshot)
    path.parent.mkdir(parents=True)
    path.write_text('{"bias": "bullish", "evaluation_id": "eval-fixed"}\n', encoding="utf-8")

    with pytest.raises(EvaluationStoreConflictError):
        store.write_snapshot(snapshot)

    path.write_text(json.dumps(snapshot.to_dict(), indent=2), encoding="utf-8")
    result = store.write_snapshot(snapshot)

    assert result.created is False


def test_outcome_uses_same_partition_and_horizon_file(tmp_path) -> None:
    store = EvaluationStore(tmp_path)
    snapshot = _snapshot()
    outcome = evaluate_strategy_outcome(snapshot, _candles(), horizon="1h")

    result = store.write_outcome(snapshot, outcome)

    assert result.created is True
    assert result.path == tmp_path / "evaluation/codex-xauusd-shadow/XAUUSD/2026-07-17/eval-fixed/outcomes/1h.json"
    assert store.read_outcome(snapshot, "1h") == outcome.to_dict()
    assert store.write_outcome(snapshot, outcome).created is False


def test_outcome_id_mismatch_cannot_cross_partition(tmp_path) -> None:
    store = EvaluationStore(tmp_path)
    snapshot = _snapshot()
    other = _snapshot(evaluation_id="eval-other")
    outcome = evaluate_strategy_outcome(other, _candles(), horizon="1h")

    with pytest.raises(ValueError, match="evaluation_id"):
        store.write_outcome(snapshot, outcome)


@pytest.mark.parametrize(
    "field,value",
    [
        ("account_id", "../escape"),
        ("asset", "XAUUSD/other"),
        ("trade_date", ""),
        ("evaluation_id", "eval\\other"),
    ],
)
def test_path_components_are_whitelisted(tmp_path, field: str, value: str) -> None:
    store = EvaluationStore(tmp_path)
    context = {
        "account_id": "codex-xauusd-shadow",
        "asset": "XAUUSD",
        "trade_date": "2026-07-17",
        "evaluation_id": "eval-fixed",
    }
    context[field] = value

    with pytest.raises(ValueError, match=field):
        store.snapshot_path(context)


def test_missing_or_malformed_artifact_is_reported(tmp_path) -> None:
    store = EvaluationStore(tmp_path)
    snapshot = _snapshot()

    with pytest.raises(FileNotFoundError):
        store.read_snapshot(snapshot)

    path = store.snapshot_path(snapshot)
    path.parent.mkdir(parents=True)
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON object"):
        store.read_snapshot(snapshot)
