# 前端改造规划

本规划只针对 `apps/frontend-web/src`，不恢复 `apps/frontend`，不把 `dashboard.html` 当新功能入口。

## 1. 统一 contracts/types

- 页面：全部页面
- 当前状态：adapters/types 已分散存在。
- 目标状态：每个 API contract 有明确 TypeScript 类型，字段状态与 `apps/api/schemas` 对齐。
- 涉及组件：`src/types/*`、`src/adapters/*`
- API 依赖：全部 read model API。
- 是否可先 mock：可以，但必须显式标注 mock。
- 验收标准：`npm run typecheck` 通过，mock/live 状态不混淆。

## 2. Reports 增加三产物入口

- 页面：Reports / Report Detail
- 当前状态：Report Detail 已有 source/analysis/visual/evidence/analysis-inputs。
- 目标状态：每个 report 明确显示 `source.md`、`analysis.md`、`visual.html`、`report_structured.json` 是否存在。
- 涉及组件：`ReportDetailPage.tsx`、`adapters/reports.ts`
- API 依赖：`/api/reports/{report_id}/artifacts`
- 是否可先 mock：不建议。
- 验收标准：缺失 artifact 显示 unavailable，不伪造。

## 3. Report Detail 深化

- 页面：`/reports/:report_id`
- 当前状态：已实现详情页。
- 目标 Tab：可视化报告、LLM分析、原文MD、图片证据、分析输入、数据溯源、版本记录、复盘记录。
- 涉及组件：`ReportDetailPage.tsx`
- API 依赖：`/api/reports/{report_id}/*`、`/api/source-trace/by-report/{report_id}`
- 是否可先 mock：版本/复盘可先空态。
- 验收标准：每个 Tab 有真实数据或明确空态。

## 4. Agent Tasks 改造成 Run 控制台

- 页面：Agent Tasks / Agent Task Detail
- 当前状态：已接 `/api/runs`、reviews、agent inspection。
- 目标状态：以 Run 为核心展示步骤、输入、输出、artifact、review、agent prompt/input/output。
- 涉及组件：`AgentTasksPage.tsx`、`AgentTaskDetailPage.tsx`、`components/agent-tasks/*`
- API 依赖：`/api/runs*`、`/api/reviews`、`/api/agent-analysis/inspect`
- 是否可先 mock：可用 `agent-runs.json`，但必须标注。
- 验收标准：单 run 的失败/blocked/retryable 可读。

## 5. Data Ingestion 接入真实 DataSourceStatus

- 页面：Data Ingestion
- 当前状态：已接数据源状态和全局摘要，有 mock fallback。
- 目标状态：统一 LIVE/STALE/PARTIAL/FALLBACK/OFFLINE/MOCK/MANUAL_REQUIRED。
- 涉及组件：`DataIngestionPage.tsx`、`components/data-ingestion/*`
- API 依赖：`/api/data-sources/status`、`/api/data-status/summary`
- 是否可先 mock：可以，但状态必须显式。
- 验收标准：页面能区分 configured/raw/parsed/analysis_ready。

## 6. Strategy Center / Strategy Cards

- 页面：Strategy Center
- 当前状态：已接 `/api/strategy-cards*`。
- 目标状态：策略卡列表、详情、source trace、适用场景、失效条件、非交易提示。
- 涉及组件：`StrategyPage.tsx`、`adapters/strategy.ts`
- API 依赖：`/api/strategy-cards*`、`/api/source-trace/by-strategy/{strategy_card_id}`
- 是否可先 mock：可 fallback。
- 验收标准：不出现自动下单语义。

## 7. 新增或完善 MarketKlineChart

- 页面：Market Monitor / Dashboard
- 当前状态：已有 `components/market-monitor/MultiLineChart.tsx` 和 `components/charts/PriceLineChart.tsx`。
- 目标状态：明确 MarketKlineChart，支持 asset/timeframe/source 状态。
- 涉及组件：新增或整合 chart components。
- API 依赖：当前 `/api/market/monitor/history`，后续可接 `/api/market/candles`。
- 是否可先 mock：可。
- 验收标准：图表数据源、时间范围、fallback 明确。

## 8. Market Monitor 拆 Tab

- 页面：Market Monitor
- 当前状态：综合页面已存在。
- 目标 Tab：Overview、Realtime Chart、Pricing Chain、Cross Asset、Calendar/Events。
- 涉及组件：`MarketMonitorPage.tsx`、`components/market-monitor/*`
- API 依赖：market、macro、Jin10 calendar/flash。
- 是否可先 mock：Calendar/Events 可先空态。
- 验收标准：每个 Tab 的 API 状态独立。

## 9. CME Options 拆 Tab

- 页面：CME Options
- 当前状态：期权结构页面已存在。
- 目标 Tab：Overview、GEX/Gamma、Wall Map、Skew/Flow、Scenario、Data/Model Trace。
- 涉及组件：`CMEOptionsPage.tsx`、`components/cme-options/*`
- API 依赖：`/api/options/snapshot`、`/api/options/dates`、source trace。
- 是否可先 mock：不建议核心指标 mock。
- 验收标准：GEX/Gamma 等核心计算来自后端。

## 10. Event Flow 增加 Event Detail / Drawer

- 页面：Event Flow
- 当前状态：已有 detail route。
- 目标状态：列表和详情之间支持 drawer/route，显示 source、影响资产、关联报告。
- 涉及组件：`EventFlowPage.tsx`、`EventFlowDetailPage.tsx`
- API 依赖：`/api/events/flow/overview`
- 是否可先 mock：可空态。
- 验收标准：详情可追溯到 source ref。

## 11. Knowledge Base 增加 Knowledge Detail

- 页面：Knowledge Base
- 当前状态：详情复用 `KnowledgeBasePage.tsx`。
- 目标状态：明确 Knowledge Detail view，支持 source、版本、关联 playbook/report。
- 涉及组件：`KnowledgeBasePage.tsx`
- API 依赖：`/api/knowledge/items/{item_id}`、`/api/playbooks*`
- 是否可先 mock：可空态。
- 验收标准：知识内容不与当前运行状态混淆。

## 12. Settings 拆成配置中心

- 页面：Settings / Settings Audit
- 当前状态：已有 settings、history、agent registry、prompt、feedback。
- 目标状态：数据源配置、密钥、Agent、Prompt、Playbook、审计历史分区清晰。
- 涉及组件：`SettingsPage.tsx`、`SettingsAuditPage.tsx`
- API 依赖：`/api/settings*`、`/api/agents/*`、`/api/playbooks*`
- 是否可先 mock：不建议写操作 mock。
- 验收标准：写操作有 audit_id/request_id，secret 不明文显示。
