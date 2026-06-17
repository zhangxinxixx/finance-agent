# 文档整理索引

更新时间：2026-05-26

> 本索引用于整理当前仓库内的 Markdown 文档位置与用途。未移动或删除任何现有文件，避免破坏已有引用。

## 1. 当前文档分组

### 1.1 项目规则 / Agent 约束

| 文件 | 用途 |
| --- | --- |
| `AGENTS.md` | 项目主约束、架构边界、命令约定、验收原则。所有 Agent 执行任务前应遵守。 |
| `docs/dev/workbench-maintenance.md` | Hermes/Codex 工作台维护指南，包含 tmux pane 派发、可视化 Codex job、飞书 `lark-channel-bridge` 远程入口和排障命令。 |
| `docs/dev/feishu-docs/README.md` | 飞书云文档唯一维护入口，记录当前云端入口、归档边界、发布命令、渲染规范和 V2 中台。 |
| `docs/dev/feishu-doc-publish.md` | 旧路径兼容入口，指向 `docs/dev/feishu-docs/`。 |
| `docs/dev/feishu-doc-rendering-roadmap.md` | 旧路径兼容入口，指向 `docs/dev/feishu-docs/rendering-spec.md` 与官方能力说明。 |
| `docs/dev/playwright-mcp.md` | Playwright MCP 浏览器取证和前端验收接入说明，包含 Codex MCP 配置、登录态 profile、输出目录和安全边界。 |
| `docs/13_NEWS_DATA_PIPELINE.md` | 新闻数据源采集状态、事件加工 artifact、follow-up 任务和后续日报流程架构。 |

### 1.2 前端设计与实现文档

| 文件 | 用途 |
| --- | --- |
| `docs/frontend/design-system.md` | P0-09 前的旧设计系统基线；当前需由 FinAnalytics Pro 设计系统映射更新。 |
| `docs/frontend/component-map.md` | P0-09 前的 Figma Make 组件映射基线；当前新增视觉迁移以 FinAnalytics Pro HTML 映射为准。 |
| `docs/frontend/p0-visual-migration-task-plan.md` | P0-09 至 P0-15 前端视觉迁移任务拆分：设计系统映射、Reports、Agent Tasks、Data Ingestion、Dashboard、Market Monitor、CME Options。 |
| `docs/frontend/figma-make-review.md` | Figma Make 原型代码审查报告。 |
| `docs/frontend/page-specs/dashboard.md` | Dashboard 页面规格。 |
| `docs/frontend/page-specs/data-ingestion.md` | 数据接入页规格。 |
| `docs/frontend/page-specs/market-monitor.md` | 市场监控页规格。 |
| `docs/frontend/page-specs/cme-options.md` | CME 期权结构页规格。 |
| `docs/frontend/tasks/p0-shell.md` | 历史 Shell / Vite / React 脚手架任务卡；不得作为当前新派发任务直接执行。 |
| `docs/frontend/tasks/p0-dashboard.md` | 历史 Dashboard P0 页面任务卡；当前 Dashboard 新视觉以 P0-13 为准。 |
| `docs/frontend/tasks/p0-data-ingestion.md` | 历史数据接入页 P0 任务卡；当前 Data Ingestion 新视觉以 P0-12 为准。 |
| `docs/frontend/tasks/p0-market-monitor.md` | 历史市场监控页 P0 任务卡；当前 Market Monitor 新视觉以 P0-14 为准。 |
| `docs/frontend/tasks/p0-cme-options.md` | 历史 CME 期权页 P0 任务卡；当前 CME Options 新视觉以 P0-15 为准。 |
| `docs/frontend/tasks/p0-playwright-visual-check.md` | 历史 Playwright 视觉验收任务卡；当前视觉验收以 P0-09 FinAnalytics Pro 映射为准。 |

### 1.2b 后端契约与底座规划

| 文件 | 用途 |
| --- | --- |
| `docs/backend/foundation-roadmap.md` | 下一阶段后端底座优先路线：Schema/Contract、TaskRun/TaskStep、SourceTrace、报告三产物、Review、DataSourceStatus、StrategyCard、Market K 线 API，以及前端分批接入节奏。 |

### 1.3 Figma Make 原型资料

| 文件 | 用途 |
| --- | --- |
| `docs/frontend/figma-make/README.md` | Figma Make 导出说明。 |
| `docs/frontend/figma-make/ATTRIBUTIONS.md` | Figma Make 导出依赖/署名。 |
| `docs/frontend/figma-make/guidelines/Guidelines.md` | 原型侧通用 guidelines。 |

说明：这组文件应作为原型参考，不应作为正式前端实现入口。正式前端目标目录是 `apps/frontend-web`。

### 1.3b FinAnalytics Pro 设计系统参考

| 文件 | 用途 |
| --- | --- |
| `docs/frontend/finanalytics-pro-design-system/FinAnalytics_Preview.html` | 最新 FinAnalytics Pro 页面视觉和设计 token source of truth；只读参考，不直接复制进 React。 |
| `docs/frontend/finanalytics-pro-design-system/knowledge-base.html` | Knowledge Base 专用页面参考：知识列表、详情、图谱和运营面板。 |
| `docs/frontend/finanalytics-pro-design-system/ui_kit/` | 可复用 shell、status bar、right panel、primitives 参考。 |
| `docs/frontend/finanalytics-pro-design-system/uploads/01_dashboard_overview.png` 至 `09_settings.png` | 九个页面视觉密度检查图。 |

### 1.4 Hermes 执行计划

| 文件 | 用途 |
| --- | --- |
| `hermes/plans/mvp-frontend-workbench-plan.md` | 金融分析中台前端工作台化改造总计划。 |
| `hermes/plans/deepseek-v4-frontend-task-cards.md` | DeepSeek V4 Pro 子模型任务分配。 |
| `hermes/plans/p0-c4-renderer-strategy-card-task-cards.md` | C4 renderer / final report / strategy card 任务卡。 |
| `hermes/plans/p1-c4-real-data-frontend-task-cards.md` | 真实数据 + C4 前端集成任务卡。 |
| `hermes/plans/p2-analysis-db-migration-task-cards.md` | Analysis DB 迁移任务卡。 |
| `hermes/plans/p4-system-upgrade-task-cards.md` | 系统升级任务卡。 |
| `hermes/plans/p0-analysis-snapshot-builder-task-cards.md` | Analysis snapshot builder 任务卡。 |
| `hermes/plans/p0-readonly-pseudo-agents-task-cards.md` | 只读 pseudo agents 任务卡。 |
| `hermes/plans/p3-positioning-technical.md` | Positioning + Technical 数据源接入计划。 |
| `hermes/plans/2026-05-16_225000-dashboard-v03-realign.md` | Dashboard v0.3 对齐设计稿计划。 |
| `hermes/plans/codex-execution-queue-20260507.md` | Codex 执行队列记录。 |

### 1.5 Hermes 提示词 / Codex 任务包

| 文件 | 用途 |
| --- | --- |
| `hermes/prompts/architect.md` | 架构师提示词。 |
| `hermes/prompts/frontend-layout-unification.md` | 正式前端视觉终版统一任务包。 |
| `hermes/prompts/codex-dashboard-v03-phase1.md` | Dashboard v0.3 Phase 1 Codex 任务包。 |
| `hermes/prompts/codex-dashboard-v03-phase2.md` | Dashboard v0.3 Phase 2 Codex 任务包。 |
| `hermes/prompts/codex-p0-dashboard.md` | Codex Mem0 接入程序 / P0 Dashboard 相关任务包。 |
| `hermes/prompts/p0-09-finanalytics-design-system-mapping.md` | Task P0-09：FinAnalytics Pro 设计系统映射与共享 UI 组件整理任务包。 |
| `hermes/prompts/codex-mem0-integration-smoke.md` | Mem0 对接 smoke test 任务包。 |
| `hermes/prompts/mem0-prefetch-runbook.md` | Mem0 prefetch runbook。 |

### 1.6 记忆与项目状态

| 文件 | 用途 |
| --- | --- |
| `hermes/memory/project-state.md` | 当前项目状态摘要与入口。 |
| `hermes/memory/project_mainline_seed.md` | 项目主线 seed。 |
| `hermes/memory/memory_update_log.md` | 记忆更新日志。 |
| `docs/memory/mem0_project_mainline.md` | Mem0 在项目开发主线中的定位。 |

### 1.7 评审记录

| 文件 | 用途 |
| --- | --- |
| `hermes/reviews/frontend-workbench-final-review.md` | 前端 workbench 最终评审。 |
| `hermes/reviews/p2-analysis-db-readiness.md` | P2 Analysis DB readiness review。 |
| `hermes/reviews/p2-analysis-db-final-review.md` | P2 Analysis DB final review。 |

### 1.8 初始交付归档文档

| 文件 | 建议 |
| --- | --- |
| `docs/archive/initial-delivery/系统架构与功能拆解说明_交付版.md` | 初始系统架构设计，保留作为历史架构依据；当前执行以 `AGENTS.md`、`hermes/memory/project-state.md` 和最新 plans 为准。 |
| `docs/archive/initial-delivery/开发规划文档_交付版.md` | 初始阶段规划，保留作为路线来源；当前排期以 `hermes/plans/` 和 Obsidian 路线图为准。 |
| `docs/archive/initial-delivery/多Agent开发分工计划_交付版.md` | 初始多 Agent 分工方案，保留作为工作流来源；当前约束以 `AGENTS.md` 为准。 |
| `docs/archive/initial-delivery/Hermes启动指令_交付版.md` | 初始启动指令，项目已启动，保留归档，不再作为日常入口。 |
| `docs/archive/initial-delivery/Phase0首批任务卡_交付版.md` | Phase 0 初始任务卡，大部分已过期，保留归档用于追溯。 |
| `docs/archive/initial-delivery/AGENTS模板_finance-agent.md` | 初始 AGENTS 模板，已被根目录 `AGENTS.md` 取代，保留归档。 |

## 2. 推荐阅读入口

### 新 Agent / 新会话

1. `AGENTS.md`
2. `hermes/memory/project-state.md`
3. `docs/backend/foundation-roadmap.md`（如涉及后端底座、报告、任务状态、溯源、前后端契约）
4. `docs/frontend/design-system.md`（如涉及前端）
5. 对应的 `docs/frontend/page-specs/*.md` 或 `hermes/plans/*.md`

### 前端开发

1. `docs/frontend/design-system.md`
2. `docs/frontend/component-map.md`
3. `docs/frontend/page-specs/dashboard.md`
4. `docs/frontend/tasks/p0-shell.md`
5. `docs/frontend/tasks/p0-playwright-visual-check.md`

### Mem0 / 项目记忆

1. `docs/memory/mem0_project_mainline.md`
2. `hermes/prompts/mem0-prefetch-runbook.md`
3. `hermes/prompts/codex-mem0-integration-smoke.md`

### Codex 派发

1. `AGENTS.md`
2. `hermes/plans/*-task-cards.md`
3. `hermes/prompts/*.md`

## 3. 建议后续归档策略

当前已建立索引并完成初始交付文档归档。若后续要进一步清理，建议按下面规则执行：

1. `docs/frontend/`：保留长期前端规范、页面规格、任务卡。
2. `docs/memory/`：保留 Mem0 / 项目记忆说明。
3. `hermes/plans/`：保留可执行计划和阶段任务卡。
4. `hermes/prompts/`：保留可复用的 Codex / 子 Agent 任务包。
5. `hermes/reviews/`：保留验收与评审记录。
6. 根目录只保留 `AGENTS.md`、README 类入口文档；初始交付件已迁入 `docs/archive/initial-delivery/`。
7. 旧 `apps/frontend/` Next.js 前端和旧 `apps/frontend-web/dashboard.html` 已删除；新前端以 `apps/frontend-web/src` 为准。

## 4. 本次整理排除范围

以下文件未纳入本索引：

- `storage/outputs/**`：运行生成的报告输出，不属于仓库规划/开发文档。
- `node_modules/**`：第三方依赖文档，不属于项目文档。
