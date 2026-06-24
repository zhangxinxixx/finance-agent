from __future__ import annotations

from apps.collectors.jin10.articles import HIGH_VALUE_XNEWS_CATEGORIES


def test_high_value_xnews_categories_include_daily_entry_points() -> None:
    assert HIGH_VALUE_XNEWS_CATEGORIES["30"]["label"] == "金十早餐"
    assert HIGH_VALUE_XNEWS_CATEGORIES["53"]["label"] == "热点头条"
    assert HIGH_VALUE_XNEWS_CATEGORIES["31"]["label"] == "精选分析"
    assert HIGH_VALUE_XNEWS_CATEGORIES["58"]["label"] == "财料"
    assert HIGH_VALUE_XNEWS_CATEGORIES["421"]["kind"] == "topic"
