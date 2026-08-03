#!/usr/bin/env python3
"""Finalize the day's serial gold macro analysis before the 21:00 cutoff.

The close stage consumes the latest deterministic premarket snapshot, the
current Jin10 analysis context, and the previous-day final report lineage. It
then runs the canonical composite pipeline, which writes an observation or
accepted final report according to the existing quality gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.analysis.jin10.daily_context import build_daily_analysis_context
from apps.worker.composite_analysis_pipeline import run_composite_analysis_pipeline


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build the final serial gold macro report for a trade date.")
    parser.add_argument("--date", required=True, help="Trade date, YYYY-MM-DD.")
    parser.add_argument("--storage-root", default="storage")
    parser.add_argument("--asset", default="XAUUSD")
    parser.add_argument("--run-id", default=None, help="Optional immutable close run id.")
    return parser


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _latest_premarket_snapshot(
    storage_root: Path, *, trade_date: str, asset: str
) -> tuple[dict[str, Any], Path | None]:
    base = storage_root / "features" / "snapshots" / asset
    candidates: list[tuple[str, float, Path]] = []
    if not base.exists():
        return {}, None
    for date_dir in base.iterdir():
        if not date_dir.is_dir() or date_dir.name > trade_date:
            continue
        for path in date_dir.glob("*/premarket_snapshot.json"):
            try:
                candidates.append((date_dir.name, path.stat().st_mtime, path))
            except OSError:
                continue
    for _, _, path in sorted(candidates, reverse=True):
        payload = _read_json(path)
        if payload:
            return payload, path
    return {}, None


def _close_run_id(*, trade_date: str, snapshot: dict[str, Any], context: dict[str, Any]) -> str:
    material = json.dumps(
        {
            "trade_date": trade_date,
            "premarket_snapshot_id": snapshot.get("snapshot_id"),
            "context_input_snapshot_ids": context.get("input_snapshot_ids") or {},
            "context_freshness": context.get("freshness") or {},
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return f"daily-close-{trade_date}-{hashlib.sha256(material.encode()).hexdigest()[:12]}"


def _build_close_snapshot(
    *,
    snapshot: dict[str, Any],
    context: dict[str, Any],
    trade_date: str,
    run_id: str,
    asset: str,
    snapshot_time: datetime,
) -> dict[str, Any]:
    close_snapshot = dict(snapshot)
    close_snapshot["asset"] = asset
    close_snapshot["trade_date"] = trade_date
    close_snapshot["run_id"] = run_id
    close_snapshot["snapshot_id"] = f"{asset}:{trade_date}:{run_id}"
    close_snapshot["snapshot_time"] = snapshot_time.isoformat()
    close_snapshot["gold_analysis_context"] = {"status": "available", "data": context}
    input_ids = dict(close_snapshot.get("input_snapshot_ids") or {})
    input_ids["gold_analysis_context"] = dict(context.get("input_snapshot_ids") or {})
    close_snapshot["input_snapshot_ids"] = input_ids
    close_snapshot["source_refs"] = [
        *list(close_snapshot.get("source_refs") or []),
        *list(context.get("source_refs") or []),
    ]
    return close_snapshot


def _gold_policy_runtime_kwargs(
    *,
    storage_root: Path,
    snapshot: dict[str, Any],
    decision_as_of: datetime,
    run_id: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Prepare typed controls for the authoritative daily-close runtime."""

    try:
        from apps.analysis.gold_policy.canonical_predecessor import resolve_canonical_predecessor
        from apps.analysis.gold_policy.runtime_inputs import (
            prepare_gold_policy_formal_options_inputs,
            prepare_gold_policy_runtime_inputs,
        )
        from apps.analysis.gold_policy.runtime_controls import (
            build_gold_daily_close_runtime_controls,
        )

        runtime = prepare_gold_policy_runtime_inputs(storage_root=storage_root, snapshot=snapshot)
        session_date = runtime.current.as_of.astimezone(timezone.utc).date()
        target_run_id = run_id or "daily-macro-close-controls"
        target_bundle_path = (
            storage_root / "analysis" / "gold_mainlines" / session_date.isoformat() / target_run_id / "daily_close"
        )
        canonical = resolve_canonical_predecessor(
            storage_root=storage_root,
            session_date=session_date,
            target_bundle_path=target_bundle_path,
        )
        if canonical.status in {"invalid", "ambiguous"}:
            raise RuntimeError(f"canonical daily-close lookup failed: {canonical.reason_code}")
        head = canonical.head if canonical.status == "found" else None
        previous_feature = head.feature_snapshot if head is not None else runtime.previous
        formal_options = prepare_gold_policy_formal_options_inputs(
            storage_root=storage_root,
            current=runtime.current,
            decision_as_of=decision_as_of,
        )
        controls = build_gold_daily_close_runtime_controls(
            current_feature=runtime.current,
            previous_feature=previous_feature,
            previous_transition=(head.transition_decision if head is not None else None),
            decision_as_of=decision_as_of,
            options_regime_snapshot=formal_options.snapshot,
        )
        return (
            {
                "gold_feature_snapshot_prebuilt": runtime.current,
                "previous_gold_feature_snapshot_prebuilt": (runtime.previous if head is None else None),
                "gold_daily_close_controls_prebuilt": controls,
                "gold_policy_execution_mode": "authoritative",
            },
            {
                "status": "ready",
                "execution_mode": "authoritative",
                "lookup": runtime.lookup.summary(),
                "canonical_lookup": {
                    "status": canonical.status,
                    "reason_code": canonical.reason_code,
                },
                "formal_options": formal_options.summary(),
                "control_reason_codes": list(controls.reason_codes),
            },
        )
    except Exception as exc:
        return (
            {},
            {
                "status": "failed",
                "reason_code": "gold_policy_runtime_prepare_failed",
                "error": f"{type(exc).__name__}: {exc}",
                "lookup": {},
            },
        )


def _authoritative_output_paths(*, storage_root: Path, outputs: dict[str, Any]) -> tuple[list[str], list[str]]:
    execution = outputs.get("gold_daily_close_execution")
    if execution is None:
        return [], []
    bundle_path = Path(execution.write_result.bundle_path)
    report_names = (
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
    reports = [str(bundle_path / name) for name in report_names]
    if not all(Path(path).is_file() for path in reports):
        return [], []
    strategy_cards = [
        str(bundle_path / "strategy_card.json"),
        str(bundle_path / "strategy_card.md"),
    ]
    from apps.analysis.gold_policy.daily_close_store import load_gold_daily_close_head

    lookup = load_gold_daily_close_head(storage_root=storage_root)
    if lookup.status != "found" or lookup.head is None:
        return reports, strategy_cards
    strategy_path = lookup.head.selected_bundle_path / "strategy_decision.v2.json"
    if not strategy_path.is_file():
        strategy_path = lookup.head.selected_bundle_path / "strategy_decision.v1.json"
    return reports, strategy_cards + ([str(strategy_path)] if strategy_path.is_file() else [])


def run_daily_macro_close(
    *, trade_date: str, storage_root: Path, asset: str = "XAUUSD", run_id: str | None = None
) -> dict[str, Any]:
    context = build_daily_analysis_context(trade_date=trade_date, storage_root=storage_root, asset=asset)
    premarket, premarket_path = _latest_premarket_snapshot(storage_root, trade_date=trade_date, asset=asset)
    if not premarket:
        return {
            "status": "blocked",
            "trade_date": trade_date,
            "reason": "premarket_snapshot_missing",
            "gold_analysis_context": context.get("status"),
        }
    close_run_id = run_id or _close_run_id(trade_date=trade_date, snapshot=premarket, context=context)
    manifest_path = (
        storage_root / "outputs" / "daily_macro_close" / asset / trade_date / close_run_id / "close_manifest.json"
    )
    if manifest_path.exists():
        return {"status": "complete", "run_id": close_run_id, "manifest": str(manifest_path)}

    raw_snapshot_time = premarket.get("snapshot_time") or premarket.get("trade_date") or trade_date
    try:
        decision_as_of = datetime.fromisoformat(str(raw_snapshot_time).replace("Z", "+00:00"))
    except ValueError:
        return {
            "status": "blocked",
            "run_id": close_run_id,
            "reason": "premarket_snapshot_time_invalid",
        }
    if decision_as_of.tzinfo is None or decision_as_of.utcoffset() is None:
        decision_as_of = decision_as_of.replace(tzinfo=timezone.utc)
    decision_as_of = decision_as_of.astimezone(timezone.utc)
    snapshot = _build_close_snapshot(
        snapshot=premarket,
        context=context,
        trade_date=trade_date,
        run_id=close_run_id,
        asset=asset,
        snapshot_time=decision_as_of,
    )
    # Input passports must be derived from the original premarket artifact:
    # the close wrapper has a new snapshot_time, but it must not relabel a
    # reused observation as newly fresh.
    runtime_kwargs, gold_policy_runtime = _gold_policy_runtime_kwargs(
        storage_root=storage_root,
        snapshot=premarket,
        decision_as_of=decision_as_of,
        run_id=close_run_id,
    )
    if gold_policy_runtime["status"] != "ready":
        return {
            "status": "blocked",
            "run_id": close_run_id,
            "reason": gold_policy_runtime["reason_code"],
            "gold_policy_runtime": gold_policy_runtime,
        }
    summaries, outputs = run_composite_analysis_pipeline(
        storage_root=storage_root,
        snapshot=snapshot,
        run_id=close_run_id,
        created_at=decision_as_of,
        **runtime_kwargs,
    )
    canonical_report_paths, canonical_strategy_paths = _authoritative_output_paths(
        storage_root=storage_root, outputs=outputs
    )
    legacy_report_paths = list((outputs.get("report_result") or {}).get("paths") or [])
    legacy_strategy_card_paths = list((outputs.get("card_result") or {}).get("paths") or [])
    manifest = {
        "schema_version": "daily-macro-close-v1",
        "status": "completed",
        "trade_date": trade_date,
        "asset": asset,
        "run_id": close_run_id,
        "cutoff": "21:00 Asia/Shanghai",
        "premarket_snapshot": str(premarket_path) if premarket_path else None,
        "input_snapshot_ids": snapshot.get("input_snapshot_ids") or {},
        "gold_analysis_context": {
            "status": context.get("status"),
            "baseline_kind": context.get("baseline_kind"),
            "analysis_baseline": context.get("analysis_baseline") or {},
            "freshness": context.get("freshness") or {},
        },
        "gold_policy_runtime": gold_policy_runtime,
        "gold_policy_artifact_paths": dict(outputs.get("gold_policy_artifact_paths") or {}),
        "summaries": summaries,
        "final_report_paths": canonical_report_paths or legacy_report_paths,
        "strategy_card_paths": canonical_strategy_paths or legacy_strategy_card_paths,
        "legacy_final_report_paths": legacy_report_paths,
        "legacy_strategy_card_paths": legacy_strategy_card_paths,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return {
        "status": "completed",
        "run_id": close_run_id,
        "manifest": str(manifest_path),
        "final_report_paths": manifest["final_report_paths"],
        "strategy_card_paths": manifest["strategy_card_paths"],
        "gold_analysis_context": manifest["gold_analysis_context"],
        "gold_policy_runtime": manifest["gold_policy_runtime"],
        "gold_policy_artifact_paths": manifest["gold_policy_artifact_paths"],
    }


def main() -> int:
    args = _parser().parse_args()
    result = run_daily_macro_close(
        trade_date=args.date,
        storage_root=Path(args.storage_root).expanduser(),
        asset=args.asset,
        run_id=args.run_id,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result.get("status") in {"completed", "complete"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
