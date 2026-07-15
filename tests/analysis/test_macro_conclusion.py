from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

from apps.analysis.agents.schemas import AgentBias, AgentOutput, AgentStatus, DataCategory
from apps.analysis.macro.conclusion import build_macro_conclusion
from apps.analysis.macro.full_report import render_macro_full_report_markdown
from apps.features.macro.snapshot import build_macro_snapshot


def test_current_manual_macro_doc_generates_target_conclusion() -> None:
    snapshot = build_macro_snapshot(_current_doc_points(), as_of="2026-05-08")
    conclusion = build_macro_conclusion(snapshot)
    assert conclusion.market_phase == "transition_release"
    assert conclusion.bias == "中性偏多"
    assert conclusion.quantity_layer == "偏松"
    assert conclusion.price_layer == "钱仍贵"
    assert conclusion.dollar_layer == "顺风"
    assert conclusion.state == "过渡释放态"
    assert conclusion.action == "回踩接多 / 等待"
    assert "不建议在当前环境里直接追高" in conclusion.no_go_actions
    assert conclusion.missing_inputs == []
    markdown = render_macro_full_report_markdown(snapshot, conclusion)
    assert "# XAUUSD 宏观 / 流动性更新（2026-05-08）" in markdown
    assert "今天黄金的宏观环境更接近 **中性偏多**" in markdown
    assert "过渡释放态" in markdown
    assert "XAUUSD 宏观交易引擎" not in markdown
    assert "US10Y - T10YIE" in markdown
    assert "黄金六因子模型" in markdown
    assert "利率曲线 / 2Y-3M利差" in markdown
    assert "回踩接多" in markdown


def test_recent_trade_day_macro_doc_uses_authoritative_transition_phase() -> None:
    snapshot = build_macro_snapshot(_recent_trade_day_points(), as_of="2026-06-26")
    conclusion = build_macro_conclusion(snapshot)

    assert conclusion.market_phase == "transition_release"
    assert conclusion.bias == "中性偏空"
    assert conclusion.quantity_layer == "分裂偏紧"
    assert conclusion.price_layer == "钱仍贵"
    assert conclusion.dollar_layer == "逆风"
    assert conclusion.state == "过渡释放态"
    assert conclusion.action == "等待"
    assert conclusion.action_priority == "主要"
    assert "DXY 跌破 100.8" in conclusion.trigger_upgrade
    assert "10Y 实际利率跌回 2.10% 下方" in conclusion.trigger_upgrade
    assert "DXY 重新上破 101.8" in conclusion.trigger_downgrade
    assert "不在 DXY 101 上方直接追多" in conclusion.no_go_actions
    assert "DXY 当前 101.366" in conclusion.reasoning
    assert "机会成本仍高位压制黄金" in conclusion.reasoning
    assert "准备金周变化 -82.030B" in conclusion.reasoning

    markdown = render_macro_full_report_markdown(snapshot, conclusion)
    assert "过渡释放态" in markdown
    assert "分裂偏紧" in markdown
    assert "过渡释放态下的等待" in markdown
    assert "DXY 跌破 100.8" in markdown
    assert "10Y 实际利率跌回 2.10% 下方" in markdown
    assert "实际收益率 | 高位压制 | 待LLM判断" in markdown
    assert "利率曲线 / 2Y-3M利差" in markdown
    assert "规则预判更接近：**过渡释放态**。" in markdown
    assert "## 系统性风险雷达" in markdown
    assert "## 三路径推演" in markdown
    assert "## 联网补充与系统数据源缺口" not in markdown
    assert "## 数据源" not in markdown
    assert "规则预判方向与动作仅供对照，不是最终结论。" in markdown


def test_trend_tailwind_without_bullish_bias_does_not_create_long_action() -> None:
    snapshot = build_macro_snapshot(_recent_trade_day_points(), as_of="2026-06-26")

    with patch(
        "apps.analysis.macro.conclusion.classify_macro_regime",
        return_value={"market_phase": "trend_tailwind"},
    ):
        conclusion = build_macro_conclusion(snapshot)

    assert conclusion.state == "趋势顺风态"
    assert conclusion.bias == "中性偏空"
    assert conclusion.action == "等待"
    assert conclusion.action_priority == "等待阶段与方向共振"


def test_macro_reasoning_matches_neutral_dollar_layer() -> None:
    points = [
        {
            **point,
            "value": 100.0 if point["symbol"] == "DXY" else point["value"],
        }
        for point in _current_doc_points()
    ]

    snapshot = build_macro_snapshot(points, as_of="2026-05-08")
    conclusion = build_macro_conclusion(snapshot)

    assert conclusion.dollar_layer == "中性"
    assert "美元层为中性" in conclusion.reasoning
    assert "美元对黄金形成顺风" not in conclusion.reasoning


def test_macro_reasoning_matches_neutral_real_rate_layer() -> None:
    points = [
        {
            **point,
            "value": _neutral_real_rate_value(point),
        }
        for point in _current_doc_points()
    ]

    snapshot = build_macro_snapshot(points, as_of="2026-05-08")
    conclusion = build_macro_conclusion(snapshot)

    assert "实际利率层为中性" in conclusion.reasoning
    assert "机会成本中期缓和" not in conclusion.reasoning


def test_macro_full_report_does_not_overstate_neutral_dollar_or_falling_reserves() -> None:
    points = [
        {
            **point,
            "value": _neutral_dollar_and_falling_reserves_value(point),
        }
        for point in _current_doc_points()
    ]

    snapshot = build_macro_snapshot(points, as_of="2026-05-08")
    conclusion = build_macro_conclusion(snapshot)
    markdown = render_macro_full_report_markdown(snapshot, conclusion)

    assert conclusion.dollar_layer == "中性"
    assert snapshot.indicators["RESERVES"].weekly_change < 0
    assert "数量层和美元层偏向支持黄金" not in markdown
    assert "准备金上升" not in markdown


def test_macro_full_report_prefers_llm_output_when_present() -> None:
    snapshot = build_macro_snapshot(_recent_trade_day_points(), as_of="2026-06-26")
    conclusion = build_macro_conclusion(snapshot)
    macro_output = AgentOutput(
        version="1.0",
        agent_name="macro_liquidity_agent",
        module="macro",
        snapshot_id="macro-test",
        input_snapshot_ids={"analysis_snapshot": "macro-test"},
        bias=AgentBias.BEARISH,
        confidence=0.9,
        key_findings=["LLM 正文优先"],
        risk_points=["LLM 风险"],
        watchlist=["DXY"],
        invalid_conditions=[],
        summary="LLM 宏观摘要",
        source_refs=[],
        status=AgentStatus.SUCCESS,
        created_at=datetime.now(timezone.utc),
        market_phase="rate_pressure",
        regime_drivers={"drivers": {"dxy": {"value": 101.366}}},
        data_category=DataCategory.EXTERNAL_OPINION,
        llm_raw_output=(
            "# XAUUSD 宏观交易引擎 v2.1\n\n"
            "## 一句话结论\n\nLLM 正文已接入。\n\n"
            "## 流动性与利率统一数据表\n\n| 重复表 | 不应展示 |\n\n"
            "## 数据源\n\n- 不应展示的来源\n\n"
            "## 风险\n\n保留的风险。"
        ),
    )

    markdown = render_macro_full_report_markdown(snapshot, conclusion, macro_output=macro_output)

    assert "## LLM 宏观分析" in markdown
    assert "LLM 正文已接入" in markdown
    assert markdown.count("## 一句话结论") == 1
    assert "重复表" not in markdown
    assert "不应展示的来源" not in markdown
    assert "保留的风险" in markdown
    assert "## 当前所处环境阶段判断" not in markdown
    assert "## 口径与规则校验" in markdown
    assert "确定性规则预判" in markdown


def test_macro_full_report_degrades_empty_snapshot_without_neutral_conclusion_or_missing_table() -> None:
    snapshot = build_macro_snapshot(
        [],
        as_of="2026-07-21",
        unavailable_symbols=["DGS10", "DXY", "SOFR"],
        source_refs=[{"symbol": "DGS10", "source": "fred", "reason": "network failed"}],
    )
    conclusion = build_macro_conclusion(snapshot)

    markdown = render_macro_full_report_markdown(snapshot, conclusion)

    assert "## 本次报告不可用" in markdown
    assert "没有获得任何有效指标" in markdown
    assert f"缺失指标数：{len(snapshot.unavailable_symbols)}" in markdown
    assert "## 一句话结论" not in markdown
    assert "流动性与利率统一数据表" not in markdown
    assert "中性" not in markdown
    assert "## 数据源" not in markdown


def test_macro_full_report_adds_us03m_and_explains_positive_spread_driver() -> None:
    points = _curve_points(
        dgs2=[("2026-06-17", 4.20), ("2026-07-10", 4.21), ("2026-07-17", 4.18)],
        dgs3mo=[("2026-06-17", 3.83), ("2026-07-10", 3.85), ("2026-07-17", 3.85)],
    )
    snapshot = build_macro_snapshot(points, as_of="2026-07-17")
    conclusion = build_macro_conclusion(snapshot)

    markdown = render_macro_full_report_markdown(snapshot, conclusion)

    assert "| US03M | 2026-07-17 | 3.85%" in markdown
    assert "3M 周度持平、月度上行，当前政策价格未松" in markdown
    assert "| 2Y-3M 利差 | 2026-07-17 | 0.33%" in markdown
    assert "正斜率、周度收窄；2Y 下行、3M 未降，未来紧缩溢价缓和但当前短端未松" in markdown
    assert "正斜率、周度收窄" in markdown
    assert "2Y 下行而 3M 未降，仅代表未来紧缩溢价缓和，当前短端尚未宽松" in markdown
    assert "不把转正、走阔或收窄机械等同于宽松" in markdown
    assert "4100" not in markdown
    assert "3720" not in markdown


def test_macro_full_report_does_not_treat_opposing_curve_legs_as_one_way_signal() -> None:
    points = _curve_points(
        dgs2=[("2026-07-10", 4.10), ("2026-07-17", 4.20)],
        dgs3mo=[("2026-07-10", 3.90), ("2026-07-17", 3.85)],
    )
    snapshot = build_macro_snapshot(points, as_of="2026-07-17")
    conclusion = build_macro_conclusion(snapshot)

    markdown = render_macro_full_report_markdown(snapshot, conclusion)

    assert "2Y 上行而 3M 下行" in markdown
    assert "鹰派预期与近期政策价格转松并存" in markdown
    assert "曲线变化不能单向解读" in markdown


def _curve_points(
    *,
    dgs2: list[tuple[str, float]],
    dgs3mo: list[tuple[str, float]],
) -> list[dict[str, object]]:
    series = {"DGS2": dgs2, "DGS3MO": dgs3mo}
    return [
        {
            "symbol": symbol,
            "date": date_value,
            "value": value,
            "source": "fred",
            "source_url": f"fixture://fred/{symbol}",
            "retrieved_at": "2026-07-17T00:00:00+00:00",
            "raw_path": f"fixture/{symbol}.json",
        }
        for symbol, observations in series.items()
        for date_value, value in observations
    ]


def _neutral_dollar_and_falling_reserves_value(point: dict[str, object]) -> object:
    if point["symbol"] == "DXY":
        return 100.0
    if point["symbol"] == "WRESBAL" and point["date"] == "2026-05-06":
        return 2800.0
    return point["value"]


def _neutral_real_rate_value(point: dict[str, object]) -> object:
    real_rate_inputs = {
        ("DGS10", "2026-04-07"): 4.30,
        ("T10YIE", "2026-04-07"): 2.25,
        ("DGS10", "2026-04-30"): 4.25,
        ("T10YIE", "2026-04-30"): 2.20,
        ("DGS10", "2026-05-07"): 4.25,
        ("T10YIE", "2026-05-07"): 2.20,
    }
    return real_rate_inputs.get((point["symbol"], point["date"]), point["value"])


def _current_doc_points() -> list[dict[str, object]]:
    series = {
        "RRPONTSYD": [("2026-04-07", 15.345), ("2026-04-30", 8.261), ("2026-05-07", 0.773)],
        "RRPONTSYAWARD": [("2026-04-07", 3.50), ("2026-04-30", 3.50), ("2026-05-07", 3.50)],
        "TGA": [("2026-04-06", 775.430), ("2026-04-29", 988.100), ("2026-05-06", 862.760)],
        "WRESBAL": [("2026-04-06", 3116.659), ("2026-04-29", 2919.011), ("2026-05-06", 3033.000)],
        "SOFR": [("2026-04-06", 3.65), ("2026-04-29", 3.63), ("2026-05-06", 3.61)],
        "EFFR": [("2026-04-06", 3.64), ("2026-04-29", 3.64), ("2026-05-06", 3.64)],
        "IORB": [("2026-04-08", 3.65), ("2026-05-01", 3.65), ("2026-05-08", 3.65)],
        "DGS2": [("2026-04-07", 3.84), ("2026-04-30", 3.84), ("2026-05-07", 3.87)],
        "DGS10": [("2026-04-07", 4.34), ("2026-04-30", 4.36), ("2026-05-07", 4.36)],
        "DFII10": [("2026-04-07", 1.97), ("2026-04-30", 1.90), ("2026-05-07", 1.91)],
        "T10YIE": [("2026-04-07", 2.37), ("2026-04-30", 2.46), ("2026-05-07", 2.45)],
        "DXY": [("2026-04-08", 98.967), ("2026-05-01", 98.137), ("2026-05-08", 97.927)],
    }
    points: list[dict[str, object]] = []
    for symbol, obs in series.items():
        for d, v in obs:
            points.append({"symbol": symbol, "date": d, "value": v, "source": "fixture", "source_url": "fixture://", "retrieved_at": "2026-05-08T00:00:00+00:00", "raw_path": "fixture"})
    return points


def _recent_trade_day_points() -> list[dict[str, object]]:
    series = {
        "RRPONTSYD": [("2026-05-27", 1.853), ("2026-06-19", 0.251), ("2026-06-26", 6.426)],
        "RRPONTSYAWARD": [("2026-05-27", 3.50), ("2026-06-19", 3.50), ("2026-06-26", 3.50)],
        "TGA": [("2026-05-26", 842.660), ("2026-06-18", 915.080), ("2026-06-25", 871.470)],
        "WRESBAL": [("2026-05-24", 3129.566), ("2026-06-17", 3033.446), ("2026-06-24", 2951.416)],
        "SOFR": [("2026-05-25", 3.63), ("2026-06-18", 3.62), ("2026-06-25", 3.64)],
        "EFFR": [("2026-05-25", 3.62), ("2026-06-18", 3.63), ("2026-06-25", 3.63)],
        "IORB": [("2026-05-18", 3.65), ("2026-06-18", 3.65), ("2026-06-26", 3.65)],
        "DGS2": [("2026-05-25", 4.00), ("2026-06-18", 4.19), ("2026-06-25", 4.09)],
        "DGS10": [("2026-05-25", 4.48), ("2026-06-18", 4.46), ("2026-06-25", 4.40)],
        "T10YIE": [("2026-05-26", 2.39), ("2026-06-18", 2.25), ("2026-06-25", 2.21), ("2026-06-26", 2.20)],
        "DXY": [("2026-05-27", 99.196), ("2026-06-19", 100.856), ("2026-06-26", 101.366)],
    }
    points: list[dict[str, object]] = []
    for symbol, obs in series.items():
        for d, v in obs:
            points.append({"symbol": symbol, "date": d, "value": v, "source": "fixture", "source_url": "fixture://", "retrieved_at": "2026-06-26T00:00:00+00:00", "raw_path": "fixture"})
    return points
