from __future__ import annotations

from types import SimpleNamespace

from apps.collectors.jin10.fetcher import Jin10FetchedReport
from scripts.fetch_jin10_report import (
    _apply_category_override,
    _apply_report_type_override,
    _is_applicable_daily_report,
    _resolve_listing_category,
    _select_listing_reports,
)


def _report(
    *,
    title: str = "黄金周一面临惯性下探的风险",
    category: str = "报告",
    report_type: str = "daily",
) -> Jin10FetchedReport:
    return Jin10FetchedReport(
        article_id="221333",
        date="2026-06-07",
        title=title,
        category=category,
        report_type=report_type,
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


def test_apply_report_type_override_preserves_inferred_type_when_not_explicit() -> None:
    report = _apply_report_type_override(_report(category="黄金周报", report_type="weekly"), None)

    assert report.report_type == "weekly"
    assert report.category == "黄金周报"


def test_apply_category_override_uses_requested_non_daily_category_code() -> None:
    report = _apply_category_override(_report(title="黄金上方看涨总增持逾千手", category="金银报告", report_type="daily"), "274")

    assert report.report_type == "positioning"
    assert report.category == "持仓报告"


def test_apply_category_override_uses_market_observation_category_code() -> None:
    report = _apply_category_override(
        _report(title="VIP每日市场观察：市场赔率表提示降息预期升温", category="报告", report_type="daily"),
        "458",
    )

    assert report.report_type == "market_observation"
    assert report.category == "市场观察"


def test_apply_category_override_uses_master_review_category_code() -> None:
    report = _apply_category_override(
        _report(title="周末·大师复盘：全球资产交易线索", category="报告", report_type="daily"),
        "786",
    )

    assert report.report_type == "research"
    assert report.category == "周末·大师复盘"
    assert report.series == "master_review"
    assert report.subcategory == "master_review"


def test_is_applicable_daily_report_accepts_only_main_gold_daily_report() -> None:
    assert _is_applicable_daily_report(_report(title="美联储开启政策新周期", category="金银报告")) is True
    assert _is_applicable_daily_report(_report(title="金价下一站在哪？｜黄金头条", category="报告")) is False
    assert _is_applicable_daily_report(_report(title="一图读懂美联储利率决议丨财料", category="金银报告")) is False
    assert _is_applicable_daily_report(_report(title="某投行金评：黄金走势", category="金银报告")) is False
    assert _is_applicable_daily_report(_report(title="一周热榜精选：弱非农下加息押注退潮", category="金银报告")) is False
    assert _is_applicable_daily_report(_report(title="普通报告但分类不对", category="报告")) is False
    assert (
        _is_applicable_daily_report(
            _report(title="新闻交易员：拥挤交易在漏风", category="金银报告", report_type="research")
        )
        is False
    )
    assert (
        _is_applicable_daily_report(
            _report(title="VIP每日市场观察：黄金等待确认", category="金银报告", report_type="market_observation")
        )
        is False
    )


def test_resolve_listing_category_preserves_non_daily_category_without_report_type_override() -> None:
    assert _resolve_listing_category(category="274", report_type=None, article_id=None) == "274"
    assert _resolve_listing_category(category="301", report_type=None, article_id=None) == "301"
    assert _resolve_listing_category(category="272", report_type=None, article_id=None) == "272"
    assert _resolve_listing_category(category="271", report_type=None, article_id=None) == "271"
    assert _resolve_listing_category(category="458", report_type=None, article_id=None) == "458"
    assert _resolve_listing_category(category="786", report_type=None, article_id=None) == "786"
    assert _resolve_listing_category(category="274", report_type="weekly", article_id=None) == "536"


def test_select_listing_reports_collects_recent_market_observation_reports_up_to_limit() -> None:
    entries = [
        SimpleNamespace(article_id="224001"),
        SimpleNamespace(article_id="224000"),
        SimpleNamespace(article_id="223999"),
        SimpleNamespace(article_id="223998"),
    ]
    reports_by_id = {
        "224001": _report(title="普通 VIP 研究", category="报告", report_type="daily"),
        "224000": _report(title="VIP每日市场观察：市场赔率表提示降息预期升温", category="报告", report_type="daily"),
        "223999": _report(title="市场赔率表：美元与黄金情绪分化", category="报告", report_type="daily"),
        "223998": _report(title="VIP每日市场观察：非农前风险偏好降温", category="报告", report_type="daily"),
    }

    selected = _select_listing_reports(
        entries,
        fetch_report=lambda entry: reports_by_id[entry.article_id],
        category="458",
        report_type=None,
        max_reports=2,
    )

    assert [item.title for item in selected] == [
        "VIP每日市场观察：市场赔率表提示降息预期升温",
        "市场赔率表：美元与黄金情绪分化",
    ]
    assert [item.report_type for item in selected] == ["market_observation", "market_observation"]
