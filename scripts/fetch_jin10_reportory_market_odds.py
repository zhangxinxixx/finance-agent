from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.collectors.jin10.reportory import (  # noqa: E402
    fetch_reportory_market_odds_via_browser_profile,
    write_reportory_market_odds_report,
)


DEFAULT_BROWSER_PROFILE = (Path.home() / ".config" / "finance-agent" / "jin10-browser")


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch a Jin10 Reportory market-odds report.")
    parser.add_argument("--url", required=True)
    parser.add_argument("--published-at")
    parser.add_argument("--title")
    parser.add_argument("--external-root", default="~/jin10-reports")
    parser.add_argument(
        "--browser-profile",
        default=os.getenv("JIN10_BROWSER_PROFILE") or str(DEFAULT_BROWSER_PROFILE),
    )
    args = parser.parse_args()

    report = fetch_reportory_market_odds_via_browser_profile(
        source_url=args.url,
        user_data_dir=args.browser_profile,
        title=args.title,
        published_at=args.published_at,
    )
    report_dir = write_reportory_market_odds_report(report, external_root=args.external_root)
    print(
        json.dumps(
            {
                "article_id": report.report_id,
                "date": report.report_date,
                "title": report.title,
                "published_at": report.published_at,
                "report_type": "market_observation",
                "category": "市场观察",
                "source_url": report.source_url,
                "report_dir": str(report_dir),
                "card_count": len(report.card_images),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
