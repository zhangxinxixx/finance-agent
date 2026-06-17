# Frontend ViewModel Spec

- Project: finance-agent
- Date: 2026-05-26
- Frontend target: `apps/frontend-web/`
- Status: P0-01/P0-02 common traceability baseline

This document defines the frontend ViewModel direction for reconnecting `apps/frontend-web` to backend APIs. It is a planning contract, not necessarily the final TypeScript source file.

## P2 action ViewModel primitives

P2 introduces write-capable UI, but components still consume normalized ViewModels only. API action results must not be represented by optimistic local business state unless the backend response confirms the new state.

```ts
export type ActionStatus =
  | "idle"
  | "pending"
  | "accepted"
  | "success"
  | "partial"
  | "manual_required"
  | "queued_not_implemented"
  | "conflict"
  | "error";

export interface ActionErrorView {
  code: string;
  message: string;
  status?: number | string | null;
}

export interface ActionTraceView {
  audit_id?: string | null;
  run_id?: string | null;
  next_run_id?: string | null;
  source_refs: SourceRef[];
  artifact_refs: ArtifactRef[];
}

export interface ActionStateView {
  action: string;
  status: ActionStatus;
  label: string;
  disabled_reason?: string | null;
  trace?: ActionTraceView | null;
  error?: ActionErrorView | null;
  updated_at?: string | null;
}
```

P2 page-specific rules:

- Review action buttons must carry `expected_status`; 409/conflict requires refresh and must not update the item as resolved.
- Data Ingestion retry/upload actions must render returned `run_id` or `manual_required`; source cards cannot flip to healthy from local state alone.
- Settings write ViewModels must never include plaintext secrets; only `masked`, `configured`, and timestamps are allowed.
- Playbook template ViewModels must keep `version` and `status`; draft templates cannot affect Strategy matching.
- Strategy calibration ViewModels must expose `sample_size` and `unavailable_reason`; sample gaps cannot become precise win-rate claims.

## 1. ViewModel principles

### 1.1 Raw API is not UI state

Backend API payloads reflect storage, analysis, and report artifacts. UI components should not depend on deep raw paths.

Required flow:

```text
Raw API response -> adapter normalization -> ViewModel -> page/components
```

### 1.2 Components must be data-driven

Display components should render arrays or normalized objects passed by adapters.

Avoid component-local business hardcoding such as:

```ts
marketSummary.XAUUSD
macroLiquidity.RRP
source.FRED
snapshot.gex.netgex_aggregate.gamma_zero.price
```

Prefer:

```ts
metrics.map(metric => <MetricCard key={metric.id} metric={metric} />)
levels.map(level => <KeyLevelRow key={level.id} level={level} />)
```

### 1.3 ViewModels preserve traceability

Every ViewModel that shows analysis/report/strategy should carry source context:

- `source_refs`;
- `snapshot_id`;
- `input_snapshot_ids`;
- `trade_date`;
- `run_id`;
- `generated_at`;
- `source_endpoint`.

## 2. Common primitives

These should eventually live in `apps/frontend-web/src/types/common.ts` or equivalent.

```ts
export type DataStatus = "available" | "partial" | "unavailable" | "error";

export type DataAvailability = "LIVE" | "PARTIAL" | "MOCK" | "UNAVAILABLE";

export type BackendDataStatus =
  | "live"
  | "available"
  | "partial"
  | "stale"
  | "fallback"
  | "mock"
  | "unavailable"
  | "manual_required"
  | "error"
  | "failed"
  | "ok"
  | "warn"
  | "warning"
  | "ready"
  | "done"
  | "prelim"
  | "final"
  | string;

export type DataSourceKind = "api" | "mock" | "fallback" | "unavailable";

export type Bias = "bullish" | "bearish" | "mixed" | "neutral" | "unknown";

export type Severity = "info" | "success" | "warning" | "danger" | "muted";

export interface SourceRef {
  source_ref: string;
  endpoint?: string;
  artifact_path?: string;
  snapshot_id?: string;
  input_snapshot_ids?: string[];
  trade_date?: string;
  dataDate?: string;
  asOf?: string;
  run_id?: string;
  generated_at?: string;
  provider?: string;
  source_url?: string;
}

export interface PageState<T> {
  status: DataStatus;
  data: T | null;
  error?: string;
  updated_at?: string;
  source_refs: SourceRef[];
}

export interface ModuleStatus {
  id: string;
  label: string;
  status: DataStatus;
  message?: string;
  updated_at?: string;
  source_refs: SourceRef[];
}

export interface MetricValue {
  value: number | string | null;
  unit?: string;
  display: string;
  precision?: number;
}

export interface MetricItem {
  id: string;
  label: string;
  value: MetricValue;
  status: DataStatus;
  direction?: "up" | "down" | "flat" | "unknown";
  semantic?: "bullish" | "bearish" | "neutral" | "risk" | "liquidity" | "unavailable";
  timestamp?: string;
  source_refs: SourceRef[];
}
```

P0-01/P0-02 adds concrete source files for the shared traceability baseline:

- `apps/frontend-web/src/types/common.ts`
- `apps/frontend-web/src/types/source-trace.ts`
- `apps/frontend-web/src/types/snapshot.ts`
- `apps/frontend-web/src/types/artifact.ts`
- `apps/frontend-web/src/types/page-envelope.ts`

Rules:

- `DataStatus` stays lower-case and remains the normalized component status.
- `DataAvailability` is the user-visible data provenance state for `LIVE / PARTIAL / MOCK / UNAVAILABLE`.
- Backend statuses such as `stale`, `fallback`, `manual_required`, `prelim`, and `mock` must be normalized in adapters or `lib/status.ts`.
- `MOCK` must remain distinguishable from `PARTIAL`; mock data may render a partial page, but it is not live data.

## 2.1 Traceability primitives

These are the shared fields every analysis/report page must preserve even when a page renders an unavailable or mock fallback state.

```ts
export interface ArtifactRef {
  artifact_id?: string | null;
  artifact_type?: string | null;
  family?: string | null;
  title?: string | null;
  format?: string | null;
  content_type?: string | null;
  file_path?: string | null;
  path?: string | null;
  is_primary?: boolean | null;
  run_id?: string | null;
  snapshot_id?: string | null;
  dataDate?: string | null;
  asOf?: string | null;
  status?: DataStatus | null;
  availability?: DataAvailability | null;
  source_refs?: SourceRef[];
}

export interface SnapshotRef {
  snapshot_id: string | null;
  dataDate?: string | null;
  asOf?: string | null;
  run_id?: string | null;
  status?: DataStatus | null;
  availability?: DataAvailability | null;
  source_refs?: SourceRef[];
  artifact_refs?: ArtifactRef[];
  input_snapshot_ids?: string[];
}

export interface SourceTraceEnvelope {
  target_type: "snapshot" | "report" | "strategy" | "run" | "artifact" | "source" | "unknown";
  target_id?: string | null;
  status: DataStatus;
  availability?: DataAvailability | null;
  run_id?: string | null;
  snapshot_id?: string | null;
  dataDate?: string | null;
  asOf?: string | null;
  source_refs: SourceRef[];
  artifact_refs: ArtifactRef[];
  input_snapshots?: SnapshotRef[];
  related_artifacts?: ArtifactRef[];
  error_reason?: string | null;
}

export interface PageEnvelope<T> {
  status: DataStatus;
  availability: DataAvailability;
  source: DataSourceKind;
  data: T | null;
  dataDate?: string | null;
  asOf?: string | null;
  run_id?: string | null;
  snapshot_id?: string | null;
  source_refs: SourceRef[];
  artifact_refs: ArtifactRef[];
  snapshots?: SnapshotRef[];
  sourceTrace?: SourceTraceEnvelope | null;
  updated_at?: string | null;
  warnings?: string[];
  error?: {
    message: string;
    code?: string;
    status?: number | string | null;
  } | null;
}
```

Rules:

- Missing `snapshot_id` is valid, but the UI must show `snapshot unavailable` when the page depends on traceability.
- Missing artifacts make the affected module `partial`; pages must not silently hide missing source/analysis/visual/evidence tabs.
- Page code should consume `PageEnvelope<T>` or a page-specific ViewModel derived from it rather than raw backend payloads.

## 3. Reports primitives

```ts
export type ReportFormat = "markdown" | "html" | "json" | "text";

export interface ReportMeta {
  type: string;
  family?: string;
  title?: string;
  asset?: string;
  trade_date?: string;
  run_id?: string;
  format: ReportFormat;
  status: DataStatus;
  generated_at?: string;
  source_endpoint?: string;
  artifact_path?: string;
}

export interface MarkdownReportView {
  meta: ReportMeta;
  content: string;
  source_refs: SourceRef[];
}

export interface VisualReportView {
  meta: ReportMeta;
  html?: string;
  json?: unknown;
  default_view?: string;
  source_refs: SourceRef[];
}
```

## 4. Dashboard ViewModel

```ts
export interface DashboardViewModel {
  status: DataStatus;
  trade_date?: string;
  run_id?: string;
  generated_at?: string;

  market_state: MarketStateViewModel;
  key_drivers: DriverItem[];
  strategy_card: StrategyCardViewModel | null;
  cme_summary: CMEOptionsSummaryViewModel | null;
  macro_summary: MacroSummaryViewModel | null;
  risk_alerts: RiskItem[];
  data_status: DataStatusSummaryViewModel | null;
  latest_reports: ReportMeta[];

  modules: ModuleStatus[];
  source_refs: SourceRef[];
}

export interface MarketStateViewModel {
  label: string;
  bias: Bias;
  confidence: number | null;
  status: DataStatus;
  summary?: string;
  updated_at?: string;
  source_refs: SourceRef[];
}

export interface DriverItem {
  id: string;
  label: string;
  summary: string;
  status: DataStatus;
  severity?: Severity;
  source_refs: SourceRef[];
}

export interface RiskItem {
  id: string;
  label: string;
  detail: string;
  severity: Severity;
  status: DataStatus;
  source_refs: SourceRef[];
}
```

Rules:

- `market_state.bias` must come from backend output or explicit backend-neutral fallback, not frontend inference.
- `key_drivers` should be backend-provided or adapter-projected from backend summaries; do not create new analysis from indicators.
- If `strategy_card` is unavailable, show unavailable state instead of inventing strategy.

## 5. Strategy Card ViewModel

```ts
export interface StrategyCardViewModel {
  status: DataStatus;
  bias: Bias;
  confidence: number | null;
  scenario_summary?: string;
  trigger_conditions: string[];
  invalid_conditions: string[];
  risk_points: string[];
  watchlist: string[];
  is_trade_instruction: boolean;
  trade_date?: string;
  run_id?: string;
  source_refs: SourceRef[];
}
```

Rules:

- Display trigger / invalid / risk_points explicitly.
- If `is_trade_instruction === false`, show the non-trading/research disclaimer.
- Do not derive missing trigger/invalid conditions in frontend.

## 6. Data Ingestion ViewModel

```ts
export interface DataIngestionViewModel {
  status: DataStatus;
  updated_at?: string;
  summary: DataStatusSummaryViewModel | null;
  system_status: DataIngestionSystemStatusViewModel | null;
  sources: DataSourceStatusViewModel[];
  layers: PipelineLayerStatus[];
  source_refs: SourceRef[];
}

export interface DataStatusSummaryViewModel {
  status: DataStatus;
  label: string;
  source_count: number;
  generated_at: string;
  available_count?: number;
  partial_count?: number;
  unavailable_count?: number;
  error_count?: number;
  updated_at?: string;
  source_refs: SourceRef[];
  source_groups: Array<{ group: string; count: number }>;
}

export interface DataIngestionSystemStatusViewModel {
  overall_status: "LIVE" | "PARTIAL" | "MOCK" | "UNAVAILABLE";
  latest_run_id: string | null;
  latest_run_status: string | null;
  latest_run_created_at: string | null;
  latest_run_trade_date: string | null;
  snapshot_id: string | null;
  data_date: string | null;
  missing_sources: string[];
}

export interface DataSourceStatusViewModel {
  id: string;
  label: string;
  group: string;
  type: "api" | "pdf" | "scrape" | "scraper" | "structured" | "webhook";
  role: string;
  raw_status: "ok" | "warn" | "error" | "unavailable";
  endpoint?: string | null;
  configured: boolean;
  raw_ingested: boolean;
  parsed: boolean;
  analysis_ready: boolean;
  latest_raw_time?: string | null;
  latest_parsed_time?: string | null;
  row_count: number;
  status_reason?: string | null;
  snapshot_id?: string | null;
  last_run_id?: string | null;
  next_run_time?: string | null;
  fallback_for: string[];
  fallback_sources: string[];
  notes?: string;
  status: DataStatus;
  source_refs: SourceRef[];
}

export interface PipelineLayerStatus {
  id: "configured" | "raw_ingested" | "parsed" | "analysis_ready";
  label: string;
  status: DataStatus;
  completed_count: number;
  total_count: number;
  source_refs: SourceRef[];
}
```

Rules:

- One source failing should not necessarily make the page `error`.
- Unknown status must be displayed explicitly.
- `system_status` comes from `/api/data-status/summary` and is advisory page-level health, not a replacement for per-source trace.
- `endpoint` should preserve the real `access_method` when the backend provides it.

## 7. Market Monitor ViewModel

```ts
export interface MarketMonitorViewModel {
  status: DataStatus;
  updated_at?: string;
  price_metrics: MarketMetric[];
  macro_groups: MacroMetricGroup[];
  liquidity_metrics: MarketMetric[];
  odds_summary?: MarketOddsSummaryViewModel | null;
  source_refs: SourceRef[];
}

export interface MarketMetric extends MetricItem {
  symbol?: string;
  provider?: string;
  change?: MetricValue;
  change_pct?: MetricValue;
}

export interface MacroMetricGroup {
  id: string;
  label: string;
  status: DataStatus;
  metrics: MarketMetric[];
  source_refs: SourceRef[];
}

export interface MarketOddsSummaryViewModel {
  status: DataStatus;
  events: MarketOddsEvent[];
  source_refs: SourceRef[];
}

export interface MarketOddsEvent {
  id: string;
  label: string;
  probability?: MetricValue;
  reliability?: MetricValue;
  status: DataStatus;
  source_refs: SourceRef[];
}
```

Rules:

- Metric order should come from adapter data arrays.
- Components should not know backend aliases such as `T10YIE` -> `BREAKEVEN_10Y`; normalize in adapter.

## 8. CME Options ViewModel

```ts
export interface CMEOptionsViewModel {
  status: DataStatus;
  selected_date?: string;
  available_dates: string[];
  meta: CMEOptionsSnapshotMeta | null;
  readout: OptionsMarketReadoutViewModel | null;
  key_levels: KeyLevel[];
  walls: OptionsWall[];
  data_quality: DataQualityViewModel | null;
  report: ReportMeta | null;
  source_refs: SourceRef[];
}

export interface CMEOptionsSnapshotMeta {
  product?: string;
  trade_date?: string;
  run_id?: string;
  generated_at?: string;
  p0?: MetricValue;
  forward?: MetricValue;
  status: DataStatus;
  source_refs: SourceRef[];
}

export interface OptionsMarketReadoutViewModel {
  status: DataStatus;
  call_wall?: KeyLevel;
  put_wall?: KeyLevel;
  gamma_zero?: KeyLevel;
  max_pain?: KeyLevel;
  summary?: string;
  source_refs: SourceRef[];
}

export interface KeyLevel {
  id: string;
  label: string;
  price: MetricValue;
  kind: "call_wall" | "put_wall" | "gamma_zero" | "max_pain" | "support" | "resistance" | "other";
  status: DataStatus;
  note?: string;
  source_refs: SourceRef[];
}

export interface OptionsWall {
  id: string;
  strike: MetricValue;
  side: "call" | "put" | "both" | "unknown";
  metric?: MetricValue;
  status: DataStatus;
  source_refs: SourceRef[];
}

export interface DataQualityViewModel {
  status: DataStatus;
  label: string;
  categories: MetricItem[];
  warnings: string[];
  source_refs: SourceRef[];
}
```

Rules:

- Adapter handles backend path differences.
- Frontend does not calculate options analytics.
- Data quality categories may be object/dict-like in raw API; adapter converts to arrays.

## 9. Reports Center ViewModel

```ts
export interface ReportsIndexViewModel {
  status: DataStatus;
  asset?: string;
  families: ReportFamilyViewModel[];
  dates: ReportDateCoverage[];
  source_refs: SourceRef[];
}

export interface ReportFamilyViewModel {
  id: string;
  label: string;
  status: DataStatus;
  reports: ReportMeta[];
  default_report?: ReportMeta;
}

export interface ReportDateCoverage {
  trade_date: string;
  latest_run_id?: string;
  modules: string[];
  has_final_report?: boolean;
  has_strategy_card?: boolean;
  status: DataStatus;
}

export interface ReportSelection {
  family: string;
  trade_date?: string;
  run_id?: string;
  subview?: string;
}

export interface Jin10ReportBundleView {
  meta: ReportMeta;
  default_view: "agent_analysis" | "daily_visual" | "raw_article";
  views: Jin10ReportSubview[];
  source_refs: SourceRef[];
}

export interface Jin10ReportSubview {
  id: "agent_analysis" | "daily_visual" | "raw_article";
  label: string;
  status: DataStatus;
  format: ReportFormat;
  content?: string;
  html?: string;
  source_refs: SourceRef[];
}
```

Rules:

- Prefer backend-provided optimized Chinese final/agent reports.
- For Jin10 bundle, default view is adapter/backend-provided, not UI-hardcoded beyond fallback rules.
- Missing subview is partial/unavailable, not full page failure.

### Report Detail

```ts
export type ReportDetailTabKey = "analysis" | "source" | "visual" | "evidence";

export interface ReportDetailView {
  report_id: string;
  meta: ReportMeta & {
    family: string;
    title: string;
    lifecycle_status: string;
    input_snapshot_ids: string[];
    warning_count: number;
    artifact_count: number;
  };
  data_status: DataStatus;
  source_refs: SourceRef[];
  artifact_refs: ArtifactRef[];
  source_trace: SourceTracePayload | null;
  tabs: Partial<Record<ReportDetailTabKey, ReportArtifactContentView>>;
  available_tabs: ReportDetailTabKey[];
  structured_payload?: Record<string, unknown> | null;
}

export interface ReportArtifactContentView {
  key: ReportDetailTabKey;
  label: string;
  available: boolean;
  format: ReportFormat;
  content: string;
  path?: string | null;
  source_endpoint: string;
}
```

Rules:

- `/reports/:reportId` only consumes standardized detail/artifact/source-trace adapters.
- `run_id` may temporarily serve as route `reportId` for legacy report rows, but the mismatch remains a backend gap.
- HTML/Markdown/JSON rendering choices belong to the adapter/page shell, not to business calculation logic.

## 10. Task ViewModel

```ts
export interface TaskRunSummary {
  id: string;
  name?: string;
  status: DataStatus | "running" | "queued" | "completed" | "failed";
  started_at?: string;
  finished_at?: string;
  message?: string;
}

export interface TaskRunViewModel extends TaskRunSummary {
  steps: TaskStepViewModel[];
  source_refs: SourceRef[];
}

export interface TaskStepViewModel {
  id: string;
  label: string;
  status: string;
  started_at?: string;
  finished_at?: string;
  failure_reason?: string;
  logs_available?: boolean;
}

export interface TaskLogViewModel {
  task_id: string;
  step_id?: string;
  lines: string[];
  status: DataStatus;
}

export interface AgentTasksViewModel {
  status: DataStatus;
  source: "api" | "mock" | "unavailable";
  updated_at: string;
  runs: TaskRunSummary[];
  selected_run_id?: string | null;
  selected_run: TaskRunViewModel | null;
  detail_error?: string | null;
  reviews_total: number;
  source_refs: SourceRef[];
  has_data: boolean;
}
```

Rules:

- Empty task list is not an error.
- Missing logs should render “暂无日志”.
- Frontend should not bypass `task_runs` or `task_steps`.
- `final_result_id` should be preserved but not dereferenced without a backend read model.
- `/api/runs/{run_id}/logs` may be rendered as structured step-log summary until real log lines exist.

## 11. Adapter return convention

Adapters may return direct ViewModels or wrapped page states. For page hooks, prefer:

```ts
export interface AsyncViewState<T> {
  data: T | null;
  isLoading: boolean;
  isError: boolean;
  error?: Error;
  refetch: () => void;
}
```

For normalized adapter results, prefer including status in the ViewModel itself:

```ts
const viewModel: DashboardViewModel = {
  status: "partial",
  ...
};
```

## 12. Formatting rules

Formatting belongs in `lib/format.ts` or adapters, not repeated in components.

Examples:

- numeric precision;
- percent display;
- missing value display: `—` or `暂无数据`;
- timestamp formatting;
- Chinese label mapping;
- bias label mapping.

## 13. Copy rules

User-visible page copy should be simplified Chinese.

Keep technical identifiers in original form:

- `XAUUSD`, `DXY`, `US10Y`, `SOFR`, `CME`;
- `FINAL`, `PRELIM`, `Net GEX`, `WallScore`;
- `snapshot_id`, `source_ref`, `raw`, `parsed`, `features`, `outputs`.

Avoid technical placeholder copy such as:

- “report index entries”;
- “dates coverage + report entries”;
- long English hero text.

## 14. Change-control rule

When a new adapter adds fields for UI display:

1. add or update the ViewModel type here;
2. update page data map;
3. update API contract if new endpoint/field is required;
4. then implement components.
