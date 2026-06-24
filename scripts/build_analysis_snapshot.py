#!/usr/bin/env python3
"""Build a manual premarket analysis snapshot from existing JSON artifacts.

This script is for backfill/debug use only. Production snapshot writing happens in
apps.worker.runner after deterministic macro/options pipeline steps complete.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.analysis.snapshots import build_analysis_snapshot, write_analysis_snapshot  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        macro_snapshot = _load_optional_json(args.macro_json, allow_missing=args.allow_missing, label="macro-json")
        options_snapshot = _load_optional_json(args.options_json, allow_missing=args.allow_missing, label="options-json")
        snapshot = build_analysis_snapshot(
            asset=args.asset,
            trade_date=args.trade_date,
            run_id=args.run_id,
            macro_snapshot=macro_snapshot,
            options_snapshot=options_snapshot,
        )
        path = write_analysis_snapshot(snapshot, storage_root=args.storage_root)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(path)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build premarket_snapshot.json from existing macro/options JSON files.")
    parser.add_argument("--asset", required=True)
    parser.add_argument("--trade-date", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--macro-json", required=True, type=Path)
    parser.add_argument("--options-json", required=True, type=Path)
    parser.add_argument("--storage-root", required=True, type=Path)
    parser.add_argument("--allow-missing", action="store_true")
    return parser


def _load_optional_json(path: Path, *, allow_missing: bool, label: str) -> dict[str, Any] | None:
    if not path.exists():
        if allow_missing:
            return None
        raise FileNotFoundError(f"{label} does not exist: {path}")
    if path.stat().st_size == 0:
        if allow_missing:
            return None
        raise ValueError(f"{label} is empty: {path}")

    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{label} must contain a JSON object: {path}")
    return data


if __name__ == "__main__":
    raise SystemExit(main())
