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

export type TraceableStatus =
  | DataStatus
  | DataAvailability
  | "ok"
  | "warn"
  | "neutral"
  | "info"
  | "stale"
  | "fallback"
  | "manual_required";

export interface SourceRef {
  source_ref: string;
  endpoint?: string | null;
  artifact_path?: string | null;
  snapshot_id?: string | null;
  input_snapshot_ids?: string[] | null;
  trade_date?: string | null;
  dataDate?: string | null;
  asOf?: string | null;
  run_id?: string | null;
  generated_at?: string | null;
  provider?: string | null;
  label?: string | null;
  status?: TraceableStatus | null;
  source_url?: string | null;
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

export type ReportFormat = "markdown" | "html" | "json" | "text";

export interface ReportMeta {
  type: string;
  family?: string;
  title?: string;
  asset?: string;
  trade_date?: string;
  dataDate?: string;
  asOf?: string;
  run_id?: string;
  snapshot_id?: string;
  format: ReportFormat;
  status: DataStatus;
  generated_at?: string;
  source_endpoint?: string;
  artifact_path?: string;
  source_refs?: SourceRef[];
}

export interface AsyncViewState<T> {
  data: T | null;
  isLoading: boolean;
  isError: boolean;
  error?: Error;
  refetch: () => void;
}
