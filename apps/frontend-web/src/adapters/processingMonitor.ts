import { fetchJson } from "@/adapters/apiClient";
import type {
  ProcessingInputCoverage,
  KnownProcessingCoverageStatus,
  ProcessingMixedHealth,
  ProcessingOverviewResponse,
  ProcessingCoverageStatus,
  ProcessingQualityGate,
  ProcessingSourceFreshness,
  ProcessingSourceHealth,
  ProcessingTraceMode,
  ProcessingTracePathNode,
  ProcessingTraceResponse,
} from "@/types/processing-monitor";

const OVERVIEW_PATH = "/api/processing/overview";

type RawRecord = Record<string, unknown>;

const PROCESSING_COVERAGE_STATUSES: ReadonlySet<KnownProcessingCoverageStatus> = new Set([
  "covered",
  "degraded",
  "missing",
  "stale",
  "pass",
  "needs_review",
  "blocked",
]);

function asRecord(value: unknown): RawRecord {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as RawRecord) : {};
}

function stringValue(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function normalizeCoverageStatus(value: unknown, fallback: ProcessingCoverageStatus = "unknown"): ProcessingCoverageStatus {
  const status = stringValue(value);
  return PROCESSING_COVERAGE_STATUSES.has(status as KnownProcessingCoverageStatus)
    ? (status as KnownProcessingCoverageStatus)
    : fallback;
}

function normalizeViewBindingStatus(value: unknown): "bound" | "missing" | "unknown" {
  const status = stringValue(value);
  return status === "bound" || status === "missing" ? status : "unknown";
}

function normalizeTraceStatus(value: unknown): ProcessingTraceResponse["status"] {
  const status = stringValue(value);
  return status === "matched" || status === "not_found" ? status : "unknown";
}

function nullableString(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function numberValue(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function nullableNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function nullableBoolean(value: unknown): boolean | null {
  return typeof value === "boolean" ? value : null;
}

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string" && item.length > 0) : [];
}

function fallbackActionList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => {
      if (typeof item === "string") return item;
      const record = asRecord(item);
      return stringValue(record.task_type);
    })
    .filter((item) => item.length > 0);
}

function recordList(value: unknown): RawRecord[] {
  return Array.isArray(value) ? value.filter((item): item is RawRecord => Boolean(item) && typeof item === "object" && !Array.isArray(item)) : [];
}

function normalizeTracePath(value: unknown): ProcessingTracePathNode[] {
  return recordList(value).map((item) => ({
    node_id: stringValue(item.node_id),
    label: stringValue(item.label, stringValue(item.node_id)),
    stage: stringValue(item.stage, "unknown"),
    status: normalizeCoverageStatus(item.status, "missing"),
    source_ref_count: numberValue(item.source_ref_count),
    artifact_ref_count: numberValue(item.artifact_ref_count),
  }));
}

function normalizeInputCoverage(value: unknown): ProcessingInputCoverage {
  const item = asRecord(value);
  return {
    news_input_count: numberValue(item.news_input_count),
    report_input_count: numberValue(item.report_input_count),
    followup_count: numberValue(item.followup_count),
    article_brief_count: numberValue(item.article_brief_count),
    source_ref_count: numberValue(item.source_ref_count),
    artifact_ref_count: numberValue(item.artifact_ref_count),
    without_source_ref_count: numberValue(item.without_source_ref_count),
  };
}

function normalizeMixedHealth(value: unknown): ProcessingMixedHealth {
  const item = asRecord(value);
  return {
    status: normalizeCoverageStatus(item.status),
    mixed_events_total: numberValue(item.mixed_events_total),
    mixed_without_bullish_drivers: numberValue(item.mixed_without_bullish_drivers),
    mixed_without_bearish_drivers: numberValue(item.mixed_without_bearish_drivers),
    mixed_without_dominant_driver: numberValue(item.mixed_without_dominant_driver),
    mixed_without_verification_needed: numberValue(item.mixed_without_verification_needed),
  };
}

function normalizeSourceFreshness(value: unknown): ProcessingSourceFreshness {
  const item = asRecord(value);
  return {
    source_freshness: stringValue(item.source_freshness, "unknown"),
    feature_freshness: stringValue(item.feature_freshness, "unknown"),
    analysis_freshness: stringValue(item.analysis_freshness, "unknown"),
    frontend_freshness: stringValue(item.frontend_freshness, "unknown"),
  };
}

function normalizeSourceHealth(value: unknown): ProcessingSourceHealth {
  const item = asRecord(value);
  return {
    overall_status: stringValue(item.overall_status, "unknown"),
    as_of: nullableString(item.as_of),
    p0_missing: stringList(item.p0_missing),
    p1_missing: stringList(item.p1_missing),
    p2_missing: stringList(item.p2_missing),
    stale_sources: stringList(item.stale_sources),
    fresh_sources: stringList(item.fresh_sources),
    can_build_gold_macro_overview: item.can_build_gold_macro_overview === true,
    blocking_reasons: stringList(item.blocking_reasons),
    warnings: stringList(item.warnings),
  };
}

function normalizeQualityGate(value: unknown): ProcessingQualityGate {
  const item = asRecord(value);
  const fallbackReview = asRecord(item.fallback_review);
  return {
    status: stringValue(item.status, "missing"),
    review_status: stringValue(item.review_status, "missing"),
    quality_gate_action: nullableString(item.quality_gate_action),
    publish_allowed: nullableBoolean(item.publish_allowed),
    manual_review_required: nullableBoolean(item.manual_review_required),
    fallback_recommended: nullableBoolean(item.fallback_recommended),
    retry_recommended: nullableBoolean(item.retry_recommended),
    fallback_actions: fallbackActionList(item.fallback_actions),
    fallback_reasons: stringList(item.fallback_reasons),
    fallback_review: {
      status: stringValue(fallbackReview.status, "missing"),
      fallback_used: fallbackReview.fallback_used === true,
      accepted_output: nullableString(fallbackReview.accepted_output),
      manual_review_required: fallbackReview.manual_review_required === true,
      primary_outputs: stringList(fallbackReview.primary_outputs),
      fallback_outputs: recordList(fallbackReview.fallback_outputs).map((row) => ({
        agent_name: stringValue(row.agent_name),
        snapshot_id: nullableString(row.snapshot_id),
        bias: nullableString(row.bias),
        confidence: nullableNumber(row.confidence),
        summary: nullableString(row.summary),
      })),
      accepted_outputs: asRecord(fallbackReview.accepted_outputs),
      task_results: recordList(fallbackReview.task_results).map((row) => ({
        task_type: stringValue(row.task_type),
        reason: stringValue(row.reason),
        status: stringValue(row.status, "unknown"),
        fallback_output_agent: nullableString(row.fallback_output_agent),
        fallback_of: nullableString(row.fallback_of),
      })),
      reasons: stringList(fallbackReview.reasons),
      review_items: recordList(fallbackReview.review_items),
    },
    blocking_reasons: stringList(item.blocking_reasons),
    warnings: stringList(item.warnings),
  };
}

export function normalizeProcessingOverview(raw: unknown): ProcessingOverviewResponse {
  const item = asRecord(raw);
  return {
    status: stringValue(item.status, "unavailable"),
    date: nullableString(item.date),
    run_id: nullableString(item.run_id),
    asset: stringValue(item.asset, "XAUUSD"),
    generated_from: nullableString(item.generated_from),
    trace_modes: stringList(item.trace_modes) as ProcessingTraceMode[],
    trace_path: normalizeTracePath(item.trace_path),
    input_coverage: normalizeInputCoverage(item.input_coverage),
    mainline_coverage: recordList(item.mainline_coverage).map((row) => ({
      mainline_id: stringValue(row.mainline_id),
      status: normalizeCoverageStatus(row.status, "missing"),
      event_count: numberValue(row.event_count),
      source_ref_count: numberValue(row.source_ref_count),
      missing_data: stringList(row.missing_data),
    })),
    transmission_chain_coverage: recordList(item.transmission_chain_coverage).map((row) => ({
      chain_id: stringValue(row.chain_id),
      status: normalizeCoverageStatus(row.status, "missing"),
      verification_needed: stringList(row.verification_needed),
    })),
    mixed_health: normalizeMixedHealth(item.mixed_health),
    source_freshness: normalizeSourceFreshness(item.source_freshness),
    source_health: normalizeSourceHealth(item.source_health),
    quality_gate: normalizeQualityGate(item.quality_gate),
    view_bindings: recordList(item.view_bindings).map((row) => ({
      view: stringValue(row.view),
      status: normalizeViewBindingStatus(row.status),
    })),
    source_refs: recordList(item.source_refs) as unknown as ProcessingOverviewResponse["source_refs"],
    artifact_refs: recordList(item.artifact_refs) as ProcessingOverviewResponse["artifact_refs"],
    warnings: stringList(item.warnings),
  };
}

export function normalizeProcessingTrace(raw: unknown): ProcessingTraceResponse {
  const item = asRecord(raw);
  const matchedEvent = asRecord(item.matched_event);
  return {
    status: normalizeTraceStatus(item.status),
    date: nullableString(item.date),
    run_id: nullableString(item.run_id),
    asset: stringValue(item.asset, "XAUUSD"),
    query: asRecord(item.query) as ProcessingTraceResponse["query"],
    matched_event: item.matched_event
      ? {
          event_id: nullableString(matchedEvent.event_id),
          input_id: nullableString(matchedEvent.input_id),
          primary_mainline: nullableString(matchedEvent.primary_mainline),
          processing_trace_id: nullableString(matchedEvent.processing_trace_id),
        }
      : null,
    mainlines: stringList(item.mainlines),
    transmission_chains: stringList(item.transmission_chains),
    trace_path: normalizeTracePath(item.trace_path),
    source_refs: recordList(item.source_refs) as unknown as ProcessingTraceResponse["source_refs"],
    artifact_refs: recordList(item.artifact_refs) as ProcessingTraceResponse["artifact_refs"],
    view_bindings: recordList(item.view_bindings).map((row) => ({
      view: stringValue(row.view),
      status: normalizeViewBindingStatus(row.status),
    })),
  };
}

export async function fetchProcessingOverview(): Promise<ProcessingOverviewResponse> {
  return normalizeProcessingOverview(await fetchJson<unknown>(OVERVIEW_PATH));
}

export async function fetchProcessingTrace(traceId: string): Promise<ProcessingTraceResponse> {
  return normalizeProcessingTrace(await fetchJson<unknown>(`/api/processing/trace/${encodeURIComponent(traceId)}`));
}

export async function fetchProcessingTraceByEvent(eventId: string): Promise<ProcessingTraceResponse> {
  return normalizeProcessingTrace(await fetchJson<unknown>(`/api/processing/trace-by-event/${encodeURIComponent(eventId)}`));
}

export async function fetchProcessingTraceBySourceRef(sourceRef: string): Promise<ProcessingTraceResponse> {
  return normalizeProcessingTrace(await fetchJson<unknown>(`/api/processing/trace-by-source-ref/${encodeURIComponent(sourceRef)}`));
}

export async function fetchProcessingTraceByInput(inputId: string): Promise<ProcessingTraceResponse> {
  return normalizeProcessingTrace(await fetchJson<unknown>(`/api/processing/trace-by-input/${encodeURIComponent(inputId)}`));
}

export async function fetchProcessingTraceByMainline(mainline: string): Promise<ProcessingTraceResponse> {
  return normalizeProcessingTrace(await fetchJson<unknown>(`/api/processing/trace-by-mainline/${encodeURIComponent(mainline)}`));
}

export async function fetchProcessingTraceByChain(chainId: string): Promise<ProcessingTraceResponse> {
  return normalizeProcessingTrace(await fetchJson<unknown>(`/api/processing/trace-by-chain/${encodeURIComponent(chainId)}`));
}
