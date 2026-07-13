from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, time as dt_time, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.collectors.jin10.adapter import collect_raw_index
from apps.data_layer.jin10_image_assets import DEFAULT_JIN10_IMAGE_RETENTION_DAYS


DEFAULT_EXTERNAL_ROOT = Path(os.getenv("JIN10_REPORT_ROOT", "~/jin10-reports")).expanduser()
DEFAULT_STORAGE_ROOT = Path("storage")
DEFAULT_CATEGORY = "270"
DEFAULT_REPORT_TYPE = "daily"
DEFAULT_RETRY_MINUTES = 30
DEFAULT_START_TIME = "09:50"
DEFAULT_DEADLINE_TIME = "23:30"
DEFAULT_MODEL = "gpt-5.6-sol"
DEFAULT_VISION_MODEL = "gpt-5.6-luna"
DEFAULT_BROWSER_PROFILE = Path(
    os.getenv("JIN10_BROWSER_PROFILE", "~/.finance-agent/jin10_browser_profile")
).expanduser()
NON_REPORT_SUFFIXES = ("黄金头条", "投行金评")


@dataclass(slots=True)
class AttemptResult:
    status: str
    message: str
    article_id: str | None = None
    report_dir: str | None = None
    pipeline_summary: dict[str, Any] | None = None


def _artifact_paths(*, storage_root: Path, trade_date: str, article_id: str) -> dict[str, Path]:
    base = storage_root / "outputs" / "jin10" / trade_date / article_id
    return {
        "raw_article_report_json": base / "raw_article_report.json",
        "daily_analysis_json": base / "daily_analysis.json",
        "agent_analysis_report_json": base / "agent_analysis_report.json",
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Schedule Jin10 daily report fetch/analysis with half-hour retries until success."
    )
    parser.add_argument("--date", help="Target trade date, default today in local timezone.")
    parser.add_argument("--start-time", default=DEFAULT_START_TIME, help="First eligible local time, format HH:MM.")
    parser.add_argument("--deadline", default=DEFAULT_DEADLINE_TIME, help="Stop retrying after this local time, format HH:MM.")
    parser.add_argument("--retry-minutes", type=int, default=DEFAULT_RETRY_MINUTES, help="Retry interval in minutes.")
    parser.add_argument("--category", default=DEFAULT_CATEGORY, help="Jin10 category code, default 270 for daily.")
    parser.add_argument("--report-type", default=DEFAULT_REPORT_TYPE, choices=("daily", "weekly"))
    parser.add_argument("--external-root", default=str(DEFAULT_EXTERNAL_ROOT), help="External Jin10 root.")
    parser.add_argument("--storage-root", default=str(DEFAULT_STORAGE_ROOT), help="finance-agent storage root.")
    parser.add_argument(
        "--image-retention-days",
        type=int,
        default=DEFAULT_JIN10_IMAGE_RETENTION_DAYS,
        help="Keep canonical page JPEGs and parsed figures for this many days.",
    )
    parser.add_argument("--browser-profile", default=str(DEFAULT_BROWSER_PROFILE) if DEFAULT_BROWSER_PROFILE.exists() else None)
    parser.add_argument("--model", default=DEFAULT_MODEL, help="LLM model for agent analysis.")
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
        default=DEFAULT_VISION_MODEL,
        help="Vision model. --mimo-model remains as a compatibility alias.",
    )
    parser.add_argument("--max-attempts", type=int, default=0, help="Optional max attempts. 0 means until deadline.")
    parser.add_argument("--sleep-before-start", action="store_true", help="Sleep until start-time if invoked early.")
    parser.add_argument("--dry-run", action="store_true", help="Resolve plan and existing state without executing fetch/pipeline.")
    parser.add_argument("--force-rerun", action="store_true", help="Run pipeline even when the final agent analysis already exists.")
    return parser.parse_args()


def _parse_hhmm(value: str) -> dt_time:
    return datetime.strptime(value, "%H:%M").time()


def _target_date(raw: str | None) -> date:
    if raw:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    return datetime.now().date()


def _local_window(target: date, start: str, deadline: str) -> tuple[datetime, datetime]:
    start_dt = datetime.combine(target, _parse_hhmm(start))
    deadline_dt = datetime.combine(target, _parse_hhmm(deadline))
    if deadline_dt <= start_dt:
        deadline_dt += timedelta(days=1)
    return start_dt, deadline_dt


def _sleep_until(start_dt: datetime) -> None:
    now = datetime.now()
    if now >= start_dt:
        return
    time.sleep(max((start_dt - now).total_seconds(), 0))


def _has_local_report(*, external_root: Path, trade_date: str, category: str) -> dict[str, Any] | None:
    raw_index = collect_raw_index(external_root, trade_date, category)
    reports = raw_index.get("reports") or []
    if not reports:
        return None
    return reports[0]


def _run_json_command(cmd: list[str], *, env: dict[str, str]) -> dict[str, Any]:
    completed = subprocess.run(cmd, check=True, capture_output=True, text=True, env=env)
    stdout = completed.stdout.strip()
    if not stdout:
        return {}
    return json.loads(stdout)


def _discover_article_id(*, env: dict[str, str], trade_date: str) -> dict[str, Any] | None:
    cmd = [
        sys.executable,
        "scripts/find_jin10_daily_article_ids.py",
        "--dates",
        trade_date,
        "--limit",
        "20",
    ]
    result = _run_json_command(cmd, env=env)
    resolved = (result.get("results") or {}).get(trade_date)
    if not resolved:
        return None
    title = str(resolved.get("title") or "")
    if any(token in title for token in NON_REPORT_SUFFIXES):
        return None
    return resolved


def _fetch_article(
    *,
    env: dict[str, str],
    article_id: str,
    report_type: str,
    external_root: Path,
    browser_profile: str | None,
) -> dict[str, Any]:
    cmd = [
        sys.executable,
        "scripts/fetch_jin10_report.py",
        "--article-id",
        article_id,
        "--report-type",
        report_type,
        "--external-root",
        str(external_root),
    ]
    if browser_profile:
        cmd.extend(["--browser-profile", browser_profile])
    return _run_json_command(cmd, env=env)


def _run_pipeline(
    *,
    env: dict[str, str],
    trade_date: str,
    article_id: str,
    category: str,
    vision_provider: str,
    vision_model: str,
    external_root: Path,
    storage_root: Path,
    image_retention_days: int,
) -> dict[str, Any]:
    cmd = [
        sys.executable,
        "scripts/run_daily_report_pipeline.py",
        "--date",
        trade_date,
        "--category",
        category,
        "--article-id",
        article_id,
        "--external-root",
        str(external_root),
        "--storage-root",
        str(storage_root),
        "--image-retention-days",
        str(image_retention_days),
        "--vision-provider",
        vision_provider,
        "--vision-model",
        vision_model,
    ]
    return _run_json_command(cmd, env=env)


def _attempt_once(
    *,
    trade_date: str,
    args: argparse.Namespace,
    env: dict[str, str],
) -> AttemptResult:
    external_root = Path(args.external_root).expanduser()
    storage_root = Path(args.storage_root).expanduser()
    local_report = _has_local_report(external_root=external_root, trade_date=trade_date, category=args.category)
    article_id = str(local_report.get("article_id") or "") if local_report else ""
    report_dir = str(local_report.get("external_report_dir") or "") if local_report else None

    if not article_id:
        discovered = _discover_article_id(env=env, trade_date=trade_date)
        if discovered is None:
            return AttemptResult(status="retry", message=f"{trade_date} 未发现可用日报 article_id")
        article_id = str(discovered.get("article_id") or "")
        if not article_id:
            return AttemptResult(status="retry", message=f"{trade_date} 发现结果缺少 article_id")
        if args.dry_run:
            return AttemptResult(status="ready", message=f"{trade_date} 已发现 article_id {article_id}", article_id=article_id)
        fetched = _fetch_article(
            env=env,
            article_id=article_id,
            report_type=args.report_type,
            external_root=external_root,
            browser_profile=args.browser_profile,
        )
        report_dir = str(fetched.get("report_dir") or "")

    if args.dry_run:
        return AttemptResult(
            status="ready",
            message=f"{trade_date} 已具备本地日报，待运行 pipeline",
            article_id=article_id,
            report_dir=report_dir,
        )

    artifacts = _artifact_paths(storage_root=storage_root, trade_date=trade_date, article_id=article_id)
    if artifacts["agent_analysis_report_json"].exists() and not args.force_rerun:
        return AttemptResult(
            status="success",
            message=f"{trade_date} 已存在完整 agent_analysis_report，跳过重复 pipeline",
            article_id=article_id,
            report_dir=report_dir,
            pipeline_summary={
                "date": trade_date,
                "article_id": article_id,
                "skipped": True,
                "reason": "existing_agent_analysis_report",
                "artifact": str(artifacts["agent_analysis_report_json"]),
            },
        )

    pipeline_summary = _run_pipeline(
        env=env,
        trade_date=trade_date,
        article_id=article_id,
        category=args.category,
        vision_provider=args.vision_provider,
        vision_model=args.vision_model,
        external_root=external_root,
        storage_root=storage_root,
        image_retention_days=args.image_retention_days,
    )
    return AttemptResult(
        status="success",
        message=f"{trade_date} 抓取与分析完成",
        article_id=article_id,
        report_dir=report_dir,
        pipeline_summary=pipeline_summary,
    )


def main() -> int:
    args = _parse_args()
    trade_date_obj = _target_date(args.date)
    trade_date = trade_date_obj.isoformat()
    start_dt, deadline_dt = _local_window(trade_date_obj, args.start_time, args.deadline)
    if args.sleep_before_start:
        _sleep_until(start_dt)

    env = os.environ.copy()
    env.setdefault("no_proxy", "127.0.0.1,localhost,::1")
    env.setdefault("UV_CACHE_DIR", "/tmp/uv-cache")
    env["FINANCE_AGENT_FORCE_LIVE_LLM"] = "1"
    env["OPENAI_DEFAULT_MODEL"] = args.model
    env["JIN10_AGENT_PROVIDER"] = "cockpit"
    env["JIN10_AGENT_MODEL"] = args.model
    env["JIN10_AGENT_REASONING_EFFORT"] = "high"
    env["JIN10_AGENT_REQUEST_TIMEOUT"] = "300"
    env["JIN10_AGENT_MAX_IMAGES"] = "25"
    env["JIN10_VISION_PROVIDER"] = args.vision_provider
    env["JIN10_VISION_MODEL"] = args.vision_model
    env["JIN10_VISION_REASONING_EFFORT"] = "high"
    env["JIN10_VISION_TIMEOUT"] = "120"
    env["JIN10_VISION_MAX_RETRIES"] = "0"
    env["JIN10_IMAGE_RECOGNITION"] = "vlm"

    attempts = 0
    history: list[dict[str, Any]] = []
    while True:
        now = datetime.now()
        if now < start_dt:
            if not args.sleep_before_start:
                print(
                    json.dumps(
                        {
                            "status": "waiting",
                            "trade_date": trade_date,
                            "message": f"当前时间早于开始时间 {start_dt.isoformat()}",
                            "next_run_after": start_dt.isoformat(),
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                return 0
            _sleep_until(start_dt)
            now = datetime.now()

        if now > deadline_dt:
            print(
                json.dumps(
                    {
                        "status": "deadline_exceeded",
                        "trade_date": trade_date,
                        "attempts": attempts,
                        "history": history,
                        "deadline": deadline_dt.isoformat(),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 2

        attempts += 1
        try:
            result = _attempt_once(trade_date=trade_date, args=args, env=env)
        except subprocess.CalledProcessError as exc:
            result = AttemptResult(
                status="retry",
                message=f"命令失败: {' '.join(exc.cmd)}",
            )
        history.append(
            {
                "attempt": attempts,
                "at": now.isoformat(),
                "status": result.status,
                "message": result.message,
                "article_id": result.article_id,
            }
        )
        if result.status in {"success", "ready"}:
            print(
                json.dumps(
                    {
                        "status": result.status,
                        "trade_date": trade_date,
                        "attempts": attempts,
                        "article_id": result.article_id,
                        "report_dir": result.report_dir,
                        "pipeline_summary": result.pipeline_summary,
                        "history": history,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0

        if args.max_attempts and attempts >= args.max_attempts:
            print(
                json.dumps(
                    {
                        "status": "max_attempts_exceeded",
                        "trade_date": trade_date,
                        "attempts": attempts,
                        "history": history,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 3

        time.sleep(max(args.retry_minutes, 1) * 60)


if __name__ == "__main__":
    raise SystemExit(main())
