from copy import deepcopy

import pytest

from apps.api.services.research_trade_plan import project_research_trade_plan


def project(body, snapshot=None):
    return project_research_trade_plan(narrative=body, snapshot=snapshot or {},
        report_id="report-old", run_id="run-old", snapshot_id="snapshot-old", trade_date="2026-10-06")


@pytest.mark.parametrize("level", [4310.67, 3721.25])
@pytest.mark.parametrize("swapped", [True, False])
@pytest.mark.parametrize("price_header", ["价格条件", "价格与资金条件"])
def test_real_path_prose_and_prices_preserved(level, swapped, price_header):
    headers = ["路径", "宏观条件", price_header, "失效条件"]
    rows = [
        ["上涨", "实际利率回落且美元转弱", f"站稳 {level} 后等 15m 回踩", f"跌回 {level} 下方"],
        ["下跌", "实际利率上行", f"跌破 {level}，不追第一根 K 线", "宏观压力消失"],
        ["震荡", "利率与美元分歧", f"围绕 {level} 观察", "区间失效"],
        ["补充观察", "待核验", "无已验证价位", "新证据出现"],
    ]
    order = [3, 2, 0, 1] if swapped else [0, 1, 2, 3]
    table = "\n".join("| " + " | ".join(row[i] for i in order) + " |"
                      for row in [headers, ["---"] * 4, *rows])
    paragraph = "**当前仍是研究观察。**\n宏观与价格须共同确认；不把触发位当目标位。"
    body = f"## 一句话结论\n\n{paragraph}\n\n## 条件性三路径\n\n{table}\n\n## 风险\n未确认。"
    plan = project(body)
    assert plan["summary"] == paragraph
    assert plan["scenarios"] == [dict(zip(["name", "macro_conditions", "price_conditions", "invalidation"], row)) for row in rows]
    assert plan["entry"] is None and plan["stop_loss"] is None and plan["targets"] == []


@pytest.mark.parametrize("body", ["研究正文但没有结论。", "## 一句话结论\n\n## 数据\n无正文",
    "| 指标 | 数值 |\n|---|---|\n| GC | 4300 |",
    "| 路径 | 宏观条件 | 价格条件 |\n|---|---|---|\n| 涨 | 利率下降 | 4300 |",
    "```\n| 路径 | 宏观条件 | 价格条件 | 失效条件 |\n|---|---|---|---|\n| 涨 | a | 4300 | b |\n```"])
def test_missing_or_non_strategy_table_never_fills_prices_or_conclusion(body):
    plan = project(body)
    assert plan["summary"] == ""
    assert plan["scenarios"] == []
    assert plan["entry"] is None and plan["targets"] == []


def test_legacy_renderer_column_names_and_escaped_pipe():
    body = ("| 路径 | 权重 | Trigger | Macro Confirmation | Price Path | Invalidation |\n"
            "|---|---:|---|---|---|---|\n"
            "| Primary / Up | 40% | 站稳 4310 | 利率下降 | 4310 → 4350 \\| 待确认 | 跌回 4310 |")
    assert project(body)["scenarios"] == [{"name": "Primary / Up", "macro_conditions": "利率下降",
        "price_conditions": "站稳 4310\n4310 → 4350 \\| 待确认", "invalidation": "跌回 4310"}]


def test_snapshot_guidance_gaps_and_observation_always_waiting():
    snapshot = {"snapshot_time": "2026-10-06T10:00:00Z", "gold_workflow": {"execution": {
        "status": "available", "execution_ready": True, "is_trade_instruction": True,
        "reason": "区间突破只是代理。", "flat": "空仓观察", "long": "多单检查假设", "short": "空单检查反证",
        "event_rule": "事件后不追第一根 15m 数据 K。", "timeframe_features": [
            {"timeframe": "4h", "status": "available"},
            {"timeframe": "1h", "status": "unavailable", "reason": "收盘未同步"}]}}}
    before = deepcopy(snapshot)
    plan = project("## 一句话结论\n\n仍等待确认。", snapshot)
    assert snapshot == before
    assert plan["status"] == "waiting" and plan["execution_ready"] is False and plan["is_trade_instruction"] is False
    assert plan["current_action"] == "等待确认，暂不开新单"
    assert plan["reason"] == "区间突破只是代理。"
    assert plan["position_guidance"] == {"flat": "空仓观察", "long": "多单检查假设", "short": "空单检查反证"}
    assert "1H 数据缺口：收盘未同步" in plan["attention_points"]
    assert not any(point.startswith("4H 数据缺口") for point in plan["attention_points"])
    assert any(point.startswith("15m 数据缺口") for point in plan["attention_points"])
    assert snapshot["gold_workflow"]["execution"]["event_rule"] in plan["attention_points"]
    assert sum(point == snapshot["gold_workflow"]["execution"]["event_rule"] for point in plan["attention_points"]) == 1
    assert any("超过 20 美元/盎司" in point for point in plan["attention_points"])
    assert plan["report_id"] == "report-old" and plan["snapshot_id"] == "snapshot-old"


def detailed_table(*, omit=None, duplicate=None):
    from apps.renderer.markdown.gold_detailed import table, label
    rows = [[name, label(field), f"工程 {name} {field} 原条件：1234.56 等待核验。"]
            for name in ("主路径", "上行路径", "下行路径")
            for field in ("macro", "funds", "price", "region", "trigger", "invalidation", "window")
            if (name, field) != omit]
    if duplicate:
        rows.append([duplicate[0], label(duplicate[1]), "工程重复冲突条件"])
    rows.append(["空仓", "4H", "工程持仓观察，不作为新路径"])
    return table(["路径 / 持仓", "条件项目", "模型条件（external_opinion）"], rows)


def test_actual_detailed_renderer_condition_table_keeps_all_fields():
    body = detailed_table()
    plan = project(body)
    assert [row["name"] for row in plan["scenarios"]] == ["主路径", "上行路径", "下行路径"]
    for row in plan["scenarios"]:
        name = row["name"]
        assert row["macro_conditions"] == f"宏观确认：工程 {name} macro 原条件：1234.56 等待核验。\n资金确认：工程 {name} funds 原条件：1234.56 等待核验。"
        assert row["price_conditions"] == "\n".join(f"{label}：工程 {name} {field} 原条件：1234.56 等待核验。"
                                                   for label, field in (("价格", "price"), ("观察区域", "region"), ("触发", "trigger"), ("观察窗口", "window")))
        assert row["invalidation"] == f"工程 {name} invalidation 原条件：1234.56 等待核验。"
    assert plan["execution_ready"] is False and plan["entry"] is None and plan["targets"] == []
    assert project('```\n' + body + '\n```')["scenarios"] == []


@pytest.mark.parametrize("kwargs", [{"omit": ("主路径", "invalidation")}, {"duplicate": ("主路径", "macro")}])
def test_incomplete_or_ambiguous_detailed_path_is_not_silently_filled(kwargs):
    assert [row["name"] for row in project(detailed_table(**kwargs))["scenarios"]] == ["上行路径", "下行路径"]
