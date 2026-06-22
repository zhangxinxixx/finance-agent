from __future__ import annotations

from apps.collectors.jin10.fetcher import Jin10FetchedReport
from scripts.fetch_jin10_report import _apply_report_type_override, _is_applicable_daily_report


def _report(*, title: str = "黄金周一面临惯性下探的风险", category: str = "报告") -> Jin10FetchedReport:
    return Jin10FetchedReport(
        article_id="221333",
        date="2026-06-07",
        title=title,
        category=category,
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


def test_is_applicable_daily_report_accepts_only_main_gold_daily_report() -> None:
    assert _is_applicable_daily_report(_report(title="美联储开启政策新周期", category="金银报告")) is True
    assert _is_applicable_daily_report(_report(title="金价下一站在哪？｜黄金头条", category="报告")) is False
    assert _is_applicable_daily_report(_report(title="一图读懂美联储利率决议丨财料", category="金银报告")) is False
    assert _is_applicable_daily_report(_report(title="某投行金评：黄金走势", category="金银报告")) is False
    assert _is_applicable_daily_report(_report(title="普通报告但分类不对", category="报告")) is False
