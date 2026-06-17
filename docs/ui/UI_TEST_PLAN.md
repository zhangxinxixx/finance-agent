# UI Test Plan

## 1. 目的

为 `apps/frontend-web` 定义当前阶段可执行的前端验收基线，覆盖：

- 页面级 smoke
- `mock` / `fallback` / `stale` / `unavailable` / `manual_required` 状态可见性
- 详情路由与长内容滚动
- 前端 read model 消费是否稳定

当前仓库没有 `vitest` / `playwright` 配置，本计划先以 `typecheck`、`build`、聚焦 API 回归和真实浏览器 smoke 为主。

## 2. 当前基线

- 前端入口：`apps/frontend-web/src/main.tsx`
- 路由壳：`apps/frontend-web/src/components/AppShell.tsx`
- 页面目录：`apps/frontend-web/src/pages`
- hooks 目录：`apps/frontend-web/src/hooks`
- 当前前端脚本：
  - `npm --prefix apps/frontend-web run typecheck`
  - `npm --prefix apps/frontend-web run build`
- 当前无自动化前端单测框架：
  - 无 `vitest.config.*`
  - 无 `playwright.config.*`
  - 无 `*.test.*` / `*.spec.*`

## 3. 环境前提

执行页面 smoke 前，先确保：

1. API 可访问：`http://127.0.0.1:8000`
2. Vite 前端可访问：`http://127.0.0.1:8080`
3. 本地保留：

```bash
export no_proxy=127.0.0.1,localhost,::1
```

4. 若 Playwright MCP 仍不可用，则使用本机 Chromium headless 做截图验收。

## 4. 必跑命令

每次前端治理切片至少执行：

```bash
rtk npm --prefix apps/frontend-web run typecheck
rtk npm --prefix apps/frontend-web run build
```

若改动涉及 Dashboard / Market Monitor / Event Flow read model，则追加：

```bash
UV_CACHE_DIR=/tmp/uv-cache rtk uv run pytest \
  tests/api/test_dashboard_summary_service.py \
  tests/api/test_market_monitor_api.py \
  tests/api/test_event_flow_api.py -q
```

若改动涉及 Data Ingestion action / source status，则追加：

```bash
UV_CACHE_DIR=/tmp/uv-cache rtk uv run pytest tests/api/test_data_source_status_api.py -q
```

若改动涉及 Agent / Prompt / Feedback，则追加：

```bash
UV_CACHE_DIR=/tmp/uv-cache rtk uv run pytest \
  tests/api/test_agent_analysis_inspect_api.py \
  tests/api/test_prompt_governance_api.py -q
```

## 5. 页面 Smoke 矩阵

### 一级页面

| 路由 | 页面文件 | 主要 hook / adapter | 必查项 |
| --- | --- | --- | --- |
| `/dashboard` | `apps/frontend-web/src/pages/DashboardPage.tsx` | `useDashboard` | KPI、综合分析、事件播报、经济日历、source trace、fallback 状态 |
| `/dashboard/analysis` | `apps/frontend-web/src/pages/DashboardAnalysisPage.tsx` | `useDashboard` | 综合分析正文、风险项、空态 |
| `/data-ingestion` | `apps/frontend-web/src/pages/DataIngestionPage.tsx` | `useDataIngestion` | summary、pipeline、blocker、retry 入口、drawer |
| `/market-monitor` | `apps/frontend-web/src/pages/MarketMonitorPage.tsx` | `useMarketMonitor` | regime、price cards、图表、right panel、unavailable |
| `/cme-options` | `apps/frontend-web/src/pages/CMEOptionsPage.tsx` | `useCMEOptions` | summary、gamma/key level、source trace、PRELIM/FINAL |
| `/reports` | `apps/frontend-web/src/pages/ReportsPage.tsx` | `useReports` | list / card / timeline、筛选、空态、详情跳转 |
| `/event-flow` | `apps/frontend-web/src/pages/EventFlowPage.tsx` | `useEventFlow` | 时间线、table、事件状态 badge、overview fallback |
| `/knowledge-base` | `apps/frontend-web/src/pages/KnowledgeBasePage.tsx` | `useKnowledge` | 列表、详情切换、空态 |
| `/agent-tasks` | `apps/frontend-web/src/pages/AgentTasksPage.tsx` | `useAgentTasks` | run list、filters、状态分布、详情跳转 |
| `/review-center` | `apps/frontend-web/src/pages/ReviewCenterPage.tsx` | `useReviewCenter` | review 列表、严重度/状态、unavailable |
| `/strategy` | `apps/frontend-web/src/pages/StrategyPage.tsx` | `useStrategy` | hero、signals、scenario、history、source refs |
| `/settings` | `apps/frontend-web/src/pages/SettingsPage.tsx` | `useSettings`、`useAgentRegistry` | general、datasource、api-key、agents tabs 与写入口 |
| `/settings/audit` | `apps/frontend-web/src/pages/SettingsAuditPage.tsx` | `useSettings` | 历史、回滚入口、长列表滚动 |

### 详情页面

| 路由 | 页面文件 | 必查项 |
| --- | --- | --- |
| `/data-sources/:sourceId` | `apps/frontend-web/src/pages/DataIngestionPage.tsx` | source 详情自动打开、参数切换不报错 |
| `/reports/:reportId` | `apps/frontend-web/src/pages/ReportDetailPage.tsx` | artifacts、analysis inputs、source trace、长内容内部滚动 |
| `/event-flow/:eventId` | `apps/frontend-web/src/pages/EventFlowDetailPage.tsx` | event detail、返回导航、空态 |
| `/knowledge/:knowledgeId` | `apps/frontend-web/src/pages/KnowledgeBasePage.tsx` | detail 面板切换、空态 |
| `/agent-tasks/:runId` | `apps/frontend-web/src/pages/AgentTaskDetailPage.tsx` | summary / I-O / trace / review tabs、日志和 JSON 滚动 |

## 6. 状态语义验收

以下状态必须显式显示，不允许被吞掉：

- `mock`
- `fallback`
- `stale`
- `unavailable`
- `manual_required`
- `partial`
- `error`

重点检查组件：

- `apps/frontend-web/src/components/shared/FAStatusPill.tsx`
- `apps/frontend-web/src/components/shared/StatusBadge.tsx`
- `apps/frontend-web/src/components/shared/DataStatusBar.tsx`
- `apps/frontend-web/src/components/shared/FASourceTraceBadge.tsx`
- `apps/frontend-web/src/components/shared/statusMeta.ts`

重点检查页面：

- Dashboard
- Data Ingestion
- Market Monitor
- Event Flow
- Review Center
- Settings

## 7. 长内容与滚动验收

以下区域必须内部滚动，不允许直接撑高整页：

- Agent Tasks 日志 / Prompt / Input / Output / Review 列表
- Report Detail 的 Markdown / JSON / HTML artifact
- Reports rail 或长列表视图
- Settings Audit 历史
- Data Ingestion 的 detail drawer / matrix / runs log

重点文件：

- `apps/frontend-web/src/components/agent-tasks/AgentTaskIOPanels.tsx`
- `apps/frontend-web/src/components/agent-tasks/AgentTaskTraceReviewPanels.tsx`
- `apps/frontend-web/src/components/reports/ReportArtifactPanel.tsx`
- `apps/frontend-web/src/components/reports/ReportAnalysisInputsPanel.tsx`
- `apps/frontend-web/src/pages/SettingsAuditPage.tsx`
- `apps/frontend-web/src/pages/DataIngestionPage.tsx`

## 8. 浏览器 Smoke 方式

### 优先方式

若 Playwright MCP 恢复可用，按页面逐路由截图并检查：

- 页面可加载
- console 无新的未预期 error
- 关键 panel 有内容
- 详情页和 tab 可切换

### 当前 fallback 方式

当前允许继续使用 Chromium headless：

```bash
/usr/bin/chromium-browser --headless --disable-gpu --window-size=1440,1600 \
  --screenshot=.codex/screenshots/<name>.png \
  http://127.0.0.1:8080/<route>
```

建议至少覆盖：

- `/dashboard`
- `/data-ingestion`
- `/market-monitor`
- `/cme-options`
- `/reports`
- `/reports/<sample-report-id>`
- `/event-flow`
- `/agent-tasks`
- `/agent-tasks/<sample-run-id>`
- `/review-center`
- `/strategy`
- `/settings`

## 9. 回归触发规则

出现以下改动时，必须补页面 smoke：

- `apps/frontend-web/src/main.tsx`
- `apps/frontend-web/src/pages/*`
- `apps/frontend-web/src/components/shared/statusMeta.ts`
- `apps/frontend-web/src/components/shared/ContextPanel.tsx`
- `apps/frontend-web/src/components/shared/SourceTraceCard.tsx`
- `apps/frontend-web/src/adapters/*`
- `apps/api/services/dashboard_service.py`
- `apps/api/services/market_service.py`
- `apps/api/services/event_flow_service.py`
- `apps/api/services/source_service.py`

## 10. 下一步建议

当前文档落地后，前端治理下一批优先级：

1. 拆 `apps/frontend-web/src/pages/DataIngestionPage.tsx`
2. 拆 `apps/frontend-web/src/pages/MarketMonitorPage.tsx`
3. 压缩 `apps/frontend-web/src/components/dashboard/JudgmentBanner.tsx`
4. 给前端补最小 smoke harness；若短期不接测试框架，至少补一个统一的页面截图脚本
