import { ApiError, fetchJson } from "@/adapters/apiClient";
import type {
  ArtifactSourceTraceLookup,
  ArtifactSourceTraceResponse,
  ProcessingInputCoverage,
  KnownProcessingCoverageStatus,
  ProcessingMixedHealth,
  ProcessingOverviewResponse,
  ProcessingCoverageStatus,
  ProcessingExecutionSummary,
  ProcessingFallbackOutput,
  ProcessingFallbackReview,
  ProcessingQualityGate,
  ProcessingSourceFreshness,
  ProcessingSourceHealth,
  ProcessingTraceEntityType,
  ProcessingTraceHeader,
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

function normalizedRecords(value: unknown): Array<Record<string, unknown>> {
  return recordList(value).map((item) => ({ ...item }));
}

function normalizeArtifactSourceTraceArtifactRefs(value: unknown): ArtifactSourceTraceResponse["artifact_refs"] {
  return recordList(value).map((item) => ({
    artifact_id: stringValue(item.artifact_id),
    artifact_type: stringValue(item.artifact_type),
    file_path: stringValue(item.file_path),
    storage_backend: nullableString(item.storage_backend),
    version: nullableString(item.version),
    generated_at: nullableString(item.generated_at),
    sha256: nullableString(item.sha256),
  }));
}

function normalizeArtifactSourceTraceSnapshots(value: unknown): ArtifactSourceTraceResponse["input_snapshots"] {
  return recordList(value).map((item) => ({
    snapshot_id: stringValue(item.snapshot_id),
    snapshot_type: stringValue(item.snapshot_type),
    data_date: nullableString(item.data_date),
    run_id: nullableString(item.run_id),
    data_status: stringValue(item.data_status, "unknown"),
    created_at: nullableString(item.created_at),
    input_snapshot_ids: stringList(item.input_snapshot_ids),
  }));
}

function normalizeArtifactSourceTraceWarnings(value: unknown): ArtifactSourceTraceResponse["warnings"] {
  return recordList(value).map((item) => ({
    code: stringValue(item.code),
    message: stringValue(item.message),
    severity: stringValue(item.severity, "warning"),
    field: nullableString(item.field),
    hint: nullableString(item.hint),
  }));
}

export function normalizeArtifactSourceTrace(raw: unknown): ArtifactSourceTraceResponse {
  const item = asRecord(raw);
  const snapshot = asRecord(item.snapshot);
  return {
    run_id: nullableString(item.run_id),
    snapshot_id: nullableString(item.snapshot_id),
    data_status: stringValue(item.data_status, "unknown"),
    source_refs: recordList(item.source_refs).map((source) => ({
      source_id: stringValue(source.source_id),
      source_name: stringValue(source.source_name),
      source_type: stringValue(source.source_type),
      data_date: nullableString(source.data_date),
      endpoint: nullableString(source.endpoint),
      captured_at: nullableString(source.captured_at),
      file_path: nullableString(source.file_path),
      sha256: nullableString(source.sha256),
      url: nullableString(source.url),
      status: nullableString(source.status),
    })),
    artifact_refs: normalizeArtifactSourceTraceArtifactRefs(item.artifact_refs),
    snapshot: Object.keys(snapshot).length
      ? normalizeArtifactSourceTraceSnapshots([snapshot])[0] ?? null
      : null,
    input_snapshots: normalizeArtifactSourceTraceSnapshots(item.input_snapshots),
    related_artifacts: normalizeArtifactSourceTraceArtifactRefs(item.related_artifacts),
    warnings: normalizeArtifactSourceTraceWarnings(item.warnings),
  };
}

function normalizeSourceRefs(value: unknown): ProcessingTraceResponse["source_refs"] {
  return recordList(value)
    .map((item) => ({ ...item, source_ref: stringValue(item.source_ref) }))
    .filter((item) => item.source_ref.length > 0) as ProcessingTraceResponse["source_refs"];
}

function normalizeScope(value: unknown): "event" | "run" | "unknown" {
  const scope = stringValue(value);
  return scope === "event" || scope === "run" ? scope : "unknown";
}

function normalizeTraceEntityType(value: unknown): ProcessingTraceEntityType {
  const entityType = stringValue(value);
  return ["news", "report_input", "event", "analysis_signal"].includes(entityType)
    ? (entityType as ProcessingTraceEntityType)
    : "unknown";
}

function normalizeAcceptedOutputSource(value: unknown): ProcessingTraceResponse["accepted_output_source"] {
  const source = stringValue(value);
  return source === "primary" || source === "fallback" || source === "none" ? source : "unknown";
}

function normalizeAgentArtifactRefs(value: unknown) {
  return recordList(value).map((row) => ({
    agent_name: stringValue(row.agent_name),
    status: stringValue(row.status, "unknown"),
    file_path: stringValue(row.file_path),
  }));
}

function normalizeTracePath(value: unknown): ProcessingTracePathNode[] {
  return recordList(value).map((item) => ({
    node_id: stringValue(item.node_id),
    label: stringValue(item.label, stringValue(item.node_id)),
    stage: stringValue(item.stage, "unknown"),
    status: normalizeCoverageStatus(item.status, "missing"),
    source_ref_count: numberValue(item.source_ref_count),
    artifact_ref_count: numberValue(item.artifact_ref_count),
    warnings: stringList(item.warnings),
    missing_data: stringList(item.missing_data),
    agent_artifact_refs: normalizeAgentArtifactRefs(item.agent_artifact_refs),
    source_refs: normalizeSourceRefs(item.source_refs),
    artifact_refs: normalizedRecords(item.artifact_refs) as ProcessingTracePathNode["artifact_refs"],
    scope: normalizeScope(item.scope),
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
    source_freshness: { ...asRecord(item.source_freshness) },
    mainline_impact: { ...asRecord(item.mainline_impact) },
    can_build_gold_macro_overview: item.can_build_gold_macro_overview === true,
    can_emit_strong_conclusion: item.can_emit_strong_conclusion === true,
    blocked_mainlines: stringList(item.blocked_mainlines),
    degraded_mainlines: stringList(item.degraded_mainlines),
    blocking_reasons: stringList(item.blocking_reasons),
    warnings: stringList(item.warnings),
  };
}

function normalizeFallbackOutputs(value: unknown): ProcessingFallbackOutput[] {
  return recordList(value).map((row) => ({
    agent_name: stringValue(row.agent_name),
    snapshot_id: nullableString(row.snapshot_id),
    bias: nullableString(row.bias),
    confidence: nullableNumber(row.confidence),
    summary: nullableString(row.summary),
  }));
}

function normalizeFallbackReview(value: unknown): ProcessingFallbackReview {
  const item = asRecord(value);
  return {
    status: stringValue(item.status, "missing"),
    fallback_used: item.fallback_used === true,
    accepted_output: nullableString(item.accepted_output),
    manual_review_required: item.manual_review_required === true,
    primary_outputs: stringList(item.primary_outputs),
    fallback_outputs: normalizeFallbackOutputs(item.fallback_outputs),
    accepted_outputs: { ...asRecord(item.accepted_outputs) },
    fallback_tasks: normalizedRecords(item.fallback_tasks),
    task_results: recordList(item.task_results).map((row) => ({
      task_type: stringValue(row.task_type),
      reason: stringValue(row.reason),
      status: stringValue(row.status, "unknown"),
      fallback_output_agent: nullableString(row.fallback_output_agent),
      fallback_of: nullableString(row.fallback_of),
    })),
    reasons: stringList(item.reasons),
    review_items: normalizedRecords(item.review_items),
    fallback_quality_gate_decision: { ...asRecord(item.fallback_quality_gate_decision) },
    no_strong_conclusion: item.no_strong_conclusion === true,
    strategy_card_override: { ...asRecord(item.strategy_card_override) },
  };
}

function normalizeQualityGate(value: unknown): ProcessingQualityGate {
  const item = asRecord(value);
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
    agent_loop_decision: { ...asRecord(item.agent_loop_decision) },
    fallback_review: normalizeFallbackReview(item.fallback_review),
    blocking_reasons: stringList(item.blocking_reasons),
    warnings: stringList(item.warnings),
  };
}

function normalizeTraceHeader(value: unknown): ProcessingTraceHeader {
  const item = asRecord(value);
  return {
    trace_id: nullableString(item.trace_id),
    run_id: nullableString(item.run_id),
    entity_type: normalizeTraceEntityType(item.entity_type),
    entity_id: nullableString(item.entity_id),
    status: stringValue(item.status, "unknown"),
    review_status: stringValue(item.review_status, "missing"),
    publish_allowed: nullableBoolean(item.publish_allowed),
    as_of: nullableString(item.as_of),
  };
}

function normalizeFinalOutputMode(value: unknown): ProcessingExecutionSummary["final_output"]["mode"] {
  const mode = stringValue(value);
  return mode === "accepted" || mode === "observe" ? mode : "unavailable";
}

function normalizeExecutionSummary(value: unknown): ProcessingExecutionSummary {
  const item = asRecord(value);
  const usedData = asRecord(item.used_data);
  const finalOutput = asRecord(item.final_output);
  return {
    status: stringValue(item.status, "unavailable"),
    failed_steps: stringList(item.failed_steps),
    used_data: {
      input_snapshot_ids: asRecord(usedData.input_snapshot_ids),
      source_refs: recordList(usedData.source_refs) as unknown as ProcessingExecutionSummary["used_data"]["source_refs"],
      agent_artifact_refs: recordList(usedData.agent_artifact_refs).map((row) => ({
        agent_name: stringValue(row.agent_name),
        status: stringValue(row.status, "unknown"),
        file_path: stringValue(row.file_path),
      })),
    },
    final_output: {
      mode: normalizeFinalOutputMode(finalOutput.mode),
      publish_allowed: nullableBoolean(finalOutput.publish_allowed),
      review_status: stringValue(finalOutput.review_status, "unavailable"),
      report_artifact_refs: recordList(finalOutput.report_artifact_refs) as ProcessingExecutionSummary["final_output"]["report_artifact_refs"],
      strategy_card_artifact_refs: recordList(finalOutput.strategy_card_artifact_refs) as ProcessingExecutionSummary["final_output"]["strategy_card_artifact_refs"],
    },
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
    execution_summary: normalizeExecutionSummary(item.execution_summary),
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
  const primaryOutput = asRecord(item.primary_output);
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
    trace_header: normalizeTraceHeader(item.trace_header),
    trace_path: normalizeTracePath(item.trace_path),
    source_health: normalizeSourceHealth(item.source_health),
    quality_gate: normalizeQualityGate(item.quality_gate),
    read_time_source_health: normalizeSourceHealth(item.read_time_source_health),
    read_time_warnings: stringList(item.read_time_warnings),
    read_time_generated_at: nullableString(item.read_time_generated_at),
    source_refs: normalizeSourceRefs(item.source_refs),
    artifact_refs: recordList(item.artifact_refs) as ProcessingTraceResponse["artifact_refs"],
    view_bindings: recordList(item.view_bindings).map((row) => ({
      view: stringValue(row.view),
      status: normalizeViewBindingStatus(row.status),
    })),
    primary_output: Object.keys(primaryOutput).length
      ? {
          scope: normalizeScope(primaryOutput.scope),
          agent_name: nullableString(primaryOutput.agent_name),
          run_id: nullableString(primaryOutput.run_id),
          snapshot_id: nullableString(primaryOutput.snapshot_id),
          status: stringValue(primaryOutput.status, "unknown"),
          file_path: nullableString(primaryOutput.file_path),
          artifact_refs: normalizedRecords(primaryOutput.artifact_refs) as ProcessingTraceResponse["artifact_refs"],
        }
      : null,
    fallback_outputs: normalizeFallbackOutputs(item.fallback_outputs),
    accepted_output: { ...asRecord(item.accepted_output) },
    accepted_output_source: normalizeAcceptedOutputSource(item.accepted_output_source),
    fallback_review: normalizeFallbackReview(item.fallback_review),
    agent_envelopes: recordList(item.agent_envelopes).map((row) => ({
      scope: normalizeScope(row.scope),
      agent_name: stringValue(row.agent_name),
      run_id: nullableString(row.run_id),
      snapshot_id: nullableString(row.snapshot_id),
      status: stringValue(row.status, "unknown"),
      confidence: nullableNumber(row.confidence),
      created_at: nullableString(row.created_at),
      input_snapshot_ids: { ...asRecord(row.input_snapshot_ids) },
      source_refs: normalizeSourceRefs(row.source_refs),
      artifact_refs: normalizedRecords(row.artifact_refs) as ProcessingTraceResponse["artifact_refs"],
      evidence_refs: normalizedRecords(row.evidence_refs),
      evidence_items: normalizedRecords(row.evidence_items),
      data_quality: stringList(row.data_quality),
      file_path: nullableString(row.file_path),
    })),
    input_snapshot_ids: { ...asRecord(item.input_snapshot_ids) },
    evidence_refs: normalizedRecords(item.evidence_refs),
    evidence_items: normalizedRecords(item.evidence_items),
    affected_views: stringList(item.affected_views),
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

export async function fetchArtifactSourceTrace(artifactId: string): Promise<ArtifactSourceTraceLookup> {
  try {
    const raw = await fetchJson<unknown>(`/api/source-trace/by-artifact/${encodeURIComponent(artifactId)}`);
    return { status: "matched", trace: normalizeArtifactSourceTrace(raw) };
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      return { status: "not_found", trace: null };
    }
    throw error;
  }
}
