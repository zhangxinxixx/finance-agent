# Frontend API Contract

- Project: finance-agent
- Date: 2026-06-01
- Frontend target: `apps/frontend-web/`
- Contract status: P2-10 page read-model closure complete; P2-11 prompt/feedback governance pending

This document records the read-only API contract used by the frontend refactor. It is not a backend OpenAPI spec. It is the frontend-facing agreement for pages, adapters, ViewModels, status handling, and source trace preservation.

## P2 action contract delta

P2 starts after P1 read-model closure. Frontend may render write controls only after the corresponding action contract is frozen. Until then, pages must stay read-only or show `manual_required` / `unavailable`.

### P2 action envelope

Every write-capable P2 endpoint should use the same frontend-facing shape:

```ts
type P2ActionRequest = {
  actor?: string;
  action: string;
  reason?: string;
  request_id?: string;
  expected_status?: string;
  run_id?: string;
  source_refs?: SourceRef[];
  artifact_refs?: ArtifactRef[];
};

type P2ActionResponse = {
  status: "accepted" | "success" | "partial" | "manual_required" | "queued_not_implemented" | "error";
  action: string;
  audit_id?: string;
  run_id?: string;
  next_run_id?: string;
  source_refs?: SourceRef[];
  artifact_refs?: ArtifactRef[];
  error?: {
    code: string;
    message: string;
  };
};
```

### P2 page-to-API map

| P2 slice | Page | Read APIs | Write/action APIs | Frontend rule |
|---|---|---|---|---|
| P2-01 Review Center 只读 | `/agent-tasks` or `/review-center` | `GET /api/reviews`, `GET /api/reviews/{review_id}` | none | Show filters, detail, evidence refs, run/step/artifact links; no action buttons |
| P2-02 Review actions | `/agent-tasks` or `/review-center` | same as P2-01 | `POST /api/reviews/{id}/approve`, `/reject`, `/rerun`, `/use-fallback` | Buttons require actor/reason/request_id and must render 404/409/manual_required explicitly |
| P2-03 Data Ingestion actions | `/data-ingestion` | `GET /api/data-sources/status`, `GET /api/runs/{run_id}` | `POST /api/ingestion/sources/{id}/retry`, `POST /api/ingestion/manual-upload` | UI follows returned run/action status; never mutates source card locally |
| P2-04 Settings writes | `/settings` | `GET /api/settings/status`, `GET /api/settings/history` | `POST /api/settings/preferences`, `POST /api/settings/preferences/reset`, `POST /api/settings/sources/{source_key}`, `POST /api/settings/sources/{source_key}/reset`, `POST /api/settings/secrets/{source_key}`, `POST /api/settings/secrets/{source_key}/reset`, `POST /api/settings/history/{audit_id}/rollback` | Sensitive fields remain masked; failed save must not update visible state as success |
| P2-05 Playbook templates | `/knowledge-base`, `/strategy` | `GET /api/playbooks`, `GET /api/playbooks/{playbook_id}`, `GET /api/playbooks/{playbook_id}/versions` | `POST /api/playbooks` | Frontend only registers and browses templates; Strategy matching stays backend-only |
| P2-06 Multi-asset calibration | `/strategy` | `GET /api/strategy-cards*` | none initially | Asset filters consume backend read model; insufficient samples show unavailable/partial |
| P2-07 Integration smoke | multiple | all above | all implemented above | Use isolated ports; do not rely on old local services |
| P2-08 Agent Output input layer | `/dashboard`, `/agent-tasks`, `/reports/:reportId`, optional `/agent-analysis` | `GET /api/agent-analysis/latest`, `GET /api/agent-analysis?date=...`, `GET /api/agent-analysis/inspect`, `GET /api/reports/{report_id}/analysis-inputs` | none initially | 已落地；页面只消费 Agent Output ViewModel，不做页面侧综合或正则翻译 |
| P2-09 Fact Review / Synthesis agents | `/agent-tasks`, `/reports/:reportId`, `/dashboard`, `/strategy`, `/review-center`, `/cme-options` | `GET /api/agent-analysis/latest`, `GET /api/agent-analysis/inspect`, `GET /api/agent-analysis/synthesis/latest`, `GET /api/reports/{report_id}/analysis-inputs`, `GET /api/reviews` | none initially | 已落地；unsupported/contradicted claims 必须继续出现在 warnings、ReviewItem 和回链入口里 |
| P2-10 Page read-model closure | `/review-center`, `/cme-options`, `/strategy` | `GET /api/reviews`, `GET /api/options/snapshot`, `GET /api/strategy-cards*` | none | 已落地；Review Center / CME Options / Strategy 只消费后端 read model，不做前端拼装 |

### P2 failure states

Adapters must preserve these backend states instead of collapsing them into generic errors:

| Backend condition | Preferred status | Frontend display |
|---|---|---|
| Missing actor/permission | `error` | Show permission/config error; do not retry automatically |
| Target review/source/template missing | `error` with 404 | Show not found and refresh hint |
| State changed since load | `error` with 409 | Show conflict and require refresh |
| Rerun/retry not wired to scheduler | `manual_required` or `queued_not_implemented` | Show action not fully available; do not claim rerun succeeded |
| Manual upload staged but not parsed | `partial` or `manual_required` | Show staged artifact and next required step |
| Sensitive config write unsupported | `manual_required` or `unavailable` | Show unsupported state; do not store in browser state |

## 0. P0-00 first-batch contract delta

The first implementation batch uses the new FinAnalytics Pro frontend direction to connect existing backend capabilities. It does not add write operations and does not move business calculations into the frontend.

### 0.1 First-batch page contracts

| Page | Primary APIs | Fallback APIs | Required preserved fields | Current contract gaps |
|---|---|---|---|---|
| `/reports` | `/api/reports/index`, `/api/reports/dates` | `/api/final-report/latest`, `/api/strategy-card/latest`, `/api/jin10/report-bundle/latest`, `/api/options/visual-report/latest`, `/api/macro/report` | `run_id`, `dataDate`, family/type, status, source endpoint | index lacks `report_id`, `title`, `family`, `snapshot_id`, `data_status`, `artifact_refs` |
| `/reports/:reportId` | `/api/reports/{report_id}`, `/api/reports/{report_id}/artifacts`, `/api/reports/{report_id}/source`, `/analysis`, `/visual`, `/evidence` | `/api/source-trace/by-report/{report_id}`, family/date/run legacy endpoints | `report_id`, `run_id`, `snapshot_id`, `data_status`, `source_refs`, `artifact_refs`, `dataDate`, `asOf` | artifact content APIs do not carry full trace; legacy reports do not share one stable detail key |
| `/agent-tasks` | `/api/runs`, `/api/runs/{run_id}`, `/api/runs/{run_id}/steps`, `/api/runs/{run_id}/logs`, `/api/runs/{run_id}/artifacts` | `/api/tasks`, `/api/tasks/{task_id}`, `/api/tasks/{task_id}/logs`, optional `/api/reviews` | `run_id`, `task_type`, `status`, `current_stage`, `progress`, `snapshot_id`, `final_result_id`, `source_refs`, `artifact_refs` | no `/api/source-trace/by-run/{run_id}`; no direct `agent_outputs` or `final_results` read model |
| `/data-ingestion` | `/api/data-sources/status` | `/api/data-status/summary`, `/api/runs`, `/api/source-trace/{snapshot_id}` | `source_key`, `status`, `latest_snapshot_id`, `last_run_id`, `dataDate`, `asOf`, `source_refs`, `overall_status`, `data_date` | per-source `artifact_refs`, `source_refs`, `as_of`, and status history are incomplete |

### 0.2 Field normalization rules

- `sourceTrace`: prefer backend trace payloads from `/api/source-trace/*`; if absent, show unavailable instead of generating fake refs.
- `snapshot_id`: optional but must be preserved. Missing snapshot should render as `snapshot unavailable`.
- `asOf`: normalize from backend `as_of`, `generated_at`, or source timestamp only when semantics are clear.
- `dataDate`: normalize from `trade_date`, `data_date`, or source-trace snapshot date. Preserve the raw field in `source_refs` when useful.
- `artifact_refs`: preserve arrays from report/run/detail APIs. Missing artifacts make the tab or section `partial`, not successful.
- `final_result_id`: preserve in Agent Tasks. Do not dereference from frontend until a backend read model exists.
- `run_id`: treat as execution identity, not as a stable report detail key unless paired with family/date or backend report id.

### 0.3 Backend read-model gaps to track

| Gap | Impact | Frontend behavior before backend fix |
|---|---|---|
| Reports index lacks stable `report_id` | `/reports` cannot link deterministically to `/reports/:reportId` | Use family/date/run selection; mark detail route unavailable when report id is missing |
| Report tab content APIs omit trace fields | Detail tabs need extra request for trace | Fetch `/api/source-trace/by-report/{report_id}` when available |
| Missing source trace by run | Agent Tasks drilldown takes two hops through `snapshot_id` | Use `run.snapshot_id -> /api/source-trace/{snapshot_id}` |
| Missing `agent_outputs` / `final_results` read API | Cannot expose final result details from Agent Tasks | P2-08 will add Agent Output read model; until then show `final_result_id` as metadata only |
| Missing per-agent fact review detail endpoint | 某些页面若要单独按 `agent_output_id` 拉取 fact review 仍需额外只读路由 | 当前通过 `latest / inspect / analysis-inputs / reviews` 组合消费；如后续需要单 Agent 深链接，再补独立 endpoint |
| Data source status lacks per-source artifacts and history | Data Ingestion cannot show full source provenance | Show current summary and record API gap |
| Data status summary lacks per-source trace details | Data Ingestion system summary cannot drill into missing sources directly | Show summary strip only; keep drilldown on source cards and SourceTrace |
| `asOf` / `dataDate` naming drift | Page timestamps are inconsistent | Normalize in adapter, keep raw fields in source trace |

## 1. Global rules

### 1.1 Frontend access pattern

Frontend pages must not fetch APIs directly.

Required flow:

```text
page -> hook -> adapter -> apiClient/fetchJson -> backend API -> adapter normalization -> ViewModel -> components
```

### 1.2 Status model

Frontend adapters normalize data into:

```ts
type DataStatus = "available" | "partial" | "unavailable" | "error";
```

Meaning:

- `available`: enough data exists for primary rendering.
- `partial`: page renders but one or more modules are missing or stale.
- `unavailable`: route exists but there is no usable artifact/data for the requested date/run/type.
- `error`: transport error, invalid payload, or normalization failure.

### 1.3 Source metadata

Adapters must preserve source context whenever present:

- `source_ref` / `source_refs`;
- `endpoint`;
- `artifact_path`;
- `snapshot_id`;
- `input_snapshot_ids`;
- `trade_date`;
- `run_id`;
- `generated_at` / `updated_at`.

Components may render it compactly, but adapters should not drop it.

### 1.4 Missing data behavior

- Structured APIs should prefer HTTP 200 with explicit `status: "unavailable"` when the route exists but no artifact/data exists.
- Raw passthrough snapshot APIs may return 404 for a specific missing file.
- Frontend should render an explicit unavailable state, not fake normal content.
- Mock fallback must be clearly adapter-controlled and should not be mistaken for real analysis.

## 2. API families

## 2.1 Health

### GET /health

Used by:

- startup smoke;
- backend health display when needed.

Expected:

```json
{"status":"ok"}
```

Frontend handling:

- if 200: backend reachable;
- if failed: show API unreachable status, not page-specific unavailable.

### GET /api/health

Same as `/health`, for `/api/*` consistency.

## 2.2 Dashboard summary

### GET /api/dashboard/summary

Used by:

- Dashboard;
- potentially AppHeader/system summary;
- data overview modules.

Backend purpose:

- aggregated dashboard information: pipeline status, warnings, risk alerts, latest reports, data-source status, recent tasks.
- current frontend usage splits this endpoint into two layers:
  - `/api/dashboard/summary` for operational context, latest reports/tasks, pipeline and source-status strip;
  - `/api/strategy-card/latest` for `bias/confidence/scenario_summary/risk_points/watchlist` conclusion fields.

Adapter:

- `adapters/dashboard.ts` or existing `adapters/api.ts` during transition.

Frontend ViewModel:

- `DashboardViewModel`.

Status handling:

- 200 with enough core sections -> `available`.
- 200 with missing optional sections -> `partial`.
- 200 with explicit unavailable state or no artifacts -> `unavailable` or module-level unavailable.
- request failure -> `error`.

Source trace:

- preserve report references, task IDs, source status references, generated timestamps.
- when `/api/strategy-card/latest` is available, preserve `run_id`, `input_snapshot_ids.analysis_snapshot`, `source_refs`, and any evidence refs from that payload.

Do not:

- infer market bias in the component;
- infer market bias from `intent_score` or a single options field when `/api/strategy-card/latest` is absent;
- create strategy conclusions from warnings alone;
- hide missing data-source status.

## 2.3 Data source status

### GET /api/data-sources/status

Used by:

- Data Ingestion page;
- AppHeader/DataStatusBar;
- Dashboard data-health modules.

Backend purpose:

- data-source status by provider/source, including roles, freshness, errors, and availability.

Adapter:

- `adapters/dataIngestion.ts`.

Frontend ViewModel:

- `DataIngestionViewModel`;
- source cards;
- pipeline/layer status groups.

Status handling:

- sources array non-empty -> `available` or `partial` based on individual source statuses.
- empty but route exists -> `unavailable`.
- failed request -> `error`.

Source trace:

- source key;
- source role;
- endpoint;
- last success/failure if available.

## 2.4 Data status summary

### GET /api/data-status/summary

Used by:

- AppHeader;
- shared DataStatusBar;
- Dashboard;
- Data Ingestion.

Backend purpose:

- compact cross-system data health summary.

Adapter:

- `hooks/useDataStatus.ts` + shared normalizer.

Frontend ViewModel:

- `DataStatusSummaryViewModel`.

Status handling:

- summary returned -> `available` or `partial`;
- no summary -> `unavailable`;
- request error -> `error`.

## 2.5 Market tickers

### GET /api/market/tickers

Used by:

- Market Monitor;
- Dashboard market cards.

Backend purpose:

- live or near-live market indicators such as XAUUSD and macro market tickers.

Adapter:

- `adapters/marketMonitor.ts`.

Frontend ViewModel:

- `MarketMonitorViewModel`;
- `MarketMetric[]`.

Status handling:

- each metric may be independently `available` / `unavailable`;
- a page can be `partial` when some metrics are missing;
- request failure -> `error`, with optional mock fallback only if explicitly configured.

Source trace:

- endpoint per metric;
- provider/source label;
- timestamp.

Do not:

- hardcode metric order inside components;
- calculate direction/strategy in frontend.

## 2.6 Macro latest

### GET /api/macro/latest

Used by:

- Market Monitor;
- Dashboard macro/liquidity panel;
- potentially Reports metadata.

Backend purpose:

- latest macro indicators and liquidity context.

Adapter:

- `adapters/marketMonitor.ts` for monitor use;
- `adapters/dashboard.ts` for dashboard projection.

Frontend ViewModel:

- `MacroMetric[]`;
- macro/liquidity groups.

Status handling:

- indicators present -> `available` or `partial`;
- route returns unavailable -> module `unavailable`;
- request failure -> `error`.

Pitfall:

- macro artifacts may be under run-id subdirectories. Frontend should not know storage layout; backend API/service owns that.

## 2.7 Macro report

### GET /api/macro/report?date=YYYY-MM-DD

Used by:

- Reports or Macro detail pages if exposed.

Backend purpose:

- markdown macro report.

Frontend handling:

- render via safe Markdown viewer;
- show unavailable if no content;
- preserve date/source endpoint.

## 2.8 CME options dates

### GET /api/options/dates

Used by:

- CME Options;
- Reports Center options family;
- Dashboard date selection if needed.

Expected shape:

```json
{"dates":["YYYY-MM-DD"]}
```

Adapter:

- `adapters/cmeOptions.ts`.

Status handling:

- non-empty dates -> `available`;
- empty dates -> `unavailable`;
- request failure -> `error`.

## 2.9 CME options snapshot

### GET /api/options/snapshot?date=YYYY-MM-DD

Used by:

- CME Options;
- Dashboard CME summary.

Backend purpose:

- full options analysis snapshot JSON.

Adapter:

- `adapters/cmeOptions.ts`;
- dashboard may consume a compact projection from the CME adapter.

Frontend ViewModel:

- `CMEOptionsViewModel`;
- key levels;
- options walls;
- gamma zero;
- data quality;
- source trace.

Status handling:

- valid snapshot -> `available`;
- snapshot with missing optional sections -> `partial`;
- missing snapshot -> `unavailable` or `error` depending HTTP response;
- invalid payload -> `error`.

Do not:

- calculate Black-76, GEX, wall score, gamma zero, or strategy bias in frontend.
- assume flat JSON paths without adapter guards.

Known path pitfalls:

- `snapshot.data_source.product`, not always `snapshot.product`;
- `snapshot.data_source.expiries`, not always `snapshot.expiries`;
- `snapshot.parameters.f_value`, not always `snapshot.forward_price`;
- `snapshot.gex.netgex_aggregate.gamma_zero.price`, not flat `snapshot.netgex.gamma_zero`.

## 2.10 CME options markdown report

### GET /api/options/report?date=YYYY-MM-DD

Used by:

- Reports Center CME options markdown mode;
- CME Options detail link.

Expected:

```json
{"content":"markdown...","format":"markdown"}
```

Frontend handling:

- render markdown;
- show report meta;
- if no content -> unavailable;
- do not parse report text to derive structured metrics.

## 2.11 CME visual report

### GET /api/options/visual-report/latest
### GET /api/options/visual-report?date=YYYY-MM-DD&run_id=RUN_ID

Used by:

- Reports Center `cme_options_visual` family.

Backend purpose:

- HTML/JSON visual report artifact for CME options.

Adapter:

- `adapters/reports.ts`.

Frontend ViewModel:

- `VisualReportView`.

Status handling:

- available visual artifact -> `available`;
- no visual artifact -> unavailable, with option to fallback to markdown only when explicitly configured;
- request error -> `error`.

## 2.12 Final report

### GET /api/final-report/latest
### GET /api/final-report?date=YYYY-MM-DD&run_id=RUN_ID

Used by:

- Reports Center `final_report_markdown` family;
- Dashboard conclusion/report preview.

Backend purpose:

- optimized Chinese final/agent analysis report when available.

Adapter:

- `adapters/reports.ts`;
- `adapters/dashboard.ts` for compact projection.

Frontend handling:

- render as Markdown;
- show asset/trade_date/run_id/source endpoint;
- prefer backend-selected latest/quality-scored report;
- do not hardcode a specific report's sections or prices.

## 2.13 Strategy card

### GET /api/strategy-card/latest
### GET /api/strategy-card?date=YYYY-MM-DD&run_id=RUN_ID

Used by:

- Dashboard strategy panel;
- Reports/strategy detail if exposed.

Backend purpose:

- structured strategy card JSON/MD generated by backend analysis chain.

Frontend ViewModel:

- `StrategyCardViewModel`.

Required display:

- bias label;
- confidence;
- scenario summary;
- trigger conditions;
- invalidation conditions;
- risk points;
- watchlist;
- non-trading disclaimer when `is_trade_instruction === false`.

Do not:

- generate or change trigger/invalid/risk text in frontend;
- infer a strategy from final report markdown if the card is unavailable.

## 2.14 Reports index

### GET /api/reports/index

Used by:

- Reports Center;
- Dashboard latest report modules;
- route availability checks.

Backend purpose:

- all report types index.

Expected concept:

```json
{
  "asset": "XAUUSD",
  "reports": [
    {
      "type": "final_report",
      "trade_date": "YYYY-MM-DD",
      "run_id": "...",
      "format": "markdown",
      "available": true
    }
  ]
}
```

Current P0-00 limitation:

- The current index shape is enough for list availability, but not enough for a stable detail route.
- Frontend should not invent a `report_id`.
- Until the backend index includes `report_id`, `/reports` may link to family/date/run flows or show detail unavailable.

Frontend ViewModel:

- `ReportsIndexViewModel`.

Status handling:

- reports non-empty -> `available`;
- empty reports -> `unavailable`;
- some families missing -> `partial`;
- request error -> `error`.

## 2.15 Reports dates

### GET /api/reports/dates

Used by:

- Reports Center;
- shared date selector;
- Dashboard/report navigation.

Backend purpose:

- unified date list and module coverage.

Frontend handling:

- sort dates descending unless backend already guarantees;
- preserve module coverage;
- show missing modules as unavailable, not hidden if relevant to current family.

## 2.15a Standard report detail

### GET /api/reports/{report_id}
### GET /api/reports/{report_id}/artifacts
### GET /api/reports/{report_id}/source
### GET /api/reports/{report_id}/analysis
### GET /api/reports/{report_id}/visual
### GET /api/reports/{report_id}/evidence

Used by:

- Report Detail page;
- Reports Center drilldown.

Backend purpose:

- expose one report with structured payload, trace refs, artifact refs, and tab-specific content.

Frontend ViewModel:

- `ReportDetailViewModel`;
- `ReportArtifactViewModel[]`;
- `ReportTabContentViewModel`.

Required preservation:

- `report_id`;
- `family`;
- `title`;
- `trade_date` or normalized `dataDate`;
- `run_id`;
- `snapshot_id`;
- `data_status`;
- `source_refs`;
- `artifact_refs`;
- `artifacts`;
- `structured_payload`.

Status handling:

- detail exists and primary artifact exists -> `available`;
- detail exists but one or more tab artifacts are missing -> `partial`;
- report id not found -> `unavailable`;
- malformed payload or transport error -> `error`.

Frontend must not:

- parse storage paths directly in the page;
- hide missing tabs as success;
- fabricate source trace when the backend does not provide it.

## 2.16 Jin10 daily report

### GET /api/jin10/daily-report/latest
### GET /api/jin10/daily-report?date=YYYY-MM-DD&run_id=RUN_ID

Used by:

- Reports Center legacy/daily visual path if retained.

Frontend handling:

- prefer report bundle for new UI;
- use this only for direct daily visual report views when needed.

## 2.17 Jin10 report bundle

### GET /api/jin10/report-bundle/latest
### GET /api/jin10/report-bundle?date=YYYY-MM-DD&run_id=RUN_ID

Used by:

- Reports Center `jin10_daily_visual` family.

Backend purpose:

- unified bundle for Jin10 `agent_analysis`, `daily_visual`, and `raw_article` views.

Adapter:

- `adapters/reports.ts`.

Frontend ViewModel:

- `Jin10ReportBundleView`.

Required behavior:

- default to `agent_analysis` when available;
- fallback to `daily_visual` only when agent analysis is unavailable;
- allow raw article view as a subview;
- do not rebuild or summarize article body in frontend;
- display unavailable for missing subviews.

## 2.18 Market odds

### GET /api/market-odds/snapshot?date=YYYY-MM-DD&run_id=RUN_ID
### GET /api/market-odds/report?date=YYYY-MM-DD&run_id=RUN_ID

Used by:

- Market Monitor;
- Dashboard risk/odds modules;
- possible future Market Odds page.

Frontend handling:

- treat as read-only feature/report layer;
- show event probabilities with source reliability if available;
- unavailable events should be explicit;
- do not combine probabilities into strategy in frontend.

## 2.19 Runs and Agent Tasks

### GET /api/runs
### GET /api/runs/{run_id}
### GET /api/runs/{run_id}/steps
### GET /api/runs/{run_id}/logs
### GET /api/runs/{run_id}/artifacts
### GET /api/tasks?limit=N
### GET /api/tasks/{task_id}
### GET /api/tasks/{task_id}/logs

Used by:

- Agent Tasks page;
- Data Ingestion recent task section;
- Dashboard recent tasks if present.

Backend purpose:

- canonical run list/detail through `/api/runs*`;
- task runs, task steps, logs, failure reasons;
- legacy task compatibility through `/api/tasks*`.

Frontend ViewModel:

- `TaskRunViewModel`;
- `TaskStepViewModel`;
- `TaskLogViewModel`.

Required preservation:

- `run_id`;
- `snapshot_id`;
- `task_type`;
- `trading_date`;
- `status`;
- `current_stage`;
- `progress`;
- `final_result_id`;
- `source_refs`;
- `artifact_refs`;
- `steps`;

Status handling:

- task list empty -> valid empty state;
- task detail missing -> unavailable/not found state;
- logs missing -> no logs available, not page failure.

Frontend must not:

- trigger retry/cancel/write operations in this read-only phase;
- bypass `task_runs` / `task_steps`;
- dereference `final_result_id` without a backend read model.

## 3. Page-to-API summary

| Page | Primary APIs |
|---|---|
| Dashboard | `/api/dashboard/summary`, `/api/strategy-card/latest`, `/api/final-report/latest`, `/api/options/snapshot`, `/api/macro/latest`, `/api/data-status/summary` |
| Data Ingestion | `/api/data-sources/status`, `/api/data-status/summary`, `/api/tasks?limit=20` |
| Market Monitor | `/api/market/tickers`, `/api/macro/latest`, `/api/market-odds/report` |
| CME Options | `/api/options/dates`, `/api/options/snapshot`, `/api/options/report`, `/api/options/visual-report/latest` |
| Reports | `/api/reports/index`, `/api/reports/dates`, `/api/final-report/latest`, `/api/options/visual-report/latest`, `/api/jin10/report-bundle/latest` |
| Report Detail | `/api/reports/{report_id}`, `/api/reports/{report_id}/artifacts`, `/api/reports/{report_id}/source`, `/api/reports/{report_id}/analysis`, `/api/reports/{report_id}/visual`, `/api/reports/{report_id}/evidence`, `/api/source-trace/by-report/{report_id}` |
| Agent Tasks | `/api/runs`, `/api/runs/{run_id}`, `/api/runs/{run_id}/steps`, `/api/runs/{run_id}/logs`, `/api/runs/{run_id}/artifacts`, fallback `/api/tasks*` |

## 4. Change-control rule

If a backend endpoint shape changes, update this contract before or in the same commit as frontend adapter changes.

If a frontend page starts consuming a new endpoint, update both this file and `docs/frontend/page-data-map.md`.
