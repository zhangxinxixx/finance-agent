from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.orchestration import run_automation_orchestrator


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Automation Orchestrator skeleton.")
    parser.add_argument("--date", help="Trade date, defaults to today UTC.")
    parser.add_argument("--storage-root", default="storage", help="Storage root.")
    parser.add_argument("--trigger", default="hourly", choices=["hourly", "event_sla", "pre_analysis", "incident"], help="Trigger type.")
    parser.add_argument("--hour", help="Hour suffix, defaults to current UTC hour.")
    parser.add_argument("--send-notifications", action="store_true", help="Dispatch notification_plan through FeishuNotificationAgent.")
    parser.add_argument("--no-record-task", action="store_true", help="Do not write an automation_orchestrator TaskRun.")
    args = parser.parse_args(argv)

    result = run_automation_orchestrator(
        storage_root=args.storage_root,
        trade_date=args.date,
        trigger=args.trigger,
        hour=args.hour,
        send_notifications=args.send_notifications,
        record_task_run=not args.no_record_task,
    )
    summary = {
        "trade_date": result["trade_date"],
        "observed_at": result["observed_at"],
        "trigger": result["trigger"],
        "status": result["status"],
        "artifacts": result["artifacts"],
        "notification_result_count": len(result.get("notification_results", [])),
        "task_run_id": result.get("task_run_id"),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
