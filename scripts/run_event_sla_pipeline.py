from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.event_sla import run_event_sla_pipeline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Event SLA Pipeline MVP.")
    parser.add_argument("--date", help="Trade date, defaults to today UTC.")
    parser.add_argument("--storage-root", default="storage", help="Storage root.")
    parser.add_argument("--source-type", action="append", choices=["jin10", "cme"], help="Source type to watch. Repeatable.")
    parser.add_argument("--no-record-task", action="store_true", help="Do not write event_sla_analysis TaskRuns.")
    args = parser.parse_args(argv)

    source_types = tuple(args.source_type or ["jin10", "cme"])
    result = run_event_sla_pipeline(
        storage_root=args.storage_root,
        trade_date=args.date,
        source_types=source_types,
        record_task_run=not args.no_record_task,
    )
    summary = {
        "trade_date": result["trade_date"],
        "observed_at": result["observed_at"],
        "created_count": result["created_count"],
        "events": [
            {
                "event_id": item["event_id"],
                "source_key": item["source_key"],
                "status": item["status"],
                "evidence_level": item.get("evidence_level"),
                "sla_trace": item["artifacts"].get("sla_trace"),
                "notification_request": item["artifacts"].get("notification_request"),
                "task_run_id": item.get("task_run_id"),
            }
            for item in result["events"]
        ],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
