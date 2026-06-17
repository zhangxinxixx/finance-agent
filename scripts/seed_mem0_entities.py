"""写入 app_id 级 + agent_id 级种子记忆到 Mem0。

实体体系：
  app_id:
    - finance_analysis_system    → 项目规则、架构决策、阶段/优先级
    - obsidian_knowledge_system  → Obsidian 知识库管理规则
    - agent_dev_workspace        → Agent 开发工作区规则
  agent_id:
    - 所有 11 个 Agent 的岗位说明书
"""

import time
from mem0 import MemoryClient

client = MemoryClient()

BASE_META = {"source": "entity_scoping_v2_2026-05-16", "importance": "high"}

# ═══════════════════════════════════════════════════════
# app_id: finance_analysis_system
# ═══════════════════════════════════════════════════════
APP_FAS = {
    "app_id": "finance_analysis_system",
    "entity": "app",
    "memories": [
        ("project_principle", "核心生产主链：api -> scheduler -> worker -> collectors -> parsers -> features -> analysis -> renderer -> output。新增功能必须挂到此链，不另建第二套任务主脑。", ["pipeline", "main_chain"]),
        ("project_principle", "系统开发原则：先打通 MVP 闭环再扩展复杂功能；先确定性数据处理再 Agent 推理；Agent 只负责归因/解释/冲突识别/报告生成，不替代核心指标计算。", ["principle", "mvp"]),
        ("project_principle", "架构原则：确定性脚本主链不可被 Agent 替代；Agent 只做只读后处理；路由轻逻辑；Parser 改动须补回归测试；历史报告不覆盖；DB schema additive migration。", ["architecture", "rules"]),
        ("architecture_decision", "CME FINAL/PRELIM 版本化 schema。FINAL-preferred + PRELIM 共存查询。Options wall 多日校准优先基于 FINAL 数据。", ["cme", "final", "prelim", "options"]),
        ("architecture_decision", "Market Odds 模块接入主链：schema -> snapshot -> agent -> coordinator -> API/前端。后续接入 Polymarket、CME FedWatch。", ["market_odds", "polymarket", "fedwatch"]),
        ("architecture_decision", "Analysis DB 持久化使用 SQLite + filesystem fallback。Storage: AnalysisSnapshot / AgentOutput / FinalAnalysisResult。DB 失败不破坏文件主链。", ["sqlite", "persistence", "fallback"]),
        ("architecture_decision", "Agent 体系：7 模块 Agent + 1 coordinator。只读取 AnalysisSnapshot 和 output JSON，不触碰 raw/parsed/features。", ["agent", "coordinator", "snapshot", "boundary"]),
        ("architecture_decision", "数据溯源：所有分析绑定 snapshot_id / input_snapshot_ids / source_refs / Agent 输出版本 / 报告版本。缺失显式 unavailable，不补造。四层严格分离。", ["lineage", "snapshot", "source_refs"]),
        ("architecture_decision", "核心分析模块：宏观流动性、CME期权结构、机构持仓、新闻事件、实时行情技术结构、策略引擎、风险预警。", ["modules", "analysis"]),
        ("current_phase", "当前阶段：P4 增强全部完成（P4-00~P4-10）。当前分支 fix-unified-date-filter。下一步 Dashboard v0.3 Phase 1 布局重构（3列+Header+右侧面板+导航）。", ["phase", "p4", "dashboard"]),
        ("current_priority", "优先级：① Dashboard v0.3 Phase 1 布局重构。② Options wall 多日校准收尾。③ 市场赔率/事件概率层完善。④ Hermes/Codex Mem0 执行流程固化。", ["priority", "dashboard", "options"]),
        ("memory_policy", "记忆分工原则：Obsidian 存完整文档，Mem0 存摘要和约束。Mem0 不替代 Obsidian / Git / Postgres / SQLite / MinIO / 报告中心。", ["obsidian", "mem0", "boundary"]),
    ],
}

# ═══════════════════════════════════════════════════════
# app_id: obsidian_knowledge_system
# ═══════════════════════════════════════════════════════
APP_OBSIDIAN = {
    "app_id": "obsidian_knowledge_system",
    "entity": "app",
    "memories": [
        ("project_principle", "Obsidian vault 路径：~/wiki/Finance-Agent-Knowledge-Vault。使用中文目录结构，不创建旧英文目录。", ["obsidian", "vault", "paths"]),
        ("project_principle", "Obsidian 职责：保存完整项目文档、架构设计、开发日志、分析报告、Prompt、复盘和长期知识。不做 Agent 执行时实时检索，文档更新后提取摘要同步到 Mem0。", ["obsidian", "knowledge", "complete"]),
        ("architecture_decision", "Obsidian 项目文档结构：02-项目/ 下含当前进度、路线图、任务看板、风险卡点、版本记录；03-架构/ 下含总体架构和各子架构；04-数据源/ 下含数据源总览；06-智能体工作流/ 下含 Agent 工作流。", ["obsidian", "structure"]),
        ("agent_rule", "Obsidian 文档更新后，必须同步摘要到 Mem0（app_id=finance_analysis_system）。不要只更新 Obsidian 而忘记 Mem0。", ["obsidian", "sync", "mem0"]),
    ],
}

# ═══════════════════════════════════════════════════════
# app_id: agent_dev_workspace
# ═══════════════════════════════════════════════════════
APP_DEV = {
    "app_id": "agent_dev_workspace",
    "entity": "app",
    "memories": [
        ("agent_rule", "Hermes/Codex 开发流程：执行前 get_execution_context(task) 检索项目上下文注入 Prompt。每次只执行一个 Phase，不允许全量重构。执行后 add_execution_update() 写入摘要。", ["hermes", "codex", "workflow"]),
        ("agent_rule", "Codex 任务包规范：每次只处理边界清晰、互不冲突的单个任务包。任务包必须写清：目标、允许修改范围、禁止修改范围、输入文件、输出要求、验收标准。", ["codex", "task_package"]),
        ("agent_rule", "多 Agent 协作规则：不得同时改同一文件或 migration。GPT-5.5 主控负责派发和验收，MiMo 负责上下文压缩和任务包生成，Codex 负责代码执行。", ["multi_agent", "coordination"]),
        ("architecture_decision", "开发环境：WSL (Ubuntu)，项目路径 /home/zxx/workspace/finance-agent，Python 3.14.4 venv，RTK 命令压缩工具。", ["dev_env", "wsl", "tools"]),
        ("error_pattern", "常见错误：一次性重构整个项目、多 Agent 同时改同一文件、忘记读 AGENTS.md 规则、前端自行计算策略、绕过 task_runs/task_steps。", ["errors", "patterns"]),
    ],
}

# ═══════════════════════════════════════════════════════
# agent_id: 各 Agent 岗位说明书
# ═══════════════════════════════════════════════════════
AGENTS = [
    ("macro_liquidity_agent", [
        "职责：消费 AnalysisSnapshot.macro 字段，运行 7-driver 宏观 regime 引擎（real_yield / DXY / US02Y / US10Y / breakeven / liquidity_quantity / liquidity_price），输出 rate_pressure / transition_release / trend_tailwind + confidence + gold_interpretation。",
        "数据源：real_yield 优先直读 DGS10-T10YIE；DXY/US02Y/US10Y 来自 FRED；breakeven 来自 T10YIE；liquidity_quantity 来自 ON RRP/TGA/Reserves；liquidity_price 来自 SOFR/EFFR/IORB。缺失输出 unavailable。",
        "输出：AgentOutput.market_phase 必须非空，key_findings 附加 regime 摘要，confidence 基于可用指标比例。",
    ]),
    ("cme_options_agent", [
        "职责：消费 AnalysisSnapshot.options 字段，基于 normalize/Black-76/structure 做 OI wall / GEX / IV skew / expiry structure 解读。不做原始 PDF 解析。",
        "校准：从 calibration 提取 OI delta by strike、wall score delta (1d/1w)、wall migration/stability、expiry roll detection、near-vs-next-month comparison。",
        "数据规则：优先 FINAL 数据，PRELIM 仅兜底。关键价位分上方 Call 压制 / 下方 Put 支撑 / Pin 位 / 突破门槛。",
    ]),
    ("risk_agent", [
        "是 read-only agent，只消费 AnalysisSnapshot 和各 AgentOutput，不重算任何 features。评估维度：source_quality / wall_decay / policy_reversal / macro_divergence / market_regime。模块 unavailable 必须反映到 risk_points 或 invalid_conditions。",
        "输出 AgentOutput.risk_points + watchlist。宏观/期权冲突必须在 risk_points 中标出。confidence 基于输入模块可用性。",
    ]),
    ("news_agent", [
        "消费 AnalysisSnapshot.news 字段（Jin10 快讯流），提取关键事件、判断市场情绪、标注黄金相关政策/地缘/经济事件。数据源 Jin10 MCP（非VIP），不抓取 VIP 报告图片。缺失输出 unavailable。",
        "输出 AgentOutput.bias + key_findings，重点事件入 watchlist。情绪 bullish/bearish/neutral，带 confidence。",
    ]),
    ("market_odds_agent", [
        "消费 AnalysisSnapshot.market_odds 字段，解读 CME FedWatch 概率 + OI-derived probability。数据接入路径 schema->snapshot->agent->coordinator->API。Polymarket 尚未接入，后续需评估 reliability score 和低流动性降权。",
        "输出 AgentOutput.bias + key_findings，概率变化入 watchlist。",
    ]),
    ("positioning_agent", [
        "状态：框架已定义，机构持仓数据源未接入，输出 status=unavailable。不补造持仓数据。",
    ]),
    ("technical_agent", [
        "状态：框架已定义，实时行情技术结构模块未启动。定位准实时行情/技术结构快照/策略失效提醒，不做全自动交易。当前输出 status=unavailable。",
    ]),
    ("coordinator_agent", [
        "汇总 7 模块 Agent 输出 → FinalAnalysisResult。检测冲突、聚合 bias、加权 confidence、提取公共风险点。输入各 AgentOutput + AnalysisSnapshot，输出 FinalReport (12-section JSON) + StrategyCard。不独立分析，只聚合和冲突检测。",
        "任何模块 unavailable 必须在 final report 中显式标注，不可隐式跳过。",
    ]),
    ("report_agent", [
        "职责：消费 coordinator 输出的 FinalAnalysisResult，渲染为最终 Markdown 报告和策略卡片。基于 12-section JSON 结构生成完整报告。",
        "报告结构：one_line_summary / market_phase / bias / confidence / macro_conclusion / options_analysis / risk_assessment / news_highlights / market_odds_outlook / watchlist / data_completeness / source_refs。",
        "输出格式：Markdown (final_report.md) + JSON (strategy_card.json)。不自行分析，只做渲染和格式化。",
    ]),
    ("codex_dev_agent", [
        "Hermes/Codex 开发执行规范：每次执行前通过 get_execution_context(task) 检索项目上下文注入 Prompt。每次只执行一个 Phase，不允许全量重构。执行后写入 add_execution_update() 摘要。输出：修改文件/完成项/未完成项/风险点/下一步。不改变 AGENTS.md。",
    ]),
    ("obsidian_router_agent", [
        "职责：管理 Obsidian vault 和 Mem0 之间的同步。Obsidian 文档更新后提取摘要写入 Mem0（app_id=finance_analysis_system）。Mem0 中过期/错误记忆标记后同步到 Obsidian 复盘文档。",
        "同步规则：Obsidian 为权威源，Mem0 为摘要缓存。冲突时以 Obsidian 为准。自动同步 outputs 和 Dev-Logs 待实现。",
    ]),
]


total = 0

# 写入 app_id 级
for app_data in [APP_FAS, APP_OBSIDIAN, APP_DEV]:
    app_id = app_data["app_id"]
    for mt, content, tags in app_data["memories"]:
        r = client.add(
            messages=[{"role": "user", "content": content}],
            app_id=app_id,
            metadata={
                **BASE_META,
                "memory_type": mt,
                "tags": tags + [app_id, "app"],
            },
            infer=False,
        )
        print(f"[app:{app_id}] {mt}: {r.get('status', '?')}")
        total += 1
        time.sleep(0.35)

# 写入 agent_id 级
for agent_name, memories in AGENTS:
    for content in memories:
        r = client.add(
            messages=[{"role": "user", "content": content}],
            agent_id=agent_name,
            app_id="finance_analysis_system",
            metadata={
                **BASE_META,
                "memory_type": "agent_rule",
                "tags": [agent_name, "agent", "boundary"],
            },
            infer=False,
        )
        print(f"[agent:{agent_name}] {r.get('status', '?')}")
        total += 1
        time.sleep(0.3)

print(f"\nDone: {total} entries")
print(f"  app: {sum(len(d['memories']) for d in [APP_FAS, APP_OBSIDIAN, APP_DEV])}")
print(f"  agent: {sum(len(m) for _, m in AGENTS)}")
