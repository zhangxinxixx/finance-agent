from __future__ import annotations

import json
from pathlib import Path

from apps.analysis.jin10.agent_analysis import (
    MISSING,
    _parse_llm_output_to_fields,
    _validate_llm_output_to_report_fields,
    agent_analysis_prompt_version,
    build_agent_analysis_prompt,
    build_jin10_agent_analysis_report,
    build_jin10_agent_analysis_report_with_llm,
    parse_agent_analysis_markdown,
    sanitize_agent_analysis_markdown,
)
from apps.analysis.jin10.daily_report import build_daily_report_analysis_snapshot
from apps.analysis.jin10.raw_article import build_jin10_raw_article_report, build_raw_article_context
from apps.analysis.jin10.visual_report import build_jin10_daily_analysis_report
from apps.collectors.jin10.adapter import build_jin10_outputs, write_jin10_outputs
from apps.documents.parsing import build_parsed_document
from apps.documents.schemas import SourceAssetRef, SourceDocument
from apps.extractors.report_fact_extractor import extract_report_facts
from apps.renderer.markdown.jin10_agent_analysis import render_jin10_agent_analysis_markdown


def _document(tmp_path: Path | None = None) -> SourceDocument:
    base = tmp_path or Path("/tmp/jin10-agent-analysis-test")
    report_path = base / "report.md"
    meta_path = base / "meta.json"
    report_text = """# 鹰派预期将继续施压金价，但央行购金支撑长期配置？

1、行情回顾：现货黄金先涨后跌，最高触及4586.61美元/盎司，最终报4557.55美元/盎司；现货白银报72.83美元/盎司。

2、关键指标：美国非制造业PMI维持在50上方，10年期美债收益率持稳，美元指数反弹，当前数据削弱了降息的紧迫性。

3、观点分享：分析师A表示高油价将继续打压国际现货黄金；分析师B认为央行购金和ETF资金仍提供长期配置支撑。

4、关键位：4600是第一修复确认位，4500是短线核心分界位，5000是关键整数压力。

风险提示及免责条款：若美债收益率和美元继续上行，黄金修复路径可能降级。
"""
    return SourceDocument(
        document_id="jin10-2026-05-06-218330",
        source="jin10_external",
        trade_date="2026-05-06",
        title="鹰派预期将继续施压金价，但央行购金支撑长期配置？",
        category="报告",
        category_code="270",
        source_url="https://xnews.jin10.com/details/218330",
        article_id="218330",
        external_report_dir=str(base),
        retrieved_at="2026-05-06T00:00:00+00:00",
        markdown_asset=SourceAssetRef(asset_type="report_md", path=str(report_path), sha256="", size_bytes=0),
        meta_asset=SourceAssetRef(asset_type="meta_json", path=str(meta_path), sha256="", size_bytes=0),
        image_assets=[],
        report_text=report_text,
        source_refs=[{"source": "jin10_external", "article_id": "218330", "asset_type": "report_md"}],
    )


def _agent_report():
    document = _document()
    parsed = build_parsed_document(document)
    facts = extract_report_facts(parsed)
    snapshot = build_daily_report_analysis_snapshot(parsed, facts)
    raw_report = build_jin10_raw_article_report(document)
    daily_report = build_jin10_daily_analysis_report(snapshot)
    return raw_report, daily_report, build_jin10_agent_analysis_report(raw_report, daily_report)


def _llm_payload(report) -> dict:
    payload = report.to_dict()
    payload.update(
        title="测试报告",
        one_line_conclusion="黄金更接近弱修复观察期，4500仍是核心分界位。",
        market_stage={
            "label": "弱修复观察期",
            "reason": "价格尚未完成趋势确认。",
            "confirmation_matrix": {
                "阶段": "弱修复观察期",
                "底部证据": "中等",
                "趋势反转证据": "偏弱",
                "价格确认": "未完成",
                "宏观确认": "部分完成",
                "资金确认": "未完成",
            },
        },
        key_levels=[{"value": "4500", "asset": "黄金", "source_category": "图表事实", "meaning": "核心分界位"}],
        scenario_paths=[
            {"name": "主路径", "trigger": "守住4500", "path": "区间修复", "invalid": "跌破4500"},
            {"name": "上行路径", "trigger": "收复4600", "path": "修复延续", "invalid": "回落4500"},
            {"name": "下行路径", "trigger": "跌破4500", "path": "重新承压", "invalid": "收复4600"},
        ],
        trading_implications=[
            {"role": "空仓", "wait_for": "等待确认", "invalid": "跌破4500"},
            {"role": "已有多单", "wait_for": "观察4600", "invalid": "跌破4500"},
            {"role": "已有空单", "wait_for": "观察4500", "invalid": "收复4600"},
        ],
    )
    fields = {
        "title", "one_line_conclusion", "market_stage", "logic_chain", "key_variables",
        "gold_analysis", "silver_analysis", "cross_asset_analysis", "key_levels",
        "scenario_paths", "trading_implications", "risk_points", "final_summary",
        "unresolved_items", "evidence_basis",
    }
    return {key: payload[key] for key in fields}


def test_build_agent_analysis_prompt_includes_required_framework_terms() -> None:
    raw_report, daily_report, _ = _agent_report()

    prompt = build_agent_analysis_prompt(raw_report.to_dict(), daily_report.to_dict())

    assert "报告明确事实" in prompt
    assert "相对前序判断" in prompt
    assert "最终响应必须遵守末尾 JSON schema" in prompt
    assert "只返回一个 JSON object" in prompt
    assert "# 1. 最新判断发生了什么变化？" in prompt
    assert "# 7. 三条路径推演" in prompt
    assert "# 8. 操作层面怎么理解？" in prompt
    assert "# 3. 黄金为什么涨 / 为什么跌？" in prompt
    assert "# 6. 关键位更新" in prompt
    assert "不主动联网" in prompt
    assert raw_report.title in prompt
    assert "央行购金" in prompt
    assert "=== 正文章节摘要 ===" in prompt
    assert "=== 图表前后文锚点 ===" in prompt
    assert "=== 关键位 / 利率 / 期权证据片段 ===" in prompt
    assert "有效跌破" in prompt
    assert "Call OI" in prompt
    assert "Put/Call 关键区间只能作为历史观察信号" in prompt
    assert "整体语气更像盘后研究会话或交易员复盘" in prompt
    assert "最多 3 句" in prompt
    assert "不要单独展开“三确认模型”小节" in prompt
    assert "近端确认位、动态期权锚和远期模型目标必须拆开" in prompt
    assert "## Agent 入库字段" not in prompt


def test_build_agent_analysis_prompt_embeds_previous_daily_analysis() -> None:
    raw_report, daily_report, _ = _agent_report()
    previous = {
        "title": "前序金银报告",
        "trade_date": "2026-05-31",
        "one_line_conclusion": "4366 附近日线底部确认，上涨窗口看向 5000-5200。",
        "market_stage": {"label": "修复反弹态", "reason": "前序判断偏乐观。"},
        "key_levels": [
            {"price": 4366, "type": "support", "description": "前序底部观察位"},
            {"price": 4600, "type": "resistance", "description": "前序第一确认位"},
        ],
        "final_summary": "前序报告认为 6-7 月存在上行窗口。",
    }

    prompt = build_agent_analysis_prompt(raw_report.to_dict(), daily_report.to_dict(), previous_daily_analysis=previous)

    assert "=== previous_daily_analysis（若存在） ===" in prompt
    assert "one_line_conclusion: 4366 附近日线底部确认，上涨窗口看向 5000-5200。" in prompt
    assert "price=4366" in prompt
    assert "price=4600" in prompt
    assert "upside_trigger_primary" not in prompt
    assert "valid_until_event" not in prompt
    assert "evidence_refs" not in prompt


def test_build_agent_analysis_prompt_uses_weekly_anchor_and_fresh_context() -> None:
    raw_report, daily_report, _ = _agent_report()
    context = {
        "status": "ready",
        "weekly_anchor": {
            "source_kind": "weekly_context_revision",
            "trade_date": "2026-07-12",
            "article_id": "weekly-1",
            "quality_status": "needs_review",
            "publication_status": "observe",
            "publish_allowed": False,
            "executive_summary": "周报偏修复，但仍待利率确认。",
            "claim_revisions": [{"claim_id": "overall", "action": "weaken", "reason": "实际利率仍高"}],
        },
        "latest_market": {"technical": {"price": 4557.55}, "macro": {"indicators": {"US10Y": {"value": 4.5}}}},
        "latest_news": {"market_mainline": {"summary": "油价冲击", "verification_status": "candidate"}},
        "gold_mainline": {"dominant_mainline": "fed_policy_path"},
        "oil_context": {},
        "freshness": {
                "weekly_anchor": {"status": "current", "as_of": "2026-07-12"},
                "market": {"status": "current", "as_of": "2026-07-13"},
                "news": {"status": "current", "as_of": "2026-07-13"},
            "oil": {"status": "missing", "as_of": None},
        },
        "input_snapshot_ids": {"weekly_anchor": "outputs/weekly.json", "premarket_snapshot": "features/premarket.json"},
    }

    prompt = build_agent_analysis_prompt(raw_report.to_dict(), daily_report.to_dict(), analysis_context=context)

    assert "=== analysis_baseline（周一周报 / 后续前一日最终综合分析报告） ===" in prompt
    assert "=== latest_market_context（最新价格 / 利率 / CME / COT） ===" in prompt
    assert "=== latest_news_context（最新消息 / 黄金主线 / 油价链） ===" in prompt
    assert "周报偏修复，但仍待利率确认" in prompt
    assert '"publish_allowed": false' in prompt
    assert '"price": 4557.55' in prompt
    assert "强化 / 维持 / 削弱 / 失效 / 待确认" in prompt
    assert "Brent/WTI 数值尚未确认" in prompt


def test_build_agent_analysis_prompt_marks_compacted_fallback_chart_mode() -> None:
    raw_report = {
        "trade_date": "2026-05-26",
        "article_id": "220232",
        "title": "黄金反弹进程受阻",
        "source_url": "https://svip.jin10.com/news/220232",
        "article_markdown": "# 黄金反弹进程受阻\n\n1、行情回顾：黄金震荡。\n2、关键指标：收益率仍高位。",
        "charts": [
            {"seq": 1, "title": "第1页报告图", "caption": "第1页报告图", "image_path": "images/page-1.png"},
            {"seq": 2, "title": "第2页报告图", "caption": "第2页报告图", "image_path": "images/page-2.png"},
            {"seq": 3, "title": "第3页报告图", "caption": "第3页报告图", "image_path": "images/page-3.png"},
            {"seq": 4, "title": "第4页报告图", "caption": "第4页报告图", "image_path": "images/page-4.png"},
            {"seq": 5, "title": "第5页报告图", "caption": "第5页报告图", "image_path": "images/page-5.png"},
        ],
        "generated_from": {
            "article_context": {
                "paragraph_snippets": ["1、行情回顾：黄金震荡。", "2、关键指标：收益率仍高位。"],
                "key_sentences": ["2、关键指标：收益率仍高位。"],
                "sections": [],
                "chart_anchors": [],
                "level_snippets": ["收益率仍高位。"],
                "chart_summaries": [],
                "chart_count": 5,
                "chart_render_mode": "fallback_compact",
            }
        },
    }

    prompt = build_agent_analysis_prompt(raw_report, None)

    assert "chart_render_mode: fallback_compact" in prompt
    assert "当前图表为页图 fallback：仅代表归档页面截图" in prompt


def test_build_agent_analysis_prompt_uses_market_observation_framework() -> None:
    raw_report = {
        "trade_date": "2026-07-03",
        "article_id": "223555",
        "title": "加息跌破半数，黄金赔率变脸｜市场赔率数据表-金十数据VIP",
        "source_url": "https://svip.jin10.com/news/223555",
        "article_markdown": (
            "# 加息跌破半数，黄金赔率变脸｜市场赔率数据表-金十数据VIP\n\n"
            "截至7月3日14点，今日赔率市场的核心变化，是利率压力边际缓和之后，贵金属率先拿回一段修复空间。\n\n"
            "黄金7月触及4200美元的概率升至94%，4300美元概率也达到65%，但4600美元仅5%。\n\n"
            "WTI向下触及65美元概率达到64%，美元兑日元165仍是高位锚，概率达到68%。\n"
        ),
        "charts": [],
    }
    daily_report = {
        "family": "jin10_market_observation_report",
        "report_type": "market_observation",
        "core_conclusion": "解析已完成，但正文与图表证据仍不足以形成稳定结论。",
    }

    prompt = build_agent_analysis_prompt(raw_report, daily_report)

    assert "市场观察 / 市场赔率专用分析" in prompt
    assert "不要套用每日金银报告" in prompt
    assert "# 3. 赔率和观察信号怎么读？" in prompt
    assert agent_analysis_prompt_version(raw_report, daily_report) == "jin10_agent_analysis_market_odds_v1"
    assert "# 5. 作为辅助决策依据怎么用？" in prompt
    assert "黄金7月触及4200美元的概率升至94%" in prompt
    assert "# 3. 黄金为什么涨 / 为什么跌？" not in prompt
    assert "# 7. 三条路径推演" not in prompt
    assert "previous_daily_analysis" not in prompt


def test_build_agent_analysis_prompt_uses_positioning_framework() -> None:
    raw_report = {
        "trade_date": "2026-06-29",
        "article_id": "223032",
        "title": "黄金上方看涨总增持逾千手，资金中期乐观预期有所升温-金十数据VIP",
        "source_url": "https://svip.jin10.com/news/223032",
        "article_markdown": (
            "# 黄金持仓报告\n\n"
            "期货持仓量：主力合约增加535手或0.20%。\n"
            "期权布局变化：4250 看涨期权+624手，看跌期权-2手。\n"
            "# 白银持仓报告\n\n64 看涨期权+40手，看跌期权-10手。"
        ),
        "charts": [{"seq": 1, "title": "黄金持仓报告", "summary": "看涨期权和看跌期权分布", "image_path": "figures/fig_p1_001.png"}],
    }
    daily_report = {
        "family": "jin10_positioning_report",
        "report_type": "positioning",
        "core_conclusion": "黄金期权上方增仓。",
    }

    prompt = build_agent_analysis_prompt(raw_report, daily_report)

    assert "持仓 / 期权分布专用分析" in prompt
    assert "期货持仓量、期货成交量、期权 OI" in prompt
    assert "# 2. 黄金期权结构：Call / Put / OI / 行权价" in prompt
    assert "不要套用每日金银报告" in prompt
    assert "# 3. 黄金为什么涨 / 为什么跌？" not in prompt
    assert "# 7. 三条路径推演" not in prompt


def test_build_agent_analysis_prompt_uses_technical_levels_framework() -> None:
    raw_report = {
        "trade_date": "2026-06-29",
        "article_id": "223073",
        "title": "技术刘Pro：黄金波段低点呈下移之势，白银两端筹码逐步收细-金十数据VIP",
        "source_url": "https://svip.jin10.com/news/223073",
        "article_markdown": (
            "# 国际现货黄金\n\nVAH 4092.61，POC 4064.95，VAL 4032.76。\n"
            "筹码形态：双筹码峰。形态解释：短期关注价值区间突破。"
        ),
        "charts": [{"seq": 1, "title": "国际现货黄金筹码分布", "summary": "双筹码峰", "image_path": "figures/fig_p1_001.png"}],
    }
    daily_report = {
        "family": "jin10_technical_levels_report",
        "report_type": "technical_levels",
        "core_conclusion": "黄金波段低点继续下移。",
    }

    prompt = build_agent_analysis_prompt(raw_report, daily_report)

    assert "点位 / 技术刘Pro专用分析" in prompt
    assert "VAH / VAL / POC" in prompt
    assert "# 2. 黄金：VAH / POC / VAL 与筹码形态" in prompt
    assert "不要写成宏观传导日报" in prompt
    assert "# 3. 黄金为什么涨 / 为什么跌？" not in prompt
    assert "previous_daily_analysis" not in prompt


def test_build_agent_analysis_prompt_uses_oil_framework() -> None:
    raw_report = {
        "trade_date": "2026-06-29",
        "article_id": "223009",
        "title": "美伊同意停火并重启会晤，航运数据指向低强度扰动-金十数据VIP",
        "source_url": "https://svip.jin10.com/news/223009",
        "article_markdown": (
            "# 每日原油报告\n\nWTI原油最终收跌1.76%，报70.08美元/桶；布伦特收跌2.8%，报72.58美元/桶。\n"
            "霍尔木兹海峡仍处于低强度扰动。美国油气钻井总数升至573口。"
        ),
        "charts": [{"seq": 14, "title": "WTI原油技术指标", "summary": "恐惧贪婪指标", "image_path": "figures/fig_p14_001.png"}],
    }
    daily_report = {
        "family": "jin10_oil_report",
        "report_type": "oil",
        "core_conclusion": "油价几乎跌回战前水平。",
    }

    prompt = build_agent_analysis_prompt(raw_report, daily_report)

    assert "原油报告专用分析" in prompt
    assert "供需、航运/地缘、库存、钻井、裂解价差" in prompt
    assert "# 5. 对通胀、利率、美元和黄金的间接含义" in prompt
    assert "不要使用“黄金为什么涨/跌”的固定日报章节" in prompt
    assert "# 3. 黄金为什么涨 / 为什么跌？" not in prompt
    assert "# 7. 三条路径推演" not in prompt


def test_build_agent_analysis_prompt_uses_fx_framework() -> None:
    raw_report = {
        "trade_date": "2026-06-29",
        "article_id": "223012",
        "title": "油价下跌难掩通胀黏性，更高更久成美元最强支撑-金十数据VIP",
        "source_url": "https://svip.jin10.com/news/223012",
        "article_markdown": (
            "# 每日外汇报告\n\n美元指数收跌0.07%，报101.39。10年期美债收益率收报4.371%，2年期美债收益率收报4.098%。\n"
            "CME FedWatch显示，市场已开始将9月潜在加息纳入情景。"
        ),
        "charts": [{"seq": 11, "title": "消费者信心指数", "summary": "信心回升但不及预期", "image_path": "figures/fig_p11_001.png"}],
    }
    daily_report = {
        "family": "jin10_fx_report",
        "report_type": "fx",
        "core_conclusion": "美元实际利率重新压盘。",
    }

    prompt = build_agent_analysis_prompt(raw_report, daily_report)

    assert "外汇报告专用分析" in prompt
    assert "美元指数、美债收益率、FedWatch、PCE/通胀" in prompt
    assert "# 2. 美元指数和美债收益率" in prompt
    assert "# 5. 对黄金的间接影响" in prompt
    assert "# 3. 黄金为什么涨 / 为什么跌？" not in prompt
    assert "不要沿用前序金银日报的价位链" in prompt


def test_agent_analysis_prompt_version_tracks_report_type() -> None:
    raw_report = {"title": "测试", "article_markdown": ""}

    assert (
        agent_analysis_prompt_version(raw_report, {"report_type": "market_observation"})
        == "jin10_agent_analysis_market_observation_v1"
    )
    assert agent_analysis_prompt_version(raw_report, {"report_type": "positioning"}) == "jin10_agent_analysis_positioning_v1"
    assert agent_analysis_prompt_version(raw_report, {"report_type": "technical_levels"}) == "jin10_agent_analysis_technical_levels_v1"
    assert agent_analysis_prompt_version(raw_report, {"report_type": "oil"}) == "jin10_agent_analysis_oil_v1"
    assert agent_analysis_prompt_version(raw_report, {"report_type": "fx"}) == "jin10_agent_analysis_fx_v1"
    assert agent_analysis_prompt_version(raw_report, {"report_type": "daily"}) == "jin10_agent_analysis_v3"


def test_weekly_prompt_does_not_route_to_embedded_specialty_section() -> None:
    raw_report = {
        "title": "黄金投资者周报",
        "article_markdown": "# 黄金\n周度区间判断。\n# 交易者持仓报告\n持仓变化。\n# 原油报告\n油价变化。\n# 市场赔率表\n辅助观察。",
        "charts": [],
    }
    daily_report = {
        "family": "jin10_weekly_visual",
        "report_type": "weekly",
    }

    prompt = build_agent_analysis_prompt(raw_report, daily_report)

    assert "# 1. 最新判断发生了什么变化？" in prompt
    assert "报告作者预测" in prompt
    assert "其他可报告交易商" in prompt
    assert "最大痛点是随持仓和到期时间变化的动态参考锚" in prompt
    assert "10Y 名义收益率、实际收益率、2Y 收益率、2Y-3M 利差" in prompt
    assert "趋势反转证据" in prompt
    assert "价格确认`必须写“未完成”" in prompt
    assert "不得混用量表" in prompt
    assert "禁止使用“先见底”" in prompt
    assert "持仓 / 期权分布专用分析" not in prompt
    assert "市场观察 / 市场赔率专用分析" not in prompt
    assert agent_analysis_prompt_version(raw_report, daily_report) == "jin10_agent_analysis_v3"


def test_build_jin10_agent_analysis_report_outputs_core_sections() -> None:
    _, _, report = _agent_report()

    assert report.family == "jin10_agent_analysis"
    assert report.one_line_conclusion
    assert report.market_stage["label"]
    assert report.scenario_paths
    assert report.risk_points
    assert report.source_refs
    assert report.gold_analysis


def test_build_raw_article_context_collects_sections_chart_anchors_and_level_snippets() -> None:
    markdown = """# 国际现货黄金暴力拉升，V型反弹是行情拐点还是诱多陷阱？

## 行情回顾
现货黄金先跌后涨，并重新站回4500上方。

## 图表 2-1
![图表 2-1](figures/fig_p2_001.png)
10年期美债收益率若有效跌破4.5%，黄金修复才有望延续。

## 期权线索
Call OI 回升，但 Put/Call 仍需继续确认。
"""
    charts = [{"title": "图表 2-1", "image_path": "figures/fig_p2_001.png", "summary": "收益率确认位与金价修复同框"}]

    context = build_raw_article_context(markdown, charts)

    assert context["sections"]
    assert any(item["heading"] == "行情回顾" for item in context["sections"])
    assert context["chart_anchors"]
    assert context["chart_anchors"][0]["image_path"] == "figures/fig_p2_001.png"
    assert "有效跌破4.5%" in context["chart_anchors"][0]["after"]
    assert context["level_snippets"]
    assert any("4500" in item or "4.5%" in item for item in context["level_snippets"])


def test_build_jin10_agent_analysis_report_keeps_missing_explicit() -> None:
    raw_report = {
        "document_id": "doc-1",
        "trade_date": "2026-05-06",
        "run_id": "218330",
        "article_id": "218330",
        "title": "空报告",
        "family": "jin10_raw_article",
        "article_markdown": "# 空报告\n\n只有标题。",
        "charts": [],
        "source_refs": [],
    }

    report = build_jin10_agent_analysis_report(raw_report, None)

    assert any(MISSING in item for item in report.unresolved_items) or report.key_levels[0]["value"] == MISSING
    assert report.family == "jin10_agent_analysis"


def test_agent_analysis_fallback_does_not_force_three_confirmation_template_for_short_web_summary() -> None:
    raw_report = {
        "document_id": "doc-220511",
        "trade_date": "2026-05-28",
        "run_id": "220511",
        "article_id": "220511",
        "title": "停火协议已成废纸，国际现货黄金长牛行情岌岌可危？",
        "family": "jin10_raw_article",
        "article_markdown": """# 停火协议已成废纸，国际现货黄金长牛行情岌岌可危？

文章导读：美伊的“边打边谈”行为让暂时停火协议成为废纸。全球加息预期升温，国际现货黄金遭遇双重挤压。

1、行情回顾：...

2、关键指标：...

3、观点分享：...
""",
        "charts": [
            {"title": "报告配图 1", "image_path": "https://cdn-news.jin10.com/1.png"},
            {"title": "报告配图 2", "image_path": "https://cdn-news.jin10.com/2.png"},
        ],
        "source_refs": [],
        "generated_from": {"article_context": {"paragraph_snippets": [], "key_sentences": [], "chart_summaries": [], "chart_count": 2}},
    }

    report = build_jin10_agent_analysis_report(raw_report, None)
    markdown = render_jin10_agent_analysis_markdown(report)

    assert "三确认模型" not in markdown
    assert "期权确认" not in markdown
    assert "报告主题指向" in markdown or "结构化结论仍需以后续关键变量确认" in markdown


def test_render_jin10_agent_analysis_markdown_contains_fixed_sections() -> None:
    _, _, report = _agent_report()

    markdown = render_jin10_agent_analysis_markdown(report)

    assert "Agent 二次分析报告" in markdown
    assert "# 分析溯源 / 数据来源" in markdown
    assert "# 5. 当前阶段判断与确认矩阵" in markdown
    assert "# 6. 关键位更新" in markdown
    assert "# 7. 三条路径推演" in markdown
    assert "# 8. 操作层面怎么理解？" in markdown
    assert "## Agent 入库字段" not in markdown


def test_parse_agent_analysis_markdown_strips_fences() -> None:
    assert parse_agent_analysis_markdown("```markdown\n# 标题\n```") == "# 标题"


def test_llm_agent_analysis_submits_real_images_and_records_visual_trace(monkeypatch) -> None:
    raw_report, daily_report, _ = _agent_report()
    raw = raw_report.to_dict()
    raw["article_markdown"] += "\n\n![关键图](figures/fig_p2_001.png)\n"
    raw["charts"] = [
        {
            "figure_id": "fig_p2_001",
            "page_no": 2,
            "bbox": [10, 20, 300, 400],
            "title": "关键图",
            "recognized_text": "4500",
            "image_path": "figures/fig_p2_001.png",
        }
    ]
    captured = {}

    class Response:
        content = json.dumps(_llm_payload(_agent_report()[2]), ensure_ascii=False)
        model = "gpt-5.5"
        provider = "cockpit"
        latency_ms = 42
        usage = {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}

    def fake_chat_sync(**kwargs):
        captured.update(kwargs)
        return Response()

    monkeypatch.setenv("FINANCE_AGENT_FORCE_LIVE_LLM", "1")
    monkeypatch.delenv("JIN10_AGENT_PROVIDER", raising=False)
    monkeypatch.delenv("JIN10_AGENT_MODEL", raising=False)
    monkeypatch.delenv("JIN10_AGENT_REASONING_EFFORT", raising=False)
    monkeypatch.delenv("JIN10_AGENT_REQUEST_TIMEOUT", raising=False)
    monkeypatch.delenv("JIN10_AGENT_MAX_IMAGES", raising=False)
    monkeypatch.setattr("apps.llm.gateway.chat_sync", fake_chat_sync)

    result = build_jin10_agent_analysis_report_with_llm(
        raw,
        daily_report,
        figure_image_loader=lambda chart: "data:image/png;base64,ZmFrZQ==",
    )

    user_content = captured["messages"][1]["content"]
    assert isinstance(user_content, list)
    assert any(block.get("type") == "image_url" for block in user_content)
    assert captured["provider"] == "cockpit"
    assert captured["model"] == "gpt-5.6-sol"
    assert captured["reasoning_effort"] == "high"
    assert captured["request_timeout"] == 300.0
    assert captured["json_mode"] is True
    assert result.generated_from["max_images"] == 25
    assert result.generated_from["vision_model"] == "gpt-5.5"
    assert result.generated_from["submitted_image_count"] == 1
    assert result.generated_from["image_processing_status"] == "success"
    assert result.generated_from["degraded"] is False
    assert result.generated_from["figure_results"][0]["figure_id"] == "fig_p2_001"
    assert result.generated_from["structured_output_validated"] is True
    assert "narrative_markdown" not in result.generated_from


def test_llm_agent_analysis_accepts_formal_runtime_overrides(monkeypatch) -> None:
    raw_report, daily_report, _ = _agent_report()
    captured = {}

    class Response:
        content = json.dumps(_llm_payload(_agent_report()[2]), ensure_ascii=False)
        model = "custom-sol"
        provider = "cockpit"
        latency_ms = 10
        usage = {}

    def fake_chat_sync(**kwargs):
        captured.update(kwargs)
        return Response()

    monkeypatch.setenv("FINANCE_AGENT_FORCE_LIVE_LLM", "1")
    monkeypatch.setenv("JIN10_AGENT_MODEL", "custom-sol")
    monkeypatch.setenv("JIN10_AGENT_REASONING_EFFORT", "medium")
    monkeypatch.setenv("JIN10_AGENT_REQUEST_TIMEOUT", "240")
    monkeypatch.setenv("JIN10_AGENT_MAX_TOKENS", "3000")
    monkeypatch.setenv("JIN10_AGENT_MAX_IMAGES", "8")
    monkeypatch.setattr("apps.llm.gateway.chat_sync", fake_chat_sync)

    result = build_jin10_agent_analysis_report_with_llm(raw_report, daily_report)

    assert captured["model"] == "custom-sol"
    assert captured["reasoning_effort"] == "medium"
    assert captured["request_timeout"] == 240.0
    assert captured["max_tokens"] == 3000
    assert result.generated_from["max_images"] == 8


def test_llm_agent_analysis_error_fallback_records_visual_degradation(monkeypatch) -> None:
    raw_report, daily_report, _ = _agent_report()
    raw = raw_report.to_dict()
    raw["article_markdown"] += "\n\n![关键图](figures/fig_p2_001.png)\n"
    raw["charts"] = [
        {
            "figure_id": "fig_p2_001",
            "page_no": 2,
            "bbox": [10, 20, 300, 400],
            "image_path": "figures/fig_p2_001.png",
        }
    ]

    monkeypatch.setenv("FINANCE_AGENT_FORCE_LIVE_LLM", "1")
    monkeypatch.setattr("apps.llm.gateway.chat_sync", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("vlm down")))

    result = build_jin10_agent_analysis_report_with_llm(
        raw,
        daily_report,
        figure_image_loader=lambda chart: "data:image/png;base64,ZmFrZQ==",
    )

    assert result.generated_from["source"] == "jin10_agent_analysis_fallback_after_llm_error"
    assert result.generated_from["degraded"] is True
    assert result.generated_from["degraded_reason"] == "llm_error:RuntimeError"
    assert result.generated_from["submitted_image_count"] == 1


def test_sanitize_agent_analysis_markdown_removes_agent_storage_section_and_yaml_block() -> None:
    markdown = sanitize_agent_analysis_markdown(
        """# 测试报告｜Agent 二次分析报告

## 一句话结论

结论正文。

## Agent 入库字段

```yaml
agent_stage_label: reversal_watch_window
trade_stance: wait_for_confirmation
```

# 3. 报告核心逻辑

- 先看利率确认。
"""
    )

    assert "## Agent 入库字段" not in markdown
    assert "agent_stage_label" not in markdown
    assert "trade_stance: wait_for_confirmation" not in markdown
    assert "# 3. 报告核心逻辑" in markdown


def test_parse_llm_output_to_fields_keeps_one_line_conclusion_scoped_to_section() -> None:
    markdown = """# 测试报告｜Agent 二次分析报告

## 一句话结论

黄金更接近弱修复观察期，4500关口未有效收复前不宜把反弹当成反攻。

# 分析溯源 / 数据来源

仅基于归档识别结果。

# 3. 报告核心逻辑

价格仍处在关键位附近反复。
"""

    fields = _parse_llm_output_to_fields(markdown, daily={}, raw={})

    assert fields["one_line_conclusion"] == "黄金更接近弱修复观察期，4500关口未有效收复前不宜把反弹当成反攻。"


def test_parse_llm_output_to_fields_strips_markdown_separator_from_one_line_conclusion() -> None:
    markdown = """# 测试报告｜Agent 二次分析报告

## 一句话结论

黄金当前更接近弱修复观察期。

---

# 分析溯源 / 数据来源

仅基于归档识别结果。
"""

    fields = _parse_llm_output_to_fields(markdown, daily={}, raw={})

    assert fields["one_line_conclusion"] == "黄金当前更接近弱修复观察期。"


def test_validate_llm_structured_output_rejects_incomplete_daily_coverage() -> None:
    payload = _llm_payload(_agent_report()[2])
    payload["scenario_paths"] = payload["scenario_paths"][:1]

    try:
        _validate_llm_output_to_report_fields(json.dumps(payload, ensure_ascii=False), prompt_profile="default_daily")
    except ValueError as exc:
        assert "scenario_paths:daily_coverage" in str(exc)
    else:
        raise AssertionError("incomplete daily coverage must be rejected")


def test_validated_json_and_rendered_markdown_share_conclusion_stage_and_levels() -> None:
    _, _, fallback = _agent_report()
    fields = _validate_llm_output_to_report_fields(
        json.dumps(_llm_payload(fallback), ensure_ascii=False),
        prompt_profile="default_daily",
    )
    for key, value in fields.items():
        if hasattr(fallback, key):
            setattr(fallback, key, value)

    markdown = render_jin10_agent_analysis_markdown(fallback)

    assert fields["one_line_conclusion"] in markdown
    assert fields["market_stage"]["label"] in markdown
    assert fields["key_levels"][0]["value"] in markdown


def test_write_jin10_outputs_writes_agent_analysis_artifacts(tmp_path: Path) -> None:
    external_root = tmp_path / "external"
    report_dir = external_root / "2026-05-06" / "金银报告" / "218330"
    report_dir.mkdir(parents=True)
    (report_dir / "meta.json").write_text(
        '{"id":"218330","date":"2026-05-06","title":"测试报告","category":"金银报告","source_url":"https://xnews.jin10.com/details/218330","images":[]}',
        encoding="utf-8",
    )
    (report_dir / "report.md").write_text(_document(tmp_path).report_text, encoding="utf-8")
    storage_root = tmp_path / "storage"

    outputs = build_jin10_outputs(external_root=external_root, date="2026-05-06", category="270")
    write_jin10_outputs(outputs, storage_root=storage_root)

    base = storage_root / "outputs" / "jin10" / "2026-05-06" / "218330"
    assert (base / "agent_analysis_report.json").is_file()
    assert (base / "agent_analysis_report.md").is_file()
    assert "Agent 二次分析报告" in (base / "agent_analysis_report.md").read_text(encoding="utf-8")


def test_raw_article_report_strips_unavailable_chart_parse_noise() -> None:
    document = SourceDocument(
        document_id="jin10-2026-05-26-220232",
        source="jin10_external",
        trade_date="2026-05-26",
        title="测试噪音过滤",
        category="金银报告",
        category_code="270",
        source_url="https://svip.jin10.com/news/220232",
        article_id="220232",
        external_report_dir="/tmp/jin10-220232",
        retrieved_at="2026-05-26T00:00:00+00:00",
        markdown_asset=SourceAssetRef(asset_type="report_md", path="/tmp/report.md", sha256="", size_bytes=0),
        meta_asset=SourceAssetRef(asset_type="meta_json", path="/tmp/meta.json", sha256="", size_bytes=0),
        image_assets=[],
        report_text="""# 测试噪音过滤

## 正文

1、行情回顾：黄金维持震荡。

## 报告图片

![01-chart.jpg](images/01-chart.jpg)

### 图表解析 1

- 图表解析: unavailable (missing_openai_api_key)
""",
        source_refs=[],
    )

    raw_report = build_jin10_raw_article_report(document)

    assert "图表解析: unavailable" not in raw_report.article_markdown
    assert "missing_openai_api_key" not in raw_report.article_markdown
    assert "行情回顾：黄金维持震荡" in raw_report.article_markdown


def test_raw_article_report_strips_legacy_vip_promo_lines_from_existing_report_md() -> None:
    document = SourceDocument(
        document_id="jin10-2026-05-26-220232",
        source="jin10_external",
        trade_date="2026-05-26",
        title="测试旧 report.md 清洗",
        category="金银报告",
        category_code="270",
        source_url="https://svip.jin10.com/news/220232",
        article_id="220232",
        external_report_dir="/tmp/jin10-220232",
        retrieved_at="2026-05-26T00:00:00+00:00",
        markdown_asset=SourceAssetRef(asset_type="report_md", path="/tmp/report.md", sha256="", size_bytes=0),
        meta_asset=SourceAssetRef(asset_type="meta_json", path="/tmp/meta.json", sha256="", size_bytes=0),
        image_assets=[],
        report_text="""# 测试旧 report.md 清洗

## 正文

金十VIP专享 每日金银报告 ，欢迎点击查看！

1、行情回顾：国际现货黄金报4570.33美元/盎司。

更多金银信号和消息汇总，来看今天最新的金银报告！
""",
        source_refs=[],
    )

    raw_report = build_jin10_raw_article_report(document)

    assert "欢迎点击查看" not in raw_report.article_markdown
    assert "更多金银信号和消息汇总" not in raw_report.article_markdown
    assert "国际现货黄金报4570.33美元/盎司" in raw_report.article_markdown


def test_agent_analysis_fallback_uses_raw_weekly_markdown_when_daily_is_unavailable() -> None:
    raw_report = {
        "document_id": "jin10-2026-05-24-220071",
        "trade_date": "2026-05-24",
        "run_id": "220071",
        "article_id": "220071",
        "title": "期权市场发出信号！黄金反转契机已现-金十数据VIP",
        "family": "jin10_raw_article",
        "article_markdown": """
# 黄金
10年期美债收益率继续对黄金价格产生主导影响。如果10年期美债收益率能回落至4.50%下方，那么预计金价将迎来强劲反弹。由于循环支撑/阻力位将在6月至7月期间于5000美元附近交汇，这成为潜在上行目标区。反之，如果收益率继续远高于4.5%，黄金可能承压，6月初支撑将升至4400美元。
纽约商品交易所黄金期权的看跌/看涨期权成交量比率下降，首次进入0.45至0.50区间。
7月黄金期权最大痛点价格为4625美元。
# 白银
白银价格在70美元至84美元循环支撑/阻力位之间盘整筑底，7月白银期权最大痛点价格为72.50美元。
# 交易者持仓报告
COT周期间，金价下跌3.8%，黄金期货未平仓合约OI增加2900份，掉期交易商增加8000份多头并回补1.3万份空头。
# 金银当前主要上行目标
黄金Q3-Q4周期高点在6500美元至7000美元之间。白银目标为120美元、135美元至140美元、170美元至185美元。
""",
        "charts": [{"title": "图表", "image_path": "figures/fig.png"}],
        "source_refs": [{"source": "jin10_external", "article_id": "220071"}],
    }
    daily_report = {
        "family": "jin10_daily_visual",
        "core_conclusion": "证据不足：仅完成文档归档，未形成稳定结论。",
        "market_prices": [],
        "logic_chains": [],
        "watch_variables": [],
        "key_levels": [],
        "scenario_matrix": [],
        "risks": [],
    }

    report = build_jin10_agent_analysis_report(raw_report, daily_report)
    markdown = render_jin10_agent_analysis_markdown(report)

    assert "证据不足" not in report.one_line_conclusion
    assert report.market_stage["label"] == "反转观察窗口"
    assert all("未从正文" not in item for item in report.logic_chain)
    assert report.key_variables[0]["name"] == "10年期美债收益率"
    assert any(row["value"] == "5000" for row in report.key_levels)
    assert "关键位未提及" not in markdown
    assert "证据不足" not in markdown
    assert "4.5%" in markdown
    assert "5000" in markdown
    assert "4400" in markdown
    assert "70-84" in markdown or "70" in markdown and "84" in markdown
    assert "6500" in markdown
    assert "COT" in markdown or "未平仓合约" in markdown


def test_agent_analysis_fallback_extracts_dynamic_levels_without_fixed_template() -> None:
    raw_report = {
        "document_id": "jin10-2026-05-25-dynamic",
        "trade_date": "2026-05-25",
        "run_id": "dynamic",
        "article_id": "dynamic",
        "title": "测试周报：白银突破确认，黄金等待利率回落",
        "family": "jin10_raw_article",
        "article_markdown": """
# 黄金
若10年期美债收益率跌破3.95%，黄金有望重新测试5150美元；若收益率继续上行，黄金可能回踩4320美元。
黄金看涨期权活动回升，看跌保护需求没有扩大，Put/Call成交量比率下降。
# 白银
白银站回88美元才算确认突破，若失守76美元则底部结构延后。
# 总结
当前不是立刻追多，而是等待收益率与价格同时确认。
""",
        "charts": [{"title": "动态图表", "image_path": "figures/dynamic.png"}],
        "source_refs": [{"source": "jin10_external", "article_id": "dynamic"}],
    }
    daily_report = {
        "family": "jin10_daily_visual",
        "core_conclusion": "证据不足",
        "market_prices": [],
        "logic_chains": [],
        "watch_variables": [],
        "key_levels": [],
        "scenario_matrix": [],
        "risks": [],
    }

    report = build_jin10_agent_analysis_report(raw_report, daily_report)
    markdown = render_jin10_agent_analysis_markdown(report)

    assert "3.95%" in markdown
    assert "5150" in markdown
    assert "4320" in markdown
    assert "88" in markdown
    assert "76" in markdown
    assert "4.5%" not in markdown
    assert "5000" not in markdown
    assert "4500-4600" not in markdown


def test_daily_snapshot_conclusion_and_scenarios_follow_input_evidence() -> None:
    base = _document()
    parsed = build_parsed_document(base)
    facts = extract_report_facts(parsed)
    snapshot = build_daily_report_analysis_snapshot(parsed, facts)

    assert "分析师A表示高油价将继续打压国际现货黄金" in snapshot.core_conclusion
    assert any("打压国际现货黄金" in row["summary"] for row in snapshot.scenario_matrix if row["scenario"] == "偏空")
    assert any("央行购金和ETF资金仍提供长期配置支撑" in row["summary"] for row in snapshot.scenario_matrix if row["scenario"] == "偏多")


def test_daily_snapshot_changes_with_different_parsed_markdown() -> None:
    document = SourceDocument(
        document_id="jin10-2026-05-07-218331",
        source="jin10_external",
        trade_date="2026-05-07",
        title="美元回落推动黄金修复，白银等待突破",
        category="报告",
        category_code="270",
        source_url="https://xnews.jin10.com/details/218331",
        article_id="218331",
        external_report_dir="/tmp/jin10-218331",
        retrieved_at="2026-05-07T00:00:00+00:00",
        markdown_asset=SourceAssetRef(asset_type="report_md", path="/tmp/report.md", sha256="", size_bytes=0),
        meta_asset=SourceAssetRef(asset_type="meta_json", path="/tmp/meta.json", sha256="", size_bytes=0),
        image_assets=[],
        report_text="""# 美元回落推动黄金修复，白银等待突破

1、行情回顾：现货黄金报4638.20美元/盎司；现货白银报81.25美元/盎司。

2、关键指标：10年期美债收益率回落，美元指数走弱，市场重新交易降息预期。

3、观点分享：分析师C认为收益率回落给黄金修复创造窗口；分析师D表示白银若站回84美元则弹性会快于黄金。
""",
        source_refs=[{"source": "jin10_external", "article_id": "218331", "asset_type": "report_md"}],
    )

    parsed = build_parsed_document(document)
    facts = extract_report_facts(parsed)
    snapshot = build_daily_report_analysis_snapshot(parsed, facts)

    assert "收益率回落给黄金修复创造窗口" in snapshot.core_conclusion
    assert any("收益率回落" in row["summary"] for row in snapshot.scenario_matrix if row["scenario"] == "偏多")
    assert all("高油价将继续打压国际现货黄金" not in row["summary"] for row in snapshot.scenario_matrix)


def test_agent_analysis_final_summary_reads_like_stage_conclusion_not_static_template() -> None:
    raw_report = {
        "document_id": "jin10-2026-05-26-220232",
        "trade_date": "2026-05-26",
        "run_id": "220232",
        "article_id": "220232",
        "title": "黄金反弹进程受阻，美国“防御性”打击会摧毁和平前景吗？-金十数据VIP",
        "family": "jin10_raw_article",
        "article_markdown": """
# 黄金
2、关键指标：10年期美债收益率从高位回落但仍守在4.5%附近，黄金未获明显提振，反弹止步4580美元后回落。
3、观点分享：金价处于地缘消息与紧缩预期双重夹缝中，短期大概率延续窄幅震荡。
""",
        "charts": [],
        "source_refs": [],
    }
    daily_report = {
        "family": "jin10_daily_visual",
        "core_conclusion": "金价处于地缘消息与紧缩预期双重夹缝中，短期大概率延续窄幅震荡。",
        "market_prices": [],
        "logic_chains": [],
        "watch_variables": [],
        "key_levels": [],
        "scenario_matrix": [],
        "risks": [],
    }

    report = build_jin10_agent_analysis_report(raw_report, daily_report)

    assert "阶段判断" in report.final_summary
    assert "真正会决定后续方向的" in report.final_summary
    assert "机械沿用今天的结论" in report.final_summary


def test_agent_analysis_weekly_report_uses_confirmation_model_and_layered_levels() -> None:
    raw_report = {
        "document_id": "jin10-2026-05-24-220071",
        "trade_date": "2026-05-24",
        "run_id": "220071",
        "article_id": "220071",
        "title": "期权市场发出信号！黄金反转契机已现-金十数据VIP",
        "family": "jin10_raw_article",
        "article_markdown": """
# 黄金
如果10年期美债收益率能回落至4.50%下方，那么预计金价将迎来强劲反弹。由于循环支撑/阻力位将在6月至7月期间于5000美元附近交汇，这成为潜在上行目标区。反之，如果10年期美债收益率继续承压并持续在远高于4.5%的水平交易，那么黄金可能面临持续承压风险。到6月初该支撑位将升至4400美元水平。
纽约商品交易所黄金看涨期权活动在5月13日触及局部低点后开始回升。看跌期权活动徘徊在1.5万份附近筑底。黄金期权看跌/看涨期权成交量比率下降，首次进入0.45至0.50区间。6月黄金期权合约内在价值曲线在4500美元至4600美元之间底部趋于平缓。7月黄金期权最大痛点价格为4625美元。
# 白银
白银价格在70美元至84美元之间盘整筑底，7月白银期权最大痛点价格为72.50美元。白银长期目标包括120美元、135美元至140美元、170美元至185美元。
# 金银当前主要上行目标
黄金长期情景目标为6500美元至7000美元。
""",
        "charts": [{"title": "图表", "image_path": "figures/fig.png"}],
        "source_refs": [{"source": "jin10_external", "article_id": "220071"}],
    }
    daily_report = {"family": "jin10_daily_visual", "core_conclusion": "证据不足", "market_prices": [], "logic_chains": [], "watch_variables": [], "key_levels": [], "scenario_matrix": [], "risks": []}

    report = build_jin10_agent_analysis_report(raw_report, daily_report)
    markdown = render_jin10_agent_analysis_markdown(report)
    level_values = [str(row.get("value")) for row in report.key_levels]

    assert "三确认模型" in markdown
    assert "利率确认" in markdown
    assert "价格确认" in markdown
    assert "期权确认" in markdown
    assert "4400" in markdown and "不是当前基准目标" in markdown
    assert "期权信号失效" in markdown
    assert "4500" in level_values
    assert "4600" in level_values
    assert level_values.count("4.50%") == 1
    assert level_values.count("4500-4600") == 1
    assert level_values.count("6500-7000") == 1
    assert any(row.get("layer") == "long_term" and row.get("value") == "6500-7000" for row in report.key_levels)
    assert any(row.get("layer") == "trading" and row.get("value") == "5000" for row in report.key_levels)
    assert "有效跌破" in markdown
    assert "到期后需要重新评估" in markdown
    assert "4H收盘" in markdown
    assert "日线收盘" in markdown
    assert "成交量确认" in markdown
    assert "持仓确认" in markdown
    assert "Call OI" in markdown
    assert "Agent 入库字段" not in markdown
    assert "agent_stage_label" not in markdown
    assert "trade_stance" not in markdown
    assert "confirmation_level: options_leading_only" not in markdown
    assert "upside_trigger_primary" not in markdown
    assert "valid_until_event" not in markdown
    assert "data_quality_flags" not in markdown
