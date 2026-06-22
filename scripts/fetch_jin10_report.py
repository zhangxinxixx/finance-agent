from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

from apps.collectors.jin10.fetcher import (
    fetch_category_entries,
    fetch_svip_report,
    fetch_svip_report_via_browser_profile,
    write_external_report,
)

DEFAULT_JIN10_BROWSER_PROFILE = Path("/home/zxx/.hermes/jin10_browser_profile")


def _fetch_report(article_id: str, args: argparse.Namespace, client: httpx.Client):
    """根据参数选择 browser profile 或 cookie 模式拉取报告。"""
    if args.browser_profile:
        return fetch_svip_report_via_browser_profile(
            article_id=article_id,
            user_data_dir=args.browser_profile,
        )
    return fetch_svip_report(article_id=article_id, client=client, cookie=os.getenv(args.cookie_env))


def _apply_report_type_override(report, report_type: str):
    if report_type == "weekly":
        return replace(report, report_type="weekly", category="黄金周报")
    if report_type == "daily":
        return replace(report, report_type="daily", category="金银报告")
    return report


_JIN10_NON_REPORT_MARKERS = ("黄金头条", "投行金评", "财料")


def _is_applicable_daily_report(report) -> bool:
    title = report.title or ""
    if any(marker in title for marker in _JIN10_NON_REPORT_MARKERS):
        return False
    return report.category == "金银报告"


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch latest Jin10 VIP report into external report layout.")
    parser.add_argument("--article-id", help="Specific Jin10 article id to fetch.")
    parser.add_argument("--category", default="270", help="Jin10 category code, default 270 (日报). Use 536 for 周报.")
    parser.add_argument("--report-type", default="daily", choices=("daily", "weekly"),
                        help="日报(daily, category 270) 或 周报(weekly, category 536). 设定此参数会覆盖 --category.")
    parser.add_argument("--external-root", default="~/jin10-reports", help="Output root for external report layout.")
    parser.add_argument("--cookie-env", default="JIN10_SVIP_COOKIE", help="Cookie env var for VIP detail access.")
    default_browser_profile = os.getenv("JIN10_BROWSER_PROFILE") or (
        str(DEFAULT_JIN10_BROWSER_PROFILE) if DEFAULT_JIN10_BROWSER_PROFILE.exists() else None
    )
    parser.add_argument(
        "--browser-profile",
        default=default_browser_profile,
        help="Chromium user data dir with Jin10 login session. Defaults to JIN10_BROWSER_PROFILE or the Hermes Jin10 profile.",
    )
    args = parser.parse_args()

    # --report-type 覆盖 --category
    if args.report_type and not args.article_id:
        if args.report_type == "weekly":
            args.category = "536"
        else:
            args.category = "270"

    discovered: list = []
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        if args.article_id:
            # 指定文章 ID，直接抓取
            report = _fetch_report(args.article_id, args, client)
            report = _apply_report_type_override(report, args.report_type)
        else:
            discovered = fetch_category_entries(category_code=args.category, client=client)
            if not discovered:
                category_name = "周报(536)" if args.category == "536" else "日报(270)"
                raise RuntimeError(f"No Jin10 {category_name} entries found.")

            # 日报模式：遍历列表，跳过黄金头条/投行金评
            report = None
            for entry in discovered:
                candidate = _fetch_report(entry.article_id, args, client)
                if args.report_type == "daily":
                    if not _is_applicable_daily_report(candidate):
                        continue
                report = _apply_report_type_override(candidate, args.report_type)
                break

            if report is None:
                raise RuntimeError("No applicable report found in category listing")

        report_dir = write_external_report(report, external_root=args.external_root, client=client)

    print(
        json.dumps(
            {
                "article_id": report.article_id,
                "date": report.date,
                "title": report.title,
                "report_type": report.report_type,
                "category": report.category,
                "source_url": report.source_url,
                "report_dir": str(report_dir),
                "discovered_count": len(discovered),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
