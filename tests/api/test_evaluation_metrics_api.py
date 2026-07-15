from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import HTTPException

from apps.analysis.evaluation import build_strategy_snapshot, evaluate_strategy_outcome
from apps.analysis.evaluation.store import EvaluationStore
from apps.api.routes.evaluation_routes import (
    api_latest_shadow_evaluation_metrics,
    api_shadow_evaluation_metrics,
)
from apps.api.services.evaluation_service import (
    EvaluationArtifactError,
    EvaluationQueryError,
    get_latest_shadow_evaluation_metrics,
    get_shadow_evaluation_metrics,
)


def _snapshot(evaluation_id: str = "eval-api"):
    as_of = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)
    return build_strategy_snapshot(
        asset="XAUUSD", trade_date="2026-07-17", run_id="run-api", strategy_id="live-api",
        strategy_version="strategy.rules.v1", as_of=as_of, reference_price=100.0,
        bias="bullish", evaluation_id=evaluation_id, publish_allowed=True,
        quality_gate={"status": "approved"}, entry_conditions=[{"trigger_price": 100.5}],
        invalidation={"invalidation_level": 99.0},
        source_refs=[{"source": "canonical_5m", "status": "ok"}],
    )


def _candles() -> list[dict[str, object]]:
    as_of = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)
    rows = []
    for index in range(1, 13):
        close = 100.6 + index * 0.1
        rows.append({"time": (as_of + timedelta(minutes=5 * index)).isoformat(), "high": close + 0.2, "low": close - 0.2, "close": close, "partial": False})
    rows.append({"time": (as_of + timedelta(hours=1)).isoformat(), "high": 102.0, "low": 100.0, "close": 101.8, "partial": False})
    return rows


def test_service_reads_realistic_local_partition(tmp_path: Path) -> None:
    store = EvaluationStore(tmp_path)
    snapshot = _snapshot()
    store.write_snapshot(snapshot)
    store.write_outcome(snapshot, evaluate_strategy_outcome(snapshot, _candles(), horizon="1h"))

    payload = get_shadow_evaluation_metrics(trade_date="2026-07-17", storage_root=tmp_path / "evaluation")

    assert payload is not None
    assert payload["schema_version"] == "shadow_evaluation_metrics_api.v1"
    assert payload["snapshot_count"] == 1
    assert payload["outcome_count"] == 1
    assert payload["metrics"]["approved_count"] == 1
    assert payload["artifact_refs"]


def test_service_returns_none_for_empty_partition_and_rejects_paths(tmp_path: Path) -> None:
    assert get_shadow_evaluation_metrics(trade_date="2026-07-17", storage_root=tmp_path / "evaluation") is None
    with pytest.raises(ValueError):
        get_shadow_evaluation_metrics(account_id="../escape", trade_date="2026-07-17", storage_root=tmp_path / "evaluation")
    with pytest.raises(ValueError):
        get_shadow_evaluation_metrics(trade_date="2026-7-17", storage_root=tmp_path / "evaluation")
    with pytest.raises(ValueError):
        get_shadow_evaluation_metrics(asset="DXY", trade_date="2026-07-17", storage_root=tmp_path / "evaluation")


def test_latest_service_selects_latest_valid_nonempty_partition(tmp_path: Path) -> None:
    store = EvaluationStore(tmp_path)
    older = _snapshot("eval-older")
    latest = build_strategy_snapshot(
        asset="XAUUSD", trade_date="2026-07-18", run_id="run-latest", strategy_id="live-latest",
        strategy_version="strategy.rules.v1", as_of=datetime(2026, 7, 18, 12, 0, tzinfo=UTC),
        reference_price=101.0, bias="bullish", evaluation_id="eval-latest", publish_allowed=False,
        quality_gate={"status": "blocked"},
    )
    store.write_snapshot(older)
    store.write_snapshot(latest)
    (tmp_path / "evaluation" / "codex-xauusd-shadow" / "XAUUSD" / "not-a-date").mkdir()

    payload = get_latest_shadow_evaluation_metrics(storage_root=tmp_path / "evaluation")

    assert payload is not None
    assert payload["trade_date"] == "2026-07-18"
    assert payload["evaluation_ids"] == ["eval-latest"]


def test_latest_service_skips_empty_newer_partition(tmp_path: Path) -> None:
    store = EvaluationStore(tmp_path)
    store.write_snapshot(_snapshot())
    (tmp_path / "evaluation" / "codex-xauusd-shadow" / "XAUUSD" / "2026-07-18").mkdir()

    payload = get_latest_shadow_evaluation_metrics(storage_root=tmp_path / "evaluation")

    assert payload is not None
    assert payload["trade_date"] == "2026-07-17"


def test_route_raises_404_without_partition(monkeypatch) -> None:
    monkeypatch.setattr("apps.api.routes.evaluation_routes.get_shadow_evaluation_metrics", lambda **_: None)
    with pytest.raises(HTTPException) as exc_info:
        api_shadow_evaluation_metrics(trade_date="2026-07-17")
    assert exc_info.value.status_code == 404


def test_route_maps_invalid_input_to_422(monkeypatch) -> None:
    def reject(**_):
        raise EvaluationQueryError("invalid trade_date")

    monkeypatch.setattr("apps.api.routes.evaluation_routes.get_shadow_evaluation_metrics", reject)
    with pytest.raises(HTTPException) as exc_info:
        api_shadow_evaluation_metrics(trade_date="bad")
    assert exc_info.value.status_code == 422


def test_latest_route_raises_404_without_partition(monkeypatch) -> None:
    monkeypatch.setattr("apps.api.routes.evaluation_routes.get_latest_shadow_evaluation_metrics", lambda **_: None)
    with pytest.raises(HTTPException) as exc_info:
        api_latest_shadow_evaluation_metrics()
    assert exc_info.value.status_code == 404


def test_artifact_errors_are_not_mapped_to_client_input_or_path_leak(monkeypatch) -> None:
    monkeypatch.setattr(
        "apps.api.routes.evaluation_routes.get_shadow_evaluation_metrics",
        lambda **_: (_ for _ in ()).throw(EvaluationArtifactError("/secret/path must not leak")),
    )
    with pytest.raises(HTTPException) as exc_info:
        api_shadow_evaluation_metrics(trade_date="2026-07-17")
    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "Shadow evaluation artifacts are invalid"


def test_service_rejects_symlinked_artifact_partition(tmp_path: Path) -> None:
    store = EvaluationStore(tmp_path)
    store.write_snapshot(_snapshot())
    partition = tmp_path / "evaluation" / "codex-xauusd-shadow" / "XAUUSD" / "2026-07-17"
    external = tmp_path / "external-outcomes"
    external.mkdir()
    (external / "strategy_snapshot.json").write_text("{}", encoding="utf-8")
    symlink = partition / "linked"
    symlink.symlink_to(external, target_is_directory=True)
    with pytest.raises(EvaluationArtifactError):
        get_shadow_evaluation_metrics(trade_date="2026-07-17", storage_root=tmp_path / "evaluation")
