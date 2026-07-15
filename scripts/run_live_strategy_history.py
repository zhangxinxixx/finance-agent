"""Freeze the current XAUUSD live-strategy read model into local history.

The command is intentionally a dry run by default.  Use ``--write`` only
after inspecting the immutable artifact reference printed in the summary.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_STORAGE_ROOT = _PROJECT_ROOT / "storage"
_COMPONENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
LIVE_STRATEGY_SCHEMA_VERSION = "live_strategy.v1"
LIVE_STRATEGY_ASSET = "XAUUSD"

if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from apps.analysis.strategy.history_store import (  # noqa: E402
    HistoryWriteResult,
    StrategyHistoryConflictError,
    StrategyHistoryStore,
)
from apps.api.services.live_strategy_service import get_live_strategy_latest  # noqa: E402
from database.models.engine import SessionLocal  # noqa: E402


def freeze_live_strategy(
    *,
    asset: str = "XAUUSD",
    as_of: datetime | None = None,
    storage_root: Path | str = _DEFAULT_STORAGE_ROOT,
    write: bool = False,
    session_factory: Callable[[], Any] | None = None,
    live_strategy_loader: Callable[..., Mapping[str, Any]] | None = None,
    store_factory: Callable[[Path], StrategyHistoryStore] | None = None,
) -> dict[str, Any]:
    """Load and optionally persist one immutable live-strategy version."""

    normalized_asset = _validate_asset(asset)
    safe_root = _validate_storage_root(storage_root)
    session = (session_factory or SessionLocal)()
    try:
        effective_as_of = as_of or datetime.now(timezone.utc)
        live = (live_strategy_loader or get_live_strategy_latest)(
            asset=normalized_asset, db=session, now=effective_as_of
        )
    finally:
        close = getattr(session, "close", None)
        if callable(close):
            close()

    reasons = _history_gate(live)
    if reasons:
        return {
            "status": "skipped",
            "asset": normalized_asset,
            "as_of": effective_as_of.isoformat(),
            "strategy_id": live.get("strategy_id") if isinstance(live, Mapping) else None,
            "strategy_version": live.get("strategy_version") if isinstance(live, Mapping) else None,
            "reasons": reasons,
            "dry_run": not write,
            "write_requested": write,
        }
    target_ref = _target_artifact_ref(live, normalized_asset)
    # Validate JSON before either printing or writing so dry-run catches the
    # same malformed output that the append-only store would reject.
    try:
        json.dumps(dict(live), ensure_ascii=False, sort_keys=True, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("live strategy payload must be JSON serializable") from exc

    result: HistoryWriteResult | None = None
    if write:
        result = (store_factory or StrategyHistoryStore)(safe_root).write(live)
    return {
        "status": "written" if write and result and result.created else ("unchanged" if write else "dry-run"),
        "dry_run": not write,
        "write_requested": write,
        "schema_version": live.get("schema_version"),
        "asset": normalized_asset,
        "strategy_id": live.get("strategy_id"),
        "strategy_version": live.get("strategy_version"),
        "updated_at": live.get("updated_at"),
        "target_ref": result.artifact_ref if result else target_ref,
        "created": result.created if result else None,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset", default="XAUUSD", help="Asset (only XAUUSD is supported)")
    parser.add_argument(
        "--storage-root",
        default=str(_DEFAULT_STORAGE_ROOT),
        help="Project storage root or a safe subdirectory (default: storage)",
    )
    parser.add_argument("--as-of", default=None, help="Optional UTC ISO-8601 timestamp passed to the service")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="Persist the artifact")
    mode.add_argument("--dry-run", action="store_true", help="Print the target without writing (default)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        summary = freeze_live_strategy(
            asset=args.asset,
            as_of=_parse_as_of(args.as_of),
            storage_root=_validate_storage_root(Path(args.storage_root)),
            write=args.write,
        )
    except (StrategyHistoryConflictError, OSError, RuntimeError, TypeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


def _validate_asset(value: str) -> str:
    if not isinstance(value, str) or value.upper() != "XAUUSD":
        raise ValueError("--asset supports only XAUUSD")
    return "XAUUSD"


def _parse_as_of(value: str | None) -> datetime | None:
    if value is None or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("--as-of must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("--as-of must include a timezone")
    return parsed.astimezone(timezone.utc)


def _validate_storage_root(value: Path | str) -> Path:
    """Allow only ``storage`` itself or a non-symlink child directory."""

    allowed = _DEFAULT_STORAGE_ROOT.absolute()
    if allowed.is_symlink():
        raise ValueError("project storage root must not be a symlink")
    raw = Path(value).expanduser()
    candidate = Path(raw if raw.is_absolute() else _PROJECT_ROOT / raw)
    candidate = Path(os.path.abspath(candidate))
    try:
        relative_parts = candidate.relative_to(allowed).parts
    except ValueError as exc:
        raise ValueError(f"--storage-root must be inside {allowed}") from exc
    current = allowed
    for part in relative_parts:
        current /= part
        if current.is_symlink():
            raise ValueError("--storage-root must not contain symlink components")
    if candidate.exists() and not candidate.is_dir():
        raise ValueError("--storage-root must be a directory")
    return candidate


def _target_artifact_ref(strategy: Mapping[str, Any], asset: str) -> str:
    required = ("asset", "strategy_id", "strategy_version", "updated_at")
    missing = [field for field in required if not strategy.get(field)]
    if missing:
        raise ValueError(f"live strategy is missing required fields: {', '.join(missing)}")
    payload_asset = strategy.get("asset", asset)
    if not isinstance(payload_asset, str) or payload_asset.upper() != asset:
        raise ValueError("live strategy asset does not match --asset")
    for field in ("strategy_id", "strategy_version"):
        value = strategy[field]
        if not isinstance(value, str) or not _COMPONENT_RE.fullmatch(value):
            raise ValueError(f"live strategy has invalid {field}")
    updated_at = strategy["updated_at"]
    if not isinstance(updated_at, str):
        raise ValueError("live strategy updated_at must be ISO-8601")
    try:
        parsed = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("live strategy updated_at must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("live strategy updated_at must include a timezone")
    trade_date = parsed.astimezone(timezone.utc).date().isoformat()
    return (
        f"strategy_history/{asset}/{trade_date}/{strategy['strategy_id']}/"
        f"{strategy['strategy_version']}.json"
    )


def _history_gate(strategy: Any) -> list[str]:
    """Return deterministic reasons when a live result cannot be frozen."""

    if not isinstance(strategy, Mapping):
        return ["strategy_payload_unavailable"]
    reasons: list[str] = []
    if strategy.get("schema_version") != LIVE_STRATEGY_SCHEMA_VERSION:
        reasons.append("schema_version_required")
    if strategy.get("asset") != LIVE_STRATEGY_ASSET:
        reasons.append("asset_identity_required")
    for field in ("strategy_id", "strategy_version", "updated_at"):
        if not isinstance(strategy.get(field), str) or not strategy[field].strip():
            reasons.append(f"{field}_required")
    if strategy.get("strategy_status") == "SUSPENDED_DATA":
        reasons.append("strategy_suspended_data")

    market = strategy.get("live_market")
    if not isinstance(market, Mapping) or market.get("status") != "available":
        reasons.append("canonical_market_unavailable")

    quality = strategy.get("data_quality")
    canonical = quality.get("canonical_candle") if isinstance(quality, Mapping) else None
    if not isinstance(quality, Mapping) or canonical is None:
        reasons.append("data_quality_unavailable")
    elif not isinstance(canonical, Mapping) or canonical.get("status") != "available":
        reasons.append("canonical_data_unavailable")
    return list(dict.fromkeys(reasons))


if __name__ == "__main__":
    raise SystemExit(main())
