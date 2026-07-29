"""Run an immutable daily-close batch JSON file and print its readiness summary."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.analysis.gold_policy.daily_close_batch import (  # noqa: E402
    GoldDailyCloseBatchInput,
    execute_gold_daily_close_batch,
)
from apps.analysis.gold_policy.daily_close_store import (  # noqa: E402
    DailyCloseHeadConflictError,
    DailyCloseStoreError,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Execute a deterministic XAUUSD daily-close batch.")
    parser.add_argument("--input", required=True, help="Immutable batch JSON input path")
    parser.add_argument("--storage-root", required=True, help="Daily-close storage root")
    args = parser.parse_args()

    input_path = Path(args.input)
    try:
        payload = json.loads(input_path.read_text(encoding="utf-8"))
        batch = GoldDailyCloseBatchInput.model_validate(payload)
        summary = execute_gold_daily_close_batch(
            storage_root=Path(args.storage_root), batch=batch
        )
    except (
        OSError,
        json.JSONDecodeError,
        ValueError,
        DailyCloseStoreError,
        DailyCloseHeadConflictError,
    ) as exc:
        print(json.dumps({"status": "error", "error": f"{type(exc).__name__}: {exc}"}), file=sys.stderr)
        raise SystemExit(2) from exc
    print(json.dumps(summary.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
