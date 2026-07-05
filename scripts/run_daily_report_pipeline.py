from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.collectors.jin10.adapter import (
    build_jin10_outputs,
    persist_jin10_agent_outputs,
    persist_jin10_task_runs,
    write_jin10_outputs,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Jin10 daily analysis artifacts from external reports.")
    parser.add_argument("--date", required=True, help="Report date, for example 2026-05-06.")
    parser.add_argument("--category", default="270", help="Jin10 category code, default 270 for 金银报告.")
    parser.add_argument("--external-root", default="~/jin10-reports", help="External Jin10 output root.")
    parser.add_argument("--storage-root", default="storage", help="finance-agent storage root.")
    parser.add_argument("--vision-provider", default="mimo", choices=("mimo", "dashscope", "qwen"), help="Vision provider for page parsing.")
    parser.add_argument("--mimo-model", default="mimo-v2.5", help="MiMo vision model, for example mimo-v2.5.")
    parser.add_argument("--qwen-model", default=None, help="Legacy DashScope/Qwen vision model for compatibility.")
    parser.add_argument("--article-id", action="append", default=None, help="Only process the given Jin10 article id. Repeatable.")
    args = parser.parse_args()
    os.environ["JIN10_IMAGE_RECOGNITION"] = "vlm"
    os.environ.setdefault("JIN10_VISION_CACHE_DIR", str(Path(args.storage_root) / "parsed" / "jin10" / "vision_cache"))
    os.environ["JIN10_VISION_PROVIDER"] = args.vision_provider
    os.environ["JIN10_MIMO_VL_MODEL"] = args.mimo_model
    if args.qwen_model:
        os.environ["JIN10_QWEN_VL_MODEL"] = args.qwen_model

    outputs = build_jin10_outputs(
        external_root=Path(args.external_root).expanduser(),
        date=args.date,
        category=args.category,
        article_ids=args.article_id,
    )
    written = write_jin10_outputs(outputs, storage_root=args.storage_root)
    persisted_agent_outputs = persist_jin10_agent_outputs(outputs, storage_root=args.storage_root)
    persisted_task_runs = persist_jin10_task_runs(outputs, storage_root=args.storage_root)
    summary = {
        "date": args.date,
        "category": args.category,
        "reports": len(outputs["parsed"]["reports"]),
        "daily_reports": [
            {
                "trade_date": item["trade_date"],
                "run_id": item["run_id"],
                "family": item["json"]["family"],
                "raw_article_family": item["raw_article_json"]["family"],
                "raw_article_report_json": str(
                    Path(args.storage_root) / "outputs" / "jin10" / item["trade_date"] / item["run_id"] / "raw_article_report.json"
                ),
                "raw_article_report_md": str(
                    Path(args.storage_root) / "outputs" / "jin10" / item["trade_date"] / item["run_id"] / "raw_article_report.md"
                ),
                "visual_report_html": str(
                    Path(args.storage_root) / "outputs" / "jin10" / item["trade_date"] / item["run_id"] / "daily_analysis.html"
                ),
                "agent_analysis_report_json": str(
                    Path(args.storage_root)
                    / "outputs"
                    / "jin10"
                    / item["trade_date"]
                    / item["run_id"]
                    / "agent_analysis_report.json"
                ),
                "agent_analysis_report_md": str(
                    Path(args.storage_root)
                    / "outputs"
                    / "jin10"
                    / item["trade_date"]
                    / item["run_id"]
                    / "agent_analysis_report.md"
                ),
            }
            for item in outputs.get("daily_reports", [])
        ],
        "persisted_agent_outputs": persisted_agent_outputs,
        "persisted_task_runs": persisted_task_runs,
        "written": {layer: str(path) for layer, path in written.items()},
        "next_step_hint": "使用 scripts/generate_jin10_visual_report.py --raw-report-json <.../raw_article_report.json> 生成 prompt，再用 --agent-response <html-response> --html-output <.../daily_analysis.html> 落地 LLM 可视化报告。",
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
