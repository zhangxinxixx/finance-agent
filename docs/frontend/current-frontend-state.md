# 前端状态快照

- 日期：2026-05-28
- 状态：historical snapshot；仅用于追溯当时前端盘点，不再作为当前前端事实入口。
- 范围：`apps/frontend-web/src`
- 性质：当前 checkout 静态梳理，不代表已提交基线
- 入口结论：正式前端主线是 `apps/frontend-web/src`，旧 `apps/frontend/` 和旧 `apps/frontend-web/dashboard.html` 不再作为开发入口

> 2026-06-08 校准：当前前端事实请优先看 Obsidian `03-架构/前端页面架构.md`、repo `docs/frontend/api-contract.md` 和 `docs/dev/current-task.md`。本页中 `mock-only`、`未确认`、旧 `/api/final-report*` / `/api/strategy-card*` 优先级等说法是 2026-05-28 快照，不作为当前执行入口。

## 0. 当前状态摘要（2026-06-08）

- 正式前端仍为 `apps/frontend-web/src`。
- P1 / P2 read model 已覆盖 Review Center、CME Options、Strategy、Event Flow、Knowledge、Settings、Dashboard、Market Monitor、Reports、Agent Tasks 等页面；缺失数据必须显示 unavailable / partial / fallback，不在前端补造。
- Report Detail 已接入 analysis-inputs，Agent Tasks 已展示 Agent Prompt/Input/Output，P2-11 已补 Settings / Agent Tasks / Report Detail 的 Prompt Feedback 写入口。
- `/dashboard/analysis`、`/reports/:reportId`、`/knowledge/:knowledgeId`、`/event-flow/:eventId` 等详情/下钻路线已成为页面分层主线的一部分。
- 页面级任务状态继续以 Obsidian `06-任务看板.md` 为准。

## 1. 架构概览

当前前端是 Vite + React 18 + React Router 单页应用。

```text
Browser
  -> Vite frontend (`apps/frontend-web`)
  -> React Router routes
  -> AppShell
  -> Page component
  -> hook
  -> adapter
  -> apiClient / backend API / mock fallback
```

关键文件：

| 文件 | 作用 |
|---|---|
| `apps/frontend-web/src/main.tsx` | React 入口和路由注册 |
| `apps/frontend-web/src/components/AppShell.tsx` | 全局工作台壳层：Sidebar / Header / 页面 Outlet / 底部数据状态条 |
| `apps/frontend-web/src/components/AppSidebar.tsx` | 左侧导航菜单 |
| `apps/frontend-web/src/components/AppHeader.tsx` | 顶部 breadcrumb、搜索框、数据源状态、刷新与用户入口 |
| `apps/frontend-web/src/adapters/apiClient.ts` | 统一 `fetchJson<T>()` 和 `ApiError` |
| `apps/frontend-web/vite.config.ts` | Vite 配置，开发期 `/api` 代理到 FastAPI |
| `apps/api/main.py` | `/dashboard` 兼容旧入口，实际 307 跳转到 Vite `/dashboard` |

## 2. 当前路由

| 路由 | 页面文件 | 当前功能 |
|---|---|---|
| `/` | `main.tsx` redirect | 默认跳转到 `/dashboard` |
| `/dashboard` | `src/pages/DashboardPage.tsx` -> `components/dashboard/DashboardPage.tsx` | 总览页 |
| `/data-ingestion` | `src/pages/DataIngestionPage.tsx` | 数据接入监控 |
| `/event-flow` | `src/pages/EventFlowPage.tsx` | 事件流 |
| `/market-monitor` | `src/pages/MarketMonitorPage.tsx` | 市场监控 |
| `/cme-options` | `src/pages/CMEOptionsPage.tsx` | CME 期权结构 |
| `/reports` | `src/pages/ReportsPage.tsx` | 报告中心 |
| `/reports/:reportId` | `src/pages/ReportDetailPage.tsx` | 报告详情 |
| `/knowledge-base` | `src/pages/KnowledgeBasePage.tsx` | 知识库 |
| `/knowledge/:knowledgeId` | `src/pages/KnowledgeBasePage.tsx` | 知识详情 |
| `/agent-tasks` | `src/pages/AgentTasksPage.tsx` | Agent 任务运行工作台 |
| `/agent-tasks/:runId` | `src/pages/AgentTaskDetailPage.tsx` | Agent 任务详情 |
| `/review-center` | `src/pages/ReviewCenterPage.tsx` | 审查中心 |
| `/settings` | `src/pages/SettingsPage.tsx` | 系统设置 |
| `/strategy` | `src/pages/StrategyPage.tsx` | 策略中心 |

备注：

- `src/pages/LoginPage.tsx` 存在，但当前未在 `main.tsx` 注册路由。
- `src/pages/PlaceholderPage.tsx` 存在且被 import，但当前没有实际路由使用。
- `/strategy` 策略中心已在 `main.tsx` 和 `AppSidebar.tsx` 注册；Dashboard 顶部跳转按钮组已增加策略中心入口。
- 动态路由状态以当前 `apps/frontend-web/src/main.tsx` 和浏览器验收为准；本页不再维护实时路由 fallback 细节。

## 3. 页面模块功能

### `/dashboard` 总览

核心模块：

- 判断横幅：展示今日市场状态和高层结论。
- KPI strip：`XAUUSD`、`DXY`、`US10Y`、`REAL_10Y`、净 GEX、钉住价位。
- 市场快照：展示市场指标和模块状态。
- CME 期权摘要：展示 options 摘要、墙位和意图。
- 综合分析摘要：展示综合结论、价位共振地图、交易剧本、改判条件。
- 右侧面板：展示报告、风险、任务或上下文信息。
- 页面底部状态：展示 dashboard 内的数据源状态。

主要数据路径：

- `useDashboard()`
- `adapters/api.ts`
- `/api/dashboard/summary`
- `/api/reports/dates`
- `/api/strategy-card/latest`
- `mocks/dashboard.json`

### `/data-ingestion` 数据接入

核心模块：

- 页面头部：数据接入状态、生成时间、最后刷新时间。
- `PipelineArrowStepper`：按 pipeline layer 展示数据流转状态。
- `SourceGauge`：展示总数据源、可用、部分可用、错误数量。
- `GroupedSourceTable`：按分组展示数据源状态。
- 阻断问题面板：聚合 error / warn / missing source。
- `PipelineRunsLog`：展示数据源相关运行日志或最近状态。

主要数据路径：

- `useDataIngestion()`
- `adapters/dataIngestion.ts`
- `/api/data-sources/status`
- `/api/data-status/summary`
- `mocks/data-ingestion.json`

### `/event-flow` 事件流

核心模块：

- 筛选栏：资产、区域、事件类型、重要性、时间范围、传导方向、定价状态、数据来源。
- 左侧事件时间线：选择活跃事件。
- 中间事件传导链：展示事件、冲击类型、一级变量、二级变量、定价状态和交易判断。
- 情绪指标：高冲击事件、风险情绪、避险需求等。
- 事件表：事件明细列表。
- 右侧面板：风险雷达、影响资产、事件报告入口。

主要数据路径：

- `useEventFlow()`
- `adapters/eventFlow.ts`
- 当前为 mock-only adapter。

### `/market-monitor` 市场监控

核心模块：

- 页面标题和状态 pill：API Live / Mock、快照时间、诊断状态。
- `MarketPriceCards`：核心市场指标卡。
- `MultiLineChart`：跨资产/宏观指标趋势。
- `FactorPanel`：因子说明或摘要。
- `AssetTable`：资产指标表。
- `Heatmap`：指标热力图。
- `RightPanel`：市场 regime、环境或侧栏上下文。

主要数据路径：

- `useMarketMonitor()`
- `adapters/marketMonitor.ts`
- `/api/market/tickers`
- `/api/macro/latest`
- `mocks/market-monitor.json`

### `/cme-options` CME 期权结构

核心模块：

- 日期加载：从 options dates 选择可用交易日。
- 页面头部：source、报告状态、expiries、Black-76 标识。
- Intent Banner：当前期权结构意图和置信度。
- KPI strip：结构状态、Net GEX、Gamma Zero、当前 F、主战区、主墙位。
- 左列：价格层级、日变化。
- 中列：Gamma Zero、Options wall table、IV skew、source trace。
- 右列：交易剧本、GEX 倾向、分析摘要、关键观测。

主要数据路径：

- `useCMEOptions(selectedDate)`
- `adapters/cmeOptions.ts`
- `/api/options/dates`
- `/api/options/snapshot`
- `mocks/cme-options.json`

### `/reports` 报告中心

核心模块：

- KPI strip：今日报告、Snapshot 绑定、待复核、已发布、可导出、最新生成。
- Toolbar：搜索、视图切换。
- 左侧 `ReportsRail`：报告类型、状态、日期等筛选。
- 主内容区：grid / list / timeline 三种列表视图。
- 内嵌 viewer：按 report family 渲染不同报告。
- 支持报告族：
  - `final_report_markdown`
  - `cme_options_visual`
  - `jin10_daily_visual`
  - `jin10_weekly_visual`

主要数据路径：

- `useReports()`
- `adapters/reports.ts`
- `/api/reports/index`
- `/api/reports/dates`
- `/api/final-report/latest`
- `/api/final-report`
- `/api/options/visual-report/latest`
- `/api/options/visual-report`
- `/api/jin10/report-bundle/latest`
- `/api/jin10/report-bundle`
- `/api/jin10/weekly-report/latest`
- `/api/jin10/weekly-report`

### `/reports/:reportId` 报告详情

核心模块：

- 报告 meta：family、asset、trade date、run id、snapshot id、asOf、artifact 数。
- 状态 badges：data status、lifecycle status、review status。
- 报告产物工作台：`analysis` / `source` / `visual` / `evidence` tabs。
- 内容渲染：Markdown / HTML iframe / JSON pre。
- 右侧数据溯源：source refs、snapshot/run/asOf/dataDate 信封。

主要数据路径：

- `useReportDetail(reportId)`
- `adapters/reports.ts`
- `/api/reports/{report_id}`
- `/api/source-trace/by-report`

### `/knowledge-base` 知识库

核心模块：

- 搜索框：按主题、规则、输入数据、引用模块搜索。
- 主题和状态筛选。
- 类型 tabs：全部、方法论、Playbook、研究笔记、复盘、Agent 规则、数据字典。
- 左侧知识条目列表。
- 中间知识详情。
- 右侧运营面板：统计、pinned、候选 playbook 等。

主要数据路径：

- `useKnowledge()`
- `adapters/knowledge.ts`
- 当前为 mock-only adapter。

### `/agent-tasks` Agent 任务

核心模块：

- 页面头部：运行数量、待复核数量、更新时间。
- 运行列表：最近 run queue，支持通过 `run_id` URL 参数选中。
- 选中运行摘要：task type、status、stage、progress、snapshot、final result、成本、token。
- 步骤时间线：task steps 和 stage 状态。
- 运行日志摘要：runtime log。
- Artifact refs：输出产物引用。
- 数据溯源：source refs。
- Review queue：待人工复核项。

主要数据路径：

- `useAgentTasks(selectedRunId)`
- `adapters/agentTasks.ts`
- `/api/runs`
- `/api/reviews`
- `mocks/agent-runs.json`

### `/settings` 系统设置

核心模块：

- 设置 tabs：通用设置、数据源接入、Agent 模型、报告模板、API 密钥。
- 数据源卡片：连接状态、API key mask、本地 toggle。
- 全局配置项：默认 LLM、时区、语言、日内更新频率等。
- 系统信息。
- 存储与导入统计。
- 近期变更日志。

主要数据路径：

- `useSettings()`
- `adapters/settings.ts`
- 当前为 mock-only adapter，本地 toggle 不写后端。

### `/strategy` 策略中心

当前状态：

- 页面已实现基础只读入口，并已注册路由和侧边栏入口。
- 数据层通过 `useStrategy()` -> `adapters/strategy.ts` 先消费 `/api/strategy-card/latest`，失败时显式 mock fallback。
- 后端已有单数策略卡端点：`/api/strategy-card/latest`、`/api/strategy-card?date&run_id`。
- 后端已有兼容型复数 read model：`/api/strategy-cards`、`/api/strategy-cards/latest`、`/api/strategy-cards/{strategy_card_id}`。
- 后端已有溯源端点：`/api/source-trace/by-strategy/{strategy_card_id}`。
- 前端当前优先消费复数 read model：`/api/strategy-cards/latest` + `/api/strategy-cards?limit=20`；失败时回落单数 `/api/strategy-card/latest`，再失败才显示 mock。
- 页面已支持历史策略列表和按 `strategy_card_id` 切换详情；历史项点击调用 `/api/strategy-cards/{strategy_card_id}`。
- Dashboard 已提供 `/strategy` 跳转入口，但不复制 Strategy Center 详情内容。

当前页面模块：

- 顶部总控：当日 `StrategyCard` 的 bias、confidence、market_regime、run_id、snapshot_id。
- 主方案：main_scenario、alternative_scenarios、key_levels。
- 条件区：trigger_conditions、invalidation_conditions、confirmation_conditions、risk_points。
- 信号汇聚：只展示后端返回的 module_signals；缺失模块显示 unavailable。
- Playbook 匹配：只展示后端返回的 playbook_matches；不在前端执行规则匹配。
- 右侧溯源：source_refs、artifact_refs、evidence_refs、报告回链。

边界：

- 前端不生成策略、不计算 bias、不匹配 Playbook。
- Dashboard 只保留策略摘要和跳转入口，点击进入 `/strategy`。
- 一键生成报告、复盘写回、Playbook 模板管理属于 P2，不进入 P1 MVP。

## 4. 当前工作区改动

当前 `git status --short` 显示前端和文档工作区存在未提交变更。

已修改的前端文件：

```text
apps/frontend-web/src/components/dashboard/DashboardComposite.tsx
apps/frontend-web/src/components/dashboard/DashboardPage.tsx
apps/frontend-web/src/components/market-monitor/AssetTable.tsx
apps/frontend-web/src/components/market-monitor/Heatmap.tsx
apps/frontend-web/src/components/market-monitor/MultiLineChart.tsx
apps/frontend-web/src/index.css
apps/frontend-web/src/pages/CMEOptionsPage.tsx
apps/frontend-web/src/pages/DataIngestionPage.tsx
apps/frontend-web/src/pages/EventFlowPage.tsx
apps/frontend-web/src/pages/KnowledgeBasePage.tsx
apps/frontend-web/src/pages/MarketMonitorPage.tsx
apps/frontend-web/src/pages/ReportsPage.tsx
```

新增但未跟踪的前端组件：

```text
apps/frontend-web/src/components/data-ingestion/GroupedSourceTable.tsx
apps/frontend-web/src/components/data-ingestion/PipelineArrowStepper.tsx
apps/frontend-web/src/components/data-ingestion/PipelineRunsLog.tsx
apps/frontend-web/src/components/data-ingestion/SourceGauge.tsx
apps/frontend-web/src/components/event-flow/ImpactAssets.tsx
```

其他未跟踪项：

```text
docs/superpowers/
```

当前 diff 统计：

```text
12 frontend files changed, 261 insertions(+), 817 deletions(-)
```

其中最大变化集中在 `DataIngestionPage.tsx`：页面从大文件中抽出多个 `components/data-ingestion/*` 组件，页面自身保留数据加载、状态判断和布局组装。

## 5. 当前风险与待确认

| 项 | 状态 | 说明 |
|---|---|---|
| 编译状态 | 已通过 | 2026-05-28 已运行 `npm run typecheck` 和 `npm run build`；路由级 lazy chunk 拆分后 Vite chunk size warning 已消除 |
| 浏览器页面状态 | 历史项 | 2026-06 后已多轮覆盖关键页面 smoke；当前验收状态看 `docs/dev/current-task.md` 和开发日志 |
| API 联通 | 历史项 | 关键 read model 已多轮接入；当前接口事实看 `docs/frontend/api-contract.md` |
| Mem0 项目上下文 | 历史项 | 当前 finance-agent 任务仍按 `AGENTS.md` 先跑 Mem0 prefetch；结果以实时命令为准 |
| 动态路由 fallback | 历史项 | 以当前 Vite 配置和浏览器验收为准 |
| mock-only 页面 | 历史项 | Event / Knowledge / Settings 已有 API-first 或写治理接入；具体 fallback 状态看当前 adapter/API |
| 未提交改动归属 | 历史项 | 当前 dirty worktree 以实时 `git status --short` 为准 |

## 6. P1 ViewModel 口径

> 本节由 P1-00 统一 Read Model 口径任务生成，用于 P1 各页面实现前的类型对齐。

### 6.1 复用基础类型

| 类型 | 文件 | 作用 |
|---|---|---|
| `PageEnvelope<T>` | `types/page-envelope.ts` | 通用页面数据信封（status, availability, source, data, source_refs, artifact_refs, sourceTrace） |
| `ModuleEnvelope<T>` | `types/page-envelope.ts` | 模块级信封，在 PageEnvelope 基础上增加 id/label |
| `SourceRef` | `types/common.ts` | 溯源引用（source_ref, endpoint, snapshot_id, run_id 等） |
| `DataStatus` | `types/common.ts` | `"available" \| "partial" \| "unavailable" \| "error"` |
| `DataAvailability` | `types/common.ts` | `"LIVE" \| "PARTIAL" \| "MOCK" \| "UNAVAILABLE"` |

### 6.2 P1 页面最小 ViewModel

P1 当前只冻结 Strategy / Event Flow / Knowledge / Settings 四类页面的只读 Read Model。Dashboard、Reports、Market Monitor、CME Options 已进入 P0 收口，不在本节扩展新类型。

**Strategy** — `StrategyViewModel`（`types/strategy.ts`）

| 字段 | 类型 | 说明 |
|---|---|---|
| `status` | `DataStatus` | 页面状态 |
| `source` | `"api" \| "mock" \| "unavailable"` | 数据来源 |
| `hero` | `StrategyHeroViewModel` | bias、direction、confidence、market_regime、trade_date、run_id、snapshot_id |
| `scenario` | `StrategyScenarioViewModel \| null` | 主方案、备选方案、关键位、触发/失效/确认/风险条件 |
| `module_signals` | `StrategyModuleSignal[]` | 后端聚合后的模块信号，只展示不推导 |
| `playbook_matches` | `StrategyPlaybookMatch[]` | 后端返回的 Playbook 匹配结果，只展示不匹配 |
| `artifact_refs` | `ArtifactRef[]` | 相关策略卡、报告或结构化产物 |
| `source_refs` | `SourceRef[]` | 溯源引用 |
| `has_data` | `boolean` | 是否有可展示数据 |

**Event Flow** — `EventFlowViewModel`（`types/event-flow.ts`）

| 字段 | 类型 | 说明 |
|---|---|---|
| `status` | `DataStatus` | 页面状态 |
| `source` | `"api" \| "mock" \| "unavailable"` | 数据来源 |
| `timeline` | `EventFlowTimelineItem[]` | 事件时间线 |
| `chain` | `EventFlowChainStep[]` | 后端返回的事件传导链 |
| `sentiment` | `EventFlowSentimentItem[]` | 情绪指标 |
| `radar` | `EventFlowRadarAxis[]` | 风险雷达 |
| `table` | `EventFlowTableRow[]` | 事件明细表 |
| `source_refs` | `SourceRef[]` | 溯源引用；当前 mock 适配器可为空或暂缺 |
| `has_data` | `boolean` | 是否有可展示数据 |

**Knowledge** — `KnowledgeViewModel`（`types/knowledge.ts`）

| 字段 | 类型 | 说明 |
|---|---|---|
| `status` | `DataStatus` | 页面状态；当前 mock 适配器可暂缺 |
| `source` | `"api" \| "mock" \| "unavailable"` | 数据来源；当前 mock 适配器可暂缺 |
| `items` | `KnowledgeItem[]` | 知识条目 |
| `selectedItem` | `KnowledgeItem \| null` | 当前选中知识条目 |
| `stats` | `{ total, agentReady, playbookCount, ... }` | 统计 |
| `source_refs` | `SourceRef[]` | 溯源引用；当前 mock 适配器可为空或暂缺 |
| `has_data` | `boolean` | 是否有可展示数据 |

**Settings** — `SettingsViewModel`（`types/settings.ts`）

| 字段 | 类型 | 说明 |
|---|---|---|
| `status` | `DataStatus` | 页面状态 |
| `source` | `"api" \| "mock" \| "unavailable"` | 数据来源 |
| `sources` | `SettingsSourceViewModel[]` | 数据源只读状态，不包含明文密钥 |
| `globalConfig` | `Array<{ label: string; value: string }>` | 全局配置摘要 |
| `systemInfo` | `Array<{ label: string; value: string }>` | 系统信息摘要 |
| `source_refs` | `SourceRef[]` | 溯源引用 |
| `has_data` | `boolean` | 是否有可展示数据 |

### 6.3 状态映射规则

| 后端 source | DataStatus | DataAvailability | 前端展示 |
|---|---|---|---|
| `api` + 有数据 | `available` | `LIVE` | 正常展示，状态条显示 Live |
| `api` + 部分缺失 | `partial` | `PARTIAL` | 展示已有数据，缺失区域标注 unavailable |
| `mock` | `available` | `MOCK` | 展示数据，状态条显示 Mock |
| `fallback` | `partial` | `PARTIAL` | 展示数据，标注降级 |
| `unavailable` | `unavailable` | `UNAVAILABLE` | 骨架屏 + 不可用提示 |
| `error` | `error` | `UNAVAILABLE` | 错误提示 + 重试按钮 |

### 6.4 共享字段规范

所有 P1 ViewModel 必须包含以下字段：

- `status: DataStatus` — 页面级数据状态。
- `source: "api" | "mock" | "unavailable"` — 数据来源类型。
- `source_refs: SourceRef[]` — 页面级溯源引用。
- `has_data: boolean` — 是否有可展示数据。
- `updated_at?: string | null` — 最后更新时间（可选）。

## 7. 历史建议下一步

以下建议是 2026-05-28 快照中的历史建议；当前任务入口以 Obsidian `06-任务看板.md` 和 repo `docs/dev/current-task.md` 为准。

1. 按关注点拆分当时前端改动：

- Data Ingestion 组件抽取。
- Dashboard / Market Monitor / CME Options 视觉细节调整。
- Reports / Event Flow / KnowledgeBase 页面细节调整。
- `docs/superpowers/` 单独判断是否属于本任务。

2. 浏览器验证时至少覆盖：

- `/dashboard`
- `/data-ingestion`
- `/market-monitor`
- `/cme-options`
- `/reports`
- `/reports/:reportId`
- `/agent-tasks`

3. 提交前应确认：

- mock fallback 不掩盖真实 API 错误。
- 所有缺失数据仍显式展示为 unavailable / partial / error。
- 前端没有新增第二套入口。
- 没有把业务策略推导放到前端。
