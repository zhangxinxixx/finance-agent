from __future__ import annotations

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
    assert "Gamma Zero 暂无" in payload["options_alignment"]


def test_integrated_analysis_orders_confirmation_levels_from_near_to_far() -> None:
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
        market_tickers={"tickers": {"xauusd": {"price": 4033.0}}},
        gold_macro_overview=None,
        agent_summary={},
        composite_analysis={"status": "partial", "trade_date": "2026-07-16"},
        source_trace=[],
    )

    assert payload is not None
    assert "以 4,144.6/4,265 作为修复升级确认" in payload["trade_implication"]
    assert any("4,144.6/4,265 确认区" in item for item in payload["trigger_upgrade"])
    assert any("4,144.6/4,265" in item for item in payload["invalidation"])


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
        market_tickers={"tickers": {"xauusd": {"price": 3980.2}}},
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
    assert "短线承接验证失败" in payload["options_alignment"]
    assert "区间修复条件失效" in payload["trade_implication"]
    assert "守住支撑但" not in payload["trade_implication"]
    assert any("重新收复 4,015/4,010" in item for item in payload["trigger_upgrade"])
    assert any("维持在 4,015/4,010 支撑带下方" in item for item in payload["trigger_downgrade"])
    assert any("已有效跌破 4,010" in item for item in payload["invalidation"])
    assert payload["quick_supports"] == [
        {
            "level": 3990.0,
            "label": "CME 快支撑",
            "source": "cme_options",
            "source_label": "CME",
            "trade_date": "2026-07-15",
            "timeframe": None,
            "basis": "CME 期权快照第三档支撑",
            "status": "broken",
            "source_ref": "GET /api/options/snapshot",
        },
        {
            "level": 3944.71,
            "label": "Jin10 近端防线",
            "source": "jin10_daily_report",
            "source_label": "Jin10",
            "trade_date": "2026-07-17",
            "timeframe": "4H",
            "basis": "4小时图年内低点，是4000美元失守后的近端保卫位。",
            "status": "active",
            "source_ref": "storage/outputs/jin10/2026-07-17/224807/agent_analysis_report.json",
        },
    ]


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
