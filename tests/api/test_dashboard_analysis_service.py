from __future__ import annotations

from copy import deepcopy

import pytest

from apps.api.services import dashboard_analysis_service as service
from apps.api.services.dashboard_analysis_service import build_dashboard_integrated_analysis


def test_integrated_analysis_adds_macro_causality_and_uses_prelim_options() -> None:
    payload = build_dashboard_integrated_analysis(
        macro_snapshot={
            "as_of": "2026-07-14",
            "indicators": {
                "ON_RRP_USAGE": _indicator("ON_RRP_USAGE", 0.8, weekly_change=-1.9, unit="B"),
                "TGA": _indicator("TGA", 738.27, weekly_change=-38.57, unit="B"),
                "RESERVES": _indicator("RESERVES", 3098.91, weekly_change=132.01, unit="B"),
                "SOFR": _indicator("SOFR", 3.55, weekly_change=-0.09, unit="%"),
                "EFFR": _indicator("EFFR", 3.62, weekly_change=-0.01, unit="%"),
                "IORB": _indicator("IORB", 3.65, weekly_change=0.0, unit="%"),
                "US02Y": _indicator("US02Y", 4.21, weekly_change=0.07, unit="%"),
                "US10Y": _indicator("US10Y", 4.56, weekly_change=0.07, unit="%"),
                "BREAKEVEN_10Y": _indicator("BREAKEVEN_10Y", 2.26, weekly_change=0.02, unit="%"),
                "REAL_10Y": _indicator("REAL_10Y", 2.32, weekly_change=0.06, monthly_change=0.11, unit="%"),
                "DXY": _indicator("DXY", 101.13, unit="index"),
            },
            "unavailable_symbols": [],
            "source_refs": {},
        },
        options_snapshot={
            "trade_date": "2026-07-13",
            "snapshot_id": "options:2026-07-13:test",
            "data_source": {"status": "PRELIM", "source_url": "https://cme.test/bulletin.pdf"},
            "intent": {"type": "I4_trend_launch", "score": 0.46},
            "gex": {"netgex_aggregate": {"gamma_zero": {"price": 4148.7}}},
            "support_resistance": {
                "support": [{"strike": 3995}, {"strike": 3985}],
                "resistance": [{"strike": 4140}],
            },
        },
        market_tickers={"tickers": {"xauusd": {"price": 4019.0}}},
        gold_macro_overview={
            "as_of": "2026-07-14T00:00:00Z",
            "phase": "weak_repair_watch",
            "net_bias": "neutral_bearish",
            "dominant_mainline": "fed_policy_path",
            "driver_conflict": {
                "dominant_driver": "higher_for_longer_rate_pressure",
                "explanation": "避险支撑与利率压力并存。",
            },
            "analysis_readiness": {"status": "partial", "ready_count": 3, "total_count": 9, "next_gaps": []},
        },
        agent_summary={"synthesis": {"confidence": 0.47}},
        composite_analysis={
            "status": "available",
            "trade_date": "2026-07-14",
            "run_id": "composite-run",
            "degraded_newer_reports": [],
        },
        source_trace=[],
    )

    assert payload is not None
    assert payload["overall_bias"] == "中性偏空"
    assert payload["macro_regime"] == "过渡释放态"
    assert payload["confidence"] == 0.47
    assert payload["run_id"] == "composite-run"
    assert "名义利率快于通胀预期上行" in payload["rates_state"]
    assert "实际利率抬升会提高持有黄金的机会成本" in payload["rates_state"]
    assert "最新 PRELIM 数据，可直接参与结构分析" in payload["options_alignment"]
    assert "3,995/3,985" in payload["options_alignment"]
    assert "4,140" in payload["options_alignment"]
    assert "4,148.7" in payload["options_alignment"]
    assert "等待 FINAL" not in payload["options_alignment"]
    assert "高利率维持更久" in payload["reasoning"]
    assert any("3,995/3,985" in item for item in payload["trigger_downgrade"])
    assert any("PRELIM" in item for item in payload["risks"])


def test_integrated_analysis_keeps_missing_inputs_explicit() -> None:
    payload = build_dashboard_integrated_analysis(
        macro_snapshot={"as_of": "2026-07-14", "indicators": {}, "unavailable_symbols": ["DXY"], "source_refs": {}},
        options_snapshot=None,
        market_tickers={"tickers": {}},
        gold_macro_overview={
            "analysis_readiness": {
                "status": "partial",
                "ready_count": 0,
                "total_count": 9,
                "next_gaps": ["实际利率与美元缺少数据源接入：dxy"],
            }
        },
        agent_summary={},
        composite_analysis={"status": "partial", "trade_date": "2026-07-14", "degraded_newer_reports": []},
        source_trace=[],
    )

    assert payload is not None
    assert "DXY" in payload["missing_inputs"]
    assert "实际利率与美元缺少数据源接入：dxy" in payload["missing_inputs"]
    assert payload["options_alignment"] == "CME 期权结构不可用，当前综合判断不使用期权确认。"


def _rate_analysis(macro_snapshot):
    return build_dashboard_integrated_analysis(
        macro_snapshot=macro_snapshot, options_snapshot=None, market_tickers={},
        gold_macro_overview=None, agent_summary={}, composite_analysis={}, source_trace=[],
    )


def test_archived_rate_aliases_preserve_facts_and_match_canonical_analysis():
    indicators = {
        "US10Y": _indicator("US10Y", 4.56, weekly_change=0.07, unit="%"),
        "REAL10Y": {**_indicator("REAL10Y", 2.68, weekly_change=0.06, monthly_change=0.11, unit="%"),
                    "date": "2026-07-13", "daily_change": 0.01, "source": "official_treasury",
                    "source_url": "https://treasury.test/real-yields"},
        "T10YIE": {**_indicator("T10YIE", 2.26, weekly_change=0.02, unit="%"),
                   "date": "2026-07-10", "daily_change": -0.01, "source": "FRED"},
    }
    snapshot = {"as_of": "2026-07-14", "indicators": indicators,
                "source_refs": {"REAL10Y": {"source": "official_treasury", "date": "2026-07-13"}}}
    original = deepcopy(snapshot)
    canonical = deepcopy(snapshot)
    canonical["indicators"]["REAL_10Y"] = canonical["indicators"].pop("REAL10Y")
    canonical["indicators"]["BREAKEVEN_10Y"] = canonical["indicators"].pop("T10YIE")
    result = _rate_analysis(snapshot)
    assert result == _rate_analysis(canonical)
    assert "10Y 实际利率 2.68%（2026-07-13，周+0.06%）" in result["rates_state"]
    assert "10Y 盈亏平衡通胀 2.26%（周+0.02%）" in result["rates_state"]
    assert "实际利率抬升会提高持有黄金的机会成本" in result["rates_state"]
    conclusion = service._macro_conclusion(snapshot)
    assert "高位压制" in conclusion.reasoning
    assert "REAL_10Y" not in conclusion.missing_inputs
    assert "BREAKEVEN_10Y" not in conclusion.missing_inputs
    normalized = service._normalize_rate_aliases(indicators)
    assert normalized["REAL_10Y"] == indicators["REAL10Y"]
    assert normalized["BREAKEVEN_10Y"] == indicators["T10YIE"]
    assert snapshot == original


@pytest.mark.parametrize("canonical_value", [None, {}, {"value": None, "status": "unavailable"},
                                            {"value": 1.81, "date": "2026-07-09", "weekly_change": -0.08,
                                             "daily_change": -0.02, "monthly_change": -0.1,
                                             "unit": "%", "source": "canonical_source"}])
def test_rate_canonical_values_including_unavailable_block_aliases(canonical_value):
    indicators = {
        "US10Y": _indicator("US10Y", 4.56, weekly_change=0.07, unit="%"),
        "REAL_10Y": deepcopy(canonical_value), "BREAKEVEN_10Y": deepcopy(canonical_value),
        "REAL10Y": _indicator("REAL10Y", 2.68, weekly_change=0.06, unit="%"),
        "T10YIE": _indicator("T10YIE", 2.26, weekly_change=0.02, unit="%"),
    }
    snapshot = {"as_of": "2026-07-14", "indicators": indicators}
    original = deepcopy(snapshot)
    without_aliases = deepcopy(snapshot)
    without_aliases["indicators"].pop("REAL10Y")
    without_aliases["indicators"].pop("T10YIE")
    result = _rate_analysis(snapshot)
    assert result == _rate_analysis(without_aliases)
    assert service._macro_conclusion(snapshot) == service._macro_conclusion(without_aliases)
    normalized = service._normalize_rate_aliases(indicators)
    assert normalized["REAL_10Y"] == canonical_value
    assert normalized["BREAKEVEN_10Y"] == canonical_value
    if not canonical_value or canonical_value.get("value") is None:
        assert "10Y 实际利率 暂无%" in result["rates_state"]
        assert "10Y 盈亏平衡通胀 暂无%" in result["rates_state"]
    else:
        assert "10Y 实际利率 1.81%（2026-07-09，周-0.08%）" in result["rates_state"]
        assert "中期缓和" in service._macro_conclusion(snapshot).reasoning
    assert snapshot == original


def test_integrated_analysis_ignores_malformed_option_levels() -> None:
    payload = build_dashboard_integrated_analysis(
        macro_snapshot=None,
        options_snapshot={
            "trade_date": "2026-07-14",
            "data_source": "invalid",
            "intent": [],
            "gex": {"netgex_aggregate": {"gamma_zero": {"price": "not-a-number"}}},
            "support_resistance": {
                "support": [{"strike": "bad"}, {"strike": "3,995"}, {"strike": 3985}],
                "resistance": "invalid",
            },
        },
        market_tickers={"tickers": {"xauusd": {"price": 4019.0}}},
        gold_macro_overview=None,
        agent_summary={},
        composite_analysis={"status": "partial", "trade_date": "2026-07-14"},
        source_trace=[],
    )

    assert payload is not None
    assert "3,985" in payload["options_alignment"]
    assert "3,995" not in payload["options_alignment"]
    assert "Selected Expiry Window Proxy Gamma Flip 暂无" in payload["options_alignment"]
    assert "GC-XAUUSD 基差" in payload["options_alignment"]
    assert "Gamma Zero" not in payload["options_alignment"]


def test_integrated_analysis_keeps_proxy_flip_out_of_mandatory_confirmation_levels() -> None:
    payload = build_dashboard_integrated_analysis(
        macro_snapshot=None,
        options_snapshot={
            "trade_date": "2026-07-15",
            "data_source": {"status": "PRELIM"},
            "gex": {"netgex_aggregate": {"gamma_zero": {"price": 4144.6}}},
            "support_resistance": {
                "support": [{"strike": 4015}, {"strike": 4010}],
                "resistance": [{"strike": 4265}],
            },
        },
        market_tickers={"tickers": {"xauusd": {"price": 4033.0, "source": "cme_gc_futures"}}},
        gold_macro_overview=None,
        agent_summary={},
        composite_analysis={"status": "partial", "trade_date": "2026-07-16"},
        source_trace=[],
    )

    assert payload is not None
    assert "4,265 作为 GC 阻力观察" in payload["trade_implication"]
    assert "Proxy Flip 不单独构成趋势闸门" in payload["trade_implication"]
    assert any("4,265 阻力" in item for item in payload["trigger_upgrade"])
    assert all("4,144.6/4,265" not in item for item in payload["trigger_upgrade"])
    assert all("4,144.6/4,265" not in item for item in payload["invalidation"])


def test_integrated_analysis_marks_support_as_broken_when_live_price_is_below_band() -> None:
    payload = build_dashboard_integrated_analysis(
        macro_snapshot=None,
        options_snapshot={
            "trade_date": "2026-07-15",
            "data_source": {"status": "FINAL"},
            "gex": {"netgex_aggregate": {"gamma_zero": {"price": 4144.7}}},
            "support_resistance": {
                "support": [{"strike": 4015}, {"strike": 4010}, {"strike": 3990}],
                "resistance": [{"strike": 4265}],
            },
        },
        market_tickers={"tickers": {"xauusd": {"price": 3980.2, "source": "cme_gc_futures"}}},
        gold_macro_overview=None,
        agent_summary={},
        composite_analysis={"status": "stale", "trade_date": "2026-07-16"},
        source_trace=[],
        jin10_analysis={
            "trade_date": "2026-07-17",
            "run_id": "224807",
            "key_levels": [
                {
                    "asset": "黄金｜短中线交易位",
                    "meaning": "4小时图年内低点，是4000美元失守后的近端保卫位。",
                    "source_category": "图表事实",
                    "value": "3944.71美元",
                }
            ],
        },
    )

    assert payload is not None
    assert "已跌破 4,015/4,010 支撑带" in payload["options_alignment"]
    assert "GC 期货结构承接转弱" in payload["options_alignment"]
    assert "GC 结构转弱" in payload["trade_implication"]
    assert any("GC 期货代理价重新收复 4,015/4,010" in item for item in payload["trigger_upgrade"])
    assert any("GC 期货代理价维持在 4,015/4,010 支撑带下方" in item for item in payload["trigger_downgrade"])
    assert any("GC 期货参考价低于 4,010" in item for item in payload["invalidation"])
    assert any("破位仍需收盘与回测确认" in item for item in payload["invalidation"])
    assert all("已有效跌破" not in item for item in payload["invalidation"])
    assert all("结构已失效" not in item for item in payload["invalidation"])
    assert payload["quick_supports"] == [
        {
            "level": 3990.0,
            "label": "CME GC 期货快支撑",
            "source": "cme_options",
            "source_label": "CME",
            "trade_date": "2026-07-15",
            "timeframe": None,
            "basis": "CME 期权快照第三档支撑（GC 期货坐标）",
            "status": "broken",
            "source_ref": "GET /api/options/snapshot",
        },
    ]


def test_jin10_chart_levels_cannot_become_current_support_with_any_quote() -> None:
    kwargs = {
        "macro_snapshot": None,
        "options_snapshot": {
            "trade_date": "2026-07-15",
            "data_source": {"status": "FINAL"},
            "support_resistance": {
                "support": [{"strike": 4015}, {"strike": 4010}],
                "resistance": [],
            },
        },
        "gold_macro_overview": None,
        "agent_summary": {},
        "composite_analysis": {"status": "partial", "trade_date": "2026-07-16"},
        "source_trace": [],
        "jin10_analysis": {
            "trade_date": "2026-07-16",
            "run_id": "spot-source-test",
            "key_levels": [
                {
                    "asset": "黄金｜短中线交易位",
                    "meaning": "4小时图近端防线。",
                    "source_category": "图表事实",
                    "value": "4000美元",
                },
            ],
        },
    }

    unknown = build_dashboard_integrated_analysis(
        **kwargs,
        market_tickers={"tickers": {"xauusd": {"price": 4019.0}}},
    )
    explicit_spot = build_dashboard_integrated_analysis(
        **kwargs,
        market_tickers={
            "tickers": {
                "xauusd": {"price": 4019.0, "source": "twelvedata_xauusd_quote"},
            },
        },
    )

    assert unknown is not None and explicit_spot is not None
    assert unknown["quick_supports"] == []
    assert explicit_spot["quick_supports"] == []


def test_integrated_analysis_uses_relative_real_rate_condition_and_does_not_map_gc_to_spot() -> None:
    payload = build_dashboard_integrated_analysis(
        macro_snapshot={
            "as_of": "2026-09-17",
            "indicators": {
                "REAL_10Y": _indicator("REAL_10Y", 2.41, weekly_change=0.03, unit="%"),
            },
            "unavailable_symbols": [],
            "source_refs": {},
        },
        options_snapshot={
            "trade_date": "2026-09-16",
            "data_source": {"status": "PRELIM"},
            "parameters": {"f_value": 4353.4},
            "gex": {"gamma_flip": {"price": 4390.0}},
            "support_resistance": {
                "support": [{"strike": 4300}],
                "resistance": [{"strike": 4400}],
            },
        },
        market_tickers={
            "tickers": {
                "xauusd": {"price": 4353.4, "source": "cme_gc_futures"},
            },
        },
        gold_macro_overview=None,
        agent_summary={},
        composite_analysis={"status": "partial", "trade_date": "2026-09-17"},
        source_trace=[],
    )

    assert payload is not None
    rendered = " ".join(
        [
            payload["options_alignment"],
            payload["trade_implication"],
            *payload["trigger_upgrade"],
            *payload["trigger_downgrade"],
            *payload["invalidation"],
        ]
    )
    assert "由当前 2.41% 继续上行" in rendered
    assert "向 2.40%" not in rendered
    assert "Gamma Zero" not in rendered
    assert "Proxy Flip 不单独构成趋势闸门" in rendered
    assert "不能映射为 XAUUSD 现货确认" in rendered
    assert "XAUUSD 重新" not in rendered
    assert "出现现货确认" not in rendered


def _indicator(
    symbol: str,
    value: float,
    *,
    weekly_change: float | None = None,
    monthly_change: float | None = None,
    unit: str,
) -> dict[str, object]:
    return {
        "symbol": symbol,
        "date": "2026-07-14",
        "value": value,
        "daily_change": None,
        "weekly_change": weekly_change,
        "monthly_change": monthly_change,
        "label": symbol,
        "unit": unit,
        "direction_note": "",
    }
