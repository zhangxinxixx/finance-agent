from copy import deepcopy

import pytest

from apps.api.services.gold_research_horizons import project_research_horizons
from apps.api.services.gold_workspace_service import build_gold_workspace
from tests.api.test_gold_workspace import NOW, report


def projection(body: str, status="historical"):
    return {**report(), "status": status, "narrative": body}


def test_explicit_horizons_copy_original_text_and_identity_without_new_direction():
    short = "工程短线：**价格结构待确认**，需等待回收。"
    long = "工程长线：宏观背景存在分歧，长期趋势尚未确认。"
    body = f"## 一句话结论\n\n总体判断。\n\n## 短线分析\n\n{short}\n\n### 失效条件\n\n工程条件。\n\n## 长线分析\n\n{long}\n"
    data = projection(body)
    before = deepcopy(data)
    horizons = project_research_horizons(data)
    assert data == before
    for key, summary in (("short_term", short), ("long_term", long)):
        row = horizons[key]
        assert row["summary"] == summary
        assert row["status"] == "historical" and row["basis"] == "report_explicit"
        assert all(row[field] == data[field] for field in ("report_id", "run_id", "snapshot_id", "trade_date", "as_of"))
        assert "bias" not in row and "entry" not in row
    assert "### 失效条件\n\n工程条件。" in horizons["short_term"]["sections"][0]["content"]


def test_existing_report_macro_excerpts_are_background_not_independent_forecast():
    body = "## 日度利率缓和，但周度长端压力没有消失\n\n工程宏观背景原文。\n\n## 黄金价格行为偏弱，但还不是完整的趋势确认\n\n工程价格结构原文。\n\n## 未来一至三个交易日：等待\n\n工程条件原文。"
    horizons = project_research_horizons(projection(body, "current"))
    assert horizons["short_term"]["summary"] == "工程价格结构原文。"
    assert len(horizons["short_term"]["sections"]) == 2
    assert horizons["long_term"]["summary"] == "工程宏观背景原文。"
    assert horizons["long_term"]["basis"] == "report_excerpt"
    assert "未单独给出周／月趋势结论" in horizons["long_term"]["note"]


def test_explicit_long_section_takes_priority_over_daily_macro_context():
    body = "## 美债收益率\n\n工程日度读数。\n\n## 长线分析\n\n工程明确长周期判断。"
    long = project_research_horizons(projection(body))["long_term"]
    assert long["basis"] == "report_explicit"
    assert long["summary"] == "工程明确长周期判断。"
    assert len(long["sections"]) == 1


@pytest.mark.parametrize("fence", ["```", "~~~", "````"])
def test_fake_horizon_headings_inside_code_do_not_create_analysis(fence):
    body = f"## 一句话结论\n\n工程一般结论。\n\n{fence}md\n## 短线分析\n\n虚构短线。\n## 长线分析\n\n虚构长线。\n{fence}\n"
    horizons = project_research_horizons(projection(body))
    assert all(row["status"] == "unavailable" and not row["sections"] for row in horizons.values())


@pytest.mark.parametrize("extra", [{"status": "unavailable"}, {"run_id": None}, {"snapshot_id": None}, {"summary": ""}])
def test_rejected_report_cannot_supply_horizon_analysis(extra):
    data = report(summary="## 短线分析\n\n工程结构。\n\n## 长线分析\n\n工程背景。")
    data.update(extra)
    result = build_gold_workspace(macro=None, quotes=None, research=data, now=NOW)
    assert all(row["status"] == "unavailable" and row["summary"] == "" for row in result["research"]["horizons"].values())


def test_horizon_freshness_inherits_report_cutoff_not_price_refresh():
    result = build_gold_workspace(macro=None, quotes=None, research=report(
        summary="## 短线分析\n\n工程结构。\n\n## 长线分析\n\n工程背景。",
        as_of="2026-10-07T04:00:00Z"), now=NOW)
    assert result["research"]["status"] == "historical"
    assert all(row["status"] == "historical" for row in result["research"]["horizons"].values())
    assert result["research"]["publish_allowed"] is False


def test_heading_only_horizons_do_not_become_analysis():
    horizons = project_research_horizons(projection("## 短线分析\n\n## 长线分析\n"))
    assert all(row["status"] == "unavailable" for row in horizons.values())


def test_code_samples_do_not_supply_a_horizon_summary():
    horizons = project_research_horizons(projection("## 短线分析\n\n```text\n\n代码中的假结论。\n\n```\n\n真正的工程研究判断。"))
    assert horizons["short_term"]["summary"] == "真正的工程研究判断。"
    code_only = project_research_horizons(projection("## 长线分析\n\n```text\n\n代码中的假结论。\n\n```"))
    assert code_only["long_term"]["status"] == "unavailable"


def test_short_excerpt_keeps_the_price_judgment_visible_after_its_data_limit():
    body = "## 黄金价格行为\n\n工程现价缺口。\n\n工程1H结构判断与15m条件。\n\n### 附件\n\n其他记录。"
    short = project_research_horizons(projection(body))["short_term"]
    assert short["summary"] == "工程现价缺口。\n\n工程1H结构判断与15m条件。"
    assert "其他记录" not in short["summary"]
