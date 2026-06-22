# Skill Context Routing

仅在需要选择专项 skill、讨论 skill 默认加载、上下文过载，或执行前端/报告/Agent 治理/验收等明确任务时读取。

## 防止 Skill 上下文过载

- 单次会话同时激活的 skill 总数不超过 15。
- Skill 使用以完成当前任务所需的最小集合为准。
- 可见 skill 不等于已激活 skill；不得因为已安装就读取其 `SKILL.md`。
- 非前端任务不启用前端/视觉/浏览器类 skill。
- 非报告/解析/宏观/CME 任务不启用对应领域 skill。
- 非验收/提交流程不启用 live acceptance / release checklist。
- 非复杂多文件任务不启用 planning 类 skill。
- 非知识沉淀任务不启用 Obsidian 类 skill。
- 存在重复能力时只保留一套主用入口。

## 可执行 Profile

`scripts/skill_context_router.py` 用目录移动实现新会话级别的 skill 暴露控制。当前会话已经注入的 skill 列表不会被 retroactively 移除；切换后需要新开 Codex 会话才能看到效果。

命令：

```bash
rtk uv run python scripts/skill_context_router.py status
rtk uv run python scripts/skill_context_router.py dry-run lean
rtk uv run python scripts/skill_context_router.py apply lean
rtk uv run python scripts/skill_context_router.py apply frontend
rtk uv run python scripts/skill_context_router.py apply reports
rtk uv run python scripts/skill_context_router.py apply obsidian
rtk uv run python scripts/skill_context_router.py apply lark
rtk uv run python scripts/skill_context_router.py apply full
```

Profile 语义：

| Profile | 作用 |
|---|---|
| `lean` | 默认开发入口，只暴露 finance-agent 常用工程/治理/验收最小集合 |
| `frontend` | 前端页面、设计 QA、浏览器验收 |
| `reports` | Jin10/CME/宏观/黄金日报/报告 artifact QA |
| `obsidian` | Obsidian vault 维护、ADR、路线图、任务看板 |
| `lark` | 飞书/Lark 文档、表格、IM、会议、任务等工具 |
| `full` | 恢复所有已发现 skill |

目录策略：

- repo skill：`/home/zxx/workspace/finance-agent/.codex/skills` <-> `/home/zxx/workspace/finance-agent/.codex/skills-disabled`
- Codex global skill：`/home/zxx/.codex/skills` <-> `/home/zxx/.codex/skills-disabled`
- Agents global skill：`/home/zxx/.agents/skills` <-> `/home/zxx/.agents/skills-disabled`
- system/plugin 注入的 skill 不在这些目录里，不能由本脚本禁用。

## 默认常开候选

仅在任务需要时使用，不自动读取：

- 工程流程与收口：`git-workflow-and-versioning`、`incremental-implementation`
- 仓库理解与约束核对：`finance-agent-grill-with-docs`
- 测试与质量：`test-driven-development`、`code-review-and-quality`
- 后端接口与数据模型：`api-and-interface-design`、`sqlalchemy-db-models`

## 推荐组合

| 场景 | 推荐 skill 组合 |
|---|---|
| 黄金日报 / 宏观分析 | `gold-daily-analysis` -> `macro-pipeline` -> `macro-snapshot-check` -> `cme-options-analysis` -> `finance-agent-report-artifact-qa` |
| CME 期权墙分析 | `cme-options-analysis` -> `cme-bulletin-debug` -> `cme-gold-parser-regression` -> `finance-agent-report-artifact-qa` |
| 前端页面重构 | `frontend-page-refactor` -> `finance-agent-frontend-dev` -> `finance-agent-frontend-design-qa` -> `finance-agent-live-acceptance` |
| 多文件 / 多阶段开发 | `finance-agent-planning-with-files` -> `repo-map` -> `incremental-implementation` -> `git-workflow-and-versioning` |
| 架构 / API / 数据边界调整 | `finance-agent-grill-with-docs` -> `api-and-interface-design` / `sqlalchemy-db-models` -> `documentation-and-adrs` |
| 前端页面 / Dashboard 验收 | `finance-agent-frontend-dev` -> `finance-agent-frontend-design-qa` -> `finance-agent-frontend-visual-polish` -> `frontend-ui-engineering` -> `finance-agent-browser-trace` -> `finance-agent-live-acceptance` |
| 报告 / Jin10 / CME / 宏观产物 | `finance-agent-analysis-pipelines` -> 对应领域 skill -> `finance-agent-report-artifact-qa` -> `vault-sync-guard` |
| Agent 管理 / Prompt Governance | `finance-agent-agent-governance` -> `security-threat-model` -> `security-best-practices` -> `finance-agent-grill-with-docs` |
| 一次性脚本固化 | `finance-agent-script-hardening` -> `cli-creator`（若已安装）-> `test-driven-development` -> `release-checklist` |
| 全链路验收 / 提交前验收 | `finance-agent-live-acceptance` -> `finance-agent-report-artifact-qa`（若涉及报告）-> `release-checklist` -> `git-workflow-and-versioning` |

## 专项说明

- `finance-agent-planning-with-files` 用于把计划绑定到真实文件清单、API、artifact 和验证命令；临时计划写入 `.codex/plans/<日期>-<slug>/`，长期状态仍写入 Obsidian。
- `finance-agent-frontend-design-qa` 用于前端设计和页面 QA；优先按当前 React/Vite、设计 token、真实数据状态和浏览器证据执行。
- `finance-agent-frontend-visual-polish` 用于前端排版、视觉层级、typography、spacing、组件状态和美化验收。
- `finance-agent-browser-trace` 用于前端验收；页面能打开不等于验收通过，必须补充 API、console、network、DOM 或截图证据。
- `finance-agent-report-artifact-qa` 用于检查 Jin10/CME/宏观报告产物的 Markdown/JSON、图片引用、`source_refs`、summary 和数据层边界。
- 若推荐 skill 未安装或当前会话未加载，继续使用同等检查清单手工执行，不得因此跳过验收。
