"""增量写入项目状态更新记忆到 Mem0。

原则：不删除旧记忆，新条目自然排名更高覆盖检索结果。
"""

import os
import sys
import time

from mem0 import MemoryClient

# ── 统一元数据 ──────────────────────────────────────
BASE_META = {
    "project_id": "finance_analysis_system",
    "scope": "project_mainline",
    "source": "project_status_update_2026-05-16",
    "version": "p4_completed",
    "updated_at": "2026-05-16",
}


def make_entry(memory_type: str, content: str, importance: str, tags: list[str]) -> dict:
    """构造一条记忆数据。"""
    return {
        "memory_type": memory_type,
        "content": content,
        "importance": importance,
        "tags": tags,
    }


# ═══════════════════════════════════════════════════════
# 更新类 [U] — 5 条
# ═══════════════════════════════════════════════════════

UPDATES: list[dict] = [
    make_entry(
        "current_phase",
        (
            "当前阶段：P4 增强阶段已完成。P4-00~P4-10 均已完成，"
            "MVP 主链路已闭环。当前分支 fix-unified-date-filter，"
            "最近提交 P4-10 minimal Obsidian/report sync。"
            "正从功能闭环转向质量增强+记忆系统集成，"
            "重点包括 Mem0 项目主线记忆、Options wall 多日校准收尾、"
            "市场赔率/事件概率层完善、分析能力产品化闭环。"
            "来源：Obsidian 项目进度 + Git log + 用户确认 (2026-05-16)。"
        ),
        importance="high",
        tags=["phase", "p4", "mvp", "status"],
    ),
    make_entry(
        "current_priority",
        (
            "第一：完成 Mem0 项目主线记忆接入，确保 Hermes/Codex 每次执行前读取项目上下文。"
            "第二：Options wall 多日校准与 FINAL OI 变化接入收尾。"
            "第三：完善市场赔率与事件概率层（Polymarket / CME FedWatch 等外部概率源）。"
            "第四：暂缓实时行情技术结构模块和分析能力产品化闭环（Playbook、报告评分、优秀案例库、人工反馈优化）。"
            "来源：用户确认 (2026-05-16)。"
        ),
        importance="high",
        tags=["priority", "mem0", "options", "market_odds"],
    ),
    make_entry(
        "frontend_direction",
        (
            "前端现状：正式前端统一为 apps/frontend-web/src（Vite + React 18），"
            "用于 Dashboard、Reports、Data Ingestion、Market Monitor、CME Options 等只读展示。"
            "旧 apps/frontend Next.js 与 apps/frontend-web/dashboard.html 已删除，不再作为新需求入口。"
            "前端通过 REST API 消费后端数据，不自行计算策略。"
            "前端定位是金融研究中台的展示层和分析结果消费端，不承担核心计算。"
            "来源：代码仓库 apps/frontend-web/，用户确认 (2026-05-25)。"
        ),
        importance="high",
        tags=["frontend", "vite", "read_only", "dashboard"],
    ),
    make_entry(
        "blocker",
        (
            "已解决历史卡点：CME 期权墙多日校准（P4-06）、报告结构不统一（P4-04）、"
            "任务链路不透明（P4-03）、宏观缺 regime 判断（P4-05）均已完成。"
            "当前未解决风险：① 本地分析效果仍不及 ChatGPT 会话分析，"
            "缺乏长期上下文、分析 Playbook、优秀案例库和人工反馈闭环（Mem0 记忆系统正在缓解）。"
            "② 市场赔率层的外部概率源（Polymarket/Bloomberg）尚未完整接入。"
            "③ Obsidian 自动同步 outputs 未完成，手动维护可能漂移。"
            "④ 实时行情与技术结构模块尚未启动，不应用旧样本补造。"
            "来源：Obsidian 风险卡点 + 用户确认 (2026-05-16)。"
        ),
        importance="high",
        tags=["blocker", "playbook", "memory", "quality"],
    ),
    make_entry(
        "next_action",
        (
            "第一：将本次项目状态更新写入 Mem0 并验证检索效果。"
            "第二：建立固定执行流程——Hermes/Codex 执行前通过 "
            "get_execution_context(task) 获取项目主线上下文并注入 Prompt。"
            "第三：执行后通过 add_execution_update() 写入本轮摘要。"
            "第四：继续推进 Options wall 多日校准收尾。"
            "第五：逐步完善 Market Odds schema 与事件概率层。"
            "来源：用户确认 (2026-05-16)。"
        ),
        importance="high",
        tags=["next_action", "hermes", "codex", "execution_context"],
    ),
]

# ═══════════════════════════════════════════════════════
# 新增类 [N] — 7 条
# ═══════════════════════════════════════════════════════

NEW_ENTRIES: list[dict] = [
    make_entry(
        "architecture_decision",
        (
            "CME FINAL/PRELIM 版本化 schema 已完成。查询策略 FINAL-preferred + PRELIM 共存，"
            "支持日内预览、盘后修正、多日校准和 OI 变化对比。"
            "Options wall 多日校准优先基于 FINAL 数据，PRELIM 作为临时预览和兜底。"
            "来源：P4-06 实现 + 用户确认 (2026-05-16)。"
        ),
        importance="high",
        tags=["cme", "final", "prelim", "options"],
    ),
    make_entry(
        "architecture_decision",
        (
            "Market Odds 市场赔率模块已接入主链，路径为 schema → snapshot → agent → "
            "coordinator → API/前端。用于补充事件概率层，后续重点接入和完善 "
            "Polymarket、CME FedWatch 等概率型数据源，辅助宏观事件和市场预期分析。"
            "来源：P4-07~P4-09 实现 + 用户确认 (2026-05-16)。"
        ),
        importance="high",
        tags=["market_odds", "polymarket", "fedwatch"],
    ),
    make_entry(
        "architecture_decision",
        (
            "Analysis DB 持久化已完成，使用 SQLite 接入 worker/API，"
            "持久化 AnalysisSnapshot / AgentOutput / FinalAnalysisResult 等分析结果。"
            "保留 filesystem fallback 机制，确保数据库不可用时前端仍可通过文件 artifact 正常消费，"
            "不破坏文件主链和报告输出。"
            "来源：P2-DB 实现 + 用户确认 (2026-05-16)。"
        ),
        importance="high",
        tags=["sqlite", "persistence", "fallback"],
    ),
    make_entry(
        "architecture_decision",
        (
            "当前 Agent 体系包括 7 个模块 Agent + 1 个 coordinator："
            "macro_liquidity_agent / cme_options_agent / risk_agent / news_agent / "
            "market_odds_agent / positioning_agent / technical_agent / coordinator_agent。"
            "Agent 当前定位为确定性规则函数 + 结构化 JSON 输出，不做自主推理。"
            "coordinator 汇总各 Agent 输出生成 final report。"
            "Agent 只读取 Analysis Snapshot 和 output JSON，不直接触碰 raw / parsed / features 原始处理层。"
            "来源：C3 实现 + 用户确认 (2026-05-16)。"
        ),
        importance="high",
        tags=["agent", "coordinator", "snapshot", "boundary"],
    ),
    make_entry(
        "agent_rule",
        (
            "Hermes/Codex 每次执行开发任务前必须调用 "
            "ProjectMainlineMemory.get_execution_context(task) 检索项目主线记忆，"
            "并将返回上下文注入 Prompt。每次只执行一个 Phase，不允许一次性全量重构。"
            "执行后必须调用 add_execution_update() 写入本轮摘要到 Mem0。"
            "执行结果必须输出：修改文件列表、完成项、未完成项、风险点、下一步建议。"
            "来源：用户确认 + AGENTS.md (2026-05-16)。"
        ),
        importance="high",
        tags=["hermes", "codex", "mem0", "workflow"],
    ),
    make_entry(
        "architecture_decision",
        (
            "所有分析结果必须绑定 snapshot_id、input_snapshot_ids、source_refs、"
            "Agent 输出版本号、报告版本和生成时间。缺失数据必须显式标记 unavailable，禁止补造。"
            "raw / parsed / features / outputs 四层必须严格分离，不可混写。"
            "历史报告不可覆盖，应按 date + run_id 或等价版本键分区保存。"
            "来源：AGENTS.md + Obsidian 数据治理规则 (2026-05-16)。"
        ),
        importance="high",
        tags=["lineage", "snapshot", "source_refs", "traceability"],
    ),
    make_entry(
        "project_principle",
        (
            "当前架构原则：确定性脚本主链不可被 Agent 替代；"
            "Agent 只做只读后处理、解释、归因、风险识别和结构化报告生成；"
            "路由保持轻逻辑，业务逻辑放 services/repositories；"
            "Parser 改动必须补回归测试；历史报告不可覆盖；"
            "新增功能必须挂到现有主链（api → scheduler → worker → collectors → parsers → "
            "features → analysis → renderer → output），不另建第二套任务主脑；"
            "DB schema 变更保持 additive migration。"
            "来源：AGENTS.md + Obsidian 总体架构 (2026-05-16)。"
        ),
        importance="high",
        tags=["architecture", "rules", "main_chain"],
    ),
    make_entry(
        "project_principle",
        (
            "记忆分工原则：Obsidian 存完整内容，Mem0 存摘要和约束。"
            "Obsidian 用于保存完整项目文档、架构设计、开发日志、分析报告、Prompt、复盘和长期知识。"
            "Mem0 只保存项目主线摘要、当前阶段、优先级、架构约束、执行规则、用户反馈、错误模式和下一步动作。"
            "Mem0 不替代 Obsidian、Git、Postgres/SQLite、ClickHouse、MinIO 或报告中心。"
            "来源：用户确认 (2026-05-16)。"
        ),
        importance="high",
        tags=["obsidian", "mem0", "memory_policy", "boundary"],
    ),
]


def main():
    if not os.environ.get("MEM0_API_KEY"):
        print("ERROR: MEM0_API_KEY not set")
        sys.exit(1)

    client = MemoryClient()
    total = 0

    def write_batch(entries: list[dict], label: str):
        nonlocal total
        print(f"\n--- {label} ({len(entries)} 条) ---")
        for i, entry in enumerate(entries):
            try:
                result = client.add(
                    messages=[{"role": "user", "content": entry["content"]}],
                    app_id="finance_analysis_system",
                    metadata={
                        **BASE_META,
                        "memory_type": entry["memory_type"],
                        "importance": entry["importance"],
                        "tags": entry["tags"],
                    },
                    infer=False,
                )
                status = result.get("status", "OK")
                print(f"  [{i + 1}] {entry['memory_type']}: {status} — {'/'.join(entry['tags'])}")
                total += 1
            except Exception as e:
                print(f"  [{i + 1}] {entry['memory_type']}: ERROR — {e}")
            time.sleep(0.5)

    write_batch(UPDATES, "更新 [U]")
    write_batch(NEW_ENTRIES, "新增 [N]")

    print("\n══════════════════════════")
    print(f"写入完成：{total} 条新记忆")
    print(f"  [U] 更新: {len(UPDATES)} 条")
    print(f"  [N] 新增: {len(NEW_ENTRIES)} 条")
    print("  [KEEP] 保留: 3 条 (project_vision / core_pipeline / dev_principle)")

    # ── 检索验证 ──
    print("\n--- 检索验证 ---")
    query = "继续 Options wall 多日校准和市场赔率 schema 落地"
    results = client.search(query, filters={"app_id": "finance_analysis_system"}, top_k=5)
    for r in results.get("results", []):
        meta = r.get("metadata", {})
        mt = meta.get("memory_type", "?")
        mem = r["memory"][:100]
        print(f"  [{mt}] {mem}...")


if __name__ == "__main__":
    main()
