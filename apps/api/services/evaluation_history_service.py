"""Read-only history read model for local shadow-evaluation artifacts.

The history service deliberately reads the append-only artifact layout rather
than recalculating strategy outcomes.  A history item represents one immutable
``strategy_snapshot.json`` partition and its already persisted outcomes.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from math import isfinite
from numbers import Real
from pathlib import Path
from typing import Any

from apps.api.services._storage import _PROJECT_ROOT

_COMPONENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_DEFAULT_ACCOUNT_ID = "codex-xauusd-shadow"
_DEFAULT_ASSET = "XAUUSD"
_MAX_ARTIFACT_BYTES = 2 * 1024 * 1024
_MAX_ARTIFACT_FILES = 1000
_MAX_LIMIT = 100
_HORIZON_ORDER = {value: index for index, value in enumerate(("1h", "4h", "session", "24h"))}
_OUTCOME_STATUSES = {"scored", "blocked", "unscorable"}
_OUTCOME_CLASSIFICATIONS = {"correct", "incorrect", "neutral", "hold", "invalidated", "blocked", "unscorable"}
_OUTCOME_LIFECYCLES = {
    "never_triggered",
    "invalidated_before_entry",
    "triggered",
    "triggered_then_invalidated",
    "target_reached",
    "same_bar_ambiguous",
    "insufficient_market_path",
    "insufficient_strategy_contract",
    "blocked",
}


class EvaluationHistoryQueryError(ValueError):
    """The caller supplied an invalid history query."""


class EvaluationHistoryArtifactError(RuntimeError):
    """An artifact is missing, unreadable, malformed, or unsafe."""


def get_shadow_evaluation_history(
    *,
    account_id: str = _DEFAULT_ACCOUNT_ID,
    asset: str = _DEFAULT_ASSET,
    limit: int = 20,
    storage_root: Path | None = None,
) -> dict[str, Any]:
    """List immutable local evaluation partitions in stable reverse order.

    ``storage_root`` points at the ``storage/evaluation`` directory, matching
    :class:`apps.analysis.evaluation.store.EvaluationStore` and the existing
    metrics service.  Missing roots and empty partitions return an empty list;
    no synthetic evaluation is created for incomplete directories.
    """

    account = _safe_component(account_id, "account_id")
    if not isinstance(asset, str):
        raise EvaluationHistoryQueryError("invalid asset")
    normalized_asset = _safe_component(asset.upper(), "asset")
    if normalized_asset != _DEFAULT_ASSET:
        raise EvaluationHistoryQueryError("shadow evaluation currently supports only XAUUSD")
    normalized_limit = _safe_limit(limit)

    root = _resolve_root(storage_root)
    asset_root = _safe_directory(root / account / normalized_asset, root)
    if asset_root is None:
        return _empty_payload(account, normalized_asset, normalized_limit)

    items: list[dict[str, Any]] = []
    for date_dir in sorted(asset_root.iterdir(), key=lambda item: item.name, reverse=True):
        if date_dir.is_symlink():
            raise EvaluationHistoryArtifactError("evaluation history path is unsafe")
        if not date_dir.is_dir():
            continue
        trade_date = _safe_trade_date(date_dir.name, artifact=True)
        _assert_inside(date_dir, asset_root)
        for evaluation_dir in sorted(date_dir.iterdir(), key=lambda item: item.name, reverse=True):
            if evaluation_dir.is_symlink():
                raise EvaluationHistoryArtifactError("evaluation history path is unsafe")
            if not evaluation_dir.is_dir():
                continue
            evaluation_id = _safe_component(evaluation_dir.name, "evaluation_id", artifact=True)
            _assert_inside(evaluation_dir, date_dir)
            item = _read_partition(
                root=root,
                account=account,
                asset=normalized_asset,
                trade_date=trade_date,
                evaluation_id=evaluation_id,
                partition=evaluation_dir,
            )
            if item is not None:
                items.append(item)

    items.sort(
        key=lambda item: (
            item["trade_date"],
            item["_sort_timestamp"],
            item["evaluation_id"],
        ),
        reverse=True,
    )
    for item in items:
        item.pop("_sort_timestamp", None)
    total = len(items)
    return {
        "schema_version": "shadow_evaluation_history.v1",
        "account_id": account,
        "asset": normalized_asset,
        "items": items[:normalized_limit],
        "total": total,
        "truncated": total > normalized_limit,
    }


# ``list_`` reads naturally at call sites and is retained as a compatibility
# alias for the eventual history route.
list_shadow_evaluation_history = get_shadow_evaluation_history


def _read_partition(
    *,
    root: Path,
    account: str,
    asset: str,
    trade_date: str,
    evaluation_id: str,
    partition: Path,
) -> dict[str, Any] | None:
    snapshot_path = partition / "strategy_snapshot.json"
    outcome_dir = partition / "outcomes"
    if outcome_dir.is_symlink():
        raise EvaluationHistoryArtifactError("evaluation history path is unsafe")
    outcome_files = []
    if outcome_dir.exists():
        if not outcome_dir.is_dir():
            raise EvaluationHistoryArtifactError("evaluation outcomes directory is invalid")
        _assert_inside(outcome_dir, partition)
        for path in sorted(outcome_dir.iterdir(), key=lambda item: item.name):
            if path.is_symlink():
                raise EvaluationHistoryArtifactError("evaluation artifact path is unsafe")
            if not path.is_file():
                continue
            if path.suffix != ".json" or not _COMPONENT_RE.fullmatch(path.stem):
                raise EvaluationHistoryArtifactError("evaluation outcome path is invalid")
            outcome_files.append(path)
            if len(outcome_files) > _MAX_ARTIFACT_FILES:
                raise EvaluationHistoryArtifactError("evaluation artifact count exceeds limit")

    if snapshot_path.is_symlink():
        raise EvaluationHistoryArtifactError("evaluation artifact path is unsafe")
    if not snapshot_path.exists():
        if outcome_files:
            raise EvaluationHistoryArtifactError("evaluation snapshot is missing")
        return None
    if not snapshot_path.is_file():
        raise EvaluationHistoryArtifactError("evaluation artifact path is unsafe")
    snapshot = _read_object(snapshot_path)
    _validate_context(snapshot, account, asset, trade_date, evaluation_id)

    outcomes = [_read_object(path) for path in outcome_files]
    for outcome in outcomes:
        _validate_outcome(outcome, evaluation_id)
    outcome_horizons = [str(outcome["horizon"]) for outcome in outcomes]
    if len(outcome_horizons) > len(_HORIZON_ORDER) or len(set(outcome_horizons)) != len(outcome_horizons):
        raise EvaluationHistoryArtifactError("evaluation outcome horizons are invalid")
    outcome_summaries = sorted(
        (_outcome_summary(outcome) for outcome in outcomes),
        key=lambda item: _HORIZON_ORDER.get(item["horizon"], len(_HORIZON_ORDER)),
    )
    counts = _outcome_counts(outcomes)
    refs = [_artifact_ref(root, snapshot_path), *(_artifact_ref(root, path) for path in outcome_files)]
    quality_gate = snapshot.get("quality_gate")
    strategy_status = snapshot.get("strategy_status")
    if not isinstance(strategy_status, str) and isinstance(quality_gate, dict):
        strategy_status = quality_gate.get("strategy_status") or quality_gate.get("status")
    if not isinstance(strategy_status, str):
        strategy_status = "unknown"
    snapshot_as_of = snapshot.get("as_of") if isinstance(snapshot.get("as_of"), str) else None
    return {
        "trade_date": trade_date,
        "evaluation_id": evaluation_id,
        "strategy_status": strategy_status,
        "as_of": snapshot_as_of,
        "publish_allowed": bool(snapshot.get("publish_allowed", False)),
        "outcome_count": len(outcomes),
        "approved_count": counts["approved_count"],
        "blocked_count": counts["blocked_count"],
        "unscorable_count": counts["unscorable_count"],
        "legacy_unverified_count": counts["legacy_unverified_count"],
        "accuracy": counts["accuracy"],
        "outcomes": outcome_summaries,
        "artifact_refs": refs,
        "_sort_timestamp": _snapshot_sort_timestamp(snapshot_as_of, snapshot_path),
    }


def _snapshot_sort_timestamp(as_of: str | None, snapshot_path: Path) -> float:
    if as_of:
        try:
            parsed = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
            if parsed.tzinfo is not None and parsed.utcoffset() is not None:
                return parsed.astimezone(timezone.utc).timestamp()
        except ValueError:
            pass
    try:
        return snapshot_path.stat().st_mtime_ns / 1_000_000_000
    except OSError:
        return 0.0


def _outcome_counts(outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    approved = sum(
        item.get("status") == "scored" and item.get("lifecycle_status") in _OUTCOME_LIFECYCLES
        for item in outcomes
    )
    legacy_unverified = sum(_is_legacy_unverified(item) for item in outcomes)
    blocked = sum(item.get("status") == "blocked" for item in outcomes)
    unscorable = sum(item.get("status") == "unscorable" for item in outcomes)
    directional = [
        item for item in outcomes
        if item.get("status") == "scored"
        and not _is_legacy_unverified(item)
        and item.get("direction_accuracy") in {"correct", "incorrect"}
    ]
    return {
        "approved_count": approved,
        "blocked_count": blocked,
        "unscorable_count": unscorable,
        "legacy_unverified_count": legacy_unverified,
        "accuracy": (sum(item.get("direction_accuracy") == "correct" for item in directional) / len(directional))
        if directional
        else None,
    }


def _validate_outcome(payload: dict[str, Any], evaluation_id: str) -> None:
    if payload.get("evaluation_id") != evaluation_id:
        raise EvaluationHistoryArtifactError("evaluation outcome context mismatch")
    if payload.get("horizon") not in _HORIZON_ORDER:
        raise EvaluationHistoryArtifactError("evaluation outcome horizon is invalid")
    if payload.get("status") not in _OUTCOME_STATUSES:
        raise EvaluationHistoryArtifactError("evaluation outcome status is invalid")


def _outcome_summary(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        classification = payload.get("classification")
        if classification not in _OUTCOME_CLASSIFICATIONS:
            raise ValueError
        lifecycle = _optional_enum(payload, "lifecycle_status", _OUTCOME_LIFECYCLES)
        return {
            "horizon": str(payload["horizon"]),
            "status": str(payload["status"]),
            "classification": str(classification),
            "verification_status": "legacy_unverified" if _is_legacy_unverified(payload) else "verified",
            "lifecycle_status": lifecycle,
            "setup_id": _optional_text(payload, "setup_id"),
            "fill_price": _optional_number(payload, "fill_price"),
            "fill_time": _optional_text(payload, "fill_time"),
            "target_price": _optional_number(payload, "target_price"),
            "target_time": _optional_text(payload, "target_time"),
            "exit_price": _optional_number(payload, "exit_price"),
            "exit_time": _optional_text(payload, "exit_time"),
            "return_abs": _optional_number(payload, "return_abs"),
            "return_pct": _optional_number(payload, "return_pct"),
            "mfe": _optional_number(payload, "mfe"),
            "mae": _optional_number(payload, "mae"),
            "reason_codes": _optional_text_list(payload, "reason_codes"),
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise EvaluationHistoryArtifactError("evaluation outcome summary is invalid") from exc


def _is_legacy_unverified(payload: dict[str, Any]) -> bool:
    return payload.get("status") == "scored" and payload.get("lifecycle_status") not in _OUTCOME_LIFECYCLES


def _optional_enum(payload: dict[str, Any], key: str, allowed: set[str]) -> str | None:
    value = _optional_text(payload, key)
    if value is not None and value not in allowed:
        raise ValueError
    return value


def _optional_text(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError
    return value


def _optional_number(payload: dict[str, Any], key: str) -> float | None:
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, Real) or not isfinite(value):
        raise ValueError
    return float(value)


def _optional_text_list(payload: dict[str, Any], key: str) -> list[str]:
    value = payload.get(key)
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError
    return list(value)


def _validate_context(payload: dict[str, Any], account: str, asset: str, trade_date: str, evaluation_id: str) -> None:
    for key, expected in {
        "account_id": account,
        "asset": asset,
        "trade_date": trade_date,
        "evaluation_id": evaluation_id,
    }.items():
        if payload.get(key) != expected:
            raise EvaluationHistoryArtifactError("evaluation snapshot context mismatch")


def _read_object(path: Path) -> dict[str, Any]:
    try:
        if path.stat().st_size > _MAX_ARTIFACT_BYTES:
            raise EvaluationHistoryArtifactError("evaluation artifact exceeds size limit")
        payload = json.loads(path.read_text(encoding="utf-8"))
    except EvaluationHistoryArtifactError:
        raise
    except (OSError, json.JSONDecodeError) as exc:
        raise EvaluationHistoryArtifactError("evaluation artifact is invalid") from exc
    if not isinstance(payload, dict):
        raise EvaluationHistoryArtifactError("evaluation artifact must be an object")
    return payload


def _resolve_root(storage_root: Path | None) -> Path:
    root = Path(storage_root) if storage_root is not None else _PROJECT_ROOT / "storage" / "evaluation"
    if root.is_symlink():
        raise EvaluationHistoryArtifactError("evaluation root path is unsafe")
    return root.expanduser().resolve()


def _safe_directory(path: Path, root: Path) -> Path | None:
    if path.is_symlink():
        raise EvaluationHistoryArtifactError("evaluation history path is unsafe")
    if not path.exists():
        return None
    if not path.is_dir():
        raise EvaluationHistoryArtifactError("evaluation history path is unsafe")
    resolved = path.resolve()
    _assert_inside(resolved, root)
    return resolved


def _assert_inside(path: Path, parent: Path) -> None:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError as exc:
        raise EvaluationHistoryArtifactError("evaluation history path is unsafe") from exc


def _safe_component(value: Any, field: str, *, artifact: bool = False) -> str:
    if not isinstance(value, str) or not _COMPONENT_RE.fullmatch(value):
        error = "evaluation artifact path is invalid" if artifact else f"invalid {field}"
        if artifact:
            raise EvaluationHistoryArtifactError(error)
        raise EvaluationHistoryQueryError(error)
    return value


def _safe_trade_date(value: str, *, artifact: bool = False) -> str:
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        if artifact:
            raise EvaluationHistoryArtifactError("evaluation trade date is invalid") from exc
        raise EvaluationHistoryQueryError("trade_date must be YYYY-MM-DD") from exc
    if parsed.isoformat() != value:
        if artifact:
            raise EvaluationHistoryArtifactError("evaluation trade date is invalid")
        raise EvaluationHistoryQueryError("trade_date must be YYYY-MM-DD")
    return value


def _safe_limit(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= _MAX_LIMIT:
        raise EvaluationHistoryQueryError(f"limit must be an integer between 1 and {_MAX_LIMIT}")
    return value


def _artifact_ref(root: Path, path: Path) -> str:
    relative = path.resolve().relative_to(root.resolve())
    return Path("evaluation", *relative.parts).as_posix()


def _empty_payload(account: str, asset: str, limit: int) -> dict[str, Any]:
    return {
        "schema_version": "shadow_evaluation_history.v1",
        "account_id": account,
        "asset": asset,
        "items": [],
        "total": 0,
        "truncated": False,
    }


__all__ = [
    "EvaluationHistoryArtifactError",
    "EvaluationHistoryQueryError",
    "get_shadow_evaluation_history",
    "list_shadow_evaluation_history",
]
