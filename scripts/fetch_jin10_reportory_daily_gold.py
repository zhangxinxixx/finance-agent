from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.collectors.jin10.reportory import (  # noqa: E402
    fetch_reportory_daily_gold_via_browser_profile,
    reportory_daily_gold_report_id,
    write_reportory_daily_gold_report,
)


DEFAULT_BROWSER_PROFILE = Path(
    os.getenv("JIN10_BROWSER_PROFILE", "~/.finance-agent/jin10_browser_profile")
).expanduser()


def _validated_directory(value: str, *, label: str, must_exist: bool) -> Path:
    path = Path(value).expanduser()
    if must_exist and not path.is_dir():
        raise ValueError(f"{label}_not_directory: {path}")
    if path.exists() and not path.is_dir():
        raise ValueError(f"{label}_not_directory: {path}")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch a Jin10 Reportory daily gold-silver report.")
    parser.add_argument("--url", required=True)
    parser.add_argument("--published-at")
    parser.add_argument("--title")
    parser.add_argument("--external-root", default="~/jin10-reports")
    parser.add_argument(
        "--browser-profile",
        default=(str(DEFAULT_BROWSER_PROFILE) if DEFAULT_BROWSER_PROFILE.exists() else None),
    )
    args = parser.parse_args()
    try:
        reportory_daily_gold_report_id(args.url)
        if not args.browser_profile:
            raise ValueError(
                "browser_profile_required: pass --browser-profile or set JIN10_BROWSER_PROFILE"
            )
        browser_profile = _validated_directory(args.browser_profile, label="browser_profile", must_exist=True)
        external_root = _validated_directory(args.external_root, label="external_root", must_exist=False)
    except ValueError as exc:
        parser.error(str(exc))

    report = fetch_reportory_daily_gold_via_browser_profile(
        source_url=args.url,
        user_data_dir=browser_profile,
        title=args.title,
        published_at=args.published_at,
    )
    report_dir = write_reportory_daily_gold_report(report, external_root=external_root)
    print(
        json.dumps(
            {
                "article_id": report.report_id,
                "date": report.report_date,
                "title": report.title,
                "published_at": report.published_at,
                "report_type": "daily",
                "category": "金银报告",
                "source_url": report.source_url,
                "report_dir": str(report_dir),
                "page_count": len(report.page_images),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
