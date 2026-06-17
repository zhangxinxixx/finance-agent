# 当前项目现状审计

审计日期：2026-06-09
代码基线：`main` / `8fbf1da`
审计模式：只读代码盘点；本文件不代表功能验收通过。

## 结论摘要

- 项目定位仍符合 `AGENTS.md`：本地可运行、可追溯、可复盘的金融分析系统，不是自动交易系统。
- 当前生产主链以 `apps/api/main.py` 触发 `apps.scheduler.runner.dispatch_premarket_task()`，再进入 `apps.worker.runner.run_premarket()`。
- 主链固定为 `api -> scheduler -> worker -> collectors -> parsers -> features -> analysis -> renderer -> output`，但当前实现里部分步骤合并在 worker 和 pipeline 函数中执行。
- 当前唯一前端主线是 `apps/frontend-web/src`，入口为 `apps/frontend-web/src/main.tsx`；未发现 `apps/frontend/` 目录。
- FastAPI `/dashboard` 仍存在，但实现为跳转到 Vite 前端 `/dashboard`，不是新功能入口。
- 数据库模型分三类 Base：`database/models/task.py` 的任务表、`database/models/analysis.py` 的分析/设置/复核/Prompt 表、`database/models/report.py` 的报告表。
- 存储层实际使用 `storage/raw`、`storage/parsed`、`storage/features`、`storage/outputs`，并已有 Jin10、CME、macro 产物样例。

## 后端入口

| 模块 | 状态 | 证据 |
| --- | --- | --- |
| FastAPI 应用 | 已实现 | `apps/api/main.py` 创建 `FastAPI(title="finance-agent")` |
| 健康检查 | 已实现 | `GET /health`、`GET /api/health` in `apps/api/main.py` |
| premarket 触发 | 已实现 | `POST /tasks/premarket`、`POST /api/tasks/premarket` 调用 `dispatch_premarket_task()` |
| 调度器 | 部分实现 | `apps/scheduler/runner.py` 用后台线程执行 worker；`apps/api/main.py` lifespan 内用 APScheduler 刷新 Jin10 和定时 premarket |
| Worker 主链 | 已实现/部分 stub | `apps/worker/runner.py` 执行 CME、macro、analysis snapshot、C4 agent、final report、strategy card；非 CME/macro 的 step 仍按 stub success 处理 |
| 服务层 | 已实现 | `apps/api/services/` 包含 dashboard、report、source_trace、task、review、settings 等服务 |
| 旧兼容层 | 已实现 | `apps/api/data_service.py` 是对 `apps.api.services.*` 的向后兼容代理 |

## 主链步骤

当前 canonical premarket step 在 `apps/premarket.py`：

```text
macro_collect -> macro_feature -> cme_download -> cme_parse -> cme_ingest -> option_wall -> report_render -> strategy_card
```

实际执行位置：

- `macro_collect`、`macro_feature`、`report_render`：`apps/worker/pipelines/macro.py`
- `cme_download`、`cme_parse`、`cme_ingest`、`option_wall`：`apps/worker/pipelines/cme.py`
- `analysis_snapshot`：`apps/worker/runner.py` 中 `_persist_analysis_snapshot()`
- C4 agents / final report / strategy card：`apps/worker/runner.py` 中 `_run_c4_agent_pipeline()`

注意：`strategy_card` 在 step 列表中存在，但 worker 对非 CME/macro step 先按 stub success 标记；真实 strategy card 写入发生在 run 末尾 C4 pipeline。后续若要严格化状态机，应把 C4 pipeline 拆成可观测 TaskStep。

## API 路由盘点

所有路由主要定义在 `apps/api/main.py`。

| 路由族 | 状态 | 主要页面/用途 |
| --- | --- | --- |
| `/api/runs*`、`/api/tasks*` | 已实现 | Agent Tasks / Run 控制台 |
| `/api/source-trace*` | 已实现 | Report Detail / Strategy 溯源 |
| `/api/dashboard/summary` | 已实现 | Dashboard |
| `/api/data-sources/status`、`/api/data-status/summary` | 已实现 | Data Ingestion / 全局数据状态 |
| `/api/ingestion/*` | 部分实现 | 重试/手工上传登记，后续仍需回主链执行 |
| `/api/reviews*` | 已实现 | Review Center |
| `/api/market/*` | 已实现/部分 fallback | Market Monitor |
| `/api/options/*` | 已实现 | CME Options |
| `/api/reports*` | 已实现 | Reports / Report Detail |
| `/api/final-report*`、`/api/strategy-card*` | legacy/read model | Dashboard / Reports 兼容读取 |
| `/api/strategy-cards*` | 已实现 | Strategy Center |
| `/api/events/flow/overview` | 已实现 | Event Flow |
| `/api/knowledge/items*` | 已实现 | Knowledge Base |
| `/api/playbooks*` | 已实现 | Settings / Playbook 管理 |
| `/api/settings*` | 已实现 | Settings / Settings Audit |
| `/api/agents/registry*`、`/api/agents/prompts*`、`/api/agents/feedback*` | 已实现 | Settings 的 Agent 管理与 Prompt Governance |
| `/api/agent-analysis*` | 已实现 | Agent 分析、检查、手动触发 |
| `/dashboard` | 兼容跳转 | 跳转到 Vite `/dashboard` |

## 前端入口与页面

入口：`apps/frontend-web/src/main.tsx`
Shell：`apps/frontend-web/src/components/AppShell.tsx`、`AppSidebar.tsx`、`AppHeader.tsx`

当前路由：

- `/dashboard`
- `/dashboard/analysis`
- `/data-ingestion`
- `/data-sources/:sourceId`
- `/market-monitor`
- `/cme-options`
- `/reports`
- `/reports/:reportId`
- `/event-flow`
- `/event-flow/:eventId`
- `/knowledge-base`
- `/knowledge/:knowledgeId`
- `/agent-tasks`
- `/agent-tasks/:runId`
- `/review-center`
- `/strategy`
- `/settings`
- `/settings/audit`

页面状态摘要：

| 页面 | 状态 | API/数据源 |
| --- | --- | --- |
| Dashboard | 已实现 | `/api/dashboard/summary`、`/api/reports/dates`、`/api/strategy-card/latest` |
| Data Ingestion | 已实现/有 mock 回退 | `/api/data-sources/status`、`/api/data-status/summary`、`/api/ingestion/*`，mock 文件 `src/mocks/data-ingestion.json` |
| Market Monitor | 已实现/部分 fallback | `/api/market/monitor`、`/api/market/tickers`、`/api/macro/latest`、`/api/market/monitor/history` |
| CME Options | 已实现 | `/api/options/snapshot`、`/api/options/dates` |
| Reports | 已实现 | `/api/reports/index`、`/api/reports/dates`、Jin10/Final/Options report APIs |
| Report Detail | 已实现 | `/api/reports/{report_id}`、artifacts/source/analysis/visual/evidence/analysis-inputs、source-trace |
| Event Flow | 已实现 | `/api/events/flow/overview` |
| Knowledge Base | 已实现 | `/api/knowledge/items`、`/api/knowledge/items/{item_id}` |
| Agent Tasks | 已实现 | `/api/runs`、`/api/reviews`、`/api/agent-analysis/inspect` |
| Review Center | 已实现 | `/api/reviews*` |
| Strategy Center | 已实现 | `/api/strategy-cards*` |
| Settings | 已实现 | `/api/settings*`、`/api/agents/registry*`、`/api/agents/prompts*`、`/api/agents/feedback*` |

## 前端数据层

- 统一 API client：`apps/frontend-web/src/adapters/apiClient.ts`
- adapters：
  - `api.ts`：Dashboard 聚合
  - `dataIngestion.ts`：数据源状态和操作
  - `marketMonitor.ts`：市场监控
  - `cmeOptions.ts`：CME 期权
  - `reports.ts`：报告与三产物
  - `agentTasks.ts`：Run/Task/Review/Agent inspection
  - `strategy.ts`：策略卡
  - `settings.ts`：配置中心
  - `agentRegistry.ts`：Agent registry / prompt / feedback
  - `eventFlow.ts`、`knowledge.ts`、`playbooks.ts`、`agentAnalysis.ts`
- mock 文件存在于 `apps/frontend-web/src/mocks/`，包括 dashboard、data ingestion、market monitor、CME options、strategy、agent-runs。

## 数据库模型

| 文件 | 主要模型 | 状态 |
| --- | --- | --- |
| `database/models/task.py` | `TaskRun`、`TaskStep`、`TaskStatus`、`StepStatus` | 已实现 |
| `database/models/analysis.py` | `AnalysisSnapshot`、`AgentOutput`、`FinalAnalysisResult`、`DataSourceStatus`、`MarketCandle`、`AppSetting`、`AppSecret`、`AppSettingEvent`、`PromptVersion`、`ReviewItem`、`PromptFeedback` | 已实现 |
| `database/models/report.py` | `ReportItem`、`ReportArtifact` | 已实现 |
| `database/models/cme.py` | `CmeRawFile`、`CmeOptionRow`、`CmeParseRun` | 已实现 |
| `database/models/playbook.py` | `PlaybookTemplate` | 已实现 |
| `database/migrations/versions/` | 仅 `__init__.py` | Alembic 版本文件缺失或尚未落库为 migrations；当前靠 `ensure_*_tables()` additive create/alter |

## 存储与产物

实际存在的样例：

- `storage/raw/jin10/<date>/index.json`
- `storage/parsed/jin10/<date>/index.json`
- `storage/features/macro/<date>/macro_snapshot.json`
- `storage/outputs/macro/<date>/macro_snapshot.md`
- `storage/outputs/cme_options/<date>/options_analysis.json`
- `storage/outputs/cme_options/<date>/options_analysis.md`
- `storage/outputs/jin10/<date>/analysis.json`
- `storage/outputs/jin10/calendar_cache.json`
- `storage/outputs/jin10/quotes_cache.json`

Run-partitioned artifact helpers存在于 `apps/output/artifacts.py`，worker pipeline 使用 `<layer>/<domain>/<date>/<run_id>/...` 写入新产物。

## 报告系统

已实现要点：

- 标准报告表：`ReportItem` + `ReportArtifact`
- 标准报告 API：`/api/reports/{report_id}`、`/api/reports/{report_id}/artifacts`、`source`、`analysis`、`visual`、`evidence`、`analysis-inputs`
- legacy/兼容报告 API：`/api/final-report*`、`/api/options/visual-report*`、`/api/jin10/*report*`
- C4 final report 写入：`apps/output/final_report.py`
- Markdown 渲染：`apps/renderer/markdown/final_report.py`
- CME HTML 渲染：`apps/renderer/html/options_visual.py`

三产物状态：

- `source.md`：报告详情 API 预留/支持 source artifact，但不同报告族是否都有标准 `source.md` 需逐 report 验证。
- `analysis.md`：final report / options / Jin10 存在 Markdown/analysis 产物，标准 artifact 覆盖仍需按 report_id 验证。
- `visual.html`：CME visual/Jin10 bundle 支持 HTML 视图；标准 `visual` endpoint 已存在。
- `report_structured.json`：final report pipeline 构建 structured report；具体文件路径由 writer 决定，需按 run artifact 验证。

## Agent 架构

已实现 agent 文件位于 `apps/analysis/agents/`：

- domain agents：`macro_liquidity.py`、`cme_options.py`、`risk.py`、`technical.py`、`positioning.py`、`news.py`、`market_odds.py`、`market_regime.py`、`event_impact.py`
- coordinator/synthesis/review：`coordinator.py`、`fact_review.py`、`synthesis.py`
- registry/schema：`registry.py`、`schemas.py`

实际 C4 run 当前由 `apps/worker/runner.py` 调用 macro/options/risk/technical/positioning/news/market_odds/coordinator，写 final report 和 strategy card。`fact_review_agent`、`daily_market_synthesis_agent` 在代码中存在相关模块/接口，但是否已接入每次 premarket 主链需按运行产物进一步验证。

## 当前风险与 NEED_VERIFY

- NEED_VERIFY：`ReportItem` / `ReportArtifact` 新表是否覆盖所有报告族，仍需真实 DB 或 API 样本验证。
- NEED_VERIFY：`source.md`、`analysis.md`、`visual.html`、`report_structured.json` 四类标准产物是否每个 report_id 都完整。
- NEED_VERIFY：`fact_review_agent` 和 `synthesis_agent` 是否稳定进入每日主链，而非仅通过 API/单独脚本存在。
- NEED_VERIFY：Alembic migrations 目录无版本文件，生产/本地数据库结构主要依赖 `ensure_*_tables()`，后续需要迁移策略。
- NEED_VERIFY：前端 mock 回退使用范围需要逐 adapter 标注，避免 UI 把 mock 伪装为 live。
