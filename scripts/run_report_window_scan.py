from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.collectors.jin10.fetcher import Jin10CategoryEntry, fetch_category_entries  # noqa: E402
from apps.collectors.cme.downloader import build_daily_bulletin_url  # noqa: E402
from apps.worker.pipelines.weekly_context_revision import (  # noqa: E402
    build_weekly_context_revision_input_snapshot,
    generate_weekly_context_revision,
)

BEIJING = ZoneInfo("Asia/Shanghai")
DEFAULT_EXTERNAL_ROOT = Path(
    os.getenv("FINANCE_AGENT_EXTERNAL_REPORT_ROOT", "~/finance-agent-data/jin10-reports")
).expanduser()
DEFAULT_STORAGE_ROOT = Path("storage")
DEFAULT_RAW_ROOT = Path(".")
DEFAULT_LOCK_PATH = Path("/tmp/finance-agent-report-window-scan.lock")


@dataclass(frozen=True, slots=True)
class ScanWindow:
    key: str
    source: str
    start: time
    end: time
    category: str | None = None
    report_type: str | None = None
    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    max_articles: int = 1
    weekdays_only: bool = False
    weekdays: tuple[int, ...] = ()
    publication_lookback_days: int = 0


WINDOWS = (
    ScanWindow(
        "jin10_gold", "jin10", time(9, 50), time(12, 10), "270", "daily", exclude=("黄金头条", "投行金评", "黄金周报")
    ),
    ScanWindow(
        "jin10_gold_weekly",
        "jin10",
        time(12, 0),
        time(18, 0),
        "536",
        "weekly",
        weekdays=(6,),
        publication_lookback_days=1,
    ),
    ScanWindow("jin10_oil", "jin10", time(9, 50), time(12, 10), "272", "oil", exclude=("原油头条", "投行油评")),
    ScanWindow("cme_metals_options", "cme", time(12, 0), time(19, 0), weekdays_only=True),
    ScanWindow(
        "jin10_gold_positioning",
        "jin10",
        time(14, 30),
        time(16, 30),
        "274",
        "positioning",
        include=("黄金",),
        max_articles=2,
    ),
    ScanWindow(
        "jin10_market_observation",
        "jin10",
        time(17, 30),
        time(19, 30),
        "458",
        "market_observation",
        include=("每日市场观察",),
    ),
    ScanWindow(
        "gold_daily_macro_close",
        "analysis",
        time(20, 0),
        time(20, 50),
        weekdays_only=True,
    ),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Poll report sources only during their observed publication windows.")
    parser.add_argument("--at", help="Override Asia/Shanghai time, for example 2026-07-16T10:00:00.")
    parser.add_argument("--only", choices=tuple(window.key for window in WINDOWS))
    parser.add_argument("--external-root", default=str(DEFAULT_EXTERNAL_ROOT))
    parser.add_argument("--storage-root", default=str(DEFAULT_STORAGE_ROOT))
    parser.add_argument("--raw-root", default=str(DEFAULT_RAW_ROOT))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--lock-path", default=str(DEFAULT_LOCK_PATH))
    return parser.parse_args()


def resolve_now(value: str | None) -> datetime:
    if not value:
        return datetime.now(BEIJING)
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=BEIJING) if parsed.tzinfo is None else parsed.astimezone(BEIJING)


def due_windows(now: datetime, *, only: str | None = None) -> list[ScanWindow]:
    local_now = now.astimezone(BEIJING)
    current_time = local_now.time().replace(tzinfo=None)
    return [
        window
        for window in WINDOWS
        if (only is None or window.key == only)
        and (not window.weekdays_only or local_now.weekday() < 5)
        and (not window.weekdays or local_now.weekday() in window.weekdays)
        and window.start <= current_time <= window.end
    ]


def publication_date(value: str | None, *, now: datetime) -> date | None:
    if not value:
        return None
    normalized = " ".join(value.split())
    local_now = now.astimezone(BEIJING)
    match = re.fullmatch(r"(\d+)分钟前", normalized)
    if match:
        return (local_now - timedelta(minutes=int(match.group(1)))).date()
    match = re.fullmatch(r"(\d+)小时前", normalized)
    if match:
        return (local_now - timedelta(hours=int(match.group(1)))).date()
    match = re.fullmatch(r"(\d+)天前", normalized)
    if match:
        return (local_now - timedelta(days=int(match.group(1)))).date()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(normalized, fmt).date()
        except ValueError:
            pass
    for fmt in ("%m-%d %H:%M", "%m-%d"):
        try:
            return datetime.strptime(normalized, fmt).replace(year=local_now.year).date()
        except ValueError:
            pass
    return None


def matching_entries(
    entries: list[Jin10CategoryEntry], *, window: ScanWindow, now: datetime
) -> list[Jin10CategoryEntry]:
    today = now.astimezone(BEIJING).date()
    matches = []
    for entry in entries:
        if window.include and not all(marker in entry.title for marker in window.include):
            continue
        if any(marker in entry.title for marker in window.exclude):
            continue
        published_on = publication_date(entry.published_at, now=now)
        if published_on is None:
            continue
        age_days = (today - published_on).days
        if age_days < 0 or age_days > window.publication_lookback_days:
            continue
        matches.append(entry)
        if len(matches) >= window.max_articles:
            break
    return matches


class CommandExecutionError(RuntimeError):
    pass


def run_command(command: list[str], *, env: dict[str, str]) -> dict[str, Any]:
    completed = subprocess.run(command, check=False, capture_output=True, text=True, env=env)
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "no subprocess output"
        raise CommandExecutionError(
            f"Command {command!r} failed with exit code {completed.returncode}: {detail[-2000:]}"
        )
    stdout = completed.stdout.strip()
    return json.loads(stdout) if stdout else {}


def scan_jin10(
    window: ScanWindow, *, now: datetime, external_root: Path, storage_root: Path, dry_run: bool, env: dict[str, str]
) -> dict[str, Any]:
    assert window.category and window.report_type
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        entries = fetch_category_entries(category_code=window.category, client=client)
    candidates = matching_entries(entries, window=window, now=now)
    actions: list[dict[str, Any]] = []
    for entry in candidates:
        published_on = publication_date(entry.published_at, now=now)
        trade_date = (published_on or now.astimezone(BEIJING).date()).isoformat()
        external_meta = external_root / trade_date / window.report_type / entry.article_id / "meta.json"
        output = storage_root / "outputs" / "jin10" / trade_date / entry.article_id / "agent_analysis_report.json"
        completion = (
            storage_root / "outputs" / "jin10" / trade_date / entry.article_id / "daily_analysis_completion.json"
        )
        if output.exists() and completion.exists():
            action: dict[str, Any] = {
                "article_id": entry.article_id,
                "status": "complete",
                "output": str(output),
            }
            if window.report_type == "weekly":
                action["revision"] = ensure_weekly_context_revision(
                    article_id=entry.article_id,
                    baseline_date=trade_date,
                    trade_date=now.astimezone(BEIJING).date().isoformat(),
                    storage_root=storage_root,
                    dry_run=dry_run,
                )
            actions.append(action)
            continue
        if dry_run:
            actions.append(
                {
                    "article_id": entry.article_id,
                    "status": "would_process_existing" if external_meta.exists() else "would_fetch_and_process",
                    "title": entry.title,
                    "published_at": entry.published_at,
                }
            )
            continue
        if not external_meta.exists():
            run_command(
                [
                    sys.executable,
                    "scripts/fetch_jin10_report.py",
                    "--article-id",
                    entry.article_id,
                    "--category",
                    window.category,
                    "--external-root",
                    str(external_root),
                ],
                env=env,
            )
        summary = run_command(
            [
                sys.executable,
                "scripts/run_daily_report_pipeline.py",
                "--date",
                trade_date,
                "--category",
                window.category,
                "--external-root",
                str(external_root),
                "--storage-root",
                str(storage_root),
                "--article-id",
                entry.article_id,
            ],
            env=env,
        )
        action = {"article_id": entry.article_id, "status": "processed", "summary": summary}
        if window.report_type == "weekly":
            action["revision"] = ensure_weekly_context_revision(
                article_id=entry.article_id,
                baseline_date=trade_date,
                trade_date=now.astimezone(BEIJING).date().isoformat(),
                storage_root=storage_root,
                dry_run=False,
            )
        actions.append(action)
    return {
        "window": window.key,
        "status": "waiting" if not candidates else "ok",
        "listing_count": len(entries),
        "candidate_count": len(candidates),
        "actions": actions,
    }


def ensure_weekly_context_revision(
    *,
    article_id: str,
    baseline_date: str,
    trade_date: str,
    storage_root: Path,
    dry_run: bool,
) -> dict[str, Any]:
    snapshot = build_weekly_context_revision_input_snapshot(
        article_id=article_id,
        baseline_date=baseline_date,
        trade_date=trade_date,
        storage_root=storage_root,
    )
    if snapshot.get("status") == "blocked":
        return {
            "status": "waiting",
            "reason": snapshot.get("blocking_reason") or "weekly_revision_inputs_blocked",
        }
    premarket_path = str((snapshot.get("input_snapshot_ids") or {}).get("premarket_snapshot") or "")
    context_run_id = Path(premarket_path).parent.name
    if not context_run_id:
        return {"status": "waiting", "reason": "missing_context_run_id"}
    run_id = f"{_safe_run_component(article_id)}-{_safe_run_component(context_run_id)}-v1"
    output_dir = storage_root / "outputs" / "weekly_context_revision" / "XAUUSD" / trade_date / run_id
    required = tuple(output_dir / name for name in ("source.md", "analysis.md", "report_structured.json"))
    if all(path.is_file() for path in required):
        return {"status": "complete", "run_id": run_id, "output": str(output_dir)}
    if dry_run:
        return {"status": "would_generate", "run_id": run_id, "input_status": snapshot.get("status")}
    try:
        result = generate_weekly_context_revision(
            article_id=article_id,
            baseline_date=baseline_date,
            trade_date=trade_date,
            run_id=run_id,
            storage_root=storage_root,
        )
    except FileExistsError:
        if all(path.is_file() for path in required):
            return {"status": "complete", "run_id": run_id, "output": str(output_dir)}
        raise
    return {
        "status": "generated" if result.get("artifact_type") == "weekly_context_revision" else str(result.get("status") or "waiting"),
        "run_id": run_id,
        "quality_status": (result.get("structured_payload") or {}).get("quality_status"),
        "publication_status": (result.get("structured_payload") or {}).get("publication_status"),
        "paths": list(result.get("paths") or []),
    }


def _safe_run_component(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-.")
    if not normalized:
        raise ValueError("weekly revision run component is empty")
    return normalized


def previous_weekday(value: date) -> date:
    candidate = value - timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate


def latest_cme_pdf(raw_root: Path, report_date: str) -> Path | None:
    candidates = sorted((raw_root / "raw" / "cme" / "daily_bulletin" / report_date).glob("*.pdf"))
    return candidates[-1] if candidates else None


def scan_cme(
    window: ScanWindow, *, now: datetime, raw_root: Path, storage_root: Path, dry_run: bool, env: dict[str, str]
) -> dict[str, Any]:
    expected_date = previous_weekday(now.astimezone(BEIJING).date()).isoformat()
    output = storage_root / "outputs" / "cme_options" / expected_date / "options_analysis.json"
    existing_pdf = latest_cme_pdf(raw_root, expected_date)
    if output.exists():
        return {"window": window.key, "status": "complete", "report_date": expected_date, "output": str(output)}
    if dry_run:
        return {
            "window": window.key,
            "status": "would_process_existing" if existing_pdf else "would_download_and_process",
            "expected_report_date": expected_date,
            "raw_pdf": str(existing_pdf) if existing_pdf else None,
        }
    raw_pdf = existing_pdf
    if raw_pdf is None:
        try:
            downloaded = run_command(
                [sys.executable, "scripts/download_cme_pdf.py", "--storage-root", str(raw_root)], env=env
            )
        except CommandExecutionError as exc:
            return {
                "window": window.key,
                "status": "waiting",
                "reason": "download_failed",
                "expected_report_date": expected_date,
                "error": str(exc),
            }
        report_date = str(downloaded.get("report_date") or "")
        if report_date != expected_date:
            return {
                "window": window.key,
                "status": "waiting",
                "expected_report_date": expected_date,
                "available_report_date": report_date or None,
            }
        raw_pdf = raw_root / str(downloaded["raw_path"])
    parsed_dir = storage_root / "parsed" / "cme" / expected_date
    parsed = run_command(
        [
            sys.executable,
            "scripts/parse_cme_pdf.py",
            "--pdf",
            str(raw_pdf),
            "--product",
            "OG",
            "--out-dir",
            str(parsed_dir),
        ],
        env=env,
    )
    ingest = run_command(
        [sys.executable, "scripts/ingest_cme_snapshot.py", "--pdf", str(raw_pdf), "--product", "OG"], env=env
    )
    subprocess.run(
        [
            sys.executable,
            "scripts/run_options_analysis.py",
            "--trade-date",
            expected_date,
            "--product",
            "OG",
            "--parsed-json",
            str(parsed["json_path"]),
            "--out-dir",
            str(output.parent),
            "--data-source-status",
            str(parsed.get("status") or "UNKNOWN"),
            "--data-source-url",
            build_daily_bulletin_url(),
        ],
        check=True,
        env=env,
    )
    return {
        "window": window.key,
        "status": "processed",
        "report_date": expected_date,
        "raw_pdf": str(raw_pdf),
        "parsed_dir": str(parsed_dir),
        "ingest": ingest,
        "output": str(output),
    }


def scan_daily_macro_close(
    window: ScanWindow,
    *,
    now: datetime,
    storage_root: Path,
    dry_run: bool,
    env: dict[str, str],
) -> dict[str, Any]:
    trade_date = now.astimezone(BEIJING).date().isoformat()
    if dry_run:
        return {
            "window": window.key,
            "status": "would_finalize",
            "trade_date": trade_date,
            "cutoff": "21:00 Asia/Shanghai",
        }
    result = run_command(
        [
            sys.executable,
            "scripts/run_daily_macro_close.py",
            "--date",
            trade_date,
            "--storage-root",
            str(storage_root),
        ],
        env=env,
    )
    return {"window": window.key, **result}


def execute(args: argparse.Namespace) -> dict[str, Any]:
    now = resolve_now(args.at)
    windows = due_windows(now, only=args.only)
    env = os.environ.copy()
    env.setdefault("no_proxy", "127.0.0.1,localhost,::1")
    env.setdefault("UV_CACHE_DIR", "/tmp/uv-cache")
    env["FINANCE_AGENT_FORCE_LIVE_LLM"] = "1"
    results = []
    for window in windows:
        if window.source == "jin10":
            results.append(
                scan_jin10(
                    window,
                    now=now,
                    external_root=Path(args.external_root).expanduser(),
                    storage_root=Path(args.storage_root),
                    dry_run=args.dry_run,
                    env=env,
                )
            )
        elif window.source == "cme":
            results.append(
                scan_cme(
                    window,
                    now=now,
                    raw_root=Path(args.raw_root),
                    storage_root=Path(args.storage_root),
                    dry_run=args.dry_run,
                    env=env,
                )
            )
        else:
            results.append(
                scan_daily_macro_close(
                    window,
                    now=now,
                    storage_root=Path(args.storage_root),
                    dry_run=args.dry_run,
                    env=env,
                )
            )
    return {
        "status": "outside_window" if not windows else "ok",
        "at": now.isoformat(),
        "dry_run": args.dry_run,
        "due_windows": [
            asdict(window) | {"start": window.start.isoformat(), "end": window.end.isoformat()} for window in windows
        ],
        "results": results,
    }


def main() -> int:
    args = parse_args()
    lock_path = Path(args.lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w", encoding="utf-8") as lock_file:
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(json.dumps({"status": "skipped", "reason": "scan_already_running"}, ensure_ascii=False))
            return 0
        try:
            payload = execute(args)
        except (httpx.HTTPError, subprocess.CalledProcessError, json.JSONDecodeError, KeyError, ValueError) as exc:
            print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False))
            return 1
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
