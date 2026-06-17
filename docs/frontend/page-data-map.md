# Frontend Page Data Map

- Project: finance-agent
- Date: 2026-05-28
- Frontend target: `apps/frontend-web/`
- Status: P0 visual migration complete; backend capability mapping baseline

This document maps each frontend page to backend APIs, adapters, ViewModels, states, and source trace requirements.

## P2 page map delta

P2 starts after the P1 read-model pages are stable. P2 page work must be vertical and contract-gated: no page may expose a write button until its API action envelope, failure states, and audit/run trace behavior are documented.

| P2 slice | Page impact | Data/API dependency | UI state requirement | Do not |
|---|---|---|---|---|
| P2-00 Contract Audit | all P2 pages | `P2ActionRequest` / `P2ActionResponse` contract in `api-contract.md` | mark unsupported actions as unavailable/manual_required | add speculative buttons |
| P2-01 Review Center 只读 | `/agent-tasks`, optional `/review-center` | `GET /api/reviews`, `GET /api/reviews/{review_id}` | filters, detail, evidence refs, run/step/artifact links | approve/reject/rerun |
| P2-02 Review actions | `/agent-tasks`, optional `/review-center` | Review action POST endpoints | pending/running/success/error/conflict/manual_required states | directly mutate ReviewItem locally |
| P2-03 Data Ingestion actions | `/data-ingestion` | ingestion retry/upload endpoints plus `/api/runs/{run_id}` | action status follows returned run/action id | mark source healthy before backend confirms |
| P2-04 Settings writes | `/settings` | settings status + write contract | masked sensitive fields, save error, unsupported write state | return or store plaintext secrets |
| P2-05 Playbook templates | `/knowledge-base`, `/strategy` | Playbook registry contract: `GET /api/playbooks`, `GET /api/playbooks/{playbook_id}`, `GET /api/playbooks/{playbook_id}/versions`, `POST /api/playbooks` | draft/published/deprecated/version/history/source refs | run matching in frontend |
| P2-06 Multi-asset calibration | `/strategy` | StrategyCard history/read-model filters | asset/horizon/regime filters and sample-size unavailable state | fabricate win rate or confidence |
| P2-07 Integration smoke | all P2-touched pages | API + Vite isolated ports | desktop/mobile no overflow; no console/pageerror/network failure | rely on stale local 8000/5173/8080 services |

## 0. P0-00 current migration baseline

P0-00 establishes the starting point for migrating the current frontend to the FinAnalytics Pro page system. The first implementation batch should focus on traceable backend connection for Reports, Report Detail, Agent Tasks, and Data Ingestion before migrating Dashboard, Market Monitor, and CME Options visuals.

### 0.1 First-batch page decision

| Target page | Current frontend state | Decision | Primary API | Fallback API | Mock fallback | Main API gaps |
|---|---|---|---|---|---|---|
| `/reports` | Implemented, but data flow mixes page-local `fetchJson`, report adapters, and family-specific state | Refactor data flow | `/api/reports/index`, `/api/reports/dates` | `/api/final-report/latest`, `/api/strategy-card/latest`, `/api/jin10/report-bundle/latest`, `/api/options/visual-report/latest`, `/api/macro/report` | Add explicit reports mock only when all real report APIs are unavailable | index lacks `report_id`, `title`, `family`, `snapshot_id`, `data_status` |
| `/reports/:reportId` | Implemented with route, page, hook, adapter, and trace/artifact tabs | Keep and tighten | `/api/reports/{report_id}` plus `/artifacts`, `/source`, `/analysis`, `/visual`, `/evidence` | `/api/source-trace/by-report/{report_id}` and family-specific legacy endpoints when family/date/run are known | Existing unavailable/mock detail shell; do not create fake trace | artifact content APIs do not return full trace fields; legacy endpoints still rely on temporary `run_id -> reportId` mapping |
| `/agent-tasks` | Implemented with page, hook, adapter, type, mock, and `/api/runs*` read path | Keep and tighten | `/api/runs`, `/api/runs/{run_id}`, `/api/runs/{run_id}/steps`, `/api/runs/{run_id}/artifacts`, `/api/runs/{run_id}/logs` | `/api/tasks`, `/api/tasks/{task_id}`, `/api/tasks/{task_id}/logs`, optional `/api/reviews` | Existing `mocks/agent-runs.json` | no `/api/source-trace/by-run/{run_id}`; no direct `agent_outputs` or `final_results` read model; logs endpoint is step-compatible not real log lines |
| `/data-ingestion` | Implemented with page, hook, adapter, type, mock, source trace, status-reason fields, and backend system summary strip | Keep and tighten | `/api/data-sources/status` | `/api/data-status/summary`, `/api/runs`, `/api/source-trace/{snapshot_id}` | Existing `mocks/data-ingestion.json` | per-source `artifact_refs`, full `source_refs`, `as_of`, collector breakdown, and history are still incomplete |

### 0.2 Traceability field support

| Field | Backend support today | First-batch frontend rule |
|---|---|---|
| `sourceTrace` | Strongest through `/api/source-trace/*`; partial in page-specific APIs | Preserve when present; fetch by report/snapshot when needed; never synthesize fake trace |
| `snapshot_id` | Present on report detail, run detail, source-trace, and data-status summary; missing from reports index | Keep optional in ViewModels; show `snapshot unavailable` when missing |
| `asOf` | Not standardized; often appears as `as_of` or generated timestamp | Normalize in adapter to `asOf` when source meaning is clear; otherwise leave unavailable |
| `dataDate` | Split across `trade_date`, `data_date`, `latest_date`, and source-trace snapshot fields | Normalize in adapter to `dataDate`; keep raw field in source refs when useful |
| `artifact_refs` | Present on report detail, run detail, step detail, source-trace; missing from report index and source status | Preserve arrays; show artifact tab as partial when missing |
| `final_result_id` | Stable on `/api/runs*` | Preserve in Agent Tasks ViewModel; do not dereference until a read model exists |
| `run_id` | Broadly present in reports and task APIs | Use as secondary navigation key; do not treat reports index `run_id` as a stable report id |

### 0.3 Current frontend data-flow gaps

- `/reports` currently performs direct page-level API calls for report index and family loading. Target flow is `page -> hook -> reports adapter -> apiClient -> ViewModel`.
- `/reports` still mixes legacy family state and newer detail route entry; list/detail contract is not yet fully unified.
- `/agent-tasks` is now implemented, but still lacks `/api/source-trace/by-run/{run_id}` and stable `final_result_id` dereference support.
- `/data-ingestion` now consumes `/api/data-status/summary` for page-level health, but per-source artifacts/history and collector-level breakdown are still missing from the backend contract.
- Reports types do not yet preserve a shared `snapshot_id`, `source_refs`, `artifact_refs`, `asOf`, `dataDate`, or standard `status`.
- Reports has no local mock fallback, unlike Dashboard, Data Ingestion, Market Monitor, and CME Options.
- Current status language mixes page UI states such as `ok/warn/error/info` with normalized `available/partial/unavailable/error`.

### 0.4 Pages intentionally deferred

Dashboard, Market Monitor, and CME Options already have usable adapters and mock fallback. They should not be the first migration surface. Use their existing code as reference, then migrate them after Reports, Agent Tasks, and Data Ingestion establish the shared `types/adapters/hooks/mocks/sourceTrace` contract.

## 1. Shared page contract

Every page should follow this flow:

```text
Page component
  -> page hook
  -> adapter(s)
  -> backend API(s)
  -> normalized ViewModel
  -> display components
```

Page components should not:

- call `fetch` directly;
- parse raw backend JSON deeply;
- calculate market conclusions;
- fabricate missing data;
- hardcode business metric order inside display components.

Every page must support:

- loading;
- empty/unavailable;
- partial data;
- error with retry;
- source trace or source summary when analysis/report data is shown.

## 2. Dashboard

### Route

- `/`
- `/dashboard` if route alias is present

### Page goal

Answer the first user question immediately: what is the current market state?

### User-facing sections

1. Market state overview
2. Key drivers
3. Strategy card / daily plan
4. CME options summary
5. Macro/liquidity summary
6. Risk alerts
7. Data status strip
8. Latest reports
9. Source trace

### API sources

| Section | API | Adapter responsibility |
|---|---|---|
| Market state overview | `/api/strategy-card/latest` + `/api/dashboard/summary` | Prefer backend strategy/scenario summary; `/api/dashboard/summary` only补运营上下文与指标，不前端硬推 bias |
| Strategy card | `/api/strategy-card/latest` | Normalize bias / confidence / invalid / risk_points / watchlist; missing trigger fields must stay empty |
| Final report preview | `/api/final-report/latest` | Use report meta and content excerpt only, no frontend summarization |
| CME summary | `/api/options/snapshot` | Project compact wall/gamma/key-level state through CME adapter |
| Macro summary | `/api/macro/latest` | Project selected macro metrics as data-driven metric list |
| Data health | `/api/data-status/summary` | Normalize system-wide status |
| Latest reports | `/api/reports/index` | Show available report families and latest dates |

### ViewModel

- `DashboardViewModel`
- `MarketStateViewModel`
- `StrategyCardViewModel`
- `DashboardModuleStatus[]`
- `SourceRef[]`

### Status rules

- `available`: market overview plus at least one real report/strategy/options/macro module is usable.
- `partial`: dashboard shell renders but one or more modules are unavailable.
- `unavailable`: no persisted report/summary artifacts are available.
- `error`: dashboard API or critical adapter normalization fails.

### Source trace requirements

Dashboard must preserve or display:

- report endpoint/source;
- strategy card date/run;
- CME snapshot source;
- macro source;
- data status endpoint.

### Prohibited frontend behavior

- Do not compute trading strategy from indicators.
- Do not infer a market bias from a single metric.
- Do not hardcode one report's prices or sections.
- Do not hide unavailable modules.

### Current API gaps

- `/api/dashboard/summary` 目前仍偏运营聚合，缺少标准 `market_state` / `strategy_card` read model，不能单独承担结论层。
- `/api/strategy-card/latest` 提供 `bias/confidence/scenario_summary/risk_points/watchlist`，但没有结构化 `trigger_conditions`；前端必须保留为空，不补造。
- `Dashboard` 里的 key levels 目前仍来自 dashboard/options 摘要，后续如需统一为 StrategyCard read model，应由后端补结构化字段。

## 3. Data Ingestion

### Route

- `/data-ingestion`

### Page goal

Show whether the data pipeline is currently usable and which sources/layers are degraded.

### User-facing sections

1. Data status bar
2. Data-source grid
3. raw / parsed / features / outputs layer overview
4. Recent ingestion failures
5. Recent tasks or pipeline steps
6. Source trace

### API sources

| Section | API | Adapter responsibility |
|---|---|---|
| Source cards | `/api/data-sources/status` | Normalize source status, role, freshness, error |
| Summary strip | `/api/data-status/summary` | Convert summary into compact status tokens |
| Recent tasks | `/api/tasks?limit=20` | Optional; show task runs related to ingestion |

### ViewModel

- `DataIngestionViewModel`
- `DataSourceStatusViewModel[]`
- `PipelineLayerStatus[]`
- `TaskRunSummary[]`

### Status rules

- `available`: one or more source statuses are returned.
- `partial`: some critical sources are unavailable or stale.
- `unavailable`: no source status data exists.
- `error`: source-status request fails.

### Source trace requirements

Each source card should retain:

- source key;
- source role;
- endpoint;
- last update/success/failure;
- failure reason if available.

### Prohibited frontend behavior

- Do not mark a source healthy because a mock exists.
- Do not treat missing optional source as full page failure.
- Do not mutate task/source state from frontend.

## 4. Market Monitor

### Route

- `/market-monitor`

### Page goal

Show current or near-current market and macro indicators with freshness and source context.

### User-facing sections

1. Price cards
2. Macro/rates panel
3. Liquidity panel
4. Real-rate/breakeven panel
5. Market regime or environment panel
6. Source trace panel

### API sources

| Section | API | Adapter responsibility |
|---|---|---|
| XAUUSD / tickers | `/api/market/tickers` | Normalize metric list and source/freshness |
| Macro indicators | `/api/macro/latest` | Normalize DXY, rates, liquidity, aliases |
| Event odds | `/api/market-odds/report` | Optional event probability/risk context |

### ViewModel

- `MarketMonitorViewModel`
- `MarketMetric[]`
- `MacroMetricGroup[]`
- `MarketOddsSummary | null`
- `SourceRef[]`

### Status rules

- `available`: primary market/ticker data returned.
- `partial`: some indicators are missing but page can render.
- `unavailable`: no live/near-live market data exists.
- `error`: all required API calls fail and no explicit unavailable payload exists.

### Source trace requirements

Each metric should retain:

- provider/source;
- endpoint;
- timestamp;
- freshness label;
- source ref if present.

### Prohibited frontend behavior

- Do not hardcode indicator order in components; order should come from adapter data.
- Do not decide bullish/bearish strategy in frontend.
- Do not mix macro source aliases in display components; normalize in adapter.

## 5. CME Options

### Route

- `/cme-options`

### Page goal

Show the option-structure readout: walls, gamma zero, key levels, and data quality.

### User-facing sections

1. Date selector
2. Snapshot meta strip
3. Options market readout
4. Gamma zero card
5. Key level map
6. Options wall table
7. Data quality panel
8. Full report link/view
9. Source trace panel

### API sources

| Section | API | Adapter responsibility |
|---|---|---|
| Date selector | `/api/options/dates` | Sort and select dates safely |
| Snapshot | `/api/options/snapshot?date=...` | Normalize snapshot paths and missing sections |
| Markdown report | `/api/options/report?date=...` | Optional full report reader |
| Visual report | `/api/options/visual-report/latest` or by date/run | Optional Reports Center visual family |

### ViewModel

- `CMEOptionsViewModel`
- `CMEOptionsSnapshotMeta`
- `OptionsWall[]`
- `KeyLevel[]`
- `DataQualityViewModel`
- `SourceRef[]`

### Status rules

- `available`: snapshot has enough data for core readout.
- `partial`: snapshot exists but some sections are missing.
- `unavailable`: no snapshot exists for date.
- `error`: request or normalization failure.

### Source trace requirements

- snapshot source;
- product;
- trade date;
- run id if available;
- artifact/report path if available;
- source refs from snapshot/report.

### Prohibited frontend behavior

- Do not compute GEX, gamma zero, wall score, p0, or strategy.
- Do not parse markdown report for structured levels.
- Do not assume old flat JSON paths inside components.

## 6. Reports Center

### Route

- `/reports`
- `/reports/:reportId`

### Page goal

Provide a compact Chinese report reading center for final reports, CME visual reports, and Jin10 bundles.

### Report families

1. `final_report_markdown`
2. `cme_options_visual`
3. `jin10_daily_visual`
4. optional future `jin10_raw_article`

### User-facing sections

1. Report family toolbar
2. Report date/run rail
3. Report meta strip
4. Main report reader
5. Jin10 subview tabs when applicable
6. Source endpoint / artifact info
7. Error/unavailable state
8. Report detail tabs: source / analysis / visual / evidence
9. Source trace panel

### API sources

| Section | API | Adapter responsibility |
|---|---|---|
| Report index | `/api/reports/index` | Normalize report family availability |
| Date coverage | `/api/reports/dates` | Normalize dates and module coverage |
| Standard report detail | `/api/reports/{report_id}` | Normalize one report into detail header, artifacts, trace, structured payload |
| Report artifacts | `/api/reports/{report_id}/artifacts` | Normalize report artifact list and primary artifact flags |
| Report source/analysis/visual/evidence | `/api/reports/{report_id}/source`, `/analysis`, `/visual`, `/evidence` | Load tab content without parsing storage paths in the page |
| Report source trace | `/api/source-trace/by-report/{report_id}` | Backfill trace fields when detail payload is partial |
| Final report | `/api/final-report/latest`, `/api/final-report?date=...&run_id=...` | Markdown report view |
| CME visual | `/api/options/visual-report/latest`, `/api/options/visual-report?date=...&run_id=...` | HTML/JSON visual report view |
| Jin10 bundle | `/api/jin10/report-bundle/latest`, `/api/jin10/report-bundle?date=...&run_id=...` | agent/daily/raw subview handling |

### ViewModel

- `ReportsIndexViewModel`
- `ReportFamilyViewModel`
- `ReportSelection`
- `MarkdownReportView`
- `VisualReportView`
- `Jin10ReportBundleView`

### Status rules

- `available`: selected report content exists.
- `partial`: report family exists but one subview is unavailable.
- `unavailable`: selected family/date/run has no content.
- `error`: index or report request fails.

### Source trace requirements

- source endpoint;
- report type/family;
- date/run;
- report id when available;
- snapshot id when available;
- artifact refs when available;
- artifact path if provided;
- default view and fallback reason for Jin10 bundle.

### Prohibited frontend behavior

- Do not generate report summaries in frontend.
- Do not hardcode one report's title, prices, or sections.
- Do not render stale/English placeholders when optimized Chinese reports are available.

## 7. Agent Tasks

### Route

- `/agent-tasks`

### Page goal

Show task execution status, step logs, and failure reasons for the finance-agent pipeline.

### User-facing sections

1. Task run list
2. Task detail panel
3. Step timeline
4. Logs viewer
5. Failure reason / retry notes
6. Artifact refs
7. Source trace drilldown when `snapshot_id` is present

### API sources

| Section | API | Adapter responsibility |
|---|---|---|
| Run list | `/api/runs` | Normalize run summaries, current stage, progress, final result, trace refs |
| Run detail | `/api/runs/{run_id}` | Normalize run detail, steps, source refs, artifact refs |
| Steps | `/api/runs/{run_id}/steps` | Normalize timeline and per-step status |
| Logs | `/api/runs/{run_id}/logs` | Normalize logs and empty logs state |
| Run artifacts | `/api/runs/{run_id}/artifacts` | Normalize run-level artifacts |
| Legacy task fallback | `/api/tasks`, `/api/tasks/{task_id}`, `/api/tasks/{task_id}/logs` | Keep as fallback only when `/api/runs*` is unavailable |
| Review queue | `/api/reviews` | Optional read-only panel for manual review tasks |

### ViewModel

- `TaskRunViewModel`
- `TaskStepViewModel`
- `TaskLogViewModel`

### Status rules

- empty task list is a valid empty state;
- missing task detail is unavailable/not found;
- missing logs is no-logs state, not full page error.

### Source trace requirements

- run id;
- task type;
- snapshot id;
- final result id;
- artifact refs;
- source refs;
- step id;
- timestamps;
- backend endpoint.

### Prohibited frontend behavior

- Do not trigger destructive operations from this read-only refactor.
- Do not bypass `task_runs` / `task_steps`.

## 8. Settings / Knowledge Base / Event Flow placeholders

These may exist as placeholders or future pages.

Rules:

- Keep them read-only or placeholder until a dedicated task defines contracts.
- Do not invent backend APIs.
- Display “待接入 / unavailable” rather than fake data.

## 9. Implementation order

1. P0-00 backend/page capability map.
2. Shared state/source/snapshot/artifact types.
3. Shared SourceTrace and status presentation.
4. Reports Center data-flow refactor.
5. Report Detail route.
6. Agent Tasks route.
7. Data Ingestion status tightening.
8. P0 first-batch smoke closeout.
9. P0-09 FinAnalytics Pro design system mapping, inserted before broad page visual migration.
10. P0-10 Reports visual alignment.
11. P0-11 Agent Tasks visual alignment.
12. P0-12 Data Ingestion visual alignment.
13. P0-13 Dashboard new design migration.
14. P0-14 Market Monitor new design migration.
15. P0-15 CME Options new design migration.

P0-09 is mandatory. Do not start Dashboard / Market Monitor / CME Options visual migration by copying `FinAnalytics_Preview.html`; first extract tokens, layout rules, and shared UI primitives into the active React frontend.

## 10. Change-control rule

When adding a new page section:

1. add/update API contract in `api-contract.md`;
2. add/update page mapping here;
3. update ViewModel spec;
4. then implement adapter/hook/component.
