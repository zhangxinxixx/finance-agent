from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.data_control import run_data_control_agent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Data Control Agent MVP.")
    parser.add_argument("--date", help="Trade date, defaults to today UTC.")
    parser.add_argument("--storage-root", default="storage", help="Storage root.")
    parser.add_argument("--no-record-task", action="store_true", help="Do not write a data_control_agent TaskRun.")
    args = parser.parse_args(argv)

    result = run_data_control_agent(
        storage_root=args.storage_root,
        trade_date=args.date,
        record_task_run=not args.no_record_task,
    )
    summary = {
        "trade_date": result["trade_date"],
        "observed_at": result["observed_at"],
        "hour": result["hour"],
        "status": result["status"],
        "main_analysis_readiness": result["main_analysis_readiness"],
        "knowledge_distillation_readiness": result["knowledge_distillation_readiness"],
        "artifacts": result["artifacts"],
        "notification_request": {
            "kind": result["notification_request"].get("kind"),
            "severity": result["notification_request"].get("severity"),
            "title": result["notification_request"].get("title"),
        },
        "task_run_id": result.get("task_run_id"),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
