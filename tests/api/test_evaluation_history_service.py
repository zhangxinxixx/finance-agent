from __future__ import annotations

import json
from pathlib import Path

import pytest

from apps.api.services.evaluation_history_service import (
    EvaluationHistoryArtifactError,
    EvaluationHistoryQueryError,
    get_shadow_evaluation_history,
)


def _write_partition(
    root: Path,
    *,
    trade_date: str,
    evaluation_id: str,
    strategy_status: str = "WATCHING",
    publish_allowed: bool = False,
    outcomes: list[dict[str, object]] | None = None,
) -> Path:
    partition = root / "codex-xauusd-shadow" / "XAUUSD" / trade_date / evaluation_id
    partition.mkdir(parents=True)
    (partition / "strategy_snapshot.json").write_text(
        json.dumps(
            {
                "account_id": "codex-xauusd-shadow",
                "asset": "XAUUSD",
                "trade_date": trade_date,
                "evaluation_id": evaluation_id,
                "publish_allowed": publish_allowed,
                "quality_gate": {"status": "approved", "strategy_status": strategy_status},
            }
        ),
        encoding="utf-8",
    )
    if outcomes:
        outcome_dir = partition / "outcomes"
        outcome_dir.mkdir()
        for outcome in outcomes:
            (outcome_dir / f"{outcome['horizon']}.json").write_text(json.dumps(outcome), encoding="utf-8")
    return partition


def _outcome(evaluation_id: str, horizon: str, status: str, accuracy: str = "not_applicable") -> dict[str, object]:
    return {
        "evaluation_id": evaluation_id,
        "horizon": horizon,
        "status": status,
        "classification": "correct" if accuracy == "correct" else status,
        "direction_accuracy": accuracy,
    }


def test_empty_root_returns_stable_empty_read_model(tmp_path: Path) -> None:
    payload = get_shadow_evaluation_history(storage_root=tmp_path / "evaluation")

    assert payload == {
        "schema_version": "shadow_evaluation_history.v1",
        "account_id": "codex-xauusd-shadow",
        "asset": "XAUUSD",
        "items": [],
        "total": 0,
        "truncated": False,
    }


def test_history_sorts_trade_date_then_evaluation_id_and_counts_outcomes(tmp_path: Path) -> None:
    root = tmp_path / "evaluation"
    _write_partition(
        root,
        trade_date="2026-07-17",
        evaluation_id="eval-a",
        strategy_status="SUSPENDED_DATA",
        outcomes=[
            _outcome("eval-a", "1h", "scored", "correct"),
            _outcome("eval-a", "4h", "blocked"),
            _outcome("eval-a", "24h", "unscorable"),
        ],
    )
    _write_partition(root, trade_date="2026-07-17", evaluation_id="eval-z")
    _write_partition(root, trade_date="2026-07-18", evaluation_id="eval-old")

    payload = get_shadow_evaluation_history(storage_root=root, limit=10)

    assert [(item["trade_date"], item["evaluation_id"]) for item in payload["items"]] == [
        ("2026-07-18", "eval-old"),
        ("2026-07-17", "eval-z"),
        ("2026-07-17", "eval-a"),
    ]
    first = payload["items"][2]
    assert first["strategy_status"] == "SUSPENDED_DATA"
    assert first["outcome_count"] == 3
    assert first["approved_count"] == 1
    assert first["blocked_count"] == 1
    assert first["unscorable_count"] == 1
    assert first["accuracy"] == 1.0
    assert all(not Path(ref).is_absolute() for ref in first["artifact_refs"])
    assert payload["total"] == 3


def test_limit_is_applied_after_stable_sort_and_reports_truncation(tmp_path: Path) -> None:
    root = tmp_path / "evaluation"
    for index in range(3):
        _write_partition(root, trade_date=f"2026-07-{17 - index:02d}", evaluation_id=f"eval-{index}")

    payload = get_shadow_evaluation_history(storage_root=root, limit=2)

    assert payload["total"] == 3
    assert payload["truncated"] is True
    assert len(payload["items"]) == 2
    with pytest.raises(EvaluationHistoryQueryError):
        get_shadow_evaluation_history(storage_root=root, limit=0)
    with pytest.raises(EvaluationHistoryQueryError):
        get_shadow_evaluation_history(storage_root=root, limit=101)


def test_bad_json_raises_controlled_error_without_absolute_path(tmp_path: Path) -> None:
    partition = _write_partition(tmp_path / "evaluation", trade_date="2026-07-17", evaluation_id="eval-bad")
    (partition / "strategy_snapshot.json").write_text("{bad", encoding="utf-8")

    with pytest.raises(EvaluationHistoryArtifactError) as exc_info:
        get_shadow_evaluation_history(storage_root=tmp_path / "evaluation")
    assert str(tmp_path) not in str(exc_info.value)


def test_symlinked_partition_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "evaluation"
    target = tmp_path / "outside"
    target.mkdir()
    linked = root / "codex-xauusd-shadow" / "XAUUSD" / "2026-07-17"
    linked.parent.mkdir(parents=True)
    linked.symlink_to(target, target_is_directory=True)

    with pytest.raises(EvaluationHistoryArtifactError):
        get_shadow_evaluation_history(storage_root=root)


def test_broken_symlinked_asset_root_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "evaluation"
    linked = root / "codex-xauusd-shadow" / "XAUUSD"
    linked.parent.mkdir(parents=True)
    linked.symlink_to(tmp_path / "missing", target_is_directory=True)

    with pytest.raises(EvaluationHistoryArtifactError):
        get_shadow_evaluation_history(storage_root=root)


def test_query_components_are_strictly_validated(tmp_path: Path) -> None:
    with pytest.raises(EvaluationHistoryQueryError):
        get_shadow_evaluation_history(account_id="../escape", storage_root=tmp_path)
    with pytest.raises(EvaluationHistoryQueryError):
        get_shadow_evaluation_history(asset="DXY", storage_root=tmp_path)
    with pytest.raises(EvaluationHistoryQueryError):
        get_shadow_evaluation_history(limit=True, storage_root=tmp_path)
