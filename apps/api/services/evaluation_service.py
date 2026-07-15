"""Read-only service for Issue #59 shadow evaluation metrics."""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any

from apps.analysis.evaluation.metrics import aggregate_outcome_metrics
from apps.api.services._storage import _PROJECT_ROOT

_COMPONENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_DEFAULT_ACCOUNT_ID = "codex-xauusd-shadow"
_DEFAULT_ASSET = "XAUUSD"
_MAX_ARTIFACT_BYTES = 2 * 1024 * 1024
_MAX_ARTIFACT_FILES = 1000


class EvaluationQueryError(ValueError):
    """The caller supplied an invalid account, asset, or date."""


class EvaluationArtifactError(RuntimeError):
    """A local evaluation artifact is unsafe, unreadable, or invalid."""


def get_shadow_evaluation_metrics(
    *,
    account_id: str = _DEFAULT_ACCOUNT_ID,
    asset: str = _DEFAULT_ASSET,
    trade_date: str,
    storage_root: Path | None = None,
) -> dict[str, Any] | None:
    """Load one local evaluation partition and aggregate its outcomes."""
    account_id = _safe_component(account_id, "account_id")
    if not isinstance(asset, str):
        raise ValueError("invalid asset")
    asset = _safe_component(asset.upper(), "asset")
    if asset != _DEFAULT_ASSET:
        raise ValueError("shadow evaluation currently supports only XAUUSD")
    trade_date = _safe_trade_date(trade_date)
    root = (storage_root or (_PROJECT_ROOT / "storage" / "evaluation")).resolve()
    partition = _safe_partition(root, account_id, asset, trade_date)
    if not partition.is_dir():
        return None

    snapshot_files = _safe_artifact_files(partition, "*/strategy_snapshot.json")
    outcome_files = _safe_artifact_files(partition, "*/outcomes/*.json")
    if not snapshot_files and not outcome_files:
        return None

    try:
        snapshots = [_read_object(path) for path in snapshot_files]
        outcomes = [_read_object(path) for path in outcome_files]
        metrics = aggregate_outcome_metrics(outcomes)
    except (OSError, ValueError, TypeError, EvaluationArtifactError) as exc:
        raise EvaluationArtifactError("evaluation artifact validation failed") from exc
    return {
        "schema_version": "shadow_evaluation_metrics_api.v1",
        "account_id": account_id,
        "asset": asset,
        "trade_date": trade_date,
        "metrics": metrics,
        "snapshot_count": len(snapshots),
        "outcome_count": len(outcomes),
        "evaluation_ids": sorted(
            {
                str(item["evaluation_id"])
                for item in snapshots + outcomes
                if isinstance(item.get("evaluation_id"), str)
            }
        ),
        "artifact_refs": [_artifact_ref(path) for path in snapshot_files + outcome_files],
    }


def get_latest_shadow_evaluation_metrics(
    *,
    account_id: str = _DEFAULT_ACCOUNT_ID,
    asset: str = _DEFAULT_ASSET,
    storage_root: Path | None = None,
) -> dict[str, Any] | None:
    """Load the latest valid local evaluation partition for one account/asset."""
    account_id = _safe_component(account_id, "account_id")
    if not isinstance(asset, str):
        raise ValueError("invalid asset")
    asset = _safe_component(asset.upper(), "asset")
    if asset != _DEFAULT_ASSET:
        raise ValueError("shadow evaluation currently supports only XAUUSD")

    root = (storage_root or (_PROJECT_ROOT / "storage" / "evaluation")).resolve()
    asset_root = _safe_partition_root(root, account_id, asset)
    if not asset_root.is_dir():
        return None

    trade_dates: list[str] = []
    for candidate in asset_root.iterdir():
        if candidate.is_symlink():
            raise EvaluationArtifactError("evaluation partition path is unsafe")
        if not candidate.is_dir():
            continue
        if not candidate.resolve().is_relative_to(asset_root.resolve()):
            raise EvaluationArtifactError("evaluation partition path is unsafe")
        try:
            trade_dates.append(_safe_trade_date(candidate.name))
        except ValueError:
            continue

    for trade_date in sorted(trade_dates, reverse=True):
        payload = get_shadow_evaluation_metrics(
            account_id=account_id,
            asset=asset,
            trade_date=trade_date,
            storage_root=root,
        )
        if payload is not None:
            return payload
    return None


def _safe_component(value: str, field: str) -> str:
    if not isinstance(value, str) or not _COMPONENT_RE.fullmatch(value):
        raise EvaluationQueryError(f"invalid {field}")
    return value


def _safe_partition_root(root: Path, account_id: str, asset: str) -> Path:
    raw_root = root / account_id / asset
    if raw_root.is_symlink():
        raise EvaluationArtifactError("evaluation partition path is unsafe")
    resolved = raw_root.resolve()
    if not resolved.is_relative_to(root):
        raise EvaluationArtifactError("evaluation partition path is unsafe")
    return resolved


def _safe_partition(root: Path, account_id: str, asset: str, trade_date: str) -> Path:
    asset_root = _safe_partition_root(root, account_id, asset)
    raw_partition = root / account_id / asset / trade_date
    if raw_partition.is_symlink():
        raise EvaluationArtifactError("evaluation partition path is unsafe")
    resolved = raw_partition.resolve()
    if not resolved.is_relative_to(asset_root):
        raise EvaluationArtifactError("evaluation partition path is unsafe")
    return resolved


def _safe_trade_date(value: str) -> str:
    if not isinstance(value, str):
        raise EvaluationQueryError("invalid trade_date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise EvaluationQueryError("trade_date must be YYYY-MM-DD") from exc
    if parsed.isoformat() != value:
        raise EvaluationQueryError("trade_date must be YYYY-MM-DD")
    return value


def _read_object(path: Path) -> dict[str, Any]:
    try:
        if path.stat().st_size > _MAX_ARTIFACT_BYTES:
            raise EvaluationArtifactError("evaluation artifact exceeds size limit")
    except OSError as exc:
        raise EvaluationArtifactError("evaluation artifact is unreadable") from exc
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvaluationArtifactError("evaluation artifact is invalid") from exc
    if not isinstance(payload, dict):
        raise EvaluationArtifactError("evaluation artifact must be an object")
    return payload


def _safe_artifact_files(partition: Path, pattern: str) -> list[Path]:
    files: list[Path] = []
    partition = partition.resolve()
    for path in sorted(partition.glob(pattern)):
        resolved = path.resolve()
        if path.is_symlink() or not resolved.is_relative_to(partition):
            raise EvaluationArtifactError("evaluation artifact path is unsafe")
        if not path.is_file():
            continue
        files.append(path)
        if len(files) > _MAX_ARTIFACT_FILES:
            raise EvaluationArtifactError("evaluation artifact count exceeds limit")
    return files


def _artifact_ref(path: Path) -> str:
    try:
        return str(path.relative_to(_PROJECT_ROOT))
    except ValueError:
        return str(path)


__all__ = ["get_latest_shadow_evaluation_metrics", "get_shadow_evaluation_metrics"]
