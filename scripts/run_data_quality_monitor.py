from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.monitoring import run_data_quality_monitor


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Data Quality & Freshness Monitor MVP.")
    parser.add_argument("--date", help="Trade date, defaults to today UTC.")
    parser.add_argument("--storage-root", default="storage", help="Storage root.")
    parser.add_argument("--run-source-probes", action="store_true", help="Run audited live ingestion source probes.")
    parser.add_argument(
        "--run-consistency-checks",
        action="store_true",
        help="Compare time-aligned independent market observations without modifying source data.",
    )
    parser.add_argument(
        "--probe-limit",
        type=int,
        choices=range(1, 21),
        default=5,
        help="Maximum preview rows requested from each live probe.",
    )
    parser.add_argument("--no-record-task", action="store_true", help="Do not write a data_quality_monitor TaskRun.")
    args = parser.parse_args(argv)

    result = run_data_quality_monitor(
        storage_root=args.storage_root,
        trade_date=args.date,
        record_task_run=not args.no_record_task,
        run_source_probes=args.run_source_probes,
        probe_limit=args.probe_limit,
        run_consistency_checks=args.run_consistency_checks,
    )
    summary = {
        "trade_date": result["trade_date"],
        "observed_at": result["observed_at"],
        "overall_status": result["data_quality_report"]["overall_status"],
        "readiness": result["downstream_readiness"]["readiness"],
        "can_run_full_analysis": result["downstream_readiness"]["can_run_full_analysis"],
        "can_run_research_distillation": result["downstream_readiness"]["can_run_research_distillation"],
        "artifacts": result["artifacts"],
        "task_run_id": result.get("task_run_id"),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
