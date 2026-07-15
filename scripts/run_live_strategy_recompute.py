"""Preview or freeze one accepted XAUUSD event recompute.

The command is read-only by default.  ``--write`` persists only the accepted
candidate strategy through the existing append-only ``StrategyHistoryStore``;
the recompute execution remains an embedded, deterministic reference.
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
_EVENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_COMPONENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_REASON_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")

if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from apps.analysis.strategy.history_store import (  # noqa: E402
    HistoryWriteResult,
    StrategyHistoryConflictError,
    StrategyHistoryStore,
)
from apps.api.services.live_strategy_recompute_service import (  # noqa: E402
    preview_live_strategy_recompute,
)
from database.models.engine import SessionLocal  # noqa: E402


class RecomputeCliValidationError(ValueError):
    """Raised for fixed, user-safe CLI validation failures."""


class RecomputePreviewError(RuntimeError):
    """Raised when the read-only preview service fails unexpectedly."""


class RecomputePreviewContractError(RuntimeError):
    """Raised when an accepted preview does not satisfy the freeze contract."""


def freeze_live_strategy_recompute(
    *,
    event_id: str,
    as_of: datetime | None = None,
    storage_root: Path | str = _DEFAULT_STORAGE_ROOT,
    write: bool = False,
    session_factory: Callable[[], Any] | None = None,
    preview_loader: Callable[..., Mapping[str, Any]] | None = None,
    store_factory: Callable[[Path], StrategyHistoryStore] | None = None,
) -> dict[str, Any]:
    """Preview and optionally freeze one accepted candidate strategy."""

    normalized_event_id = _validate_event_id(event_id)
    safe_root = _validate_storage_root(storage_root)
    normalized_as_of = _normalize_as_of(as_of)

    session = (session_factory or SessionLocal)()
    try:
        try:
            preview = (preview_loader or preview_live_strategy_recompute)(
                event_id=normalized_event_id,
                db=session,
                now=normalized_as_of,
                storage_root=safe_root,
            )
        except Exception as exc:
            raise RecomputePreviewError("recompute_preview_failed") from exc
    finally:
        close = getattr(session, "close", None)
        if callable(close):
            close()

    if not isinstance(preview, Mapping):
        raise RecomputePreviewContractError("invalid_preview_contract")
    preview_status = preview.get("status")
    if preview_status in {"blocked", "unavailable"}:
        return {
            "status": "skipped",
            "source_status": preview_status,
            "event_id": normalized_event_id,
            "reasons": _safe_reasons(preview.get("reasons"), preview_status),
            "dry_run": not write,
            "write_requested": write,
            "write_performed": False,
        }
    if preview_status != "accepted":
        raise RecomputePreviewContractError("invalid_preview_contract")

    candidate, execution_id, recompute_id = _accepted_payload(preview)
    target_ref = _target_artifact_ref(candidate)
    try:
        json.dumps(candidate, ensure_ascii=False, sort_keys=True, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise RecomputePreviewContractError("invalid_candidate_strategy") from exc

    result: HistoryWriteResult | None = None
    if write:
        result = (store_factory or StrategyHistoryStore)(safe_root).write(candidate)

    return {
        "status": "written" if result and result.created else ("unchanged" if result else "dry-run"),
        "event_id": normalized_event_id,
        "as_of": normalized_as_of.isoformat() if normalized_as_of is not None else None,
        "dry_run": not write,
        "write_requested": write,
        "write_performed": result is not None,
        "strategy_id": candidate["strategy_id"],
        "strategy_version": candidate["strategy_version"],
        "execution_id": execution_id,
        "recompute_id": recompute_id,
        "target_ref": result.artifact_ref if result else target_ref,
        "artifact_ref": result.artifact_ref if result else None,
        "created": result.created if result else None,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-id", required=True, help="Material event identifier")
    parser.add_argument(
        "--as-of",
        default=None,
        help="Optional timezone-aware ISO-8601 timestamp passed to the preview service",
    )
    parser.add_argument(
        "--storage-root",
        default="./storage",
        help="Project storage root or a safe child directory (default: ./storage)",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="Persist the accepted candidate strategy")
    mode.add_argument("--dry-run", action="store_true", help="Print the target without writing (default)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        summary = freeze_live_strategy_recompute(
            event_id=args.event_id,
            as_of=_parse_as_of(args.as_of),
            storage_root=args.storage_root,
            write=args.write,
        )
    except RecomputeCliValidationError as exc:
        _print_error(str(exc))
        return 2
    except StrategyHistoryConflictError:
        _print_error("strategy_history_conflict")
        return 1
    except RecomputePreviewError:
        _print_error("recompute_preview_failed")
        return 1
    except RecomputePreviewContractError as exc:
        _print_error(str(exc))
        return 1
    except (OSError, TypeError, ValueError):
        _print_error("strategy_history_write_failed")
        return 1
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


def _validate_event_id(value: Any) -> str:
    if not isinstance(value, str) or not _EVENT_ID_RE.fullmatch(value):
        raise RecomputeCliValidationError("invalid_event_id")
    return value


def _parse_as_of(value: str | None) -> datetime | None:
    if value is None or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise RecomputeCliValidationError("invalid_as_of") from exc
    return _normalize_as_of(parsed)


def _normalize_as_of(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise RecomputeCliValidationError("invalid_as_of")
    return value.astimezone(timezone.utc)


def _validate_storage_root(value: Path | str) -> Path:
    allowed = _DEFAULT_STORAGE_ROOT.absolute()
    if allowed.is_symlink():
        raise RecomputeCliValidationError("invalid_storage_root")
    raw = Path(value).expanduser()
    candidate = Path(raw if raw.is_absolute() else _PROJECT_ROOT / raw)
    candidate = Path(os.path.abspath(candidate))
    try:
        relative_parts = candidate.relative_to(allowed).parts
    except ValueError as exc:
        raise RecomputeCliValidationError("invalid_storage_root") from exc
    current = allowed
    for part in relative_parts:
        current /= part
        if current.is_symlink():
            raise RecomputeCliValidationError("invalid_storage_root")
    if candidate.exists() and not candidate.is_dir():
        raise RecomputeCliValidationError("invalid_storage_root")
    return candidate


def _accepted_payload(preview: Mapping[str, Any]) -> tuple[dict[str, Any], str, str]:
    candidate_value = preview.get("candidate_strategy")
    execution = preview.get("execution")
    if not isinstance(candidate_value, Mapping) or not isinstance(execution, Mapping):
        raise RecomputePreviewContractError("invalid_accepted_preview")
    execution_id = execution.get("execution_id")
    recompute = execution.get("recompute")
    recompute_id = recompute.get("recompute_id") if isinstance(recompute, Mapping) else None
    if (
        execution.get("status") != "accepted"
        or not isinstance(execution_id, str)
        or not execution_id
        or not isinstance(recompute_id, str)
        or not recompute_id
    ):
        raise RecomputePreviewContractError("invalid_accepted_preview")
    return dict(candidate_value), execution_id, recompute_id


def _target_artifact_ref(candidate: Mapping[str, Any]) -> str:
    if (
        candidate.get("schema_version") != "live_strategy.v1"
        or candidate.get("status") not in {"available", "partial"}
        or candidate.get("asset") != "XAUUSD"
        or candidate.get("strategy_status") == "SUSPENDED_DATA"
    ):
        raise RecomputePreviewContractError("invalid_candidate_strategy")
    live_market = candidate.get("live_market")
    data_quality = candidate.get("data_quality")
    canonical = data_quality.get("canonical_candle") if isinstance(data_quality, Mapping) else None
    if (
        not isinstance(live_market, Mapping)
        or live_market.get("status") != "available"
        or not isinstance(canonical, Mapping)
        or canonical.get("status") != "available"
    ):
        raise RecomputePreviewContractError("invalid_candidate_strategy")
    for field in ("strategy_id", "strategy_version"):
        value = candidate.get(field)
        if not isinstance(value, str) or not _COMPONENT_RE.fullmatch(value):
            raise RecomputePreviewContractError("invalid_candidate_strategy")
    updated_at = candidate.get("updated_at")
    if not isinstance(updated_at, str):
        raise RecomputePreviewContractError("invalid_candidate_strategy")
    try:
        parsed = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RecomputePreviewContractError("invalid_candidate_strategy") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RecomputePreviewContractError("invalid_candidate_strategy")
    trade_date = parsed.astimezone(timezone.utc).date().isoformat()
    return f"strategy_history/XAUUSD/{trade_date}/{candidate['strategy_id']}/{candidate['strategy_version']}.json"


def _safe_reasons(value: Any, fallback: str) -> list[str]:
    if not isinstance(value, list):
        return [f"preview_{fallback}"]
    reasons = [item for item in value if isinstance(item, str) and _REASON_RE.fullmatch(item)]
    return list(dict.fromkeys(reasons)) or [f"preview_{fallback}"]


def _print_error(code: str) -> None:
    print(json.dumps({"status": "error", "error": code}, sort_keys=True), file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
