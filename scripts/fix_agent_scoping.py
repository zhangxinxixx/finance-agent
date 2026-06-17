"""用原生 agent_id 重新写入 agent 级记忆。"""
import time
from mem0 import MemoryClient

c = MemoryClient()

agents = {
    "macro_liquidity_agent": [
        "职责：消费 AnalysisSnapshot.macro 字段，运行 7-driver 宏观 regime 引擎（real_yield / DXY / US02Y / US10Y / breakeven / liquidity_quantity / liquidity_price），输出 rate_pressure / transition_release / trend_tailwind + confidence + gold_interpretation。数据源：real_yield 优先直读 DGS10-T10YIE；DXY/US02Y/US10Y 来自 FRED；breakeven 来自 T10YIE；liquidity_quantity 来自 ON RRP/TGA/Reserves；liquidity_price 来自 SOFR/EFFR/IORB。缺失输出 unavailable。输出 AgentOutput.market_phase 必须非空，key_findings 附加 regime 摘要。",
    ],
    "cme_options_agent": [
        "职责：消费 AnalysisSnapshot.options 字段，基于 normalize/Black-76/structure 做 OI wall / GEX / IV skew / expiry structure 解读。不做原始 PDF 解析。校准：从 calibration 提取 OI delta by strike、wall score delta (1d/1w)、wall migration/stability、expiry roll detection、near-vs-next-month comparison。数据规则：优先 FINAL 数据，PRELIM 仅兜底。关键价位分上方 Call 压制 / 下方 Put 支撑 / Pin 位 / 突破门槛。",
    ],
    "risk_agent": [
        "是 read-only agent，只消费 AnalysisSnapshot 和各 AgentOutput，不重算任何 features。评估维度：source_quality / wall_decay / policy_reversal / macro_divergence / market_regime。模块 unavailable 必须反映到 risk_points 或 invalid_conditions。输出 AgentOutput.risk_points + watchlist。宏观/期权冲突必须在 risk_points 中标出。",
    ],
    "news_agent": [
        "消费 AnalysisSnapshot.news 字段（Jin10 快讯流），提取关键事件、判断市场情绪、标注黄金相关政策/地缘/经济事件。数据源 Jin10 MCP（非VIP），不抓取 VIP 报告图片。缺失输出 unavailable。输出 AgentOutput.bias + key_findings，情绪 bullish/bearish/neutral，带 confidence。",
    ],
    "market_odds_agent": [
        "消费 AnalysisSnapshot.market_odds 字段，解读 CME FedWatch 概率 + OI-derived probability。数据接入路径 schema->snapshot->agent->coordinator->API。Polymarket 尚未接入，后续需评估 reliability score 和低流动性降权。输出 AgentOutput.bias + key_findings，概率变化入 watchlist。",
    ],
    "positioning_agent": [
        "状态：框架已定义，机构持仓数据源未接入，输出 status=unavailable。不补造持仓数据。",
    ],
    "technical_agent": [
        "状态：框架已定义，实时行情技术结构模块未启动。定位准实时行情/技术结构快照/策略失效提醒，不做全自动交易。当前输出 status=unavailable。",
    ],
    "coordinator_agent": [
        "汇总 7 模块 Agent 输出 → FinalAnalysisResult。检测冲突、聚合 bias、加权 confidence、提取公共风险点。输入各 AgentOutput + AnalysisSnapshot，输出 FinalReport (12-section JSON) + StrategyCard。不独立分析，只聚合和冲突检测。任何模块 unavailable 必须在 final report 中显式标注。",
    ],
    "report_agent": [
        "职责：消费 coordinator 输出的 FinalAnalysisResult，渲染为最终 Markdown 报告和策略卡片。报告结构：one_line_summary / market_phase / bias / confidence / macro_conclusion / options_analysis / risk_assessment / news_highlights / market_odds_outlook / watchlist / data_completeness / source_refs。输出格式：Markdown (final_report.md) + JSON (strategy_card.json)。不自行分析，只做渲染和格式化。",
    ],
    "codex_dev_agent": [
        "Hermes/Codex 开发执行规范：每次执行前通过 get_execution_context(task) 检索项目上下文注入 Prompt。每次只执行一个 Phase，不允许全量重构。执行后写入 add_execution_update() 摘要。输出：修改文件/完成项/未完成项/风险点/下一步。不改变 AGENTS.md。多 Agent 不同时改同一文件。",
    ],
    "obsidian_router_agent": [
        "职责：管理 Obsidian vault 和 Mem0 之间的同步。Obsidian 文档更新后提取摘要写入 Mem0（app_id=finance_analysis_system）。Mem0 中过期/错误记忆标记后同步到 Obsidian 复盘文档。同步规则：Obsidian 为权威源，Mem0 为摘要缓存。冲突时以 Obsidian 为准。",
    ],
}

total = 0
for agent_name, memories in agents.items():
    for content in memories:
        r = c.add(
            messages=[{"role": "user", "content": content}],
            agent_id=agent_name,
            app_id="finance_analysis_system",
            metadata={
                "memory_type": "agent_rule",
                "importance": "high",
                "tags": [agent_name, "agent", "boundary"],
                "source": "native_agent_id_2026-05-16",
            },
            infer=False,
        )
        print(f"[{agent_name}] {r.get('status', '?')}")
        total += 1
        time.sleep(0.3)

print(f"\nDone: {total} entries across {len(agents)} agents")
