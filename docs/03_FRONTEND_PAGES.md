# 前端页面职责

当前主前端：`apps/frontend-web/src`
入口：`apps/frontend-web/src/main.tsx`
Shell：`AppShell`、`AppSidebar`、`AppHeader`

## 路由列表

| 路由 | 页面文件 | 当前职责 |
| --- | --- | --- |
| `/dashboard` | `pages/DashboardPage.tsx` | 总览、报告/策略/市场状态入口 |
| `/dashboard/analysis` | `pages/DashboardAnalysisPage.tsx` | 分析视图 |
| `/data-ingestion` | `pages/DataIngestionPage.tsx` | 数据源状态、重试、手工上传入口 |
| `/data-sources/:sourceId` | `pages/DataIngestionPage.tsx` | 数据源详情视角 |
| `/market-monitor` | `pages/MarketMonitorPage.tsx` | 市场监控、行情、宏观/跨资产读数 |
| `/cme-options` | `pages/CMEOptionsPage.tsx` | CME 期权结构 |
| `/reports` | `pages/ReportsPage.tsx` | 报告列表与报告族入口 |
| `/reports/:reportId` | `pages/ReportDetailPage.tsx` | 报告详情、三产物、证据、溯源 |
| `/event-flow` | `pages/EventFlowPage.tsx` | 事件流 overview |
| `/event-flow/:eventId` | `pages/EventFlowDetailPage.tsx` | 事件详情 |
| `/knowledge-base` | `pages/KnowledgeBasePage.tsx` | 知识库列表 |
| `/knowledge/:knowledgeId` | `pages/KnowledgeBasePage.tsx` | 知识详情视角 |
| `/agent-tasks` | `pages/AgentTasksPage.tsx` | Run 控制台 / Agent task overview |
| `/agent-tasks/:runId` | `pages/AgentTaskDetailPage.tsx` | 单次 run 详情 |
| `/review-center` | `pages/ReviewCenterPage.tsx` | 人工复核队列 |
| `/strategy` | `pages/StrategyPage.tsx` | Strategy Center / Strategy Cards |
| `/settings` | `pages/SettingsPage.tsx` | 配置中心、Agent 管理、Prompt governance |
| `/settings/audit` | `pages/SettingsAuditPage.tsx` | 配置审计历史 |

## 数据访问

统一 API client：

- `apps/frontend-web/src/adapters/apiClient.ts`

主要 adapters：

- `adapters/api.ts`：Dashboard
- `adapters/dataIngestion.ts`：Data Ingestion
- `adapters/marketMonitor.ts`：Market Monitor
- `adapters/cmeOptions.ts`：CME Options
- `adapters/reports.ts`：Reports / Report Detail
- `adapters/agentTasks.ts`：Run / Reviews / Agent inspection
- `adapters/strategy.ts`：Strategy Cards
- `adapters/settings.ts`：Settings
- `adapters/agentRegistry.ts`：Agent Registry / Prompt / Feedback
- `adapters/eventFlow.ts`：Event Flow
- `adapters/knowledge.ts`：Knowledge Base
- `adapters/playbooks.ts`：Playbooks
- `adapters/agentAnalysis.ts`：Agent Analysis

## 页面与 API

| 页面 | 主要 API | mock/fallback |
| --- | --- | --- |
| Dashboard | `/api/dashboard/summary`、`/api/reports/dates`、`/api/strategy-card/latest` | `src/mocks/dashboard.json` |
| Data Ingestion | `/api/data-sources/status`、`/api/data-status/summary`、`/api/ingestion/sources/{source_key}/retry` | `src/mocks/data-ingestion.json` |
| Market Monitor | `/api/market/monitor`、`/api/market/tickers`、`/api/macro/latest`、`/api/market/monitor/history` | `src/mocks/market-monitor.json` |
| CME Options | `/api/options/snapshot`、`/api/options/dates` | `src/mocks/cme-options.json` |
| Reports | `/api/reports/index`、`/api/reports/dates`、Jin10/Final/Options report APIs | 主要依赖后端，个别 optional fetch |
| Report Detail | `/api/reports/{report_id}`、`/api/reports/{report_id}/artifacts`、`source`、`analysis`、`visual`、`evidence`、`analysis-inputs`、`/api/source-trace/by-report/{report_id}` | optional 404 空态 |
| Event Flow | `/api/events/flow/overview` | adapter 内 fallback 需进一步标注 |
| Knowledge Base | `/api/knowledge/items`、`/api/knowledge/items/{item_id}` | adapter 内 fallback 需进一步标注 |
| Agent Tasks | `/api/runs`、`/api/runs/{run_id}`、`/api/runs/{run_id}/artifacts`、`/api/runs/{run_id}/logs`、`/api/reviews`、`/api/agent-analysis/inspect` | `src/mocks/agent-runs.json` |
| Review Center | `/api/reviews`、review action APIs | 后端不可用时显示错误 |
| Strategy Center | `/api/strategy-cards/latest`、`/api/strategy-cards`、`/api/strategy-cards/assets` | `src/mocks/strategy.json` |
| Settings | `/api/settings/status`、settings write/reset/history APIs、Agent registry/prompt/feedback APIs | 需以后端状态为准 |

## 当前约束

- 不在前端计算策略。
- 不把 mock 当 live 展示。
- 不恢复 `apps/frontend` 或 `dashboard.html`。
- 新页面、新组件、新 API 对接默认只改 `apps/frontend-web/src`。
