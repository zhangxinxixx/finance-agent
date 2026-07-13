from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from apps.analysis.jin10.agent_prompt_profiles import typed_report_prompt_spec
from apps.analysis.jin10.multimodal import ImageLoader, build_multimodal_user_content
from apps.documents.schemas import Jin10AgentAnalysisReport, Jin10DailyAnalysisReport, Jin10RawArticleReport

MISSING = "未从识别结果中稳定提取"
DEFAULT_STAGE = "方向抉择态"
DEFAULT_JIN10_AGENT_PROVIDER = "cockpit"
DEFAULT_JIN10_AGENT_MODEL = "gpt-5.6-sol"
DEFAULT_JIN10_AGENT_REASONING_EFFORT = "high"
DEFAULT_JIN10_AGENT_REQUEST_TIMEOUT = 300.0
DEFAULT_JIN10_AGENT_MAX_TOKENS = 4096
DEFAULT_JIN10_AGENT_MAX_IMAGES = 25
STAGE_LABELS = (
    "利率压制态",
    "流动性踩踏态",
    "修复反弹态",
    "高位整固态",
    "方向抉择态",
    "突破前蓄势态",
    "日线周期上涨阶段",
    "趋势顺风态",
    "中长期配置逻辑强化",
    "独立重估阶段",
    "弱修复观察期",
    "关键支撑保卫战",
)


def build_agent_analysis_prompt(
    raw_report: dict[str, Any],
    daily_report: dict[str, Any] | None = None,
    *,
    previous_daily_analysis: dict[str, Any] | None = None,
) -> str:
    """Build the future LLM prompt for Jin10 raw-report post analysis."""

    daily_block = _compact_daily_summary(daily_report) if daily_report else "未提供 daily_analysis 结构化摘要。"
    charts = raw_report.get("charts") or []
    article_context = dict((raw_report.get("generated_from") or {}).get("article_context") or {})
    chart_lines = [
        f"- 图表 {chart.get('seq')}: title={chart.get('title') or MISSING}; caption={chart.get('caption') or MISSING}; summary={chart.get('summary') or MISSING}; image_path={chart.get('image_path') or MISSING}"
        for chart in charts
    ]
    chart_block = "\n".join(chart_lines) if chart_lines else f"- {MISSING}"
    paragraph_block = "\n".join(f"- {item}" for item in article_context.get("paragraph_snippets") or []) or f"- {MISSING}"
    key_sentence_block = "\n".join(f"- {item}" for item in article_context.get("key_sentences") or []) or f"- {MISSING}"
    section_lines = [
        f"- heading={item.get('heading') or MISSING}; summary={item.get('summary') or MISSING}; paragraph_count={item.get('paragraph_count') or 0}"
        for item in article_context.get("sections") or []
    ]
    section_block = "\n".join(section_lines) if section_lines else f"- {MISSING}"
    chart_anchor_lines = [
        f"- title={item.get('title') or MISSING}; image_path={item.get('image_path') or MISSING}; before={item.get('before') or MISSING}; after={item.get('after') or MISSING}; summary={item.get('summary') or MISSING}"
        for item in article_context.get("chart_anchors") or []
    ]
    chart_anchor_block = "\n".join(chart_anchor_lines) if chart_anchor_lines else f"- {MISSING}"
    level_snippet_block = "\n".join(f"- {item}" for item in article_context.get("level_snippets") or []) or f"- {MISSING}"
    chart_summary_block = "\n".join(f"- {item}" for item in article_context.get("chart_summaries") or []) or f"- {MISSING}"
    previous_block = _compact_previous_analysis(previous_daily_analysis)
    chart_render_mode = str(article_context.get("chart_render_mode") or "none")
    chart_mode_note = (
        "当前图表为页图 fallback：仅代表归档页面截图，不代表已经完成逐图结构化解析；若缺少图表摘要或邻近正文，不要把页图本身当成强图表证据。"
        if chart_render_mode == "fallback_compact"
        else "当前图表证据可按正常结构化图表/截图摘要使用，但仍需区分事实、观点和推论。"
    )
    if _is_market_observation_report(raw_report=raw_report, daily_report=daily_report):
        return _build_market_observation_prompt(
            raw_report=raw_report,
            daily_report=daily_report,
            daily_block=daily_block,
            chart_block=chart_block,
            paragraph_block=paragraph_block,
            key_sentence_block=key_sentence_block,
            section_block=section_block,
            chart_anchor_block=chart_anchor_block,
            level_snippet_block=level_snippet_block,
            chart_summary_block=chart_summary_block,
            chart_render_mode=chart_render_mode,
            chart_mode_note=chart_mode_note,
        )
    prompt_profile = _agent_analysis_prompt_profile(raw_report=raw_report, daily_report=daily_report)
    if prompt_profile != "default_daily":
        return _build_typed_report_analysis_prompt(
            prompt_profile=prompt_profile,
            raw_report=raw_report,
            daily_report=daily_report,
            daily_block=daily_block,
            chart_block=chart_block,
            paragraph_block=paragraph_block,
            key_sentence_block=key_sentence_block,
            section_block=section_block,
            chart_anchor_block=chart_anchor_block,
            level_snippet_block=level_snippet_block,
            chart_summary_block=chart_summary_block,
            chart_render_mode=chart_render_mode,
            chart_mode_note=chart_mode_note,
        )
    return f"""你是一名专业的宏观市场与贵金属分析 Agent，默认使用简体中文。

任务：仅基于下方 Jin10 报告识别结果、图表清单与结构化摘要，写一份更接近日报研究会话风格的黄金市场二次分析报告。

写作目标：
- 先给结论，再讲“相对前序判断当前有哪些更新”，再展开逻辑、关键位、触发条件和风险。
- 重点写黄金，再写白银；跨资产只保留和黄金定价直接相关的内容。
- 让每天的报告都体现新增确认、降温、反复或失效，避免写成模板化百科摘要。
- 整体语气更像盘后研究会话或交易员复盘，不像合规说明、研究院长报告或结构化审计文。

硬性规则：
1. 不主动联网，不引入输入材料之外的实时行情或历史数据。
2. 必须区分：报告明确事实、报告作者观点、图表支持、Agent 分析推论、尚未确认部分。
3. 不把报告观点包装成事实；必要时用“报告认为”“图表显示”“我的推论是”。
4. 不给确定性预测；所有交易判断都要写触发条件、失效条件、风险点、关键观察变量。
5. 缺失内容写“{MISSING}”，不要补造。
6. 不输出 YAML、JSON 或 Agent 入库字段；那些是存储字段，不属于人读报告正文。
7. 正文不要使用大段复杂表格；关键位允许使用紧凑列表或紧凑表格。
8. 不得把前序报告价位写成本次报告明确事实；关键位来源要区分本次报告、前序延续、图表线索、Agent 保留框架。
9. 不得输出无条件交易建议，所有操作判断必须绑定触发条件、失效条件和风险点。
10. 少写“我的推论是”“需要说明的是”“这里需要注意”这类审查口吻，优先写成盘后研究会话风格；只有在证据不足或来源需要切分时再显式说明。
11. 如果 `previous_daily_analysis` 明确存在，默认先写“前序判断偏什么 / 本次为什么降温或强化”，不要把变化对比埋到正文中段。
12. 若 `previous_daily_analysis` 已给出连续关键位框架，且本次报告没有直接推翻，三条路径推演必须优先复用这组价位骨架，而不是完全退回抽象表述。
13. 开头两段必须足够短、足够硬：先直接点“前序偏什么，本次为什么降温/强化”，不要先铺背景。
14. `分析溯源 / 数据来源` 最多 3 句，不要再解释“事实/观点/推论”分类方法。
15. `操作层面怎么理解？` 每类角色尽量控制在 2-4 句，先写“先等什么确认”，再写“什么情况下失效”，避免长段解释。
16. 前序报告的价位链只能在同一时间尺度和证据层级内延续；近端确认位、动态期权锚和远期模型目标必须拆开，不得拼成自然连续上涨路径。
17. 能用短句说清时，不要展开成长段；能用“先看什么，再看什么；没发生什么，就不能说什么”就不要写概念解释。
18. 除非输入材料强要求，否则不要单独展开“三确认模型”小节，可把确认条件揉进关键位、路径推演和操作层面。
19. 证据来源必须使用明确类别：`图表事实`、`COT 数据事实`、`报告作者预测`、`报告作者解释`、`Agent 综合推论`、`前序框架延续`；不得笼统写成“本期报告明确”。
20. 仅有 Put/Call 成交量或单边成交量变化时，只能写“下行保护需求降温”或“阶段底部线索增强”；缺少 Put OI、Call OI、隐含波动率或新开/平仓方向时，禁止写“期权见底”“底部已经形成”“趋势反转确认”。
21. CFTC 的“其他可报告交易商”不得直接等同于价值型资金。只能确认该类别持仓变化；“偏价值型承接”必须明确归属于报告作者解释，并同时检查空头、净多、总持仓和占比分母是否可得。
22. COT 属于周频滞后数据，只能作为中期承接或仓位背景，不能用于确认报告日当天或日内突破。现货、期权成交、期权 OI、COT、长期周期模型必须分别注明数据时效。
23. 最大痛点是随持仓和到期时间变化的动态参考锚，不是稳定目标位。临近到期且 OI 结构明确时才可提高权重；不得把最大痛点与远期结构目标写成自然连续上涨路径。
24. 长期周期模型目标必须标为低权重作者情景；输入未提供模型参数、历史样本、命中率、误差范围或失效条件时，不得进入短中期交易评分和当前价格路径。
25. “有效突破”“站稳”“持续下降”“明显回升”“重新放大”等词必须绑定周期与判定口径。输入没有经过回测的阈值时，应写“判定阈值待回测/未提供”，不得自行发明精确 bp、均线或收盘次数。
26. 利率判断至少检查 10Y 名义收益率、实际收益率、2Y 收益率、2Y-3M 利差四项。缺失项必须写“未确认”，不得仅凭名义收益率概括为宏观已经转松。
27. 若输入提供同一时点当前价和预计区间，可计算 `区间位置=(当前价-下沿)/(上沿-下沿)`，并说明当前处于下半部、中性区或上半部；缺少同一时点当前价时不得估算。
28. 管理资金空头占比较低属于双向信号：既表示趋势性做空不拥挤，也意味着后续逼空燃料可能有限；默认按中性证据处理。
29. 标题优先使用“线索增强”“需求降温”“尚待确认”等条件化措辞。除非价格、OI、波动率与宏观变量共同确认，否则禁止使用“先见底”“反转完成”“上涨启动”。

阶段标签可选：{', '.join(STAGE_LABELS)}。

推荐主框架如下。前 1-3 节必须保留；其余标题可轻微调整，但语义必须覆盖：
# <标题>｜Agent 二次分析报告
## 一句话结论
# 分析溯源 / 数据来源
# 1. 最新判断发生了什么变化？
# 2. 报告中的行情回顾
# 3. 黄金为什么涨 / 为什么跌？
# 4. 报告核心观点：短线、中期、长期分开
# 5. 当前阶段判断与确认矩阵
# 6. 关键位更新
# 7. 三条路径推演
# 8. 操作层面怎么理解？
# 最终综合判断

关键要求：
- `一句话结论` 要直接回答当前更接近修复、承压、整固还是趋势延续；如果输入里有明确关键位，必须点名，同时说明底部线索和趋势反转是否已经确认。
- `最新判断发生了什么变化？` 是全文重点，要优先写今天相对前序判断新增确认了什么、哪些被降温、哪些逻辑仍未失效；如果没有 previous_daily_analysis，就如实写本次新增确认 / 仍未确认。
- 如果存在 `previous_daily_analysis`，默认先用一句短句概括“前序偏乐观/偏修复/偏承压，本次转为降温/强化/延后”，然后再展开。
- 如果存在 `previous_daily_analysis`，开篇优先显式写出“前序判断是什么 -> 本次被什么变量打断或强化 -> 当前该把哪条路径降级”，不要先写抽象阶段名。
- `报告中的行情回顾` 只保留与后续判断直接相关的行情与数据，不要把全文逐段改写。
- `黄金为什么涨 / 为什么跌？` 要用“数据或事件 -> 市场预期 -> 利率/美元/资金 -> 黄金”的链路表达，最多 2-4 条。
- `报告核心观点：短线、中期、长期分开` 必须区分交易压力、修复/震荡逻辑和长期配置逻辑。
- `当前阶段判断与确认矩阵` 要给出黄金主判断，并固定列出：阶段、底部证据、趋势反转证据、价格确认、宏观确认、资金确认。`底部证据`和`趋势反转证据`只能使用“强/中等/偏弱”；`价格确认`、`宏观确认`和`资金确认`只能使用“已完成/部分完成/未完成”，不得混用量表。若价格仍在作者预计区间内且尚未突破第一确认位，`价格确认`必须写“未完成”。每项附一句证据或缺口。另补一句白银相对黄金的弹性/联动；白银证据不足时必须明确。
- 如果本次报告已经明确跌破某个前序关键分界位，阶段名优先写成“某分界位失守后的方向抉择偏承压/偏修复”，不要过早写成“支撑保卫战”；真正的支撑保卫区放到下一句写清具体区间。
- `关键位更新` 只解释输入材料、前序判断或结构化摘要中明确出现的关键价格、区间或分界位；来源类别只能从“图表事实 / COT数据事实 / 报告作者预测 / 报告作者解释 / Agent综合推论 / 前序框架延续”中选择。
- 若提供了 `previous_daily_analysis`，允许继承其中仍未被当前报告否定的关键位框架，但必须明确标注为“前序报告延续”或“Agent 基于前序框架保留”，不得伪装成本次报告直接给出的事实。
- `关键位更新` 优先输出为紧凑表格或紧凑列表；至少覆盖“价格 / 品种 / 来源类别 / 当前含义”四列或四项。
- `关键位更新` 默认拆成两组：`短中线交易位` 与 `中长期参考位`。前者放交易分界位、修复确认位、突破确认位、下方防守位；后者放机构目标价、历史高位、长期情景位。两组不要混排。
- 若前序报告已经给出一组连续关键位，先区分近端价格确认位、动态期权参考位和远期结构情景。只有同一时间尺度、同一证据层级的价位才允许连成路径。
- 若本次报告没有推翻前序底部位或目标区，要明确写“前序底部位仍可观察，但当前先降级到先收复哪个位再谈下一档”，避免只保留近端价位。
- 若存在相邻的下方观察位或底部观察位，优先合并表达为连续支撑区/保卫区，而不是拆成两个孤立点。
- 中长期机构目标价、历史高位描述必须和短线交易位分组展示，不得混在同一短线表里。
- `三条路径推演` 必须包含主路径、修复/上行路径、失败/下行路径，每条都写触发条件，不写确定性预测。近端路径只使用当前区间、价格确认位和失效位；最大痛点只作为次级动态参考，远期结构目标不得直接接在近端路径之后。
- `操作层面怎么理解？` 要体现空仓、已有多单、已有空单分别要等什么确认、什么情况下失效。
- `最终综合判断` 用 3-5 条短句收束：当前阶段、最大新增变量、最重要关键位、中长期逻辑是否失效、下一步观察条件。
- 如果报告出现期权领先信号，要明确“期权领先但现货未确认”，并写出失效条件：跌破平衡区无法收回、Put 保护重新放大、Call 回升但 OI 不增加、到期后锚定区失效等。
- 如果报告出现收益率确认位、价格修复位和期权信号，把确认条件融进关键位、路径推演和操作层面即可；除非非常必要，不要单独起一个“三确认模型”大段。
- 利率确认要明确区分“盘中刺破”和“有效跌破”；价格确认要明确写周期口径，例如 4H 收盘、日线收盘。
- 期权确认必须分两层：成交量确认（Call volume 回升、Put volume 不扩张）与持仓确认（Call OI 增加、Put OI 未明显增加）；如果只有成交量没有 OI，要标注可能只是短线换手。
- 期权证据应明确列出四种组合：Put 成交下降且 Put OI 下降=保护真正退潮；Put 成交下降但 Put OI 上升=底部信号有限；Call 成交上升且 Call OI 上升=主动看涨资金进入；Call 成交上升但 Call OI 不升=更可能是短线换手。缺少对应 OI 时只给中等或偏弱辅助权重。
- COT 解读必须注明统计截止日/发布时间差；管理资金低空头要同时写“无拥挤空头”和“逼空燃料有限”两面，不得单独作为底部确认。
- 利率部分固定检查 10Y 名义收益率、实际收益率、2Y 收益率、2Y-3M 利差，并分别标记改善、恶化、中性或未确认；没有输入值就写未确认。
- 若报告给出未来预计运行区间，必须标为“报告作者预测”，不能标为市场事实；只有已经观察到的价格、成交、持仓和图表读数才能列为事实。
- Put/Call 关键区间只能作为历史观察信号，不是单独交易信号，必须和利率、价格确认共同使用。
- 允许使用少量箭头逻辑，但不要整段使用代码块表现。
- 同一条逻辑只详细解释一次，后文只引用，不重复铺陈。
- 不要把全文写成“合规审查说明”或“证据说明文”；正文要更像给交易员的日报复盘。
- 操作层面尽量短句化，避免每段都写成长说明。
- 尽量多用“先看什么，再看什么；没发生什么，就不能说什么”这种交易语言。
- `分析溯源 / 数据来源` 控制在短块内，优先交代是否联网、用了哪些输入、前序框架是否引用，不要展开成长说明。
- 如果前序判断与本次判断存在明显反差，允许在开头直接下结论，例如“前序偏修复，本次被强 PMI 和鹰派利率重新压回 4500 下方”，然后再展开。
- 更偏向“05-31 乐观 -> 06-02 降温”的变化表达，不偏向“证据_basis / inference_scope”这类存档词汇。

=== raw_report 基本信息 ===
trade_date: {raw_report.get('trade_date') or MISSING}
article_id: {raw_report.get('article_id') or MISSING}
title: {raw_report.get('title') or MISSING}
source_url: {raw_report.get('source_url') or MISSING}

=== raw_report article_markdown ===
{str(raw_report.get('article_markdown') or '').strip()}

=== 正文关键片段 ===
{paragraph_block}

=== 关键句 / 导读 / 关键位片段 ===
{key_sentence_block}

=== 正文章节摘要 ===
{section_block}

=== 图表前后文锚点 ===
{chart_anchor_block}

=== 关键位 / 利率 / 期权证据片段 ===
{level_snippet_block}

=== 图表清单 ===
{chart_block}

=== 图表摘要线索 ===
{chart_summary_block}

=== 图表渲染模式 ===
chart_render_mode: {chart_render_mode}
- {chart_mode_note}

=== daily_analysis 结构化摘要 ===
{daily_block}

=== previous_daily_analysis（若存在） ===
{previous_block}

写作细节：
- 优先提炼最关键的图表或数据支持，不必预设图表类型。
- 如果正文不足但图表摘要和关键句存在，必须如实说明“正文证据有限，但图表/摘要显示……”，不要假装拿到了完整长文。
- 如果 `chart_render_mode = fallback_compact`，必须把图表部分当成“页图 fallback 线索”，不要写成“图表已经确认/显示了完整结构信号”。
- 如果报告给出了明确价格与区间，必须写进判断，不要只写抽象方向。
- 用贴近盘面与策略讨论的表述，优先写“今天相对前序判断发生了什么变化”，但不要被某一篇样本的固定措辞绑定。
- 如果 `previous_daily_analysis` 明确给出了阶段、关键位或目标区，而本次报告又没有直接推翻，允许把它们保留为“前序框架”；但必须明确哪些内容已经被本次报告降温、延后或改为条件成立后才有效。
- 传导链、黄金路径、白银路径可以由模型自行组织，不必机械套模板。
- 不要出现“当前会话形成的核心判断脉络”“当前会话形成的关键位体系”这类会话内元表述。

请只输出 Markdown 报告正文。"""


def _agent_analysis_prompt_profile(*, raw_report: dict[str, Any], daily_report: dict[str, Any] | None) -> str:
    daily = daily_report or {}
    generated_from = daily.get("generated_from") if isinstance(daily.get("generated_from"), dict) else {}
    report_type = str(daily.get("report_type") or generated_from.get("report_type") or "").strip().lower()
    family = str(daily.get("family") or "").strip()
    if report_type in {"daily", "weekly"} or family in {"jin10_daily_visual", "jin10_weekly_visual"}:
        return "default_daily"
    if _is_market_observation_report(raw_report=raw_report, daily_report=daily_report):
        return "market_observation"
    text = " ".join(
        str(item or "")
        for item in (
            raw_report.get("title"),
            raw_report.get("article_markdown"),
            daily.get("title"),
            daily.get("family"),
            daily.get("report_type"),
            (daily.get("generated_from") or {}).get("report_type") if isinstance(daily.get("generated_from"), dict) else "",
        )
    )
    if report_type in {"market_observation", "positioning", "technical_levels", "oil", "fx"}:
        return report_type
    if family == "jin10_positioning_report" or "持仓报告" in text:
        return "positioning"
    if family == "jin10_technical_levels_report" or "技术刘" in text or "点位报告" in text:
        return "technical_levels"
    if family == "jin10_oil_report" or "原油报告" in text:
        return "oil"
    if family == "jin10_fx_report" or "外汇报告" in text:
        return "fx"
    return "default_daily"


def agent_analysis_prompt_version(raw_report: dict[str, Any], daily_report: dict[str, Any] | None = None) -> str:
    if _is_market_observation_report(raw_report=raw_report, daily_report=daily_report):
        return "jin10_agent_analysis_market_observation_v1"
    profile = _agent_analysis_prompt_profile(raw_report=raw_report, daily_report=daily_report)
    return f"jin10_agent_analysis_{profile}_v1" if profile != "default_daily" else "jin10_agent_analysis_v3"


def _is_market_observation_report(*, raw_report: dict[str, Any], daily_report: dict[str, Any] | None) -> bool:
    daily = daily_report or {}
    generated_from = daily.get("generated_from") if isinstance(daily.get("generated_from"), dict) else {}
    explicit_report_type = str(daily.get("report_type") or generated_from.get("report_type") or "").strip().lower()
    if explicit_report_type and explicit_report_type != "market_observation":
        return False
    text = " ".join(
        str(item or "")
        for item in (
            raw_report.get("title"),
            daily.get("title"),
            raw_report.get("article_markdown"),
            daily.get("family"),
            daily.get("report_type"),
        )
    )
    return (
        daily.get("family") == "jin10_market_observation_report"
        or daily.get("report_type") == "market_observation"
        or any(marker in text for marker in ("每日市场观察", "VIP每日市场观察", "市场赔率表", "市场赔率数据表"))
    )


def _market_observation_kind(*values: str | None) -> str:
    text = " ".join(value or "" for value in values)
    if any(marker in text for marker in ("市场赔率数据表", "市场赔率表", "赔率表")):
        return "市场赔率"
    if any(marker in text for marker in ("每日市场观察", "VIP每日市场观察")):
        return "市场观察"
    return "市场观察"


def _typed_report_prompt_spec(prompt_profile: str) -> dict[str, str]:
    return typed_report_prompt_spec(prompt_profile)


def _build_typed_report_analysis_prompt(
    *,
    prompt_profile: str,
    raw_report: dict[str, Any],
    daily_report: dict[str, Any] | None,
    daily_block: str,
    chart_block: str,
    paragraph_block: str,
    key_sentence_block: str,
    section_block: str,
    chart_anchor_block: str,
    level_snippet_block: str,
    chart_summary_block: str,
    chart_render_mode: str,
    chart_mode_note: str,
) -> str:
    spec = _typed_report_prompt_spec(prompt_profile)
    return f"""你是一名专业的{spec['persona']}，默认使用简体中文。

任务：{spec['task']}

材料类型：{spec['name']}

专用分析规则：
{spec['rules']}

通用硬规则：
1. 不主动联网，不引入输入材料之外的实时行情、价格、概率或新闻。
2. 必须区分：报告明确事实、图表/页图线索、报告作者观点、Agent 辅助解读、仍需确认部分。
3. 不给确定性预测；任何交易或观察含义都必须绑定触发条件、失效条件和风险点。
4. 缺失内容写“{MISSING}”，不要补造。
5. 不输出 YAML、JSON 或 Agent 入库字段。
6. 这不是固定金银日报 prompt；不要机械输出“最新判断发生了什么变化 / 黄金为什么涨跌 / 三条路径推演”。

推荐主框架如下，标题可以贴合材料，但章节语义必须覆盖：
{spec['framework']}

写作要求：
- `一句话结论` 直接说明这份专项报告最重要的结构变化，必须体现材料类型。
- `分析溯源 / 数据来源` 最多 3 句，只说明用了哪些归档输入、是否有图像/OCR 限制。
- 专项章节要优先引用报告内明确数字、点位、手数、百分比、概率或指标；没有就写缺失。
- 对黄金的影响必须按该报告类型的传导链写，不能把所有报告都改写成每日金银报告。
- 如果 `chart_render_mode = fallback_compact`，必须把图表部分当成“页图 fallback 线索”，不要写成已经完整结构化确认。

=== raw_report 基本信息 ===
trade_date: {raw_report.get('trade_date') or MISSING}
article_id: {raw_report.get('article_id') or MISSING}
title: {raw_report.get('title') or MISSING}
source_url: {raw_report.get('source_url') or MISSING}

=== raw_report article_markdown ===
{str(raw_report.get('article_markdown') or '').strip()}

=== 正文关键片段 ===
{paragraph_block}

=== 关键句 / 导读 / 关键位片段 ===
{key_sentence_block}

=== 正文章节摘要 ===
{section_block}

=== 图表前后文锚点 ===
{chart_anchor_block}

=== 关键位 / 利率 / 期权证据片段 ===
{level_snippet_block}

=== 图表清单 ===
{chart_block}

=== 图表摘要线索 ===
{chart_summary_block}

=== 图表渲染模式 ===
chart_render_mode: {chart_render_mode}
- {chart_mode_note}

=== structured_analysis 摘要 ===
{daily_block}

请只输出 Markdown 报告正文。"""


def _build_market_observation_prompt(
    *,
    raw_report: dict[str, Any],
    daily_report: dict[str, Any] | None,
    daily_block: str,
    chart_block: str,
    paragraph_block: str,
    key_sentence_block: str,
    section_block: str,
    chart_anchor_block: str,
    level_snippet_block: str,
    chart_summary_block: str,
    chart_render_mode: str,
    chart_mode_note: str,
) -> str:
    kind = _market_observation_kind(str(raw_report.get("title") or ""), str(raw_report.get("article_markdown") or ""))
    return f"""你是一名专业的宏观市场观察与赔率数据分析 Agent，默认使用简体中文。

任务：仅基于下方 Jin10 市场观察 / 市场赔率材料，写一份“辅助决策证据”分析。不要套用每日金银报告，不要把它写成黄金日报，不要沿用“黄金为什么涨 / 为什么跌”“三条路径推演”“前序日报判断”这些固定日报模板。

材料类型：{kind}

市场观察 / 市场赔率专用分析规则：
1. 不主动联网，不引入输入材料之外的实时行情、概率、价格或新闻。
2. 先看材料本身：它在观察哪几个市场，概率/赔率变化指向什么，哪些只是触及概率而不是方向预测。
3. 必须区分“赔率隐含预期”“作者观察”“Agent 辅助解读”“仍需盘面确认”。
4. 这是辅助证据，不是主判断；不能把单源赔率或观察直接升级为交易结论。
5. 市场赔率要按品种拆读：黄金、白银、原油、美元/日元、就业/美联储路径、航运/地缘或其他报告中出现的变量。
6. 每个变量尽量写“赔率变化 -> 市场预期 -> 对黄金/风险偏好/美元/原油的辅助含义 -> 失效条件”。
7. 如果材料只有图片或页图 fallback，明确写“图像证据可见但结构化抽取有限”；如果正文已提供概率数据，必须优先引用正文里的具体概率，不得再说没有内容。
8. 不输出 YAML、JSON 或 Agent 入库字段。

推荐主框架如下，标题可以贴合材料，但章节语义必须覆盖：
# <标题>｜市场观察辅助分析
## 一句话结论
# 分析溯源 / 数据来源
# 1. 这份材料在观察什么？
# 2. 核心赔率 / 观察信号
# 3. 赔率和观察信号怎么读？
# 4. 对黄金、原油、美元/日元和风险资产的辅助含义
# 5. 作为辅助决策依据怎么用？
# 6. 需要继续确认什么？
# 最终综合判断

写作要求：
- `一句话结论` 必须直接说明这份材料偏“市场观察”还是“市场赔率”，以及最核心的辅助信号。
- `核心赔率 / 观察信号` 要列出材料中明确出现的概率、价位、时间窗口或市场变量；没有就写缺失，不补造。
- `赔率和观察信号怎么读？` 要强调赔率是预期分布和触及概率，不等于价格路径承诺。
- `辅助含义` 只写对主决策的支持、削弱或风险提示，不输出确定性多空。
- `需要继续确认什么？` 写后续要看哪些行情、利率、美元、就业或地缘变量验证这份辅助信号。

=== raw_report 基本信息 ===
trade_date: {raw_report.get('trade_date') or MISSING}
article_id: {raw_report.get('article_id') or MISSING}
title: {raw_report.get('title') or MISSING}
source_url: {raw_report.get('source_url') or MISSING}

=== raw_report article_markdown ===
{str(raw_report.get('article_markdown') or '').strip()}

=== 正文关键片段 ===
{paragraph_block}

=== 关键句 / 导读 / 关键位片段 ===
{key_sentence_block}

=== 正文章节摘要 ===
{section_block}

=== 图表前后文锚点 ===
{chart_anchor_block}

=== 关键位 / 利率 / 期权证据片段 ===
{level_snippet_block}

=== 图表清单 ===
{chart_block}

=== 图表摘要线索 ===
{chart_summary_block}

=== 图表渲染模式 ===
chart_render_mode: {chart_render_mode}
- {chart_mode_note}

=== structured_analysis 摘要 ===
{daily_block}

请只输出 Markdown 报告正文。"""


def parse_agent_analysis_markdown(text: str) -> str:
    markdown = text.strip()
    if markdown.startswith("```"):
        lines = markdown.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        markdown = "\n".join(lines).strip()
    return markdown


def sanitize_agent_analysis_markdown(text: str) -> str:
    markdown = parse_agent_analysis_markdown(text)
    markdown = re.sub(
        r"(?ms)^##\s*Agent 入库字段\s*\n.*?(?=^#{1,6}\s|\Z)",
        "",
        markdown,
    )
    markdown = re.sub(
        r"(?ms)^#{1,6}\s*Agent 入库字段\s*\n(?:```[\s\S]*?```\s*|.+?(?=^#{1,6}\s|\Z))",
        "",
        markdown,
    )
    markdown = re.sub(r"(?ms)^```ya?ml\s*[\s\S]*?agent_stage_label:[\s\S]*?```\s*", "", markdown)
    markdown = re.sub(r"\n{3,}", "\n\n", markdown).strip()
    return markdown


def build_jin10_agent_analysis_report(
    raw_report: Jin10RawArticleReport | dict[str, Any],
    daily_report: Jin10DailyAnalysisReport | dict[str, Any] | None = None,
) -> Jin10AgentAnalysisReport:
    raw = _to_dict(raw_report)
    daily = _to_dict(daily_report) if daily_report is not None else {}
    title = str(raw.get("title") or daily.get("title") or "Jin10 黄金报告")
    article = str(raw.get("article_markdown") or "")
    article_context = _extract_article_context(article)
    raw_context = dict((raw.get("generated_from") or {}).get("article_context") or {})
    article_context["raw_context"] = raw_context
    conclusion = _one_line_conclusion(title, daily, article_context)
    logic = _logic_chain(daily, article_context)
    risks = _risk_points(daily, article_context)
    levels = _key_levels(daily, article_context)
    variables = _key_variables(daily, article_context)
    source_refs = list(raw.get("source_refs") or daily.get("source_refs") or [])
    return Jin10AgentAnalysisReport(
        document_id=str(raw.get("document_id") or daily.get("document_id") or ""),
        trade_date=str(raw.get("trade_date") or daily.get("trade_date") or ""),
        run_id=str(raw.get("run_id") or daily.get("run_id") or raw.get("article_id") or ""),
        article_id=str(raw.get("article_id") or daily.get("article_id") or ""),
        title=title,
        family="jin10_agent_analysis",
        asset=str(daily.get("asset") or "XAUUSD"),
        source_report_family=str(daily.get("family") or raw.get("family") or "jin10_raw_article"),
        source_artifact_refs=_source_artifact_refs(raw),
        one_line_conclusion=conclusion,
        provenance=_provenance(raw, daily),
        evidence_basis={
            "report_facts": _report_facts(daily),
            "author_views": _author_views(daily),
            "chart_support": _chart_support(raw),
            "agent_inference_scope": "仅基于归档报告识别结果进行条件化推演，不引入实时外部数据。",
            "unconfirmed": _unresolved_items(raw, daily),
        },
        market_stage=_market_stage(daily, logic, article_context),
        logic_chain=logic,
        key_variables=variables,
        gold_analysis=_gold_analysis(conclusion, daily, article_context),
        silver_analysis=_silver_analysis(daily, article_context),
        cross_asset_analysis=_cross_asset_analysis(daily, article_context),
        key_levels=levels,
        scenario_paths=_scenario_paths(daily, article_context),
        trading_implications=_trading_implications(daily, article_context),
        risk_points=risks,
        final_summary=_final_summary(conclusion, risks),
        unresolved_items=_unresolved_items(raw, daily),
        source_refs=source_refs,
        generated_from={
            "source": "jin10_agent_analysis_fallback",
            "raw_report_family": raw.get("family"),
            "daily_report_family": daily.get("family"),
            "prompt_ready": True,
        },
    )


def _to_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return dict(value)


def _compact_daily_summary(value: dict[str, Any] | None) -> str:
    if not value:
        return "{}"
    keys = [
        "core_conclusion",
        "market_prices",
        "logic_chains",
        "watch_variables",
        "key_levels",
        "scenario_matrix",
        "risks",
    ]
    lines = []
    for key in keys:
        if key in value:
            lines.append(f"{key}: {value[key]}")
    return "\n".join(lines) or str(value)


def _extract_article_context(article: str) -> dict[str, Any]:
    """Extract reusable signals from raw markdown without binding to one report."""

    compact_text = _normalize_text(article)
    readable_text = article or ""
    sentences = _split_sentences(readable_text)
    levels = _extract_levels_from_sentences(sentences)
    levels = _dedupe_level_rows(levels)
    flags = {
        "treasury_yield_driver": any(word in compact_text for word in ("10年期美债", "10年期美国国债", "收益率")),
        "yield_break_trigger": any(row.get("role") == "yield_confirm" for row in levels),
        "gold_options_bullish": _has_any(compact_text, ("黄金期权", "看涨期权", "看跌/看涨", "Put/Call", "成交量比率"))
        and _has_any(compact_text, ("回升", "下降", "筑底", "低点", "上行敞口")),
        "silver_base": "白银" in compact_text and _has_any(compact_text, ("筑底", "盘整", "企稳", "支撑", "突破")),
        "cot_support": "COT" in readable_text or "交易者持仓报告" in compact_text or "未平仓合约" in compact_text or "OI" in readable_text,
        "central_targets": any(row.get("role") == "long_term_target" for row in levels),
        "rich_directional_evidence": False,
    }
    flags["rich_directional_evidence"] = _has_rich_directional_evidence(flags=flags, levels=levels, sentences=sentences)
    return {"text": compact_text, "sentences": sentences, "levels": levels, "flags": flags}


def _split_sentences(article: str) -> list[str]:
    raw = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", article or "")
    raw = re.sub(r"#+\s*", "", raw)
    pieces = re.split(r"[。！？!?；;\n]+", raw)
    return [piece.strip() for piece in pieces if piece.strip()]


def _extract_levels_from_sentences(sentences: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for sentence in sentences:
        normalized = _normalize_text(sentence)
        if not normalized:
            continue
        role = _infer_level_role(normalized)
        if role == "mentioned_level":
            continue
        for value in _extract_numeric_values(sentence):
            if _is_noise_level(sentence, value):
                continue
            asset = _infer_asset_for_value(sentence, value)
            label = _level_label(asset, role, normalized)
            key = (asset, role, value)
            if key in seen:
                continue
            seen.add(key)
            rows.append({"label": label, "value": value, "source_block_id": "raw_article", "asset": asset, "role": role, "layer": _level_layer(role), "evidence": sentence})
    return rows


def _extract_numeric_values(sentence: str) -> list[str]:
    values: list[str] = []
    # Percent levels are only key levels when they are tied to yields or explicit ratios.
    if _has_any(_normalize_text(sentence), ("收益率", "Put/Call", "看跌/看涨", "比率")):
        values.extend(match.group(0) for match in re.finditer(r"\d+(?:\.\d+)?%", sentence))
    # Ranges, e.g. 70美元至84美元 / 135美元至140美元.
    for match in re.finditer(r"(\d+(?:\.\d+)?)\s*(?:美元)?\s*(?:至|到|-|—|~)\s*(\d+(?:\.\d+)?)\s*美元", sentence):
        values.append(f"{match.group(1)}-{match.group(2)}")
    # Money levels. Keep context-rich numbers; ignore tiny percentages already captured.
    for match in re.finditer(r"\d+(?:\.\d+)?\s*美元", sentence):
        values.append(match.group(0).replace(" ", "").replace("美元", ""))
    # Bare price-like numbers in sentences with explicit financial level words.
    if _has_any(_normalize_text(sentence), ("目标", "支撑", "压力", "站回", "收复", "跌破", "失守", "回踩", "最大痛点", "区间", "附近")):
        for match in re.finditer(r"(?<![\d.])\d{2,5}(?:\.\d+)?(?![\d.%])", sentence):
            values.append(match.group(0))
    return _dedupe(values)


def _infer_asset(sentence: str) -> str:
    if "白银" in sentence:
        return "白银"
    if "美债" in sentence or "收益率" in sentence or "美国国债" in sentence:
        return "美债"
    if "黄金" in sentence or "金价" in sentence:
        return "黄金"
    return "综合"


def _infer_asset_for_value(sentence: str, value: str) -> str:
    compact = _normalize_text(sentence)
    if "%" in value and ("收益率" in compact or "美债" in compact or "美国国债" in compact):
        return "美债"
    value_pos = compact.find(value.replace("-", "至"))
    if value_pos < 0:
        value_pos = compact.find(value.split("-")[0])
    prefix = compact[max(0, value_pos - 30): value_pos] if value_pos >= 0 else compact
    suffix = compact[value_pos: value_pos + 30] if value_pos >= 0 else compact
    window = prefix + suffix
    if "白银" in window:
        return "白银"
    if "黄金" in window or "金价" in window:
        return "黄金"
    return _infer_asset(compact)


def _is_noise_level(sentence: str, value: str) -> bool:
    compact = _normalize_text(sentence)
    value_head = value.split("-")[0]
    # Years and calendar dates are not market levels unless explicitly quoted as dollars/percentages.
    if re.fullmatch(r"20\d{2}", value_head):
        return True
    pos = compact.find(value_head)
    if pos >= 0:
        before = compact[max(0, pos - 3):pos]
        after = compact[pos + len(value_head):pos + len(value_head) + 3]
        if after.startswith(("年", "月", "日", "个交易日")):
            return True
        if before.endswith(("图", "图表")):
            return True
        if value_head == "10" and after.startswith("年期"):
            return True
    # Small bare numbers in date/figure/order contexts are usually not price levels.
    if "%" not in value and "-" not in value:
        try:
            number = float(value_head)
        except ValueError:
            return False
        if number <= 31 and not any(token in compact for token in ("美元", "收益率", "最大痛点", "目标", "支撑", "压力", "站回", "失守")):
            return True
    return False




def _level_layer(role: str) -> str:
    return "long_term" if role == "long_term_target" else "trading"


def _dedupe_level_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    range_parts: set[tuple[str, str]] = set()
    for row in rows:
        value = str(row.get("value") or "")
        if "-" in value:
            for part in value.split("-"):
                range_parts.add((str(row.get("asset") or ""), part))
    for row in rows:
        value = str(row.get("value") or "")
        asset = str(row.get("asset") or "")
        role = str(row.get("role") or "")
        key_value = _canonical_level_value(value)
        # Keep explicit short-term endpoints for gold balance zones; drop long-term/range endpoint duplicates.
        if (asset, value) in range_parts and role in {"long_term_target", "support", "mentioned_level"}:
            continue
        key = (asset, role, key_value)
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result


def _canonical_level_value(value: str) -> str:
    if value.endswith("%"):
        try:
            return f"{float(value[:-1]):.2f}%"
        except ValueError:
            return value
    return value

def _infer_level_role(sentence: str) -> str:
    if "收益率" in sentence and _has_any(sentence, ("跌破", "回落至", "下方", "确认")):
        return "yield_confirm"
    if "最大痛点" in sentence:
        return "max_pain"
    if _has_any(sentence, ("Q3", "Q4", "第三季度", "第四季度", "周期高点", "历史高点")) or (
        _has_any(sentence, ("长期", "中长期")) and _has_any(sentence, ("目标", "高点", "测试", "指向"))
    ):
        return "long_term_target"
    if _has_any(sentence, ("上行目标", "目标", "测试", "看向", "指向", "冲击")):
        return "upside_target"
    if _has_any(sentence, ("支撑", "回踩", "下方", "失守", "下沿")):
        return "support"
    if _has_any(sentence, ("压力", "阻力", "上沿")):
        return "resistance"
    if _has_any(sentence, ("区间", "平衡", "舒适", "到期", "内在价值曲线", "底部趋于平缓")):
        return "balance_zone"
    if _has_any(sentence, ("站回", "收复", "突破", "确认")):
        return "confirm"
    return "mentioned_level"


def _level_label(asset: str, role: str, sentence: str) -> str:
    role_labels = {
        "yield_confirm": "收益率确认位",
        "max_pain": "期权最大痛点",
        "long_term_target": "中长期目标",
        "upside_target": "上行目标",
        "support": "支撑/失效位",
        "resistance": "压力/阻力位",
        "balance_zone": "平衡区间",
        "confirm": "确认位",
        "mentioned_level": "报告提及价位",
    }
    return f"{asset}{role_labels.get(role, '关键位')}"


def _has_any(text: str, words: tuple[str, ...]) -> bool:
    return any(word in text for word in words)


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = value.strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return result


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", "", value or "")


def _is_placeholder_text(value: object) -> bool:
    text = str(value or "").strip()
    if not text:
        return True
    return any(marker in text for marker in ("证据不足", "未从正文", "未从识别结果", "未提及", "未发现显式", "unavailable"))


def _first_level(article_context: dict[str, Any], *, asset: str | None = None, role: str | None = None) -> str:
    for row in article_context.get("levels") or []:
        if asset is not None and row.get("asset") != asset:
            continue
        if role is not None and row.get("role") != role:
            continue
        return str(row.get("value") or "")
    return ""


def _level_values(article_context: dict[str, Any], *, asset: str | None = None, role: str | None = None) -> list[str]:
    values = []
    for row in article_context.get("levels") or []:
        if asset is not None and row.get("asset") != asset:
            continue
        if role is not None and row.get("role") != role:
            continue
        values.append(str(row.get("value") or ""))
    return [value for value in values if value]


def _has_rich_directional_evidence(
    *,
    flags: dict[str, Any],
    levels: list[dict[str, Any]],
    sentences: list[str],
) -> bool:
    level_roles = {str(row.get("role") or "") for row in levels}
    has_explicit_gold_levels = any(str(row.get("asset") or "") == "黄金" for row in levels)
    has_explicit_yield_level = "yield_confirm" in level_roles
    has_option_structure = bool(flags.get("gold_options_bullish"))
    has_long_sentence = any(len(str(sentence).strip()) >= 28 for sentence in sentences)
    score = sum(
        [
            1 if has_explicit_gold_levels else 0,
            1 if has_explicit_yield_level else 0,
            1 if has_option_structure else 0,
            1 if has_long_sentence else 0,
        ]
    )
    return score >= 3


def _one_line_conclusion(title: str, daily: dict[str, Any], article_context: dict[str, Any]) -> str:
    conclusion = str(daily.get("core_conclusion") or "").strip()
    if conclusion and "证据不足" not in conclusion:
        return conclusion
    flags = article_context["flags"]
    raw_context = article_context.get("raw_context") or {}
    key_sentences = [str(item).strip() for item in raw_context.get("key_sentences") or [] if str(item).strip()]
    chart_summaries = [str(item).strip() for item in raw_context.get("chart_summaries") or [] if str(item).strip()]
    yield_level = _first_level(article_context, asset="美债", role="yield_confirm")
    gold_target = _first_level(article_context, asset="黄金", role="upside_target")
    gold_support = (_first_level(article_context, asset="黄金", role="support") or _first_level(article_context, asset="综合", role="support"))
    if flags["rich_directional_evidence"] and flags["yield_break_trigger"] and flags["gold_options_bullish"]:
        lead = key_sentences[0] if key_sentences else "报告中的利率与期权线索开始同步偏向修复"
        parts = [lead]
        if yield_level:
            parts.append(f"核心确认条件仍是10年期美债收益率有效跌破{yield_level}")
        if gold_target:
            parts.append(f"若确认延续，上方先看{gold_target}附近")
        if gold_support:
            parts.append(f"若利率压制不解除，则要防范回踩{gold_support}附近")
        return "；".join(parts) + "。"
    if flags["rich_directional_evidence"] and (flags["treasury_yield_driver"] or flags["gold_options_bullish"]):
        base = key_sentences[0] if key_sentences else (chart_summaries[0] if chart_summaries else "报告主线仍围绕利率与期权定位是否共振")
        if yield_level:
            return f"{base}；短线先看{yield_level}这一利率确认位是否被有效突破。"
        return f"{base}；现阶段更适合围绕报告给出的触发条件判断，而不是提前押注单边。"
    if chart_summaries:
        return f"正文证据有限，但图表与摘要线索显示：{chart_summaries[0][:120]}。当前判断应先围绕这些图表给出的关键位展开。"
    if title:
        return f"报告主题指向：{title}；但结构化结论仍需以后续关键变量确认。"
    return MISSING


def _market_stage(daily: dict[str, Any], logic_chain: list[str], article_context: dict[str, Any]) -> dict[str, Any]:
    flags = article_context["flags"]
    yield_level = _first_level(article_context, asset="美债", role="yield_confirm")
    if flags["rich_directional_evidence"] and flags["yield_break_trigger"] and flags["gold_options_bullish"]:
        label = "反转观察窗口"
        reason = "期权市场先出现筑底/反攻信号，但趋势反转仍等待利率和价格确认。"
        if yield_level:
            reason += f" 报告给出的核心确认位是10年期美债收益率{yield_level}。"
    else:
        text = " ".join([str(daily.get("core_conclusion") or ""), " ".join(logic_chain)])
        if "压制" in text or "收益率" in text or "美元" in text:
            label = "利率压制态"
        elif "配置机会" in text or "修复" in text or (flags["gold_options_bullish"] and flags["rich_directional_evidence"]):
            label = "修复反弹态"
        elif daily.get("market_prices") and daily.get("logic_chains"):
            label = "高位整固态"
        else:
            label = DEFAULT_STAGE
        reason = logic_chain[0] if logic_chain else MISSING
    return {"label": label, "reason": reason}


def _logic_chain(daily: dict[str, Any], article_context: dict[str, Any]) -> list[str]:
    rows = [
        str(item.get("summary")).strip()
        for item in daily.get("logic_chains") or []
        if item.get("summary") and not _is_placeholder_text(item.get("summary"))
    ]
    if rows:
        return rows
    flags = article_context["flags"]
    chains: list[str] = []
    yield_level = _first_level(article_context, asset="美债", role="yield_confirm")
    gold_targets = _level_values(article_context, asset="黄金", role="upside_target")
    gold_supports = _level_values(article_context, asset="黄金", role="support")
    silver_levels = _level_values(article_context, asset="白银")
    if flags["rich_directional_evidence"] and (flags["treasury_yield_driver"] or flags["gold_options_bullish"]):
        price_confirm = _first_level(article_context, asset="黄金", role="balance_zone") or "报告提及的价格修复位"
        option_confirm = "Call活动继续回升、Put保护需求不扩张、Put/Call维持低位"
        chains.append(
            f"三确认模型：利率确认={('US10Y跌破' + yield_level) if yield_level else '收益率压制松动'}；"
            f"价格确认=黄金站回并稳住{price_confirm}上方；期权确认={option_confirm}。"
        )
    if flags["treasury_yield_driver"]:
        line = "长期美债收益率仍是黄金短线主导变量"
        if yield_level:
            line += f"；报告把{yield_level}作为利率压制能否松动的确认线"
        if gold_targets:
            line += f"；确认后黄金目标关注{gold_targets[0]}附近"
        if gold_supports:
            line += f"；失败时{gold_supports[0]}是下一层风险支撑，不是当前基准目标"
        chains.append(line + "。")
    if flags["rich_directional_evidence"] and flags["gold_options_bullish"]:
        chains.append("黄金期权端出现看涨活动回升、看跌保护需求未扩大、Put/Call 比率下降等信号，含义是空方优势衰减，多头开始重建，而不是现货已经无条件反转。")
    if flags["silver_base"]:
        detail = f"，关键价位包括{'、'.join(silver_levels[:4])}" if silver_levels else ""
        chains.append(f"白银比黄金更偏底部构筑/突破等待状态{detail}，需要价格重新站回关键压力区后才算弹性恢复。")
    if flags["cot_support"]:
        chains.append("COT/OI 信息用于判断下跌过程中的持仓结构：若下跌伴随 OI 增加和掉期交易商增多回补，说明走势不只是多头撤退。")
    raw_context = article_context.get("raw_context") or {}
    chart_summaries = [str(item).strip() for item in raw_context.get("chart_summaries") or [] if str(item).strip()]
    if chart_summaries and not chains:
        chains.append(f"图表摘要首先显示：{chart_summaries[0]}")
        if len(chart_summaries) > 1:
            chains.append(f"补充线索：{chart_summaries[1]}")
    return chains or [MISSING]


def _key_variables(daily: dict[str, Any], article_context: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for item in daily.get("watch_variables") or []:
        label = item.get("label") or MISSING
        if _is_placeholder_text(label):
            continue
        rows.append({"name": label, "observation": item.get("status") or MISSING, "meaning": f"用于观察 {label} 对贵金属定价的边际影响。"})
    if rows:
        return rows
    flags = article_context["flags"]
    result = []
    yield_level = _first_level(article_context, asset="美债", role="yield_confirm")
    if flags["treasury_yield_driver"]:
        result.append({"name": "10年期美债收益率", "observation": f"核心确认位：{yield_level or '报告提及的收益率分界'}", "meaning": "用于判断黄金利率压制是否解除。"})
    if flags["rich_directional_evidence"] and flags["gold_options_bullish"]:
        result.append({"name": "黄金期权 Put/Call 与看涨/看跌活动", "observation": "看涨活动回升、看跌保护需求未扩大或比率下降", "meaning": "用于判断空方优势是否衰减、多头是否重新布局。"})
    silver_values = _level_values(article_context, asset="白银")
    if flags["silver_base"]:
        result.append({"name": "白银关键区间/突破位", "observation": "、".join(silver_values[:4]) or "报告提及的白银关键位", "meaning": "用于判断白银是继续筑底还是恢复弹性。"})
    raw_context = article_context.get("raw_context") or {}
    if not result:
        for index, snippet in enumerate(raw_context.get("key_sentences") or [], start=1):
            text = str(snippet).strip()
            if text:
                result.append({"name": f"图文线索 {index}", "observation": text[:120], "meaning": "来自当天报告正文/图表摘要的关键描述，用于支持差异化判断。"})
                if len(result) >= 3:
                    break
    return result or [{"name": MISSING, "observation": MISSING, "meaning": MISSING}]


def _key_levels(daily: dict[str, Any], article_context: dict[str, Any]) -> list[dict[str, Any]]:
    rows = [
        dict(item)
        for item in daily.get("key_levels") or []
        if dict(item).get("label") and not _is_placeholder_text(dict(item).get("label"))
    ]
    return rows or article_context["levels"] or [{"label": MISSING, "value": None, "source_block_id": "unavailable"}]


def _risk_points(daily: dict[str, Any], article_context: dict[str, Any]) -> list[str]:
    rows = [str(item.get("summary") or item.get("label") or "").strip() for item in daily.get("risks") or []]
    rows = [item for item in rows if item and not _is_placeholder_text(item)]
    if rows:
        return rows
    risks = []
    yield_level = _first_level(article_context, asset="美债", role="yield_confirm")
    gold_support = (_first_level(article_context, asset="黄金", role="support") or _first_level(article_context, asset="综合", role="support"))
    if yield_level:
        risks.append(f"如果10年期美债收益率始终无法跌破{yield_level}并重新走高，当前修复判断可能被推迟。")
    if gold_support:
        risks.append(f"若10Y无法跌破确认位且黄金跌破平衡区，{gold_support}附近应作为下一层风险支撑观察位，不是当前基准目标。")
    if article_context["flags"].get("rich_directional_evidence") and article_context["flags"].get("gold_options_bullish"):
        risks.append("期权信号失效条件：黄金跌破平衡区且无法快速收回、Put成交量重新放大、Call回升但OI不增加、到期后锚定区失效。")
    if article_context["levels"]:
        risks.append("关键价位来自报告图文识别，需在真实行情中二次核验。")
    if (article_context.get("raw_context") or {}).get("chart_count", 0) and not article_context["sentences"]:
        risks.append("本次正文主要依赖多图页摘要与图表线索，若页面 OCR/VLM 偏差较大，结论可能遗漏细节。")
    return risks or [f"{MISSING}：风险提示"]


def _gold_analysis(conclusion: str, daily: dict[str, Any], article_context: dict[str, Any]) -> str:
    flags = article_context["flags"]
    raw_context = article_context.get("raw_context") or {}
    key_sentences = [str(item).strip() for item in raw_context.get("key_sentences") or [] if str(item).strip()]
    yield_level = _first_level(article_context, asset="美债", role="yield_confirm")
    gold_target = _first_level(article_context, asset="黄金", role="upside_target")
    gold_support = (_first_level(article_context, asset="黄金", role="support") or _first_level(article_context, asset="综合", role="support"))
    if flags["rich_directional_evidence"] and (flags["yield_break_trigger"] or flags["gold_options_bullish"]):
        parts = [key_sentences[0] if key_sentences else "黄金端的修复信号已经开始累积，但趋势是否反转仍未确认"]
        if yield_level:
            parts.append(f"利率确认条件是10年期美债收益率跌破{yield_level}")
        if gold_target:
            parts.append(f"若确认，上方目标关注{gold_target}附近")
        if gold_support:
            parts.append(f"若10Y无法跌破确认位且黄金跌破平衡区，{gold_support}附近才是失败路径风险支撑，不是当前基准目标")
        if flags["gold_options_bullish"]:
            parts.append("期权端更像是多头重新回补，而不是现货已经完成趋势反转")
        return "；".join(parts) + "。"
    if not daily:
        return f"{MISSING}：黄金分析仅能基于极少量识别文本，无法稳定展开。"
    follow = key_sentences[0] if key_sentences else conclusion
    return f"{follow}。从当前解析结果看，黄金更可能在既有主线里反复验证关键位，而不是直接给出单边趋势确认。"


def _silver_analysis(daily: dict[str, Any], article_context: dict[str, Any]) -> str:
    silver_values = _level_values(article_context, asset="白银")
    if article_context["flags"]["silver_base"]:
        detail = f"关键位包括{'、'.join(silver_values[:5])}" if silver_values else "关键位需结合报告原文继续核验"
        return f"白银相对黄金更偏底部构筑或突破确认状态，{detail}；在重新站回关键压力区前，不宜把中长期目标直接等同为短线追多信号。"
    if any("白银" in str(item.get("label") or "") for item in daily.get("market_prices") or []):
        return "白银跟随贵金属整体风险偏好波动，但其弹性通常高于黄金，需结合美元与收益率同步观察。"
    return f"{MISSING}：白银分析"


def _cross_asset_analysis(daily: dict[str, Any], article_context: dict[str, Any]) -> dict[str, str]:
    flags = article_context["flags"]
    yield_level = _first_level(article_context, asset="美债", role="yield_confirm")
    return {
        "美元": "若报告未明确美元主线，则不要额外补造美元结论；优先跟踪报告明确的利率和期权变量。" if flags["treasury_yield_driver"] else MISSING,
        "美债": f"10年期美债收益率是黄金反转能否确认的核心开关；{yield_level}是报告给出的关键确认位。" if yield_level else ("美债收益率是报告提及的黄金主导变量。" if flags["treasury_yield_driver"] else MISSING),
        "日元": MISSING,
        "原油": "本篇报告若未把原油作为主导变量，则不额外扩展原油传导。" if flags["treasury_yield_driver"] else MISSING,
    }


def _scenario_paths(daily: dict[str, Any], article_context: dict[str, Any]) -> list[dict[str, Any]]:
    flags = article_context["flags"]
    yield_level = _first_level(article_context, asset="美债", role="yield_confirm")
    gold_target = _first_level(article_context, asset="黄金", role="upside_target")
    gold_support = (_first_level(article_context, asset="黄金", role="support") or _first_level(article_context, asset="综合", role="support"))
    balance = _first_level(article_context, asset="黄金", role="balance_zone") or _first_level(article_context, asset="黄金", role="mentioned_level")
    if flags["rich_directional_evidence"] and (flags["yield_break_trigger"] or flags["gold_options_bullish"]):
        return [
            {
                "path": "主路径",
                "summary": f"黄金维持关键承接区，等待10年期美债收益率{('跌破' + yield_level) if yield_level else '回落'}确认；确认后上方关注{gold_target or '报告提及目标'}。",
                "trigger": f"收益率{('跌破' + yield_level) if yield_level else '回落'}，同时黄金期权上行活动继续回升。",
                "invalid": f"收益率继续高企或黄金跌向{gold_support or '报告支撑位'}。",
                "risk_points": ["期权信号可能领先价格，需等待现货价格确认。"],
                "confidence": "medium",
            },
            {
                "path": "强势路径",
                "summary": f"利率确认与价格确认共振，黄金越过短线修复位后重新交易{gold_target or '上行目标'}。",
                "trigger": "收益率和黄金价格同时给出确认。",
                "invalid": "价格突破失败并重新跌回平衡区。",
                "risk_points": ["强势路径不应在触发条件未出现前提前定价。"],
                "confidence": "low",
            },
            {
                "path": "失败路径",
                "summary": f"收益率未能确认回落，黄金跌破{balance or gold_support or '短线平衡区'}，回到弱势震荡或下探结构。",
                "trigger": "收益率继续高位、期权改善信号被价格否定。",
                "invalid": f"收益率重新跌破{yield_level or '确认位'}并带动黄金上行。",
                "risk_points": ["若关键支撑失效，反转观察窗口会后移。"],
                "confidence": "low",
            },
        ]
    matrix = [dict(item) for item in daily.get("scenario_matrix") or []]
    summaries = [str(item.get("summary") or MISSING) for item in matrix]
    confidence = [str(item.get("confidence") or "low") for item in matrix]
    return [
        {"path": "主路径", "summary": summaries[1] if len(summaries) > 1 else MISSING, "trigger": "关键宏观变量延续当前方向。", "invalid": "收益率、美元、油价的联动关系出现反向变化。", "risk_points": ["条件链条可能被单一数据打断。"], "confidence": confidence[1] if len(confidence) > 1 else "low"},
        {"path": "修复/强势路径", "summary": summaries[2] if len(summaries) > 2 else MISSING, "trigger": "悲观情绪修复且利率压力边际缓和。", "invalid": "美元和收益率再度同步抬升。", "risk_points": ["修复路径易被鹰派预期打断。"], "confidence": confidence[2] if len(confidence) > 2 else "low"},
        {"path": "失败/破位路径", "summary": summaries[0] if summaries else MISSING, "trigger": "高利率与高油价逻辑进一步强化。", "invalid": "通胀担忧回落且降息预期修复。", "risk_points": ["破位后波动可能放大。"], "confidence": confidence[0] if confidence else "low"},
    ]


def _trading_implications(daily: dict[str, Any], article_context: dict[str, Any]) -> list[dict[str, Any]]:
    watch_variables = [
        item.get("label")
        for item in daily.get("watch_variables") or []
        if item.get("label") and not _is_placeholder_text(item.get("label"))
    ]
    if not watch_variables:
        for asset, role in [("美债", "yield_confirm"), ("黄金", "balance_zone"), ("黄金", "confirm"), ("黄金", "upside_target"), ("黄金", "support"), ("白银", "confirm")]:
            values = _level_values(article_context, asset=asset, role=role)
            watch_variables.extend(f"{asset}{value}" for value in values[:2])
    raw_context = article_context.get("raw_context") or {}
    key_sentences = [str(item).strip() for item in raw_context.get("key_sentences") or [] if str(item).strip()]
    return [{
        "stance": "先观察，等确认",
        "trigger": key_sentences[0] if key_sentences else "等待报告中的利率确认位、价格修复位和期权信号形成共振。",
        "invalid": "核心确认位未突破或关键支撑失效。",
        "risk_points": ["报告判断仍依赖解析后的图文/期权线索，落地前需要价格行为二次确认。"],
        "watch_variables": watch_variables or [MISSING],
    }]


def _final_summary(conclusion: str, risks: list[str]) -> str:
    clean_conclusion = conclusion.rstrip("。；; ")
    clean_risk = (risks[0] if risks else MISSING).rstrip("。；; ")
    return (
        f"综合来看，当前更应把这份报告理解为“{clean_conclusion}”这一主线下的阶段判断，而不是已经完成的趋势确认。"
        f" 真正会决定后续方向的，仍是报告里提到的确认条件能否兑现；在那之前，最需要防范的反向风险是：{clean_risk}。"
        " 如果后续关键位、利率或期权结构出现反向变化，就需要把这次判断及时下修，而不是机械沿用今天的结论。"
        " 若判断依赖期权到期锚定区，到期后需要重新评估该锚定区是否继续有效。"
    )


def _provenance(raw: dict[str, Any], daily: dict[str, Any]) -> list[str]:
    return [
        "报告明确事实：来自 raw_article_report 与 daily_analysis 中已识别的正文、价格、关键位和 source_refs。",
        f"报告作者观点：来自 daily_analysis.logic_chains 或原始文章中的观点段落；缺失时标记为 {MISSING}。",
        f"图表/截图支持：基于 raw_article_report.charts，共 {len(raw.get('charts') or [])} 项。",
        "Agent 分析推论：仅对归档内容做条件化链条整理，不联网、不补造外部事实。",
        f"尚未确认部分：{'; '.join(_unresolved_items(raw, daily))}",
    ]


def _source_artifact_refs(raw: dict[str, Any]) -> list[str]:
    trade_date = raw.get("trade_date")
    article_id = raw.get("article_id")
    return [
        f"storage/outputs/jin10/{trade_date}/{article_id}/raw_article_report.json",
        f"storage/outputs/jin10/{trade_date}/{article_id}/daily_analysis.json",
    ]


def _unresolved_items(raw: dict[str, Any], daily: dict[str, Any]) -> list[str]:
    items = []
    if not (raw.get("charts") or []):
        items.append(f"{MISSING}：图表证据")
    article_context = _extract_article_context(str(raw.get("article_markdown") or ""))
    if not daily.get("market_prices") and not article_context["levels"]:
        items.append(f"{MISSING}：市场价格")
    if not daily.get("key_levels") and not article_context["levels"]:
        items.append(f"{MISSING}：关键位")
    if not daily.get("logic_chains") and not any(article_context["flags"].values()):
        items.append(f"{MISSING}：稳定作者观点")
    if not items:
        items.append("暂无新增未确认项，仍需警惕识别结果本身的抽取噪音。")
    return items


def _report_facts(daily: dict[str, Any]) -> list[str]:
    rows = []
    for item in daily.get("market_prices") or []:
        rows.append(f"{item.get('label')}: {item.get('value')}")
    return rows or [f"{MISSING}：价格/关键事实"]


def _author_views(daily: dict[str, Any]) -> list[str]:
    rows = [
        str(item.get("summary")).strip()
        for item in daily.get("logic_chains") or []
        if item.get("summary") and not _is_placeholder_text(item.get("summary"))
    ]
    return rows or ["作者观点优先从 raw_article_report.article_markdown 抽取；当 daily_analysis 抽取失败时，fallback 使用原文关键句和价格位。"]


def _chart_support(raw: dict[str, Any]) -> list[str]:
    charts = raw.get("charts") or []
    rows = []
    for chart in charts:
        title = chart.get("title") or chart.get("caption") or "未命名图表"
        rows.append(f"{title} -> {chart.get('image_path') or MISSING}")
    return rows or [f"{MISSING}：图表/截图支持"]


def _compact_previous_analysis(previous: dict[str, Any] | None) -> str:
    if not isinstance(previous, dict) or not previous:
        return "未提供 previous_daily_analysis。"
    key_levels = previous.get("key_levels") or []
    level_lines: list[str] = []
    for item in key_levels[:8]:
        if not isinstance(item, dict):
            continue
        price = item.get("price")
        desc = str(item.get("description") or "").strip()
        typ = str(item.get("type") or "").strip()
        if price is None and not desc:
            continue
        level_lines.append(f"- price={price}; type={typ or 'unknown'}; desc={desc or MISSING}")
    lines = [
        f"title: {previous.get('title') or MISSING}",
        f"trade_date: {previous.get('trade_date') or MISSING}",
        f"one_line_conclusion: {previous.get('one_line_conclusion') or MISSING}",
        f"market_stage: {((previous.get('market_stage') or {}).get('label')) or MISSING}",
        f"market_stage_reason: {((previous.get('market_stage') or {}).get('reason')) or MISSING}",
        "key_levels:",
        *(level_lines or [f"- {MISSING}"]),
        f"final_summary: {previous.get('final_summary') or MISSING}",
    ]
    return "\n".join(lines)


def load_previous_jin10_agent_analysis(
    *,
    trade_date: str,
    run_id: str,
    storage_root: str | Path = "storage",
) -> dict[str, Any] | None:
    base = Path(storage_root) / "outputs" / "jin10"
    if not base.exists():
        return None
    candidates: list[tuple[str, str, Path]] = []
    for date_dir in sorted(base.iterdir(), reverse=True):
        if not date_dir.is_dir():
            continue
        date_str = date_dir.name
        if date_str >= trade_date:
            continue
        for run_dir in sorted(date_dir.iterdir(), reverse=True):
            if not run_dir.is_dir():
                continue
            if date_str == trade_date and run_dir.name == run_id:
                continue
            path = run_dir / "agent_analysis_report.json"
            if path.is_file():
                candidates.append((date_str, run_dir.name, path))
    for _, _, path in candidates:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(payload, dict) and payload.get("family") == "jin10_agent_analysis":
            return payload
    return None


# ── LLM-powered analysis ──────────────────────────────────────────


def build_jin10_agent_analysis_report_with_llm(
    raw_report: Jin10RawArticleReport | dict[str, Any],
    daily_report: Jin10DailyAnalysisReport | dict[str, Any] | None = None,
    *,
    figure_image_loader: ImageLoader | None = None,
) -> Jin10AgentAnalysisReport:
    """Build Jin10 agent analysis using LLM, with deterministic fallback.

    Calls LLM with build_agent_analysis_prompt(), parses the markdown output
    into structured Jin10AgentAnalysisReport fields.
    """
    from apps.llm.gateway import chat_sync

    raw = _to_dict(raw_report)
    daily = _to_dict(daily_report) if daily_report is not None else {}
    fallback = build_jin10_agent_analysis_report(raw_report, daily_report)
    prompt_version = agent_analysis_prompt_version(raw, daily)
    llm_config = _agent_llm_config()
    previous_daily_analysis = load_previous_jin10_agent_analysis(
        trade_date=str(fallback.trade_date or raw.get("trade_date") or ""),
        run_id=str(fallback.run_id or raw.get("article_id") or ""),
    )

    # Build prompt
    prompt = build_agent_analysis_prompt(raw, daily, previous_daily_analysis=previous_daily_analysis)
    multimodal_plan = build_multimodal_user_content(
        prompt,
        raw,
        image_loader=figure_image_loader,
        max_images=llm_config["max_images"],
    )

    # Call LLM
    try:
        if _should_skip_live_llm():
            raise RuntimeError("live llm disabled in current environment")
        response = chat_sync(
            messages=[
                {"role": "system", "content": "你是一名专业的宏观市场与贵金属分析 Agent，默认使用简体中文。"},
                {"role": "user", "content": multimodal_plan.content},
            ],
            model=llm_config["model"],
            provider=llm_config["provider"],
            reasoning_effort=llm_config["reasoning_effort"],
            request_timeout=llm_config["request_timeout"],
            temperature=0.3,
            max_tokens=llm_config["max_tokens"],
            max_retries=0,
        )
        llm_markdown = sanitize_agent_analysis_markdown(response.content)
        llm_fields = _parse_llm_output_to_fields(llm_markdown, daily, raw)
        figure_results = _mark_figure_output_references(multimodal_plan.figure_results, llm_markdown)
        degraded = multimodal_plan.status == "degraded"

        return Jin10AgentAnalysisReport(
            document_id=fallback.document_id,
            trade_date=fallback.trade_date,
            run_id=fallback.run_id,
            article_id=fallback.article_id,
            title=llm_fields.get("title") or fallback.title,
            family="jin10_agent_analysis",
            asset=fallback.asset,
            source_report_family=fallback.source_report_family,
            source_artifact_refs=fallback.source_artifact_refs,
            one_line_conclusion=llm_fields.get("one_line_conclusion") or fallback.one_line_conclusion,
            provenance=fallback.provenance,
            evidence_basis={
                **fallback.evidence_basis,
                **(llm_fields.get("evidence_basis") or {}),
                "llm_markdown": llm_markdown,
            },
            market_stage=llm_fields.get("market_stage") or fallback.market_stage,
            logic_chain=llm_fields.get("logic_chain") or fallback.logic_chain,
            key_variables=llm_fields.get("key_variables") or fallback.key_variables,
            gold_analysis=llm_fields.get("gold_analysis") or fallback.gold_analysis,
            silver_analysis=llm_fields.get("silver_analysis") or fallback.silver_analysis,
            cross_asset_analysis=llm_fields.get("cross_asset_analysis") or fallback.cross_asset_analysis,
            key_levels=llm_fields.get("key_levels") or fallback.key_levels,
            scenario_paths=llm_fields.get("scenario_paths") or fallback.scenario_paths,
            trading_implications=llm_fields.get("trading_implications") or fallback.trading_implications,
            risk_points=llm_fields.get("risk_points") or fallback.risk_points,
            final_summary=llm_fields.get("final_summary") or fallback.final_summary,
            unresolved_items=llm_fields.get("unresolved_items") or fallback.unresolved_items,
            source_refs=fallback.source_refs,
            generated_from={
                "source": "jin10_agent_analysis_llm",
                "model": response.model,
                "provider": response.provider,
                "reasoning_effort": llm_config["reasoning_effort"],
                "request_timeout": llm_config["request_timeout"],
                "max_images": llm_config["max_images"],
                "latency_ms": response.latency_ms,
                "tokens": response.usage,
                "vision_model": response.model,
                "submitted_image_count": multimodal_plan.submitted_image_count,
                "image_processing_status": multimodal_plan.status,
                "degraded": degraded,
                "degraded_reason": ";".join(multimodal_plan.degraded_reasons) if degraded else None,
                "figure_results": figure_results,
                "raw_report_family": fallback.generated_from.get("raw_report_family") or raw.get("family"),
                "daily_report_family": fallback.generated_from.get("daily_report_family") or daily.get("family"),
                "prompt_version": prompt_version,
                "prompt_profile": _agent_analysis_prompt_profile(raw_report=raw, daily_report=daily),
                "prompt_ready": True,
                "narrative_markdown": llm_markdown,
                "fallback_generated_from": fallback.generated_from,
            },
        )
    except Exception as exc:
        # Fallback to deterministic analysis
        fallback.generated_from["source"] = "jin10_agent_analysis_fallback_after_llm_error"
        fallback.generated_from["prompt_version"] = prompt_version
        fallback.generated_from["prompt_profile"] = _agent_analysis_prompt_profile(raw_report=raw, daily_report=daily)
        fallback.generated_from["model"] = llm_config["model"]
        fallback.generated_from["provider"] = llm_config["provider"]
        fallback.generated_from["reasoning_effort"] = llm_config["reasoning_effort"]
        fallback.generated_from["request_timeout"] = llm_config["request_timeout"]
        fallback.generated_from["max_images"] = llm_config["max_images"]
        fallback.generated_from["vision_model"] = None
        fallback.generated_from["submitted_image_count"] = multimodal_plan.submitted_image_count
        fallback.generated_from["image_processing_status"] = multimodal_plan.status
        fallback.generated_from["degraded"] = True
        fallback.generated_from["degraded_reason"] = f"llm_error:{type(exc).__name__}"
        fallback.generated_from["figure_results"] = multimodal_plan.figure_results
        return fallback


def _agent_llm_config() -> dict[str, Any]:
    return {
        "provider": os.getenv("JIN10_AGENT_PROVIDER", DEFAULT_JIN10_AGENT_PROVIDER).strip()
        or DEFAULT_JIN10_AGENT_PROVIDER,
        "model": os.getenv("JIN10_AGENT_MODEL", DEFAULT_JIN10_AGENT_MODEL).strip()
        or DEFAULT_JIN10_AGENT_MODEL,
        "reasoning_effort": os.getenv(
            "JIN10_AGENT_REASONING_EFFORT",
            DEFAULT_JIN10_AGENT_REASONING_EFFORT,
        ).strip()
        or DEFAULT_JIN10_AGENT_REASONING_EFFORT,
        "request_timeout": _positive_float_env(
            "JIN10_AGENT_REQUEST_TIMEOUT",
            DEFAULT_JIN10_AGENT_REQUEST_TIMEOUT,
        ),
        "max_tokens": _positive_int_env("JIN10_AGENT_MAX_TOKENS", DEFAULT_JIN10_AGENT_MAX_TOKENS),
        "max_images": _non_negative_int_env("JIN10_AGENT_MAX_IMAGES", DEFAULT_JIN10_AGENT_MAX_IMAGES),
    }


def _positive_float_env(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default


def _positive_int_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default


def _non_negative_int_env(name: str, default: int) -> int:
    try:
        return max(0, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def _mark_figure_output_references(
    figure_results: list[dict[str, Any]],
    markdown: str,
) -> list[dict[str, Any]]:
    marked: list[dict[str, Any]] = []
    for item in figure_results:
        figure_id = str(item.get("figure_id") or "")
        page_no = item.get("page_no")
        referenced = bool(figure_id and figure_id in markdown)
        if not referenced and page_no is not None:
            referenced = f"page_no={page_no}" in markdown or f"第{page_no}页" in markdown
        marked.append({**item, "referenced_in_output": referenced})
    return marked


def _should_skip_live_llm() -> bool:
    if os.getenv("FINANCE_AGENT_FORCE_LIVE_LLM", "").strip().lower() in {"1", "true", "yes"}:
        return False
    return "PYTEST_CURRENT_TEST" in os.environ


def _parse_llm_output_to_fields(
    llm_markdown: str,
    daily: dict[str, Any],
    raw: dict[str, Any],
) -> dict[str, Any]:
    """Extract structured fields from LLM markdown output.

    Uses regex to extract key sections from the markdown and map them
    to Jin10AgentAnalysisReport fields.
    """
    import re

    fields: dict[str, Any] = {}

    # Extract title
    title_match = re.search(r"^#\s+(.+?)｜Agent", llm_markdown, re.MULTILINE)
    if title_match:
        fields["title"] = title_match.group(1).strip()

    # Extract one-line conclusion
    conclusion_match = re.search(
        r"(?ms)^##\s*一句话结论\s*\n(.+?)(?=^#{1,2}\s|\Z)", llm_markdown
    )
    if conclusion_match:
        fields["one_line_conclusion"] = _normalize_one_line_conclusion(conclusion_match.group(1))

    def _section(patterns: list[str]) -> str:
        joined = "|".join(patterns)
        match = re.search(rf"(?ms)^#{{1,2}}\s*(?:{joined})\s*\n(.+?)(?=^#{{1,2}}\s|\Z)", llm_markdown)
        return match.group(1).strip() if match else ""

    # Extract market stage
    stage_text = _section([
        r"市场阶段判断",
        r"4\.\s*当前阶段判断(?:更新)?",
        r"4\.\s*当前黄金的阶段判断",
        r"4\.\s*黄金现货结构[:：].*",
    ])
    if stage_text:
        stage_label = DEFAULT_STAGE
        for label in STAGE_LABELS:
            if label in stage_text:
                stage_label = label
                break
        fields["market_stage"] = {"label": stage_label, "reason": stage_text[:200]}

    # Extract logic chain
    logic_text = _section([r"核心逻辑链", r"3\.\s*报告核心逻辑", r"4\.\s*最新逻辑链", r"4\.\s*报告逻辑链"])
    if logic_text:
        fields["logic_chain"] = [
            line.strip().lstrip("- ").lstrip("0123456789. ")
            for line in logic_text.split("\n")
            if line.strip() and not line.strip().startswith("```")
        ]

    # Extract gold analysis
    gold_match = re.search(r"##\s*黄金分析\s*\n(.+?)(?=\n##|\Z)", llm_markdown, re.DOTALL)
    if gold_match:
        fields["gold_analysis"] = gold_match.group(1).strip()[:2000]

    # Extract silver analysis
    silver_match = re.search(r"##\s*白银分析\s*\n(.+?)(?=\n##|\Z)", llm_markdown, re.DOTALL)
    if silver_match:
        fields["silver_analysis"] = silver_match.group(1).strip()[:1000]

    # Extract risk points
    risk_text = _section([r"风险识别点", r"7\.\s*风险与仍待确认项"])
    if risk_text:
        fields["risk_points"] = [
            line.strip().lstrip("- ").lstrip("0123456789. ")
            for line in risk_text.split("\n")
            if line.strip() and not line.strip().startswith("```")
        ]

    # Extract final summary
    summary_text = _section([r"最终总结", r"6\.\s*交易\s*/\s*配置含义", r"7\.\s*风险与仍待确认项"])
    if summary_text:
        fields["final_summary"] = summary_text.strip()[:1000]

    # Extract key levels
    levels_text = _section([r"关键位[，,]去重后分层", r"5\.\s*关键位与触发条件"])
    if levels_text:
        fields["key_levels"] = _extract_levels_from_text(levels_text)

    # Extract scenario paths
    paths_text = _section([r"三条路径推演", r"6\.\s*交易\s*/\s*配置含义"])
    if paths_text:
        fields["scenario_paths"] = _extract_paths_from_text(paths_text)

    # Store full markdown in evidence_basis
    fields["evidence_basis"] = {
        "report_facts": _report_facts(daily),
        "author_views": _author_views(daily),
        "chart_support": _chart_support(raw),
        "agent_inference_scope": "LLM 分析，基于归档报告识别结果。",
        "unconfirmed": _unresolved_items(raw, daily),
        "llm_markdown": llm_markdown[:10000],
    }

    return fields


def _normalize_one_line_conclusion(text: str) -> str:
    lines: list[str] = []
    for raw_line in str(text or "").splitlines():
        stripped = raw_line.strip()
        if not stripped:
            if lines:
                break
            continue
        if re.fullmatch(r"[-*_]{3,}", stripped):
            break
        lines.append(stripped)
    return " ".join(lines).strip()


def _extract_levels_from_text(text: str) -> list[dict[str, Any]]:
    """Extract key price levels from LLM markdown text."""
    import re
    levels = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        # Try to find price numbers
        prices = re.findall(r"\d{4,5}(?:\.\d+)?", line)
        for price in prices:
            level_type = "neutral"
            if any(kw in line for kw in ["支撑", "地板", "support", "底"]):
                level_type = "support"
            elif any(kw in line for kw in ["阻力", "压力", "resistance", "顶"]):
                level_type = "resistance"
            levels.append({
                "price": float(price),
                "type": level_type,
                "description": line[:100],
            })
    return levels


def _extract_paths_from_text(text: str) -> list[dict[str, Any]]:
    """Extract scenario paths from LLM markdown text."""
    paths = []
    current_path: dict[str, Any] = {}
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        if line.startswith(("-", "•", "1", "2", "3")) or line.startswith("路径"):
            if current_path:
                paths.append(current_path)
            current_path = {"description": line.lstrip("- ").lstrip("0123456789. ")}
        elif current_path:
            current_path["description"] = current_path.get("description", "") + " " + line
    if current_path:
        paths.append(current_path)
    return paths
