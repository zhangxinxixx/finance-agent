from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date as calendar_date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.collectors.jin10.adapter import (
    build_jin10_outputs,
    persist_jin10_agent_outputs,
    persist_jin10_task_runs,
    write_jin10_outputs,
)
from apps.data_layer.jin10_image_assets import (
    DEFAULT_JIN10_IMAGE_RETENTION_DAYS,
    prune_jin10_image_assets,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Jin10 daily analysis artifacts from external reports.")
    parser.add_argument("--date", required=True, help="Report date, for example 2026-05-06.")
    parser.add_argument("--category", default="270", help="Jin10 category code, default 270 for 金银报告.")
    parser.add_argument("--external-root", default="~/jin10-reports", help="External Jin10 output root.")
    parser.add_argument("--storage-root", default="storage", help="finance-agent storage root.")
    parser.add_argument(
        "--image-retention-days",
        type=int,
        default=DEFAULT_JIN10_IMAGE_RETENTION_DAYS,
        help="Keep canonical Jin10 page JPEGs and parsed figures for this many days.",
    )
    parser.add_argument(
        "--vision-provider",
        default="cockpit",
        choices=("mimo", "cockpit"),
        help="Vision provider for page parsing.",
    )
    parser.add_argument(
        "--vision-model",
        "--mimo-model",
        dest="vision_model",
        default="gpt-5.6-luna",
        help="Vision model. --mimo-model remains as a compatibility alias.",
    )
    parser.add_argument("--vision-reasoning-effort", default="high", choices=("low", "medium", "high"))
    parser.add_argument("--vision-timeout", type=float, default=120.0)
    parser.add_argument("--analysis-provider", default="cockpit")
    parser.add_argument("--analysis-model", default="gpt-5.6-sol")
    parser.add_argument("--analysis-reasoning-effort", default="high", choices=("low", "medium", "high"))
    parser.add_argument("--analysis-timeout", type=float, default=300.0)
    parser.add_argument("--analysis-max-images", type=int, default=25)
    parser.add_argument("--article-id", action="append", default=None, help="Only process the given Jin10 article id. Repeatable.")
    args = parser.parse_args()
    os.environ["JIN10_IMAGE_RECOGNITION"] = "vlm"
    os.environ.setdefault("JIN10_VISION_CACHE_DIR", str(Path(args.storage_root) / "parsed" / "jin10" / "vision_cache"))
    os.environ["JIN10_VISION_PROVIDER"] = args.vision_provider
    os.environ["JIN10_VISION_MODEL"] = args.vision_model
    os.environ["JIN10_VISION_REASONING_EFFORT"] = args.vision_reasoning_effort
    os.environ["JIN10_VISION_TIMEOUT"] = str(args.vision_timeout)
    os.environ["JIN10_VISION_MAX_RETRIES"] = "0"
    os.environ["JIN10_AGENT_PROVIDER"] = args.analysis_provider
    os.environ["JIN10_AGENT_MODEL"] = args.analysis_model
    os.environ["JIN10_AGENT_REASONING_EFFORT"] = args.analysis_reasoning_effort
    os.environ["JIN10_AGENT_REQUEST_TIMEOUT"] = str(args.analysis_timeout)
    os.environ["JIN10_AGENT_MAX_IMAGES"] = str(max(0, args.analysis_max_images))

    outputs = build_jin10_outputs(
        external_root=Path(args.external_root).expanduser(),
        date=args.date,
        category=args.category,
        article_ids=args.article_id,
    )
    written = write_jin10_outputs(outputs, storage_root=args.storage_root)
    persisted_agent_outputs = persist_jin10_agent_outputs(outputs, storage_root=args.storage_root)
    persisted_task_runs = persist_jin10_task_runs(outputs, storage_root=args.storage_root)
    image_retention = prune_jin10_image_assets(
        external_root=Path(args.external_root).expanduser(),
        storage_root=Path(args.storage_root).expanduser(),
        reference_date=calendar_date.today(),
        retention_days=args.image_retention_days,
    )
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
        "image_retention": image_retention,
        "written": {layer: str(path) for layer, path in written.items()},
        "next_step_hint": "使用 scripts/generate_jin10_visual_report.py --raw-report-json <.../raw_article_report.json> 生成 prompt，再用 --agent-response <html-response> --html-output <.../daily_analysis.html> 落地 LLM 可视化报告。",
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
