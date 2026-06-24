from __future__ import annotations

from apps.features.news.relevance_gate import evaluate_news_relevance


def test_hormuz_oil_gold_message_is_high_value_candidate() -> None:
    decision = evaluate_news_relevance(
        "霍尔木兹通行量下降，原油供应风险推升通胀预期，黄金避险需求升温",
        links=["https://news.jin10.com/detail/1"],
        source_marker="来自金十数据APP重要推送",
    )

    assert decision.decision == "high_value"
    assert decision.event_type_hint == "hormuz_risk"
    assert {"XAUUSD", "WTI", "Brent", "DXY"} <= set(decision.asset_tags)
    assert decision.need_detail_fetch is True
    assert decision.need_verification is True
    assert "geo_risk" in decision.reasons


def test_fed_inflation_message_enters_candidate_stream() -> None:
    decision = evaluate_news_relevance("美联储官员称通胀仍偏高，市场下调降息预期")

    assert decision.decision in {"candidate", "high_value"}
    assert decision.event_type_hint in {"fed_hawkish", "fed_dovish", "macro_watchlist"}
    assert {"XAUUSD", "DXY", "US02Y", "US10Y"} <= set(decision.asset_tags)


def test_unrelated_message_is_rejected() -> None:
    decision = evaluate_news_relevance("体育赛事门票销售火爆，本地消费热情回升")

    assert decision.decision == "reject"
    assert decision.score < 0.2
    assert decision.asset_tags == []
    assert decision.need_detail_fetch is False


def test_source_marker_without_market_keywords_is_archive_only() -> None:
    decision = evaluate_news_relevance("点击查看详情 来自金十数据APP重要推送", source_marker="来自金十数据APP重要推送")

    assert decision.decision == "archive_only"
    assert decision.need_verification is True
