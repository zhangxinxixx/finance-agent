from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
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


EXPECTED_AGENT_ANALYSIS_FAMILY = "jin10_agent_analysis"
COMPLETION_MARKER_NAME = "daily_analysis_completion.json"


@dataclass(frozen=True, slots=True)
class DailyAnalysisCompletion:
    status: str
    reasons: tuple[str, ...]
    article_id: str

    @property
    def completed(self) -> bool:
        return self.status in {"success", "limited_success"}

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "completed": self.completed,
            "article_id": self.article_id,
            "reasons": list(self.reasons),
        }


def daily_pipeline_exit_code(
    summary: dict[str, object],
    *,
    requested_article_ids: list[str] | None,
) -> int:
    """Return non-zero unless every requested daily analysis is durably complete."""

    reports = summary.get("daily_reports")
    daily_reports = [item for item in reports if isinstance(item, dict)] if isinstance(reports, list) else []
    if not daily_reports:
        return 2
    completed_ids = {
        str(item.get("run_id") or item.get("article_id") or "")
        for item in daily_reports
        if isinstance(item.get("completion"), dict)
        and bool(item["completion"].get("completed"))
    }
    if requested_article_ids and not set(requested_article_ids).issubset(completed_ids):
        return 2
    if len(completed_ids) != len(daily_reports):
        return 2
    return 0


def validate_daily_analysis_completion(
    *,
    storage_root: Path | str,
    trade_date: str,
    article_id: str,
    pipeline_summary: dict[str, object] | None,
) -> DailyAnalysisCompletion:
    """Validate durable daily-analysis artifacts and AgentOutput persistence truth."""

    reasons: list[str] = []
    base = Path(storage_root).expanduser() / "outputs" / "jin10" / trade_date / article_id
    json_path = base / "agent_analysis_report.json"
    markdown_path = base / "agent_analysis_report.md"
    payload: dict[str, object] = {}
    try:
        loaded = json.loads(json_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            payload = loaded
        else:
            reasons.append("agent_analysis_json_not_object")
    except FileNotFoundError:
        reasons.append("agent_analysis_json_missing")
    except (OSError, json.JSONDecodeError):
        reasons.append("agent_analysis_json_invalid")

    payload_article_id = str(payload.get("article_id") or payload.get("run_id") or "")
    if payload and payload_article_id != article_id:
        reasons.append("article_id_mismatch")
    if payload and str(payload.get("family") or "") != EXPECTED_AGENT_ANALYSIS_FAMILY:
        reasons.append("agent_analysis_family_invalid")
    if payload and not str(payload.get("one_line_conclusion") or "").strip():
        reasons.append("one_line_conclusion_empty")
    if payload and not payload.get("source_refs"):
        reasons.append("source_refs_empty")

    quality_audit = payload.get("quality_audit") if isinstance(payload.get("quality_audit"), dict) else {}
    quality_status = str(quality_audit.get("status") or "").strip().lower()
    if quality_status == "rejected":
        reasons.append("quality_audit_rejected")
    elif quality_status not in {"accepted", "needs_review"}:
        reasons.append("quality_audit_status_invalid")

    try:
        if not markdown_path.read_text(encoding="utf-8").strip():
            reasons.append("agent_analysis_markdown_empty")
    except OSError:
        reasons.append("agent_analysis_markdown_missing")

    summary = pipeline_summary if isinstance(pipeline_summary, dict) else {}
    if int(summary.get("reports") or 0) <= 0:
        reasons.append("pipeline_reports_empty")
    daily_reports = summary.get("daily_reports")
    matching_reports = [
        item
        for item in daily_reports if isinstance(item, dict) and str(item.get("run_id") or item.get("article_id") or "") == article_id
    ] if isinstance(daily_reports, list) else []
    if not matching_reports:
        reasons.append("target_daily_report_missing")
    persisted = summary.get("persisted_agent_outputs")
    persisted_match = next(
        (
            item
            for item in persisted
            if isinstance(item, dict)
            and str(item.get("run_id") or "") == article_id
            and item.get("agent_output_id")
        ),
        None,
    ) if isinstance(persisted, list) else None
    if persisted_match is None:
        reasons.append("agent_output_not_persisted")

    if reasons:
        return DailyAnalysisCompletion(status="failed", reasons=tuple(dict.fromkeys(reasons)), article_id=article_id)
    status = "limited_success" if quality_status == "needs_review" else "success"
    return DailyAnalysisCompletion(status=status, reasons=(), article_id=article_id)


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
        help="Keep disposable VLM cache entries for this many days; canonical evidence is never pruned.",
    )
    parser.add_argument(
        "--vision-provider",
        default="cockpit",
        choices=("mimo", "cockpit", "jojocode"),
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
        storage_root=args.storage_root,
    )
    written = write_jin10_outputs(outputs, storage_root=args.storage_root)
    persisted_agent_outputs = persist_jin10_agent_outputs(outputs, storage_root=args.storage_root)
    persisted_task_runs = persist_jin10_task_runs(outputs, storage_root=args.storage_root)
    image_retention = prune_jin10_image_assets(
        external_root=Path(args.external_root).expanduser(),
        storage_root=Path(args.storage_root).expanduser(),
        reference_date=calendar_date.fromisoformat(args.date),
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
    for item in summary["daily_reports"]:
        completion = validate_daily_analysis_completion(
            storage_root=args.storage_root,
            trade_date=item["trade_date"],
            article_id=item["run_id"],
            pipeline_summary=summary,
        )
        item["completion"] = completion.to_dict()
        marker_path = (
            Path(args.storage_root)
            / "outputs"
            / "jin10"
            / item["trade_date"]
            / item["run_id"]
            / COMPLETION_MARKER_NAME
        )
        marker_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return daily_pipeline_exit_code(summary, requested_article_ids=args.article_id)


if __name__ == "__main__":
    raise SystemExit(main())
