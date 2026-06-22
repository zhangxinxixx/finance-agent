# finance-agent / AGENTS.md

本文件是默认自动注入入口，只保留高频硬规则。更长的治理、Skill、Obsidian、命令和验收细则按任务命中后再读取 `docs/agent-context/` 下的专题文档，避免每次请求都加载全量上下文。

环境级命令规则见 `/home/zxx/.codex/RTK.md`：外部命令默认优先使用 `rtk` 压缩输出。

## 1. 默认执行风格

- 默认使用简体中文与用户交流，除非用户明确要求其他语言。
- 保留命令、代码、路径、环境变量、接口字段名的原文。
- 回答优先给结论、修改点、关键代码或验证结果；避免重复背景。
- 不确定时明确说明，不编造不存在的文件、变量、接口或依赖。
- 默认遵循 Karpathy Guidelines：简单直接、外科手术式改动、能验证再扩大范围。
- 先评估请求复杂度和风险，再决定是否需要 Plan/Spec、澄清或专项 skill；不要机械化扩大流程。

## 2. 项目定位与主链

这是一个本地可运行、可追溯、可复盘的金融分析系统，不是自动交易系统。

生产主链固定为：

```text
api -> scheduler -> worker -> collectors -> parsers -> features -> analysis -> renderer -> output
```

任何新增功能必须挂到这条主链路中，不要新增第二套任务主脑。

当前默认阶段是 MVP：官方宏观数据采集、CME Daily Bulletin PDF 下载解析、宏观指标和期权墙计算、Markdown 报告和策略卡片、最小 Dashboard、任务日志、失败原因、重试。

暂不做：自动交易下单、多 Agent 生产主脑、Prefect Server、LangGraph 接管 worker、大规模 ClickHouse、全自动多站点 VIP 登录态、复杂权限系统。

## 3. 按需读取路由

默认不要读取这些专题文档。只有任务命中对应场景时再打开：

| 场景 | 按需读取 |
|---|---|
| Hermes OS、Core/Executor/Subagent、CodeGraph、Reasoning OS、Memory/Output Layer | `docs/agent-context/hermes-governance.md` |
| Skill 选择、上下文过载、前端/报告/Agent 治理/验收 skill 路由 | `docs/agent-context/skill-context-routing.md` |
| Obsidian 计划沉淀、版本记录、ADR、知识库归档 | `docs/agent-context/obsidian-rules.md` |
| 命令、Mem0 预取、验证矩阵、验收收口 | `docs/agent-context/commands-and-acceptance.md` |

读取原则：

- 普通问答、状态查询、简单 shell 命令不读取专题文档。
- 单文件小改只读当前文件和必要邻近上下文。
- 跨文件开发、架构调整、数据链路、前端验收、报告产物或提交前验收，按上表读取最小必要文档。
- Skill 是模板库，不参与路由决策；可见 skill 不等于已激活 skill。
- 若需要减少未来新会话的 skill 元数据注入，用 `scripts/skill_context_router.py` 应用 profile；当前会话已注入的 skill 列表不会被 retroactively 移除。

## 4. 架构与数据边界

可以做：

- 补 `collectors`、`parsers`、`features`、`analysis`、`renderer`。
- 补 `api` 只读接口。
- 补 `dashboard` 只读页面。
- 补测试、迁移、脚本、文档。
- 补 CME、FRED、Fed、Treasury 主链。

禁止做：

- 不要让前端自己计算策略。
- 不要让 Agent 直接改原始数据。
- 不要绕过 `task_runs` 和 `task_steps`。
- 不要覆盖历史报告。
- 不要为了重构破坏当前可运行链路。

数据原则：

- `raw`、`parsed`、`features`、`outputs` 分层不能混。
- 原始 API 响应和 PDF 文件必须归档。
- 每个 AI 分析结果必须绑定 `input_snapshot_ids` 和 `source_refs`。
- 缺失数据必须显式标记，不允许补造。
- 手工上传仅作为兜底，不作为 MVP 主流程。

## 5. 前端入口规则

当前前端只保留一套主线：

- `apps/frontend-web/src`：一级主线。所有新页面、新组件、新报告展示和 API 对接默认只允许修改这里。
- `apps/frontend-web/`：Vite + React 18 正式前端工程。配置、构建脚本和静态资源仅在服务当前主线时修改。
- `apps/frontend/`：已删除的旧 Next.js 前端，不允许恢复为新需求入口。
- `apps/frontend-web/dashboard.html`：已删除的早期 FastAPI 直出 HTML，不允许恢复或新增能力。

除非用户明确说明兼容修复，否则前端开发不得修改、重建或新增第二套入口。FastAPI `/dashboard` 仅作为兼容跳转，真实页面以 Vite `/dashboard` 为准。

## 6. 代码修改与检索原则

- 修改代码前先概述计划。
- 涉及多个文件时先说明影响范围和验证方式。
- 优先最小改动；优先修复现有链路，而不是重写。
- 不做无关重构；不引入不必要依赖；不改变无关逻辑。
- routes 保持轻逻辑，业务逻辑放到 services/repositories。
- parser 改动必须补样本或回归测试。
- 禁止为定位问题直接全文遍历项目；先用 CodeGraph、`rg` 或 `git grep` 精准定位影响范围，再读取必要文件。
- 检索和批量操作默认排除 `node_modules`、`.git`、`dist`、`build`、`.venv`、缓存和生成物目录。
- 输入一律视为不可信；涉及路径、命令、外部参数、上传内容时优先使用白名单和结构化 API。

Plan / Spec：

- 复杂任务（多文件修改、架构调整、新功能、迁移、批量替换）必须先输出 Plan/Spec。
- Plan 至少包含：目标、理解、待确认问题、方案对比、影响范围、风险点、验证方式。
- 存在多种方案或需求不明确时，先暂停提问，不用猜测推进。
- 仅修正文案、单文件小改、格式调整、规则文件自身维护等低风险任务，可不新建 Obsidian 执行方案，但仍需说明范围和验证方式。

## 7. 命令与 Mem0

项目 Python 依赖由 `uv` 管理，项目根固定 `.python-version = 3.11`，本地虚拟环境为 `.venv/`。

- 跑项目 Python 代码必须使用：`uv run python ...`，或明确使用 `.venv/bin/python`。
- 不要用裸 `python3 ...` 跑项目模块或脚本。
- 必须优先使用 `rtk` 执行外部命令以减少输出。
- localhost smoke test 或长任务前保留小写：`no_proxy=127.0.0.1,localhost,::1`。

非平凡开发任务前预取项目记忆：

```bash
rtk uv run python scripts/mem0_prefetch_context.py "<task>"
```

跳过场景：普通问答、状态查询、简单 shell 命令、token/用量统计、纯格式化说明。

若命令提示任务未命中检索条件，则继续正常执行；若因 `MEM0_API_KEY` 缺失失败，报告失败并继续，不编造上下文。若上游上下文已注入 `## Mem0 Context`，执行 Agent 不需要重复查询 Mem0。

详细命令清单和验证矩阵见 `docs/agent-context/commands-and-acceptance.md`。

## 8. Obsidian / 长期记录

Obsidian vault 固定为：`/home/zxx/wiki/Finance-Agent-Knowledge-Vault`。

必须写入 vault 的情况：

- 完成一个 Phase 或 Task 组 -> 写版本记录；若有架构决策则写 ADR。
- 修改了主链架构或模块边界 -> 写 ADR。
- 发现并解决重要风险/卡点 -> 更新风险与卡点页。
- 每周或里程碑节点 -> 更新当前进度页。

唯一入口摘要：

- 当前进度：`02-项目/金融分析系统/02-当前进度.md`
- 当前任务：`02-项目/金融分析系统/06-任务看板.md`
- 开发路线图：`02-项目/金融分析系统/04-开发路线图.md`
- 版本/变更记录：`02-项目/金融分析系统/09-版本记录.md`
- 风险与卡点：`02-项目/金融分析系统/08-风险与卡点.md`
- 架构事实：`03-架构/总体架构.md` 及对应架构页
- 每日过程：`07-开发日志/YYYY-MM-DD.md`

完整写入规则、模板、归档口径见 `docs/agent-context/obsidian-rules.md`。

## 9. 验收原则

按改动范围选择验证：

- API：跑 API tests 和 `/health`。
- worker/pipeline：跑 smoke test。
- collector：保存 raw 样本并跑采集测试。
- parser：跑 fixture regression。
- features：跑公式和边界测试。
- renderer/output：检查 Markdown/JSON 非空和字段完整。
- dashboard：打开页面检查只读 API 是否可消费。

完成前必须说明：

- 改了哪些文件。
- 跑了哪些验证。
- 哪些验证没跑，原因是什么。

声称「完成/修复/通过」前，必须用实际命令、diff、日志或页面/API 证据确认；复杂验收按需读取 `docs/agent-context/commands-and-acceptance.md`。

## 10. Agent 边界摘要

- 主控 Agent（Core）是唯一决策中枢，负责目标定义、架构决策、优先级排序、风险控制、任务派发和最终验收。
- Subagent 是纯执行器，只执行边界清晰、互不冲突的任务包；不得规划、路由、写入记忆或选择 Skill。
- 多 Agent 不得同时修改同一文件或同一 migration。
- 子 Agent 输出是自述信息，必须由主控二次验证后才能作为事实采纳。
- 复杂 Hermes / 多 Agent / Reasoning OS 任务读取 `docs/agent-context/hermes-governance.md`。
