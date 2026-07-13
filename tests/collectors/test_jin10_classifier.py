from __future__ import annotations

from apps.collectors.jin10.classifier import classify_jin10_report, resolve_jin10_report_identity


def test_classify_report_families_for_stable_svip_categories() -> None:
    assert classify_jin10_report(category_code="270", title="每日金银报告").report_type == "daily"
    assert classify_jin10_report(category_code="536", title="VIP黄金周报").report_type == "weekly"
    assert classify_jin10_report(category_code="274", title="黄金期权持仓报告").report_type == "positioning"
    assert classify_jin10_report(category_code="301", title="现货黄金点位报告").report_type == "technical_levels"
    assert classify_jin10_report(category_code="272", title="原油报告").report_type == "oil"
    assert classify_jin10_report(category_code="271", title="外汇报告").report_type == "fx"


def test_classify_report_family_from_category_text_when_code_missing() -> None:
    assert classify_jin10_report(category="持仓报告", title="黄金期权持仓报告").report_type == "positioning"
    assert classify_jin10_report(category="点位报告", title="现货黄金点位报告").report_type == "technical_levels"
    assert classify_jin10_report(category="原油报告", title="原油市场日报").report_type == "oil"
    assert classify_jin10_report(category="外汇报告", title="美元指数外汇报告").report_type == "fx"


def test_resolve_report_identity_separates_cover_classification_from_issue_theme() -> None:
    identity = resolve_jin10_report_identity(
        category_code="536",
        category="黄金周报",
        title="黄金短期难以摆脱横盘僵局，期权暗示阶段性底部形成-金十数据VIP",
        report_type="weekly",
        cover_text=(
            "黄金 投资者周报 2026年7月11日\n"
            "黄金短期难以摆脱横盘僵局，期权暗示阶段性底部形成"
        ),
    )

    assert identity["report_type"] == "weekly"
    assert identity["report_family"] == "jin10_weekly_visual"
    assert identity["classification_label"] == "黄金投资者周报"
    assert identity["report_theme"] == "黄金短期难以摆脱横盘僵局，期权暗示阶段性底部形成"
    assert identity["verification_status"] == "confirmed"
    assert {item["source"] for item in identity["evidence"]} == {"listing", "cover"}


def test_resolve_report_identity_marks_unclassified_cover_for_review() -> None:
    identity = resolve_jin10_report_identity(
        category_code="536",
        category="黄金周报",
        title="期权暗示阶段性底部形成-金十数据VIP",
        report_type="weekly",
        cover_text="期权暗示阶段性底部形成\n未来数周大概率区间震荡",
    )

    assert identity["classification_label"] == "黄金投资者周报"
    assert identity["verification_status"] == "needs_review"


def test_classify_market_observation_reports_from_vip_titles() -> None:
    daily_observation = classify_jin10_report(category="VIP智库", title="VIP每日市场观察：黄金等待非农确认")
    odds_table = classify_jin10_report(category="VIP智库", title="市场赔率表：降息概率与黄金风险偏好")
    odds_data_table = classify_jin10_report(category="VIP智库", title="加息跌破半数，黄金赔率变脸｜市场赔率数据表-金十数据VIP")

    assert daily_observation.report_type == "market_observation"
    assert daily_observation.report_family == "jin10_market_observation_report"
    assert daily_observation.asset_scope == "cross_asset"
    assert odds_table.report_type == "market_observation"
    assert odds_table.report_family == "jin10_market_observation_report"
    assert odds_data_table.report_type == "market_observation"
    assert odds_data_table.report_family == "jin10_market_observation_report"


def test_classify_non_daily_gold_articles_as_research_even_under_daily_category() -> None:
    hotlist = classify_jin10_report(
        category_code="270",
        category="金银报告",
        title="一周热榜精选：弱非农下加息押注退潮！大空头警告AI派对结束-金十数据VIP",
    )
    headline = classify_jin10_report(category_code="270", category="金银报告", title="黄金头条：央行买盘观察")

    assert hotlist.report_type == "research"
    assert hotlist.report_family == "jin10_research_report"
    assert headline.report_type == "research"
    assert headline.report_family == "jin10_research_report"


def test_classify_master_review_category_as_research_series() -> None:
    classification = classify_jin10_report(category_code="786", title="周末·大师复盘：全球资产交易线索")

    assert classification.category_code == "786"
    assert classification.category == "周末·大师复盘"
    assert classification.report_type == "research"
    assert classification.report_family == "jin10_research_report"
    assert classification.asset_scope == "cross_asset"
    assert classification.series == "master_review"
    assert classification.subcategory == "master_review"


def test_classify_master_review_from_category_text_when_code_missing() -> None:
    classification = classify_jin10_report(category="周末·大师复盘", title="大师复盘：美元与黄金节奏")

    assert classification.category_code == "786"
    assert classification.category == "周末·大师复盘"
    assert classification.report_type == "research"
    assert classification.series == "master_review"
    assert classification.subcategory == "master_review"


def test_classify_master_review_from_title_when_category_is_generic_report() -> None:
    classification = classify_jin10_report(category="报告", title="非农仅增5.7万，美联储为何不能轻易转鸽？｜大师复盘")

    assert classification.category_code == "786"
    assert classification.category == "周末·大师复盘"
    assert classification.report_type == "research"
    assert classification.series == "master_review"
