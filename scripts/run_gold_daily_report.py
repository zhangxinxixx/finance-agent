#!/usr/bin/env python3
"""Run the authoritative Gold Policy daily report without Jin10 or Legacy agents."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session as DBSession

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.analysis.gold_policy.daily_close_runtime import execute_gold_daily_close_runtime
from apps.analysis.gold_policy.canonical_predecessor import resolve_canonical_predecessor
from apps.analysis.gold_policy.daily_close_store import verify_gold_daily_close_bundle
from apps.analysis.gold_policy.runtime_controls import build_gold_daily_close_runtime_controls
from apps.analysis.gold_policy.runtime_inputs import (
    prepare_gold_policy_formal_options_inputs,
    prepare_gold_policy_runtime_inputs,
)
from apps.worker.report_registry_sink import register_gold_policy_report_bundle
from database.models.engine import SessionLocal


_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_REPORT_FILES = (
    "source.md",
    "analysis.md",
    "visual.html",
    "report_structured.json",
    "evidence.json",
    "data_quality.json",
    "report_manifest.json",
    "strategy_card.json",
    "strategy_card.md",
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build one authoritative XAUUSD Gold Policy daily report package.")
    parser.add_argument("--date", required=True, help="UTC trade date, YYYY-MM-DD.")
    parser.add_argument("--storage-root", default="storage", help="Formal snapshot and output root.")
    parser.add_argument(
        "--snapshot-path", default=None, help="Optional exact premarket_snapshot.json path under storage root."
    )
    parser.add_argument("--run-id", default=None, help="Optional immutable report run id.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate inputs and print the planned immutable bundle path without writing.",
    )
    return parser


def run_gold_daily_report(
    *,
    trade_date: str,
    storage_root: Path,
    snapshot_path: Path | None = None,
    run_id: str | None = None,
    dry_run: bool = False,
    db: DBSession | None = None,
) -> dict[str, Any]:
    """Execute the typed close and optionally stage its verified bundle in the registry."""

    try:
        requested_date = date.fromisoformat(trade_date)
    except ValueError:
        return {"status": "blocked", "reason": "trade_date_invalid", "trade_date": trade_date}
    root = storage_root.expanduser().resolve()
    snapshot, resolved_snapshot, snapshot_error = _load_formal_snapshot(
        root=root,
        trade_date=requested_date,
        requested_path=snapshot_path,
    )
    if snapshot_error is not None:
        return {
            "status": "blocked",
            "reason": snapshot_error,
            "trade_date": trade_date,
            "jin10": "not_used",
        }

    try:
        runtime = prepare_gold_policy_runtime_inputs(storage_root=root, snapshot=snapshot)
        current = runtime.current
        if current.as_of.astimezone(UTC).date() != requested_date:
            raise ValueError("formal_feature_date_mismatch")
        resolved_run_id = run_id or _default_run_id(
            trade_date=trade_date,
            feature_id=current.snapshot_id,
        )
        if not _RUN_ID.fullmatch(resolved_run_id):
            raise ValueError("run_id_invalid")
        decision_time = _decision_as_of(snapshot, current)
        formal_options = prepare_gold_policy_formal_options_inputs(
            storage_root=root,
            current=current,
            decision_as_of=decision_time,
        )
        bundle_path = root / "analysis" / "gold_mainlines" / trade_date / resolved_run_id / "daily_close"
        existing = _existing_completed_result(
            storage_root=root,
            bundle_path=bundle_path,
            trade_date=trade_date,
            run_id=resolved_run_id,
            snapshot_path=resolved_snapshot,
        )
        if existing is not None and not dry_run:
            return _stage_report_registry(
                existing,
                db=db,
                storage_root=root,
                bundle_path=bundle_path,
            )
        predecessor = resolve_canonical_predecessor(
            storage_root=root,
            session_date=requested_date,
            target_bundle_path=bundle_path,
        )
        if predecessor.status in {"invalid", "ambiguous"}:
            raise ValueError(f"canonical_predecessor_{predecessor.reason_code}")
        head = predecessor.head if predecessor.status == "found" else None
        previous = head.feature_snapshot if head is not None else runtime.previous
        controls = build_gold_daily_close_runtime_controls(
            current_feature=current,
            previous_feature=previous,
            previous_transition=head.transition_decision if head is not None else None,
            decision_as_of=decision_time,
            options_regime_snapshot=formal_options.snapshot,
        )
    except Exception as exc:
        return {
            "status": "blocked",
            "reason": "gold_policy_runtime_prepare_failed",
            "detail": f"{type(exc).__name__}: {exc}",
            "trade_date": trade_date,
            "snapshot_path": str(resolved_snapshot),
            "jin10": "not_used",
        }

    if dry_run:
        return {
            "status": "dry_run",
            "trade_date": trade_date,
            "run_id": resolved_run_id,
            "snapshot_path": str(resolved_snapshot),
            "feature_snapshot_id": current.snapshot_id,
            "predecessor_status": predecessor.status,
            "planned_bundle_path": str(bundle_path),
            "planned_report_files": list(_REPORT_FILES),
            "control_reason_codes": list(controls.reason_codes),
            "formal_options": formal_options.summary(),
            "jin10": "not_used",
        }

    try:
        execution = execute_gold_daily_close_runtime(
            storage_root=root,
            run_id=resolved_run_id,
            current_feature=current,
            controls=controls,
            bootstrap_previous_feature=runtime.previous if head is None else None,
        )
        report_paths = _complete_report_paths(execution.write_result.bundle_path)
        if report_paths is None:
            raise RuntimeError("gold_report_package_incomplete")
        data_quality = _read_json(execution.write_result.bundle_path / "data_quality.json")
        report_manifest = _read_json(execution.write_result.bundle_path / "report_manifest.json")
        completed = {
            "status": "completed",
            "trade_date": trade_date,
            "run_id": resolved_run_id,
            "snapshot_path": str(resolved_snapshot),
            "daily_close_result_id": execution.result.result_id,
            "canonical_action": execution.result.canonical_action.value,
            "report_status": data_quality.get("report_status"),
            "report_paths": report_paths,
            "strategy_card_paths": [
                str(execution.write_result.bundle_path / "strategy_card.json"),
                str(execution.write_result.bundle_path / "strategy_card.md"),
            ],
            "report_manifest": report_manifest,
            "jin10": "not_used",
        }
        return _stage_report_registry(
            completed,
            db=db,
            storage_root=root,
            bundle_path=execution.write_result.bundle_path,
        )
    except Exception as exc:
        return {
            "status": "blocked",
            "reason": "gold_daily_report_execution_failed",
            "detail": f"{type(exc).__name__}: {exc}",
            "trade_date": trade_date,
            "run_id": resolved_run_id,
            "jin10": "not_used",
        }


def _load_formal_snapshot(
    *,
    root: Path,
    trade_date: date,
    requested_path: Path | None,
) -> tuple[dict[str, Any], Path, str | None]:
    if requested_path is not None:
        candidate = requested_path.expanduser().resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            return {}, candidate, "snapshot_path_outside_storage_root"
        candidates = [candidate]
    else:
        base = root / "features" / "snapshots" / "XAUUSD" / trade_date.isoformat()
        canonical = base / "premarket" / "premarket_snapshot.json"
        candidates = [canonical] if canonical.is_file() else sorted(base.glob("*/premarket_snapshot.json"))
    existing = [path for path in candidates if path.is_file() and not path.is_symlink()]
    if not existing:
        return {}, root, "premarket_snapshot_missing"
    if len(existing) != 1:
        return {}, root, "premarket_snapshot_ambiguous"
    path = existing[0]
    payload = _read_json(path)
    if not payload:
        return {}, path, "premarket_snapshot_invalid"
    declared_date = payload.get("trade_date")
    if declared_date is not None and declared_date != trade_date.isoformat():
        return {}, path, "premarket_snapshot_date_mismatch"
    return payload, path, None


def _default_run_id(*, trade_date: str, feature_id: str) -> str:
    digest = hashlib.sha256(feature_id.encode("utf-8")).hexdigest()[:12]
    return f"gold-daily-report-{trade_date}-{digest}"


def _decision_as_of(snapshot: dict[str, Any], feature: Any) -> datetime:
    """Use only same-session persisted evidence times, never the wall clock."""

    candidates = [feature.as_of.astimezone(UTC)]
    raw_snapshot_time = snapshot.get("snapshot_time")
    if isinstance(raw_snapshot_time, str):
        try:
            snapshot_time = datetime.fromisoformat(raw_snapshot_time.replace("Z", "+00:00"))
            if snapshot_time.tzinfo is not None and snapshot_time.utcoffset() is not None:
                candidates.append(snapshot_time.astimezone(UTC))
        except ValueError:
            pass
    for value in _source_reference_times(feature.model_dump(mode="json")):
        candidates.append(value)
    session = feature.as_of.astimezone(UTC).date()
    eligible = [value for value in candidates if value.date() == session and value >= feature.as_of]
    if not eligible:
        raise ValueError("formal_feature_has_no_same_session_decision_time")
    return max(eligible)


def _source_reference_times(value: object) -> tuple[datetime, ...]:
    times: list[datetime] = []
    if isinstance(value, dict):
        retrieved_at = value.get("retrieved_at")
        if isinstance(retrieved_at, str):
            try:
                parsed = datetime.fromisoformat(retrieved_at.replace("Z", "+00:00"))
                if parsed.tzinfo is not None and parsed.utcoffset() is not None:
                    times.append(parsed.astimezone(UTC))
            except ValueError:
                pass
        for nested in value.values():
            times.extend(_source_reference_times(nested))
    elif isinstance(value, list):
        for nested in value:
            times.extend(_source_reference_times(nested))
    return tuple(times)


def _complete_report_paths(bundle_path: Path) -> list[str] | None:
    paths = [bundle_path / name for name in _REPORT_FILES]
    return [str(path) for path in paths] if all(path.is_file() for path in paths) else None


def _existing_completed_result(
    *,
    storage_root: Path,
    bundle_path: Path,
    trade_date: str,
    run_id: str,
    snapshot_path: Path,
) -> dict[str, Any] | None:
    verification = verify_gold_daily_close_bundle(
        storage_root=storage_root,
        bundle_path=bundle_path,
    )
    if verification.status != "valid" or verification.receipt is None:
        return None
    report_paths = _complete_report_paths(bundle_path)
    data_quality = _read_json(bundle_path / "data_quality.json")
    report_manifest = _read_json(bundle_path / "report_manifest.json")
    if not report_paths or not data_quality or not report_manifest:
        return None
    return {
        "status": "completed",
        "trade_date": trade_date,
        "run_id": run_id,
        "snapshot_path": str(snapshot_path),
        "daily_close_result_id": verification.receipt.result_id,
        "canonical_action": verification.receipt.action.value,
        "report_status": data_quality.get("report_status"),
        "report_paths": report_paths,
        "strategy_card_paths": [
            str(bundle_path / "strategy_card.json"),
            str(bundle_path / "strategy_card.md"),
        ],
        "report_manifest": report_manifest,
        "jin10": "not_used",
    }


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _stage_report_registry(
    completed: dict[str, Any],
    *,
    db: DBSession | None,
    storage_root: Path,
    bundle_path: Path,
) -> dict[str, Any]:
    if db is None:
        return completed
    try:
        report_id = register_gold_policy_report_bundle(
            db,
            storage_root=storage_root,
            bundle_path=bundle_path,
        )
    except Exception as exc:
        return {
            **completed,
            "status": "blocked",
            "reason": "gold_report_registry_failed",
            "registry_status": "failed",
            "detail": type(exc).__name__,
        }
    return {
        **completed,
        "report_id": report_id,
        "registry_status": "staged",
    }


def _registry_commit_failure(
    *,
    args: argparse.Namespace,
    detail: str,
    result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        **(result or {}),
        "status": "blocked",
        "reason": "gold_report_registry_commit_failed",
        "registry_status": "failed",
        "detail": detail,
        "trade_date": args.date,
        "jin10": "not_used",
    }


def main(
    argv: Sequence[str] | None = None,
    *,
    session_factory: Callable[[], Any] | None = None,
) -> int:
    args = _parser().parse_args(argv)
    call_kwargs = {
        "trade_date": args.date,
        "storage_root": Path(args.storage_root),
        "snapshot_path": Path(args.snapshot_path) if args.snapshot_path else None,
        "run_id": args.run_id,
        "dry_run": args.dry_run,
    }
    if args.dry_run:
        result = run_gold_daily_report(**call_kwargs)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if result["status"] == "dry_run" else 2

    session: Any | None = None
    try:
        session = (session_factory or SessionLocal)()
    except Exception as exc:
        result = _registry_commit_failure(
            args=args,
            detail=type(exc).__name__,
        )
    else:
        try:
            result = run_gold_daily_report(**call_kwargs, db=session)
            if result.get("status") == "completed" and result.get("registry_status") == "staged":
                try:
                    session.commit()
                except Exception as exc:
                    _rollback_quietly(session)
                    result = _registry_commit_failure(
                        args=args,
                        detail=type(exc).__name__,
                        result=result,
                    )
                else:
                    result["registry_status"] = "registered"
            else:
                _rollback_quietly(session)
        finally:
            close = getattr(session, "close", None)
            if callable(close):
                close()
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.get("status") == "completed" and result.get("registry_status") == "registered" else 2


def _rollback_quietly(session: Any) -> None:
    rollback = getattr(session, "rollback", None)
    if callable(rollback):
        try:
            rollback()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
