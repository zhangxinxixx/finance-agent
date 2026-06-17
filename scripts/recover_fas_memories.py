"""恢复 finance_analysis_system 项目级记忆。"""
import time
from mem0 import MemoryClient

c = MemoryClient()

memories = [
    ("project_principle", "核心生产主链：api -> scheduler -> worker -> collectors -> parsers -> features -> analysis -> renderer -> output。新增功能必须挂到此链，不另建第二套任务主脑。", ["pipeline", "main_chain"]),
    ("project_principle", "系统开发原则：先打通 MVP 闭环再扩展复杂功能；先确定性数据处理再 Agent 推理；Agent 只负责归因/解释/冲突识别/报告生成，不替代核心指标计算。", ["principle", "mvp"]),
    ("project_principle", "架构原则：确定性脚本主链不可被 Agent 替代；Agent 只做只读后处理；路由轻逻辑；Parser 改动须补回归测试；历史报告不覆盖；DB schema additive migration。", ["architecture", "rules"]),
    ("project_principle", "记忆分工原则：Obsidian 存完整文档，Mem0 存摘要和约束。Mem0 不替代 Obsidian / Git / Postgres / SQLite / MinIO / 报告中心。", ["obsidian", "mem0", "boundary"]),
    ("architecture_decision", "CME FINAL/PRELIM 版本化 schema。FINAL-preferred + PRELIM 共存查询。Options wall 多日校准优先基于 FINAL 数据。", ["cme", "final", "prelim", "options"]),
    ("architecture_decision", "Market Odds 模块接入主链：schema -> snapshot -> agent -> coordinator -> API/前端。后续接入 Polymarket、CME FedWatch。", ["market_odds", "polymarket", "fedwatch"]),
    ("architecture_decision", "Analysis DB 持久化使用 SQLite + filesystem fallback。持久化 AnalysisSnapshot / AgentOutput / FinalAnalysisResult。DB 失败不破坏文件主链。", ["sqlite", "persistence", "fallback"]),
    ("architecture_decision", "Agent 体系：7 模块 Agent + 1 coordinator。只读取 AnalysisSnapshot 和 output JSON，不触碰 raw/parsed/features。", ["agent", "coordinator", "snapshot", "boundary"]),
    ("architecture_decision", "数据溯源：所有分析绑定 snapshot_id / input_snapshot_ids / source_refs / Agent 输出版本 / 报告版本。缺失显式 unavailable，不补造。四层严格分离。", ["lineage", "snapshot", "source_refs"]),
    ("architecture_decision", "核心分析模块：宏观流动性、CME期权结构、机构持仓、新闻事件、实时行情技术结构、策略引擎、风险预警。", ["modules", "analysis"]),
    ("current_priority", "优先级：① Dashboard v0.3 Phase 1 布局重构。② Options wall 多日校准收尾。③ 市场赔率/事件概率层完善。④ Hermes/Codex Mem0 执行流程固化。", ["priority", "dashboard", "options"]),
]

for i, (mt, content, tags) in enumerate(memories):
    r = c.add(
        messages=[{"role": "user", "content": content}],
        app_id="finance_analysis_system",
        metadata={
            "memory_type": mt,
            "importance": "high",
            "tags": tags + ["finance_analysis_system", "app"],
            "source": "app_fas_recovery_2026-05-16",
        },
        infer=False,
    )
    print(f"[{i+1}/{len(memories)}] {mt}: {r.get('status', '?')}")
    time.sleep(0.5)

print(f"Done: {len(memories)} entries")
