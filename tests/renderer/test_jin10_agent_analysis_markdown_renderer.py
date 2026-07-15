from __future__ import annotations

from apps.documents.schemas import Jin10AgentAnalysisReport
from apps.renderer.markdown.jin10_agent_analysis import render_jin10_agent_analysis_markdown


def test_render_jin10_agent_analysis_markdown_contains_fixed_sections() -> None:
    report = Jin10AgentAnalysisReport(
        document_id="doc-1",
        trade_date="2026-05-06",
        run_id="218330",
        article_id="218330",
        title="测试日报",
        family="jin10_agent_analysis",
        asset="XAUUSD",
        source_report_family="jin10_daily_visual",
        source_artifact_refs=["storage/outputs/jin10/2026-05-06/218330/raw_article_report.json"],
        one_line_conclusion="黄金处于高位整固与方向抉择并存的观察阶段。",
        provenance=[
            "报告明确事实：黄金与白银价格、PMI、10年期美债收益率来自识别结果。",
            "Agent 分析推论：仅基于识别结果进行条件化推演。",
        ],
        evidence_basis={
            "report_facts": ["黄金最高触及4586.61美元/盎司"],
            "author_views": ["高油价将继续打压国际现货黄金"],
        },
        market_stage={"label": "方向抉择态", "reason": "多空信号并存。"},
        logic_chain=["如果油价维持高位，那么通胀担忧会抬升高利率预期，从而压制黄金机会成本。"],
        key_variables=[
            {"name": "10年期美债收益率", "observation": "持稳", "meaning": "压制金价上行弹性"},
        ],
        gold_analysis="黄金短线受利率与油价预期压制，但悲观情绪过热意味着下方承接不能忽视。",
        silver_analysis="白银跟随贵金属风险偏好波动，未从识别结果中稳定提取更强独立驱动。",
        cross_asset_analysis={
            "美元": "美元若维持偏强，将继续抬升黄金机会成本。",
            "美债": "美债收益率稳定偏高，对黄金形成估值压制。",
            "日元": "未从识别结果中稳定提取。",
            "原油": "油价偏强会抬升通胀担忧，形成条件化压制链条。",
        },
        key_levels=[
            {"label": "黄金最高价", "value": 4586.61, "bias": "压力参考"},
        ],
        scenario_paths=[
            {"path": "主路径", "trigger": "收益率维持高位", "invalid": "收益率明显回落", "risk_points": ["波动放大"]},
            {"path": "修复/强势路径", "trigger": "降息预期修复", "invalid": "美元再度走强", "risk_points": ["数据反复"]},
            {"path": "失败/破位路径", "trigger": "油价再冲高", "invalid": "通胀担忧回落", "risk_points": ["避险切换"]},
        ],
        trading_implications=[
            {
                "stance": "等待确认",
                "trigger": "确认收益率回落后再考虑增配黄金",
                "invalid": "美元与收益率同步走强",
                "risk_points": ["价格剧烈波动"],
                "watch_variables": ["10年期美债收益率", "油价"],
            }
        ],
        risk_points=["报告观点可能带有作者主观偏向。"],
        final_summary="当前更适合条件化跟踪，而不是给出确定性突破判断。",
        unresolved_items=["日元方向未从识别结果中稳定提取。"],
        source_refs=[{"source": "jin10_external", "article_id": "218330"}],
        generated_from={"raw_report_family": "jin10_raw_article", "daily_report_family": "jin10_daily_visual"},
    )

    markdown = render_jin10_agent_analysis_markdown(report)

    assert "Agent 二次分析报告" in markdown
    assert "# 分析溯源 / 数据来源" in markdown
    assert "# 6. 关键位更新" in markdown
    assert "# 风险与仍待确认项" in markdown
    assert "## 确认口径与时间尺度" not in markdown
    assert "## Agent 入库字段" not in markdown
    assert "agent_stage_label: reversal_watch_window" not in markdown
    assert "next_upside_target: unavailable" not in markdown
    assert "next_downside_risk: unavailable" not in markdown
    assert "5000" not in markdown
    assert "4400" not in markdown


def test_render_jin10_agent_analysis_markdown_ignores_legacy_narrative_and_uses_structured_fields() -> None:
    report = Jin10AgentAnalysisReport(
        document_id="doc-1",
        trade_date="2026-05-25",
        run_id="218330",
        article_id="218330",
        title="测试日报",
        family="jin10_agent_analysis",
        asset="XAUUSD",
        source_report_family="jin10_daily_visual",
        source_artifact_refs=[],
        one_line_conclusion="兜底结论",
        provenance=[],
        evidence_basis={},
        market_stage={"label": "方向抉择态", "reason": "测试"},
        logic_chain=[],
        key_variables=[],
        gold_analysis="",
        silver_analysis="",
        cross_asset_analysis={},
        key_levels=[],
        scenario_paths=[],
        trading_implications=[],
        risk_points=[],
        final_summary="",
        unresolved_items=[],
        source_refs=[],
        generated_from={
            "narrative_markdown": """# 测试日报｜Agent 二次分析报告

## 一句话结论

当前反弹不能直接视为反攻信号。

## Agent 入库字段

```yaml
trade_stance: wait_for_confirmation
```

# 3. 报告核心逻辑

- 先看利率确认，再看价格确认。
""",
        },
    )

    markdown = render_jin10_agent_analysis_markdown(report)

    assert "兜底结论" in markdown
    assert "当前反弹不能直接视为反攻信号。" not in markdown
    assert "# 3. 黄金为什么涨 / 为什么跌？" in markdown
    assert "## Agent 入库字段" not in markdown
    assert "trade_stance: wait_for_confirmation" not in markdown


def test_render_update_section_mentions_unconfirmed_and_primary_risk() -> None:
    report = Jin10AgentAnalysisReport(
        document_id="doc-2",
        trade_date="2026-05-26",
        run_id="220232",
        article_id="220232",
        title="测试更新段落",
        family="jin10_agent_analysis",
        asset="XAUUSD",
        source_report_family="jin10_daily_visual",
        source_artifact_refs=[],
        one_line_conclusion="黄金仍处于震荡修复与利率压制并存阶段。",
        provenance=[],
        evidence_basis={"report_facts": [], "author_views": []},
        market_stage={"label": "利率压制态", "reason": "10年期美债收益率回落有限，价格修复未扩展。"},
        logic_chain=["收益率没有继续下行，价格修复也缺少放量确认。"],
        key_variables=[],
        gold_analysis="",
        silver_analysis="",
        cross_asset_analysis={},
        key_levels=[{"label": "黄金支撑/分界位", "value": "4500"}],
        scenario_paths=[],
        trading_implications=[],
        risk_points=["若收益率重新走高，黄金可能回到更弱的震荡区间。"],
        final_summary="",
        unresolved_items=["当前尚未确认收益率是否会有效跌破报告中的关键分界位。"],
        source_refs=[],
        generated_from={},
    )

    markdown = render_jin10_agent_analysis_markdown(report)

    assert "本次仍未确认的部分主要是" in markdown
    assert "如果后续出现反向变化，优先警惕" in markdown
    assert "4500" in markdown


def test_render_trading_implications_reads_like_guidance_not_field_dump() -> None:
    report = Jin10AgentAnalysisReport(
        document_id="doc-3",
        trade_date="2026-05-27",
        run_id="220300",
        article_id="220300",
        title="测试执行含义",
        family="jin10_agent_analysis",
        asset="XAUUSD",
        source_report_family="jin10_daily_visual",
        source_artifact_refs=[],
        one_line_conclusion="当前修复信号仍需等待收益率和价格双确认。",
        provenance=[],
        evidence_basis={"report_facts": [], "author_views": []},
        market_stage={"label": "修复反弹态", "reason": "价格修复存在，但确认条件未完成。"},
        logic_chain=["当前反弹更多是修复，不是趋势确认。"],
        key_variables=[],
        gold_analysis="",
        silver_analysis="",
        cross_asset_analysis={},
        key_levels=[],
        scenario_paths=[],
        trading_implications=[
            {
                "stance": "先观察，等确认",
                "trigger": "10年期美债收益率继续回落，且黄金站回关键修复位",
                "invalid": "收益率重新抬升且黄金跌回支撑下方",
                "risk_points": ["修复被数据反向打断"],
                "watch_variables": ["10年期美债收益率", "黄金关键修复位"],
            }
        ],
        risk_points=[],
        final_summary="",
        unresolved_items=[],
        source_refs=[],
        generated_from={},
    )

    markdown = render_jin10_agent_analysis_markdown(report)

    assert "当前更适合的做法是" in markdown
    assert "只有当以下条件出现" in markdown
    assert "当前判断需要回撤或重做" in markdown
    assert "修复被数据反向打断" in markdown


def test_renderer_omits_missing_optional_guidance_fields_and_duplicate_suffixes() -> None:
    report = Jin10AgentAnalysisReport(
        document_id="doc-4",
        trade_date="2026-07-16",
        run_id="224688",
        article_id="224688",
        title="测试日报｜Agent 二次分析报告",
        family="jin10_agent_analysis",
        asset="XAUUSD",
        source_report_family="jin10_daily_visual",
        source_artifact_refs=[],
        one_line_conclusion="修复仍待确认。",
        provenance=[],
        evidence_basis={"report_facts": [], "author_views": []},
        market_stage={"label": "修复反弹态", "reason": "确认不足。"},
        logic_chain=[],
        key_variables=[],
        gold_analysis="",
        silver_analysis="",
        cross_asset_analysis={},
        key_levels=[],
        scenario_paths=[{
            "name": "主路径",
            "path": "维持区间观察。",
            "trigger": "价格未突破确认区。",
            "invalid": "价格突破确认区。",
        }],
        trading_implications=[{
            "role": "空仓",
            "wait_for": "等待价格和宏观共振。",
            "invalid": "价格跌破支撑。",
        }],
        risk_points=[],
        final_summary="等待确认。",
        unresolved_items=[],
        source_refs=[],
        generated_from={},
    )

    markdown = render_jin10_agent_analysis_markdown(report)

    assert markdown.count("Agent 二次分析报告") == 1
    assert "- 风险点：\n" not in markdown
    assert "- 置信度：\n" not in markdown
    assert "unavailable" not in markdown
    assert "。。" not in markdown
    assert markdown.count("等待价格和宏观共振") == 1
    assert "当前更适合的做法是：等待价格和宏观共振。" in markdown
