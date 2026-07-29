from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

from apps.collectors.jin10.fetcher import (
    fetch_category_entries,
    fetch_svip_report,
    fetch_svip_report_via_browser_profile,
)
from apps.collectors.jin10.reportory import (
    fetch_reportory_daily_gold_entries,
    reportory_daily_gold_report_date,
)

DEFAULT_JIN10_BROWSER_PROFILE = Path(
    os.getenv("JIN10_BROWSER_PROFILE", "~/.finance-agent/jin10_browser_profile")
).expanduser()
_JIN10_NON_REPORT_SUFFIXES = ("黄金头条", "投行金评")


def _fetch_report(article_id: str, browser_profile: str | None, client: httpx.Client):
    if browser_profile:
        return fetch_svip_report_via_browser_profile(article_id=article_id, user_data_dir=browser_profile)
    return fetch_svip_report(article_id=article_id, client=client, cookie=os.getenv("JIN10_SVIP_COOKIE"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Find Jin10 daily report article ids for target dates.")
    parser.add_argument("--dates", nargs="+", required=True, help="Target dates like 2026-06-03 2026-06-04")
    parser.add_argument("--category", default="270", help="Jin10 category code, default 270")
    parser.add_argument("--limit", type=int, default=20, help="Max category entries to inspect")
    default_browser_profile = os.getenv("JIN10_BROWSER_PROFILE") or (
        str(DEFAULT_JIN10_BROWSER_PROFILE) if DEFAULT_JIN10_BROWSER_PROFILE.exists() else None
    )
    parser.add_argument("--browser-profile", default=default_browser_profile)
    args = parser.parse_args()

    targets = set(args.dates)
    results: dict[str, dict[str, str]] = {}
    inspected: list[dict[str, str]] = []
    discovery_errors: list[dict[str, str]] = []
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        try:
            reportory_entries = fetch_reportory_daily_gold_entries(client=client)[: args.limit]
        except Exception as exc:
            reportory_entries = []
            discovery_errors.append({"source": "reportory_daily_gold", "error": str(exc)})
        for entry in reportory_entries:
            report_date = reportory_daily_gold_report_date(entry.source_url)
            inspected.append(
                {
                    "article_id": entry.article_id,
                    "date": report_date,
                    "title": entry.title,
                    "report_type": "daily",
                    "category": "金银报告",
                    "source_url": entry.source_url,
                }
            )
            if report_date in targets and report_date not in results:
                results[report_date] = {
                    "article_id": entry.article_id,
                    "title": entry.title,
                    "category": "金银报告",
                    "report_type": "daily",
                    "source_url": entry.source_url,
                    "published_at": str(entry.published_at or ""),
                }

        entries = (
            []
            if targets.issubset(results.keys())
            else fetch_category_entries(category_code=args.category, client=client)[: args.limit]
        )
        for entry in entries:
            report = _fetch_report(entry.article_id, args.browser_profile, client)
            inspected.append(
                {
                    "article_id": report.article_id,
                    "date": report.date,
                    "title": report.title,
                    "report_type": report.report_type,
                    "category": report.category,
                    "source_url": report.source_url,
                }
            )
            if any(token in report.title for token in _JIN10_NON_REPORT_SUFFIXES):
                continue
            if report.report_type != "daily":
                continue
            if report.date in targets and report.date not in results:
                results[report.date] = {
                    "article_id": report.article_id,
                    "title": report.title,
                    "category": report.category,
                    "report_type": report.report_type,
                    "source_url": report.source_url,
                    "published_at": str(entry.published_at or ""),
                }
            if targets.issubset(results.keys()):
                break

    print(
        json.dumps(
            {
                "targets": sorted(targets),
                "results": results,
                "inspected": inspected,
                "discovery_errors": discovery_errors,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
