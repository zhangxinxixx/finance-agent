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
    as_of: str | None = None,
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
                **({"as_of": as_of} if as_of else {}),
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


def _outcome(
    evaluation_id: str,
    horizon: str,
    status: str,
    accuracy: str = "not_applicable",
    **overrides: object,
) -> dict[str, object]:
    return {
        "evaluation_id": evaluation_id,
        "horizon": horizon,
        "status": status,
        "classification": "correct" if accuracy == "correct" else status,
        "direction_accuracy": accuracy,
        **overrides,
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
            _outcome(
                "eval-a",
                "1h",
                "scored",
                "correct",
                lifecycle_status="target_reached",
                setup_id="setup-long",
                fill_price=4000.5,
                fill_time="2026-07-17T01:05:00+00:00",
                target_price=4025.0,
                target_time="2026-07-17T01:30:00+00:00",
                exit_price=4025.0,
                exit_time="2026-07-17T01:30:00+00:00",
                return_abs=24.5,
                return_pct=0.0061242345,
                mfe=24.5,
                mae=1.25,
                reason_codes=["target_observed"],
            ),
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
    assert first["legacy_unverified_count"] == 0
    assert first["accuracy"] == 1.0
    assert first["outcomes"][0] == {
        "horizon": "1h",
        "status": "scored",
        "classification": "correct",
        "verification_status": "verified",
        "lifecycle_status": "target_reached",
        "setup_id": "setup-long",
        "fill_price": 4000.5,
        "fill_time": "2026-07-17T01:05:00+00:00",
        "target_price": 4025.0,
        "target_time": "2026-07-17T01:30:00+00:00",
        "exit_price": 4025.0,
        "exit_time": "2026-07-17T01:30:00+00:00",
        "return_abs": 24.5,
        "return_pct": 0.0061242345,
        "mfe": 24.5,
        "mae": 1.25,
        "reason_codes": ["target_observed"],
    }
    assert first["outcomes"][1]["lifecycle_status"] is None
    assert first["outcomes"][1]["fill_price"] is None
    assert all(not Path(ref).is_absolute() for ref in first["artifact_refs"])
    assert payload["total"] == 3


def test_history_marks_legacy_hold_unverified_and_excludes_it_from_approved_counts(tmp_path: Path) -> None:
    root = tmp_path / "evaluation"
    _write_partition(
        root,
        trade_date="2026-07-18",
        evaluation_id="eval-legacy-hold",
        publish_allowed=True,
        outcomes=[
            _outcome(
                "eval-legacy-hold",
                "1h",
                "scored",
                "correct",
                classification="hold",
                reason_codes=["trigger_not_observed"],
            )
        ],
    )

    item = get_shadow_evaluation_history(storage_root=root)["items"][0]

    assert item["approved_count"] == 0
    assert item["legacy_unverified_count"] == 1
    assert item["accuracy"] is None
    assert item["outcomes"][0]["classification"] == "hold"
    assert item["outcomes"][0]["verification_status"] == "legacy_unverified"


def test_history_sorts_same_day_partitions_by_snapshot_as_of_not_random_id(tmp_path: Path) -> None:
    root = tmp_path / "evaluation"
    _write_partition(
        root,
        trade_date="2026-07-21",
        evaluation_id="eval-z-old",
        as_of="2026-07-21T08:00:00+00:00",
    )
    _write_partition(
        root,
        trade_date="2026-07-21",
        evaluation_id="eval-a-new",
        as_of="2026-07-21T10:00:00+00:00",
    )

    items = get_shadow_evaluation_history(storage_root=root)["items"]

    assert [item["evaluation_id"] for item in items] == ["eval-a-new", "eval-z-old"]
    assert items[0]["as_of"] == "2026-07-21T10:00:00+00:00"


def test_history_rejects_malformed_present_outcome_summary_fields(tmp_path: Path) -> None:
    root = tmp_path / "evaluation"
    _write_partition(
        root,
        trade_date="2026-07-17",
        evaluation_id="eval-bad-outcome",
        outcomes=[_outcome("eval-bad-outcome", "1h", "scored", fill_price=True)],
    )

    with pytest.raises(EvaluationHistoryArtifactError, match="outcome summary"):
        get_shadow_evaluation_history(storage_root=root)


def test_history_accepts_insufficient_strategy_contract_lifecycle(tmp_path: Path) -> None:
    root = tmp_path / "evaluation"
    _write_partition(
        root,
        trade_date="2026-07-18",
        evaluation_id="eval-replayed",
        outcomes=[
            _outcome(
                "eval-replayed",
                "1h",
                "unscorable",
                lifecycle_status="insufficient_strategy_contract",
                reason_codes=["evaluation_setup_missing"],
            )
        ],
    )

    payload = get_shadow_evaluation_history(storage_root=root)

    assert payload["items"][0]["outcomes"][0]["lifecycle_status"] == "insufficient_strategy_contract"


def test_history_rejects_noncanonical_or_duplicate_outcome_horizons(tmp_path: Path) -> None:
    root = tmp_path / "evaluation"
    partition = _write_partition(
        root,
        trade_date="2026-07-17",
        evaluation_id="eval-bad-horizon",
        outcomes=[_outcome("eval-bad-horizon", "1h", "scored")],
    )
    outcome_dir = partition / "outcomes"
    (outcome_dir / "duplicate.json").write_text(
        json.dumps(_outcome("eval-bad-horizon", "1h", "scored")),
        encoding="utf-8",
    )

    with pytest.raises(EvaluationHistoryArtifactError, match="horizons"):
        get_shadow_evaluation_history(storage_root=root)

    (outcome_dir / "duplicate.json").write_text(
        json.dumps(_outcome("eval-bad-horizon", "2h", "scored")),
        encoding="utf-8",
    )
    with pytest.raises(EvaluationHistoryArtifactError, match="horizon"):
        get_shadow_evaluation_history(storage_root=root)


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
