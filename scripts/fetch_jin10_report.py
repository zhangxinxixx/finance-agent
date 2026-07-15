from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

from apps.collectors.jin10.fetcher import (
    fetch_category_entries,
    fetch_svip_report,
    fetch_svip_report_via_browser_profile,
    write_external_report,
)
from apps.collectors.jin10.classifier import classify_jin10_report

DEFAULT_JIN10_BROWSER_PROFILE = Path(
    os.getenv("JIN10_BROWSER_PROFILE", "~/.finance-agent/jin10_browser_profile")
).expanduser()


def _fetch_report(article_id: str, args: argparse.Namespace, client: httpx.Client):
    """根据参数选择 browser profile 或 cookie 模式拉取报告。"""
    if args.browser_profile:
        return fetch_svip_report_via_browser_profile(
            article_id=article_id,
            user_data_dir=args.browser_profile,
        )
    return fetch_svip_report(article_id=article_id, client=client, cookie=os.getenv(args.cookie_env))


def _apply_report_type_override(report, report_type: str | None):
    if report_type is None:
        return report
    if report_type == "weekly":
        return replace(report, report_type="weekly", category="黄金周报")
    if report_type == "daily":
        return replace(report, report_type="daily", category="金银报告")
    return report


def _apply_category_override(report, category_code: str):
    classification = classify_jin10_report(category_code=category_code, title=report.title, report_type=report.report_type)
    if classification.category_code not in {"271", "272", "274", "301", "458", "786"}:
        return report
    return replace(
        report,
        report_type=classification.report_type,
        category=classification.category,
        series=classification.series,
        subcategory=classification.subcategory,
    )


_JIN10_NON_REPORT_MARKERS = ("黄金头条", "投行金评", "财料", "一周热榜精选")


def _is_applicable_daily_report(report) -> bool:
    title = report.title or ""
    if any(marker in title for marker in _JIN10_NON_REPORT_MARKERS):
        return False
    return report.category == "金银报告" and report.report_type == "daily"


def _is_applicable_market_observation_report(report) -> bool:
    classification = classify_jin10_report(
        category_code="458",
        category=report.category,
        title=report.title,
        report_type=report.report_type,
    )
    return classification.report_type == "market_observation"


def _is_applicable_report_for_category(report, *, category: str, report_type: str | None) -> bool:
    if category == "270" and report_type in {None, "daily"}:
        return _is_applicable_daily_report(report)
    if category == "458":
        return _is_applicable_market_observation_report(report)
    return True


def _select_listing_reports(
    entries: list[Any],
    *,
    fetch_report: Callable[[Any], Any],
    category: str,
    report_type: str | None,
    max_reports: int,
) -> list[Any]:
    selected: list[Any] = []
    target_count = max(1, max_reports)
    for entry in entries:
        candidate = fetch_report(entry)
        if not _is_applicable_report_for_category(candidate, category=category, report_type=report_type):
            continue
        candidate = _apply_category_override(candidate, category)
        selected.append(_apply_report_type_override(candidate, report_type))
        if len(selected) >= target_count:
            break
    return selected


def _resolve_listing_category(*, category: str, report_type: str | None, article_id: str | None) -> str:
    if article_id:
        return category
    if report_type == "weekly":
        return "536"
    if report_type == "daily":
        return "270"
    return category


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch latest Jin10 VIP report into external report layout.")
    parser.add_argument("--article-id", help="Specific Jin10 article id to fetch.")
    parser.add_argument("--category", default="270", help="Jin10 category code, default 270 (日报). Use 536 for 周报.")
    parser.add_argument("--report-type", default=None, choices=("daily", "weekly"),
                        help="日报(daily, category 270) 或 周报(weekly, category 536). 设定此参数会覆盖 --category.")
    parser.add_argument("--max-reports", type=int, default=1, help="Fetch up to N matching reports from category listing.")
    parser.add_argument("--external-root", default="~/jin10-reports", help="Output root for external report layout.")
    parser.add_argument("--cookie-env", default="JIN10_SVIP_COOKIE", help="Cookie env var for VIP detail access.")
    default_browser_profile = os.getenv("JIN10_BROWSER_PROFILE") or (
        str(DEFAULT_JIN10_BROWSER_PROFILE) if DEFAULT_JIN10_BROWSER_PROFILE.exists() else None
    )
    parser.add_argument(
        "--browser-profile",
        default=default_browser_profile,
        help="Chromium user data dir with Jin10 login session. Defaults to JIN10_BROWSER_PROFILE.",
    )
    args = parser.parse_args()

    args.category = _resolve_listing_category(category=args.category, report_type=args.report_type, article_id=args.article_id)

    discovered: list = []
    reports: list = []
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        if args.article_id:
            # 指定文章 ID，直接抓取
            report = _fetch_report(args.article_id, args, client)
            report = _apply_category_override(report, args.category)
            report = _apply_report_type_override(report, args.report_type)
            reports = [report]
        else:
            discovered = fetch_category_entries(category_code=args.category, client=client)
            if not discovered:
                category_name = "周报(536)" if args.category == "536" else "日报(270)"
                raise RuntimeError(f"No Jin10 {category_name} entries found.")

            reports = _select_listing_reports(
                discovered,
                fetch_report=lambda entry: _fetch_report(entry.article_id, args, client),
                category=args.category,
                report_type=args.report_type,
                max_reports=args.max_reports,
            )

            if not reports:
                raise RuntimeError("No applicable report found in category listing")

        written = [
            {
                "report": report,
                "report_dir": write_external_report(report, external_root=args.external_root, client=client),
            }
            for report in reports
        ]

    first = written[0]
    report = first["report"]
    report_dir = first["report_dir"]

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
                "fetched_count": len(written),
                "reports": [
                    {
                        "article_id": item["report"].article_id,
                        "date": item["report"].date,
                        "title": item["report"].title,
                        "report_type": item["report"].report_type,
                        "category": item["report"].category,
                        "source_url": item["report"].source_url,
                        "report_dir": str(item["report_dir"]),
                    }
                    for item in written
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
