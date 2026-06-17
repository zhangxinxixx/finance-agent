"""写入 agent_id 级记忆到 Mem0 — 使用 metadata 标记实体作用域。"""
import time
from mem0 import MemoryClient

client = MemoryClient()

agents = {
    "macro_liquidity_agent": [
        "macro_liquidity_agent 职责：消费 AnalysisSnapshot.macro 字段，运行 7-driver 宏观 regime 引擎（real_yield / DXY / US02Y / US10Y / breakeven / liquidity_quantity / liquidity_price），输出 rate_pressure / transition_release / trend_tailwind 三态 + confidence + gold_interpretation。",
        "macro_liquidity_agent 数据源：real_yield 优先直读 DGS10-T10YIE；DXY/US02Y/US10Y 来自 FRED；breakeven 来自 T10YIE；liquidity_quantity 来自 ON RRP/TGA/Reserves；liquidity_price 来自 SOFR/EFFR/IORB。缺失指标输出 unavailable。",
        "macro_liquidity_agent 输出通过 AgentOutput 写入 coordinator，market_phase 字段必须非空，key_findings 附加 regime 摘要。",
    ],
    "cme_options_agent": [
        "cme_options_agent 职责：消费 AnalysisSnapshot.options 字段，基于 normalize/Black-76/structure 做 OI wall / GEX / IV skew / expiry structure 解读。不做原始 PDF 解析。",
        "cme_options_agent 校准逻辑：从 calibration 提取 OI delta by strike、wall score delta (1d/1w)、wall migration/stability、expiry roll detection (active/starting/none)、near-vs-next-month comparison。",
        "cme_options_agent 数据规则：优先用 FINAL 数据，PRELIM 仅兜底。关键价位分上方 Call 压制 / 下方 Put 支撑 / Pin 位 / 突破门槛。",
    ],
    "risk_agent": [
        "risk_agent 是 read-only agent，只消费 AnalysisSnapshot 和各 Agent 的 AgentOutput，不重算任何 macro/options/technical features。评估维度：source_quality / wall_decay / policy_reversal / macro_divergence / market_regime。模块 unavailable 必须反映到 risk_points 或 invalid_conditions。",
        "risk_agent 输出 AgentOutput.risk_points + watchlist，宏观/期权冲突必须在 risk_points 中标出。confidence 基于各输入模块的可用性。",
    ],
    "news_agent": [
        "news_agent 职责：消费 AnalysisSnapshot.news 字段（Jin10 快讯流），提取关键事件、判断市场情绪、标注与黄金相关的政策/地缘/经济数据事件。数据源 Jin10 MCP（非VIP），不抓取 VIP 报告图片。缺失输出 unavailable。",
        "news_agent 输出 AgentOutput.bias + key_findings，重点事件入 watchlist。情绪 bullish/bearish/neutral，带 confidence。",
    ],
    "market_odds_agent": [
        "market_odds_agent 职责：消费 AnalysisSnapshot.market_odds 字段，解读 CME FedWatch 概率 + OI-derived probability，输出事件概率和宏观预期。数据接入路径 schema->snapshot->agent->coordinator->API/前端。当前 Polymarket 未接入。",
        "market_odds_agent 输出 AgentOutput.bias + key_findings，概率变化入 watchlist。后续需评估 reliability score 和低流动性降权。",
    ],
    "positioning_agent": [
        "positioning_agent 状态：框架已定义，机构持仓数据源未接入，输出 status=unavailable。不补造持仓数据。",
    ],
    "technical_agent": [
        "technical_agent 状态：框架已定义，实时行情技术结构模块未启动。第一阶段定位准实时行情/技术结构快照/策略失效提醒，不做全自动交易。当前输出 status=unavailable。",
    ],
    "coordinator_agent": [
        "coordinator_agent 职责：汇总 7 个模块 Agent 输出，生成 FinalAnalysisResult。检测冲突、聚合 bias、加权 confidence、提取公共风险点。输入各 AgentOutput + AnalysisSnapshot，输出 FinalReport (12-section JSON) + StrategyCard。不独立分析，只聚合和冲突检测。",
        "coordinator_agent 任何模块 unavailable 必须在 final report 中显式标注，不可隐式跳过。",
    ],
    "codex_dev_agent": [
        "Hermes/Codex 开发执行规范：每次执行前通过 get_execution_context(task) 检索项目上下文注入 Prompt。每次只执行一个 Phase，不允许全量重构。执行后写入 add_execution_update() 摘要。输出：修改文件/完成项/未完成项/风险点/下一步。多 Agent 不同时改同一文件。",
    ],
}

total = 0
for agent_name, memories in agents.items():
    for content in memories:
        r = client.add(
            messages=[{"role": "user", "content": content}],
            agent_id=agent_name,
            app_id="finance_analysis_system",
            metadata={
                "scope": "project_mainline",
                "project_id": "finance_analysis_system",
                "memory_type": "agent_rule",
                "importance": "high",
                "tags": [agent_name, "agent", "boundary"],
                "source": "entity_scoping_2026-05-16",
            },
            infer=False,
        )
        print(f"[{agent_name}] {r.get('status', '?')}")
        total += 1
        time.sleep(0.3)

print(f"Done: {total} entries across {len(agents)} agents")
