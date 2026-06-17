from __future__ import annotations

from apps.collectors.jin10.fetcher import Jin10FetchedReport
from scripts.fetch_jin10_report import _apply_report_type_override


def _report() -> Jin10FetchedReport:
    return Jin10FetchedReport(
        article_id="221333",
        date="2026-06-07",
        title="黄金周一面临惯性下探的风险",
        category="报告",
        report_type="daily",
        source_url="https://svip.jin10.com/news/221333",
        report_markdown="# report",
        raw_html="<html></html>",
        image_urls=[],
        fetched_at="2026-06-08T00:00:00+00:00",
    )


def test_apply_report_type_override_for_explicit_weekly_article() -> None:
    report = _apply_report_type_override(_report(), "weekly")

    assert report.report_type == "weekly"
    assert report.category == "黄金周报"


def test_apply_report_type_override_for_explicit_daily_article() -> None:
    report = _apply_report_type_override(_report(), "daily")

    assert report.report_type == "daily"
    assert report.category == "金银报告"
