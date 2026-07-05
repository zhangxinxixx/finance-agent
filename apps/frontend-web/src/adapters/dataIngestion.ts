import { fetchJson, ApiError } from "@/adapters/apiClient";
import type { DataStatus, SourceRef } from "@/types/common";
import type { DataStatusSummary } from "@/types/dashboard";
import type {
  DataIngestionMockFile,
  DataIngestionResponse,
  DataIngestionResponseSource,
  DataIngestionStatus,
  DataIngestionViewModel,
  DataSourceItem,
  DataSourceMetadata,
  DataSourceStatuses,
  DataIngestionSummary,
  DataSourceActionRequest,
  DataSourceActionResponse,
  DataSourceTestRequest,
  DataSourceTestResponse,
  DataSourceArtifactEvidence,
  DataSourceArtifactItem,
  DataSourceArtifactLayer,
  DataSourcePollingStrategy,
  DataSourcePressureProfile,
  DataSourceRawRef,
  NewsSourceRuntimeViewModel,
  PipelineLayerStatus,
  PipelineStageStatus,
  StageHealth,
  SourcePipelineHealth,
  SourceDomain,
  SourcePriority,
  DownstreamStatus,
  NewsFeatureSummaryViewModel,
} from "@/types/data-ingestion";

const DATA_INGESTION_MOCK_URL = new URL("../mocks/data-ingestion.json", import.meta.url);
const DATA_INGESTION_STATUS_PATH = "/api/data-sources/status";
const DATA_STATUS_SUMMARY_PATH = "/api/data-status/summary";
const DATA_INGESTION_RETRY_PATH = "/api/ingestion/sources";

type ApiDataSourceStatus = Omit<
  DataSourceItem,
  "endpoint" | "row_count" | "status" | "source_refs" | "snapshot_id" | "affected_modules" | "artifact_evidence" | "pipeline_health"
> & {
  access_method?: string | null;
  latest_snapshot_id?: string | null;
  latest_update_time?: string | null;
  freshness_status?: string | null;
  freshness_reason?: string | null;
  row_count?: number | null;
  status?: string | null;
  last_run_id?: string | null;
  next_run_time?: string | null;
  metadata?: Record<string, unknown> | null;
  affected_modules?: unknown;
  artifact_evidence?: unknown;
  pipeline_health?: unknown;
};

type ApiDataSourceStatuses = {
  sources: ApiDataSourceStatus[];
};

function normalizeMetadata(metadata: Record<string, unknown> | null | undefined, sourceName: string): DataSourceMetadata {
  const fallbackFor = metadata?.fallback_for;
  const fallbackSources = metadata?.fallback_sources;
  const databaseTables = metadata?.database_tables;
  const artifactLayers = metadata?.artifact_layers;

  return {
    ...(metadata ?? {}),
    provider_role: typeof metadata?.provider_role === "string" ? metadata.provider_role : "derived",
    fallback_for: Array.isArray(fallbackFor) ? fallbackFor.filter((item): item is string => typeof item === "string") : [],
    fallback_sources: Array.isArray(fallbackSources) ? fallbackSources.filter((item): item is string => typeof item === "string") : [],
    frontend_label: typeof metadata?.frontend_label === "string" ? metadata.frontend_label : sourceName,
    notes: typeof metadata?.notes === "string" ? metadata.notes : undefined,
    latest_raw_ref: normalizeRawRef(metadata?.latest_raw_ref),
    latest_raw_url: typeof metadata?.latest_raw_url === "string" ? metadata.latest_raw_url : null,
    database_tables: Array.isArray(databaseTables) ? databaseTables.filter((item): item is string => typeof item === "string") : [],
    artifact_layers: Array.isArray(artifactLayers) ? artifactLayers.filter((item): item is string => typeof item === "string") : [],
    polling_strategy: normalizePollingStrategy(metadata?.polling_strategy),
    pressure_profile: normalizePressureProfile(metadata?.pressure_profile),
  };
}

function normalizeRawRef(value: unknown): DataSourceRawRef | null {
  if (!value || typeof value !== "object") return null;
  const raw = value as Record<string, unknown>;
  return {
    label: typeof raw.label === "string" ? raw.label : null,
    url: typeof raw.url === "string" ? raw.url : null,
    raw_path: typeof raw.raw_path === "string" ? raw.raw_path : null,
    parsed_path: typeof raw.parsed_path === "string" ? raw.parsed_path : null,
    source_ref: typeof raw.source_ref === "string" ? raw.source_ref : null,
    published_at: typeof raw.published_at === "string" ? raw.published_at : null,
  };
}

function normalizePollingStrategy(value: unknown): DataSourcePollingStrategy | null {
  if (!value || typeof value !== "object") return null;
  const raw = value as Record<string, unknown>;
  return {
    mode: typeof raw.mode === "string" ? raw.mode : null,
    cadence: typeof raw.cadence === "string" ? raw.cadence : null,
    query: typeof raw.query === "string" ? raw.query : null,
    cache_ttl_seconds: typeof raw.cache_ttl_seconds === "number" ? raw.cache_ttl_seconds : null,
  };
}

function normalizePressureProfile(value: unknown): DataSourcePressureProfile | null {
  if (!value || typeof value !== "object") return null;
  const raw = value as Record<string, unknown>;
  return {
    level: typeof raw.level === "string" ? raw.level : null,
    upgrade_required: Boolean(raw.upgrade_required),
    recommendation: typeof raw.recommendation === "string" ? raw.recommendation : null,
  };
}

function normalizeStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string" && item.trim().length > 0) : [];
}

function normalizeArtifactLayer(value: unknown, fallback: DataSourceArtifactLayer): DataSourceArtifactLayer {
  return value === "raw" || value === "parsed" || value === "features" || value === "analysis" ? value : fallback;
}

function normalizeBackendArtifactItem(value: unknown, fallbackLayer: DataSourceArtifactLayer): DataSourceArtifactItem | null {
  if (!value || typeof value !== "object") return null;
  const raw = value as Record<string, unknown>;
  const path = typeof raw.path === "string" && raw.path.trim().length > 0 ? raw.path : null;
  if (!path) return null;
  return {
    key: typeof raw.key === "string" && raw.key.trim().length > 0 ? raw.key : path,
    label: typeof raw.label === "string" && raw.label.trim().length > 0 ? raw.label : path.split("/").pop() ?? path,
    layer: normalizeArtifactLayer(raw.layer, fallbackLayer),
    path,
  };
}

function normalizeBackendArtifactItems(value: unknown, fallbackLayer: DataSourceArtifactLayer): DataSourceArtifactItem[] {
  return Array.isArray(value)
    ? value
        .map((item) => normalizeBackendArtifactItem(item, fallbackLayer))
        .filter((item): item is DataSourceArtifactItem => item !== null)
    : [];
}

function normalizeBackendArtifactEvidence(value: unknown): DataSourceArtifactEvidence | null {
  if (!value || typeof value !== "object") return null;
  const raw = value as Record<string, unknown>;
  const evidence: DataSourceArtifactEvidence = {
    preferred_artifact_path: typeof raw.preferred_artifact_path === "string" ? raw.preferred_artifact_path : null,
    collector_raw_artifact_path: typeof raw.collector_raw_artifact_path === "string" ? raw.collector_raw_artifact_path : null,
    collector_parsed_artifact_path: typeof raw.collector_parsed_artifact_path === "string" ? raw.collector_parsed_artifact_path : null,
    latest_raw_url: typeof raw.latest_raw_url === "string" ? raw.latest_raw_url : null,
    raw_artifacts: normalizeBackendArtifactItems(raw.raw_artifacts, "raw"),
    parsed_artifacts: normalizeBackendArtifactItems(raw.parsed_artifacts, "parsed"),
    feature_artifacts: normalizeBackendArtifactItems(raw.feature_artifacts, "features"),
    analysis_artifacts: normalizeBackendArtifactItems(raw.analysis_artifacts, "analysis"),
  };

  const hasEvidence =
    Boolean(evidence.preferred_artifact_path) ||
    Boolean(evidence.collector_raw_artifact_path) ||
    Boolean(evidence.collector_parsed_artifact_path) ||
    Boolean(evidence.latest_raw_url) ||
    evidence.raw_artifacts.length > 0 ||
    evidence.parsed_artifacts.length > 0 ||
    evidence.feature_artifacts.length > 0 ||
    evidence.analysis_artifacts.length > 0;
  return hasEvidence ? evidence : null;
}

const PIPELINE_STAGE_STATUSES = new Set<PipelineStageStatus>([
  "OK",
  "WARN",
  "ERROR",
  "BLOCKED",
  "WAITING",
  "NO_DATA",
  "PARTIAL",
  "READY",
  "NO_SNAPSHOT",
  "SKIPPED",
]);

function normalizeStageStatus(value: unknown): PipelineStageStatus {
  const normalized = typeof value === "string" ? value.toUpperCase() : "";
  return PIPELINE_STAGE_STATUSES.has(normalized as PipelineStageStatus) ? (normalized as PipelineStageStatus) : "NO_DATA";
}

function normalizeBackendStage(value: unknown): StageHealth {
  if (!value || typeof value !== "object") return { status: "NO_DATA" };
  const raw = value as Record<string, unknown>;
  return {
    status: normalizeStageStatus(raw.status),
    message: typeof raw.message === "string" ? raw.message : undefined,
    updatedAt: typeof raw.updated_at === "string" ? raw.updated_at : typeof raw.updatedAt === "string" ? raw.updatedAt : undefined,
    durationMs: typeof raw.duration_ms === "number" ? raw.duration_ms : typeof raw.durationMs === "number" ? raw.durationMs : undefined,
    errorCode: typeof raw.error_code === "string" ? raw.error_code : typeof raw.errorCode === "string" ? raw.errorCode : undefined,
    inputRef: typeof raw.input_ref === "string" ? raw.input_ref : typeof raw.inputRef === "string" ? raw.inputRef : undefined,
    outputRef: typeof raw.output_ref === "string" ? raw.output_ref : typeof raw.outputRef === "string" ? raw.outputRef : undefined,
  };
}

function normalizeDownstreamStatus(value: unknown): DownstreamStatus {
  return value === "READY" || value === "DEGRADED" || value === "BLOCKED" ? value : "BLOCKED";
}

function normalizeBackendPipelineHealth(
  value: unknown,
  source: Pick<DataSourceItem, "source_key" | "source_name" | "source_group" | "source_type" | "metadata" | "last_run_id" | "snapshot_id" | "affected_modules">,
): SourcePipelineHealth | null {
  if (!value || typeof value !== "object") return null;
  const raw = value as Record<string, unknown>;
  const stages = raw.stages && typeof raw.stages === "object" ? (raw.stages as Record<string, unknown>) : {};
  const backendAffectedModules = normalizeStringArray(raw.affected_modules);
  const affectedModules = backendAffectedModules.length > 0 ? backendAffectedModules : source.affected_modules;

  return {
    sourceId: typeof raw.source_id === "string" ? raw.source_id : source.source_key,
    sourceName: typeof raw.source_name === "string" ? raw.source_name : source.metadata.frontend_label ?? source.source_name,
    sourceType: (typeof raw.source_type === "string" ? raw.source_type : source.source_type) as SourcePipelineHealth["sourceType"],
    domain: inferDomain(typeof raw.domain === "string" ? raw.domain : source.source_group),
    priority: inferPriority(typeof raw.priority === "string" ? raw.priority : source.metadata.provider_role),
    stages: {
      connection: normalizeBackendStage(stages.connection),
      collect: normalizeBackendStage(stages.collect),
      rawLanding: normalizeBackendStage(stages.raw_landing ?? stages.rawLanding),
      parse: normalizeBackendStage(stages.parse),
      validate: normalizeBackendStage(stages.validate),
      snapshot: normalizeBackendStage(stages.snapshot),
      consumerReady: normalizeBackendStage(stages.consumer_ready ?? stages.consumerReady),
    },
    latestRunId: typeof raw.latest_run_id === "string" ? raw.latest_run_id : source.last_run_id ?? undefined,
    snapshotId: typeof raw.snapshot_id === "string" ? raw.snapshot_id : source.snapshot_id ?? undefined,
    rawArtifactRef: typeof raw.raw_artifact_ref === "string" ? raw.raw_artifact_ref : undefined,
    factTable: typeof raw.fact_table === "string" ? raw.fact_table : undefined,
    affectedModules,
    downstreamStatus: normalizeDownstreamStatus(raw.downstream_status),
    latestDataDate: typeof raw.latest_data_date === "string" ? raw.latest_data_date : undefined,
    stalenessDays: typeof raw.staleness_days === "number" ? raw.staleness_days : null,
  };
}

function toUiStatus(status: string | null | undefined): DataIngestionStatus {
  switch (status) {
    case "ok":
      return "ok";
    case "partial":
    case "stale":
    case "warn":
      return "warn";
    case "failed":
    case "error":
      return "error";
    case "not_connected":
    case "unavailable":
    default:
      return "unavailable";
  }
}

function normalizeApiStatuses(payload: ApiDataSourceStatuses): DataSourceStatuses {
  return {
    generated_at: new Date().toISOString(),
    last_refresh_at: null,
    sources: payload.sources.map((source) => {
      const metadata = normalizeMetadata(source.metadata, source.source_name);
      const affectedModules = normalizeStringArray(source.affected_modules);
      const normalizedSource: DataSourceItem = {
        source_key: source.source_key,
        source_name: source.source_name,
        source_group: source.source_group,
        source_type: source.source_type,
        endpoint: source.access_method ?? null,
        configured: Boolean(source.configured),
        raw_ingested: Boolean(source.raw_ingested),
        parsed: Boolean(source.parsed),
        analysis_ready: Boolean(source.analysis_ready),
        latest_raw_time: source.latest_raw_time ?? null,
        latest_parsed_time: source.latest_parsed_time ?? null,
        latest_update_time: source.latest_update_time ?? source.latest_parsed_time ?? source.latest_raw_time ?? null,
        freshness_status: source.freshness_status ?? null,
        freshness_reason: source.freshness_reason ?? null,
        row_count: source.row_count ?? 0,
        status: toUiStatus(source.status),
        error_message: source.error_message ?? null,
        source_refs: [`GET ${DATA_INGESTION_STATUS_PATH}#${source.source_key}`],
        snapshot_id: source.latest_snapshot_id ?? null,
        last_run_id: source.last_run_id ?? null,
        next_run_time: source.next_run_time ?? null,
        metadata,
        affected_modules: affectedModules,
        artifact_evidence: normalizeBackendArtifactEvidence(source.artifact_evidence),
      };
      return {
        ...normalizedSource,
        pipeline_health: normalizeBackendPipelineHealth(source.pipeline_health, normalizedSource),
      };
    }),
  };
}

function normalizeSourceItem(source: DataSourceItem): DataSourceItem {
  return {
    ...source,
    latest_update_time: source.latest_update_time ?? source.latest_parsed_time ?? source.latest_raw_time ?? null,
    freshness_status: source.freshness_status ?? null,
    freshness_reason: source.freshness_reason ?? null,
    last_run_id: source.last_run_id ?? null,
    next_run_time: source.next_run_time ?? null,
    metadata: normalizeMetadata(source.metadata, source.source_name),
    affected_modules: normalizeStringArray(source.affected_modules),
    artifact_evidence: source.artifact_evidence ?? null,
    pipeline_health: source.pipeline_health ?? null,
  };
}

function createEmptyStatuses(): DataSourceStatuses {
  return {
    generated_at: "unavailable",
    last_refresh_at: null,
    sources: [],
  };
}

function createEmptySummary(): DataIngestionSummary {
  return {
    generated_at: "unavailable",
    source_count: 0,
    configured_count: 0,
    raw_ingested_count: 0,
    parsed_count: 0,
    analysis_ready_count: 0,
    status_counts: {
      ok: 0,
      warn: 0,
      error: 0,
      unavailable: 0,
    },
    source_groups: [],
    pipeline: {
      configured: "unavailable",
      raw_ingested: "unavailable",
      parsed: "unavailable",
      analysis_ready: "unavailable",
    },
    source_trace: [],
  };
}

function buildPipelineStatus(total: number, completed: number): "done" | "running" | "pending" | "unavailable" {
  if (total === 0) {
    return "unavailable";
  }
  if (completed === 0) {
    return "pending";
  }
  if (completed === total) {
    return "done";
  }
  return "running";
}

function buildSummaryFromStatuses(statuses: DataSourceStatuses): DataIngestionSummary {
  const sourceGroups = new Map<string, number>();
  const statusCounts: Record<DataIngestionStatus, number> = {
    ok: 0,
    warn: 0,
    error: 0,
    unavailable: 0,
  };

  let configuredCount = 0;
  let rawIngestedCount = 0;
  let parsedCount = 0;
  let analysisReadyCount = 0;

  for (const source of statuses.sources) {
    sourceGroups.set(source.source_group, (sourceGroups.get(source.source_group) ?? 0) + 1);
    statusCounts[source.status] += 1;

    if (source.configured) configuredCount += 1;
    if (source.raw_ingested) rawIngestedCount += 1;
    if (source.parsed) parsedCount += 1;
    if (source.analysis_ready) analysisReadyCount += 1;
  }

  return {
    generated_at: statuses.generated_at,
    source_count: statuses.sources.length,
    configured_count: configuredCount,
    raw_ingested_count: rawIngestedCount,
    parsed_count: parsedCount,
    analysis_ready_count: analysisReadyCount,
    status_counts: statusCounts,
    source_groups: Array.from(sourceGroups.entries()).map(([group, count]) => ({ group, count })),
    pipeline: {
      configured: buildPipelineStatus(statuses.sources.length, configuredCount),
      raw_ingested: buildPipelineStatus(statuses.sources.length, rawIngestedCount),
      parsed: buildPipelineStatus(statuses.sources.length, parsedCount),
      analysis_ready: buildPipelineStatus(statuses.sources.length, analysisReadyCount),
    },
    source_trace: statuses.sources.map((source) => ({
      name: source.source_name,
      trade_date: source.latest_raw_time?.slice(0, 10) ?? "—",
      file: "GET /api/data-sources/status",
      snapshot_id: source.snapshot_id,
      source_ref: source.source_refs[0] ?? `GET ${DATA_INGESTION_STATUS_PATH}#${source.source_key}`,
      endpoint: source.endpoint,
      latest_raw_time: source.latest_raw_time,
      latest_parsed_time: source.latest_parsed_time,
      status: source.status,
    })),
  };
}

function toDataStatus(status: DataIngestionStatus): DataStatus {
  switch (status) {
    case "ok":
      return "available";
    case "warn":
      return "partial";
    case "error":
      return "error";
    case "unavailable":
    default:
      return "unavailable";
  }
}

function stageToDataStatus(status: "done" | "running" | "pending" | "unavailable"): DataStatus {
  switch (status) {
    case "done":
      return "available";
    case "running":
      return "partial";
    case "pending":
    case "unavailable":
    default:
      return "unavailable";
  }
}

function sourceToSourceRef(source: DataSourceItem, responseSource: DataIngestionResponseSource): SourceRef {
  const asOf = source.latest_update_time ?? source.latest_parsed_time ?? source.latest_raw_time ?? null;
  const dataDate = source.latest_parsed_time?.slice(0, 10) ?? source.latest_raw_time?.slice(0, 10) ?? null;
  return {
    source_ref: source.source_refs[0] ?? `GET ${DATA_INGESTION_STATUS_PATH}#${source.source_key}`,
    endpoint: responseSource === "mock" ? "mocks/data-ingestion.json" : source.endpoint ?? DATA_INGESTION_STATUS_PATH,
    artifact_path: sourceArtifactPath(source),
    snapshot_id: source.snapshot_id,
    run_id: source.last_run_id ?? null,
    trade_date: dataDate,
    dataDate,
    asOf,
    generated_at: asOf,
    provider: source.source_name,
    label: source.metadata.frontend_label ?? source.source_name,
    status: toDataStatus(source.status),
  };
}

function readMetadataPath(metadata: DataSourceMetadata, keys: string[]): string | null {
  for (const key of keys) {
    const value = metadata[key];
    if (typeof value === "string" && value.trim().length > 0) {
      return value;
    }
  }
  return null;
}

function inferArtifactLayer(path: string): DataSourceArtifactLayer {
  if (path.includes("/raw/") || path.startsWith("raw/")) return "raw";
  if (path.includes("/parsed/") || path.startsWith("parsed/")) return "parsed";
  if (path.includes("/features/") || path.startsWith("features/")) return "features";
  return "analysis";
}

function createArtifactItem(
  key: string,
  label: string,
  path: string | null | undefined,
  layer?: DataSourceArtifactLayer,
): DataSourceArtifactItem | null {
  if (!path) return null;
  return {
    key,
    label,
    layer: layer ?? inferArtifactLayer(path),
    path,
  };
}

function dedupeArtifactItems(items: DataSourceArtifactItem[]): DataSourceArtifactItem[] {
  const seen = new Set<string>();
  return items.filter((item) => {
    const dedupeKey = `${item.layer}|${item.path}`;
    if (seen.has(dedupeKey)) return false;
    seen.add(dedupeKey);
    return true;
  });
}

function sourceArtifactPath(source: DataSourceItem): string | null {
  if (source.artifact_evidence?.preferred_artifact_path) {
    return source.artifact_evidence.preferred_artifact_path;
  }
  return readMetadataPath(source.metadata, [
    "artifact_path",
    "brief_artifact_path",
    "collector_parsed_artifact_path",
    "collector_raw_artifact_path",
    "raw_artifact_path",
    "raw_path",
    "file_path",
    "path",
    "file",
  ]);
}

function readMetadataNumber(metadata: DataSourceMetadata, key: string): number | null {
  const value = metadata[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function buildNewsFeatureSummary(metadata: DataSourceMetadata): NewsFeatureSummaryViewModel | null {
  const latestFeatureDate = readMetadataPath(metadata, ["latest_feature_date"]);
  const latestFeatureRunId = readMetadataPath(metadata, ["latest_feature_run_id"]);
  const marketMainline = metadata.market_mainline;
  const marketMainlineHeadline =
    marketMainline &&
    typeof marketMainline === "object" &&
    typeof (
      (marketMainline as Record<string, unknown>).headline ??
      (marketMainline as Record<string, unknown>).summary
    ) === "string"
      ? (((marketMainline as Record<string, unknown>).headline ??
          (marketMainline as Record<string, unknown>).summary) as string)
      : null;

  const summary: NewsFeatureSummaryViewModel = {
    latest_feature_date: latestFeatureDate,
    latest_feature_run_id: latestFeatureRunId,
    market_mainline_headline: marketMainlineHeadline,
    confirmed_event_count: readMetadataNumber(metadata, "confirmed_event_count") ?? 0,
    candidate_event_count: readMetadataNumber(metadata, "candidate_event_count") ?? 0,
    unconfirmed_risk_count: readMetadataNumber(metadata, "unconfirmed_risk_count") ?? 0,
    calendar_event_count: readMetadataNumber(metadata, "calendar_event_count") ?? 0,
    event_candidate_count: readMetadataNumber(metadata, "event_candidate_count"),
    brief_artifact_path: readMetadataPath(metadata, ["brief_artifact_path", "article_briefs_artifact_path"]),
    event_candidates_artifact_path: readMetadataPath(metadata, ["event_candidates_artifact_path"]),
    impact_assessments_artifact_path: readMetadataPath(metadata, ["impact_assessments_artifact_path"]),
    market_reactions_artifact_path: readMetadataPath(metadata, ["market_reactions_artifact_path"]),
    report_events_artifact_path: readMetadataPath(metadata, ["report_events_artifact_path"]),
  };

  const hasSummaryEvidence =
    Boolean(summary.latest_feature_date) ||
    Boolean(summary.latest_feature_run_id) ||
    Boolean(summary.market_mainline_headline) ||
    Boolean(summary.brief_artifact_path) ||
    Boolean(summary.event_candidates_artifact_path) ||
    Boolean(summary.impact_assessments_artifact_path) ||
    Boolean(summary.market_reactions_artifact_path) ||
    Boolean(summary.report_events_artifact_path) ||
    summary.confirmed_event_count > 0 ||
    summary.candidate_event_count > 0 ||
    summary.unconfirmed_risk_count > 0 ||
    summary.calendar_event_count > 0 ||
    (summary.event_candidate_count ?? 0) > 0;

  return hasSummaryEvidence ? summary : null;
}

function buildArtifactEvidence(source: DataSourceItem): DataSourceArtifactEvidence | null {
  const preferredArtifactPath = sourceArtifactPath(source);
  const collectorRawArtifactPath = readMetadataPath(source.metadata, ["collector_raw_artifact_path", "raw_artifact_path", "raw_path"]);
  const collectorParsedArtifactPath = readMetadataPath(source.metadata, ["collector_parsed_artifact_path"]);
  const latestRawUrl = source.metadata.latest_raw_url ?? source.metadata.latest_raw_ref?.url ?? null;
  const newsFeatureSummary = buildNewsFeatureSummary(source.metadata);

  const rawArtifacts = dedupeArtifactItems(
    [
      createArtifactItem("latest-raw", "latest raw", source.metadata.latest_raw_ref?.raw_path ?? null, "raw"),
      createArtifactItem("collector-raw", "collector raw", collectorRawArtifactPath, "raw"),
      createArtifactItem("cache", "cache artifact", readMetadataPath(source.metadata, ["cache_artifact_path"]), "raw"),
    ].filter((item): item is DataSourceArtifactItem => item !== null),
  );

  const parsedArtifacts = dedupeArtifactItems(
    [
      createArtifactItem("latest-parsed", "latest parsed", source.metadata.latest_raw_ref?.parsed_path ?? null, "parsed"),
      createArtifactItem("collector-parsed", "collector parsed", collectorParsedArtifactPath, "parsed"),
      createArtifactItem("preferred-parsed", "preferred artifact", preferredArtifactPath, inferArtifactLayer(preferredArtifactPath ?? "")),
    ].filter((item): item is DataSourceArtifactItem => item !== null && item.layer === "parsed"),
  );

  const featureArtifacts = dedupeArtifactItems(
    [
      createArtifactItem("article-briefs", "article briefs", readMetadataPath(source.metadata, ["article_briefs_artifact_path", "brief_artifact_path"]), "features"),
      createArtifactItem("daily-triggers", "daily analysis triggers", readMetadataPath(source.metadata, ["daily_analysis_triggers_artifact_path"]), "features"),
      createArtifactItem("event-candidates", "event candidates", readMetadataPath(source.metadata, ["event_candidates_artifact_path"]), "features"),
      createArtifactItem("impact-assessments", "impact assessments", readMetadataPath(source.metadata, ["impact_assessments_artifact_path"]), "features"),
      createArtifactItem("market-reactions", "market reactions", readMetadataPath(source.metadata, ["market_reactions_artifact_path"]), "features"),
      createArtifactItem("preferred-features", "preferred artifact", preferredArtifactPath, inferArtifactLayer(preferredArtifactPath ?? "")),
    ].filter((item): item is DataSourceArtifactItem => item !== null && item.layer === "features"),
  );

  const analysisArtifacts = dedupeArtifactItems(
    [
      createArtifactItem("report-events", "report events", readMetadataPath(source.metadata, ["report_events_artifact_path"]), "analysis"),
      createArtifactItem("preferred-analysis", "preferred artifact", preferredArtifactPath, inferArtifactLayer(preferredArtifactPath ?? "")),
    ].filter((item): item is DataSourceArtifactItem => item !== null && item.layer === "analysis"),
  );

  if (
    !preferredArtifactPath &&
    !collectorRawArtifactPath &&
    !collectorParsedArtifactPath &&
    !latestRawUrl &&
    rawArtifacts.length === 0 &&
    parsedArtifacts.length === 0 &&
    featureArtifacts.length === 0 &&
    analysisArtifacts.length === 0 &&
    !newsFeatureSummary
  ) {
    return null;
  }

  return {
    preferred_artifact_path: preferredArtifactPath,
    collector_raw_artifact_path: collectorRawArtifactPath,
    collector_parsed_artifact_path: collectorParsedArtifactPath,
    latest_raw_url: latestRawUrl,
    raw_artifacts: rawArtifacts,
    parsed_artifacts: parsedArtifacts,
    feature_artifacts: featureArtifacts,
    analysis_artifacts: analysisArtifacts,
    news_feature_summary: newsFeatureSummary,
  };
}

function buildNewsRuntime(metadata: DataSourceMetadata, group: string): NewsSourceRuntimeViewModel | null {
  if (group !== "news") {
    return null;
  }

  const latestCollectorRuntime =
    metadata.latest_collector_runtime &&
    typeof metadata.latest_collector_runtime === "object"
      ? (metadata.latest_collector_runtime as Record<string, unknown>)
      : null;

  const runtime: NewsSourceRuntimeViewModel = {
    collection_diagnostics_artifact_path: readMetadataPath(metadata, ["collection_diagnostics_artifact_path"]),
    latest_collection_status: readMetadataPath(metadata, ["latest_collection_status"]),
    latest_source_ref_count: readMetadataNumber(metadata, "latest_source_ref_count"),
    latest_source_ref_statuses: Array.isArray(metadata.latest_source_ref_statuses)
      ? metadata.latest_source_ref_statuses.filter((item): item is string => typeof item === "string")
      : [],
    latest_reason_codes: Array.isArray(metadata.latest_reason_codes)
      ? metadata.latest_reason_codes.filter((item): item is string => typeof item === "string")
      : [],
    latest_collection_warnings: Array.isArray(metadata.latest_collection_warnings)
      ? metadata.latest_collection_warnings.filter((item): item is string => typeof item === "string")
      : [],
    latest_collector_runtime: latestCollectorRuntime
      ? {
          collector: typeof latestCollectorRuntime.collector === "string" ? latestCollectorRuntime.collector : undefined,
          status: typeof latestCollectorRuntime.status === "string" ? latestCollectorRuntime.status : undefined,
          items: typeof latestCollectorRuntime.items === "number" ? latestCollectorRuntime.items : undefined,
          unavailable_feeds:
            typeof latestCollectorRuntime.unavailable_feeds === "number"
              ? latestCollectorRuntime.unavailable_feeds
              : undefined,
          warnings: Array.isArray(latestCollectorRuntime.warnings)
            ? latestCollectorRuntime.warnings.filter((item): item is string => typeof item === "string")
            : [],
          error: typeof latestCollectorRuntime.error === "string" ? latestCollectorRuntime.error : undefined,
        }
      : null,
  };

  const hasRuntimeEvidence =
    Boolean(runtime.collection_diagnostics_artifact_path) ||
    Boolean(runtime.latest_collection_status) ||
    runtime.latest_source_ref_count !== null ||
    runtime.latest_source_ref_statuses.length > 0 ||
    runtime.latest_reason_codes.length > 0 ||
    runtime.latest_collection_warnings.length > 0 ||
    Boolean(runtime.latest_collector_runtime);

  return hasRuntimeEvidence ? runtime : null;
}

function deriveSourceStatusReason(source: DataSourceItem): string | null {
  if (!source.configured) {
    return "source not configured";
  }
  if (source.error_message) {
    return source.error_message;
  }
  if (source.status === "warn" && !source.parsed) {
    return "raw ingested but parsed not ready";
  }
  if (source.status === "warn" && source.parsed && !source.analysis_ready) {
    return "parsed available but analysis not ready";
  }
  if (
    source.status === "ok" &&
    !source.latest_raw_time &&
    !source.latest_parsed_time &&
    !source.snapshot_id &&
    !source.last_run_id
  ) {
    return "status ok but no run/snapshot evidence";
  }
  if (source.status === "unavailable") {
    return "configured but upstream unavailable";
  }
  return null;
}

function buildOverallStatus(sources: DataSourceItem[], responseSource: DataIngestionResponseSource): DataStatus {
  if (responseSource === "unavailable" || sources.length === 0) {
    return "unavailable";
  }
  if (sources.some((source) => source.status === "error")) {
    return "error";
  }
  if (responseSource === "mock" || sources.some((source) => source.status === "warn" || source.status === "unavailable")) {
    return "partial";
  }
  return "available";
}

function buildLayerStatuses(summary: DataIngestionSummary, sourceRefs: SourceRef[]): PipelineLayerStatus[] {
  const total = summary.source_count;
  return [
    {
      id: "configured",
      label: "configured",
      status: stageToDataStatus(summary.pipeline.configured),
      completed_count: summary.configured_count,
      total_count: total,
      source_refs: sourceRefs,
    },
    {
      id: "raw_ingested",
      label: "raw_ingested",
      status: stageToDataStatus(summary.pipeline.raw_ingested),
      completed_count: summary.raw_ingested_count,
      total_count: total,
      source_refs: sourceRefs,
    },
    {
      id: "parsed",
      label: "parsed",
      status: stageToDataStatus(summary.pipeline.parsed),
      completed_count: summary.parsed_count,
      total_count: total,
      source_refs: sourceRefs,
    },
    {
      id: "analysis_ready",
      label: "analysis_ready",
      status: stageToDataStatus(summary.pipeline.analysis_ready),
      completed_count: summary.analysis_ready_count,
      total_count: total,
      source_refs: sourceRefs,
    },
  ];
}

/* ── 7-stage pipeline health inference ──────────────────────────────── */

/** Map source_key to a source domain for coloring/grouping. */
function inferDomain(group: string): SourceDomain {
  switch (group) {
    case "macro":
      return "macro";
    case "cme":
      return "cme";
    case "technical":
    case "market":
      return "market";
    case "positioning":
      return "positioning";
    case "news":
      return "news";
    case "report":
      return "report";
    default:
      return "macro";
  }
}

/** Map provider_role to SourcePriority */
function inferPriority(role: string): SourcePriority {
  switch (role) {
    case "official_primary":
      return "PRIMARY";
    case "fallback":
      return "FALLBACK";
    case "supplemental":
      return "SUPPLEMENTAL";
    case "derived":
      return "DERIVED";
    default:
      return "PRIMARY";
  }
}

/** Known downstream affected modules per source_key. */
const SOURCE_AFFECTED_MODULES: Record<string, string[]> = {
  fred: ["Dashboard", "Reports", "Market Monitor"],
  openbb_macro: ["Dashboard", "Reports"],
  fed: ["Liquidity", "Reports", "Dashboard"],
  treasury: ["Liquidity", "Reports", "Dashboard"],
  dxy: ["Dashboard", "Market Monitor", "Gold Attribution"],
  cme_daily_bulletin: ["CME Options", "Reports"],
  cme_options: ["CME Options", "Reports", "Dashboard"],
  technical_yahoo: ["Dashboard", "Market Monitor", "Technical"],
  positioning_cot: ["Dashboard", "Reports", "Market Monitor"],
  jin10_news: ["Event Flow", "Dashboard", "Reports"],
  fed_rss: ["Event Flow", "Reports", "Daily Brief"],
  bls_calendar: ["Event Flow", "Reports", "Daily Brief"],
  bea_calendar: ["Event Flow", "Reports", "Daily Brief"],
  eia_energy: ["Event Flow", "Reports", "Daily Brief"],
  gdelt_news: ["Event Flow", "Reports", "Daily Brief"],
  google_news_rss: ["Event Flow", "Reports", "Daily Brief"],
  reuters_public_news: ["Event Flow", "Reports", "Daily Brief"],
};

function ok(message?: string): StageHealth {
  return { status: "OK", message };
}
function ready(message?: string): StageHealth {
  return { status: "READY", message };
}
function err(message?: string): StageHealth {
  return { status: "ERROR", message };
}
function blocked(message?: string): StageHealth {
  return { status: "BLOCKED", message };
}
function warn(message?: string): StageHealth {
  return { status: "WARN", message };
}
function noData(message?: string): StageHealth {
  return { status: "NO_DATA", message };
}
function noSnapshot(message?: string): StageHealth {
  return { status: "NO_SNAPSHOT", message };
}
function waiting(message?: string): StageHealth {
  return { status: "WAITING", message };
}
function withStageRefs(stage: StageHealth, refs: Pick<StageHealth, "inputRef" | "outputRef">): StageHealth {
  return { ...stage, ...refs };
}

function inferPipelineHealth(source: DataSourceItem): SourcePipelineHealth {
  const { configured, raw_ingested, parsed, analysis_ready, status, error_message, source_key, source_group } = source;

  // Determine if data has ever flowed through this source (directly or via pipeline)
  const hasSnapshot = Boolean(source.snapshot_id);
  const hasRawTime = Boolean(source.latest_raw_time);
  const hasParsedTime = Boolean(source.latest_parsed_time);
  const isFailed = status === "error" || status === "unavailable";
  const isWarn = status === "warn";

  // Compute latest data date from timestamps
  const rawDate = source.latest_raw_time?.slice(0, 10);
  const parsedDate = source.latest_parsed_time?.slice(0, 10);
  const updateDate = source.latest_update_time?.slice(0, 10);
  const latestDataDate = updateDate ?? parsedDate ?? rawDate ?? undefined;
  const today = new Date().toISOString().slice(0, 10);
  const stalenessDays = latestDataDate
    ? Math.floor((new Date(today).getTime() - new Date(latestDataDate).getTime()) / 86400000)
    : null;

  // For sources with snapshot_id, data HAS entered the analysis pipeline even if
  // raw_ingested=false (e.g. fred data arrives via openbb_macro, not directly).
  const dataAvailable = raw_ingested || hasSnapshot || hasRawTime;
  const parseAvailable = parsed || hasParsedTime || (hasSnapshot && !raw_ingested);
  const artifactPath = sourceArtifactPath(source);
  const snapshotRef = source.snapshot_id ?? undefined;

  // Connection: configured?
  const connection: StageHealth = configured ? ok() : err("not configured");

  // Collect: data collection status
  const collect: StageHealth = withStageRefs(
    !configured
      ? blocked("upstream not configured")
      : raw_ingested
        ? ok(hasRawTime ? `latest: ${rawDate}` : undefined)
        : dataAvailable
          ? warn(isFailed ? `source failed, using historical data` : `via pipeline/snapshot`)
          : isFailed
            ? err(error_message ?? "collection failed")
            : noData("no data collected"),
    { outputRef: artifactPath ?? undefined },
  );

  // Raw landing: is there evidence of raw data?
  const rawLanding: StageHealth = withStageRefs(
    !configured
      ? blocked()
      : raw_ingested
        ? ok(hasRawTime ? `last: ${rawDate}` : "raw ingested")
        : dataAvailable
          ? warn(hasRawTime ? `historical: ${rawDate}` : "via pipeline, no direct raw timestamp")
          : noData(),
    { outputRef: artifactPath ?? undefined },
  );

  // Parse: parsing status
  const parse: StageHealth = withStageRefs(
    !configured
      ? blocked()
      : parsed
        ? ok(hasParsedTime ? `last: ${parsedDate}` : undefined)
        : parseAvailable
          ? warn("available via snapshot, no direct parse timestamp")
          : !dataAvailable
            ? blocked("no raw data")
            : isWarn
              ? warn("raw ingested but parse incomplete")
              : err("parse failed"),
    { inputRef: artifactPath ?? undefined, outputRef: snapshotRef },
  );

  // Validate: data quality check
  const validate: StageHealth = !configured
    ? blocked()
    : (parsed || parseAvailable)
      ? (status === "ok" ? ok() : isWarn ? warn("partial data quality") : warn("degraded quality"))
      : !dataAvailable
        ? blocked("parse not ready")
        : blocked("parse not ready");

  // Snapshot: analysis snapshot availability
  const snapshot: StageHealth = withStageRefs(
    !configured
      ? blocked()
      : analysis_ready
        ? ready(hasSnapshot ? `snapshot: ${source.snapshot_id!.slice(0, 8)}` : "ready")
        : hasSnapshot
          ? ready(`historical snapshot: ${source.snapshot_id!.slice(0, 8)}`)
          : (parsed || parseAvailable)
            ? noSnapshot("parsed but no snapshot yet")
            : blocked("upstream incomplete"),
    { inputRef: snapshotRef, outputRef: snapshotRef },
  );

  // Consumer ready: can downstream modules consume?
  const consumerReady: StageHealth = withStageRefs(
    !configured
      ? blocked()
      : analysis_ready
        ? ready()
        : hasSnapshot
          ? warn("using historical snapshot")
          : (parsed || parseAvailable)
            ? warn("partial availability")
            : blocked("upstream incomplete"),
    { inputRef: snapshotRef },
  );

  const downstreamStatus: DownstreamStatus = analysis_ready
    ? "READY"
    : hasSnapshot
      ? "DEGRADED"  // historical data available but not fresh
      : (parsed || parseAvailable)
        ? "DEGRADED"
        : "BLOCKED";

  return {
    sourceId: source.source_key,
    sourceName: source.metadata.frontend_label ?? source.source_name,
    sourceType: source.source_type.toUpperCase() as SourcePipelineHealth["sourceType"],
    domain: inferDomain(source_group),
    priority: inferPriority(source.metadata.provider_role),
    stages: { connection, collect, rawLanding, parse, validate, snapshot, consumerReady },
    latestRunId: source.last_run_id ?? undefined,
    snapshotId: source.snapshot_id ?? undefined,
    rawArtifactRef: artifactPath ?? undefined,
    affectedModules: source.affected_modules.length > 0 ? source.affected_modules : SOURCE_AFFECTED_MODULES[source_key] ?? [source_group],
    downstreamStatus,
    latestDataDate,
    stalenessDays,
  };
}

function buildDataIngestionViewModel(
  summary: DataIngestionSummary,
  statuses: DataSourceStatuses,
  responseSource: DataIngestionResponseSource,
  systemStatus: DataStatusSummary | null,
): DataIngestionViewModel {
  const sourceRefs = statuses.sources.map((source) => sourceToSourceRef(source, responseSource));
  const status = buildOverallStatus(statuses.sources, responseSource);

  return {
    status,
    updated_at: statuses.last_refresh_at ?? summary.generated_at,
    summary: {
      status,
      label: responseSource === "mock" ? "mock fallback" : responseSource,
      source_count: summary.source_count,
      generated_at: summary.generated_at,
      available_count: summary.status_counts.ok,
      partial_count: summary.status_counts.warn,
      unavailable_count: summary.status_counts.unavailable,
      error_count: summary.status_counts.error,
      updated_at: statuses.last_refresh_at ?? summary.generated_at,
      source_refs: sourceRefs,
      source_groups: summary.source_groups,
    },
    system_status: systemStatus
      ? {
          overall_status: systemStatus.overall_status,
          latest_run_id: systemStatus.latest_run?.run_id ?? null,
          latest_run_status: systemStatus.latest_run?.status ?? null,
          latest_run_created_at: systemStatus.latest_run?.created_at ?? null,
          latest_run_trade_date: systemStatus.latest_run?.trade_date ?? null,
          snapshot_id: systemStatus.snapshot_id,
          data_date: systemStatus.data_date,
          missing_sources: systemStatus.missing_sources,
          stale_sources: systemStatus.stale_sources,
        }
      : null,
    sources: statuses.sources.map((source) => ({
      id: source.source_key,
      label: source.metadata.frontend_label ?? source.source_name,
      group: source.source_group,
      type: source.source_type,
      role: source.metadata.provider_role,
      status: toDataStatus(source.status),
      raw_status: source.status,
      endpoint: source.endpoint,
      configured: source.configured,
      raw_ingested: source.raw_ingested,
      parsed: source.parsed,
      analysis_ready: source.analysis_ready,
      latest_raw_time: source.latest_raw_time,
      latest_parsed_time: source.latest_parsed_time,
      latest_update_time: source.latest_update_time,
      freshness_status: source.freshness_status,
      freshness_reason: source.freshness_reason,
      row_count: source.row_count,
      error_message: source.error_message,
      status_reason: deriveSourceStatusReason(source),
      snapshot_id: source.snapshot_id,
      last_run_id: source.last_run_id,
      next_run_time: source.next_run_time,
      fallback_for: source.metadata.fallback_for,
      fallback_sources: source.metadata.fallback_sources,
      notes: source.metadata.notes,
      latest_raw_ref: source.metadata.latest_raw_ref ?? null,
      database_tables: source.metadata.database_tables ?? [],
      artifact_layers: source.metadata.artifact_layers ?? [],
      polling_strategy: source.metadata.polling_strategy ?? null,
      pressure_profile: source.metadata.pressure_profile ?? null,
      artifact_evidence: source.artifact_evidence ?? buildArtifactEvidence(source),
      news_runtime: buildNewsRuntime(source.metadata, source.source_group),
      source_refs: [sourceToSourceRef(source, responseSource)],
      pipeline_health: source.pipeline_health ?? inferPipelineHealth(source),
    })),
    layers: buildLayerStatuses(summary, sourceRefs),
    source_refs: sourceRefs,
  };
}

function createUnavailableResponse(reason: string): DataIngestionResponse {
  const summary = createEmptySummary();
  const statuses = createEmptyStatuses();
  return {
    summary,
    statuses,
    has_data: false,
    source: "unavailable",
    error_reason: reason,
    view_model: buildDataIngestionViewModel(summary, statuses, "unavailable", null),
  };
}

async function loadMockDataIngestion(): Promise<DataIngestionResponse> {
  const response = await fetch(DATA_INGESTION_MOCK_URL);

  if (!response.ok) {
    throw new Error(`加载 Data Ingestion mock 失败：${response.status}`);
  }

  const payload = (await response.json()) as DataIngestionMockFile;

  const statuses = {
    ...payload.statuses,
    sources: payload.statuses.sources.map(normalizeSourceItem),
  };
  const summary = payload.summary;

  return {
    summary,
    statuses,
    has_data: statuses.sources.length > 0,
    source: "mock",
    view_model: buildDataIngestionViewModel(summary, statuses, "mock", null),
  };
}

export async function fetchDataIngestionData(): Promise<DataIngestionResponse> {
  try {
    const [payload, systemStatus] = await Promise.all([
      fetchJson<ApiDataSourceStatuses>(DATA_INGESTION_STATUS_PATH),
      fetchJson<DataStatusSummary>(DATA_STATUS_SUMMARY_PATH).catch(() => null),
    ]);

    if (!Array.isArray(payload.sources)) {
      throw new ApiError("Data Ingestion API 响应缺少 sources", {
        url: DATA_INGESTION_STATUS_PATH,
      });
    }

    const statuses = normalizeApiStatuses(payload);
    const summary = buildSummaryFromStatuses(statuses);

    return {
      summary,
      statuses: {
        generated_at: statuses.generated_at,
        last_refresh_at: statuses.last_refresh_at,
        sources: statuses.sources,
      },
      has_data: statuses.sources.length > 0,
      source: "api",
      view_model: buildDataIngestionViewModel(summary, statuses, "api", systemStatus),
    };
  } catch (apiCause) {
    const apiError = apiCause instanceof Error ? apiCause.message : "Data Ingestion API 请求失败";

    try {
      const mockData = await loadMockDataIngestion();
      return {
        ...mockData,
        source: "mock",
        error_reason: apiError,
        view_model: buildDataIngestionViewModel(mockData.summary, mockData.statuses, "mock", null),
      };
    } catch (mockCause) {
      const mockError = mockCause instanceof Error ? mockCause.message : "Data Ingestion mock 请求失败";
      return createUnavailableResponse(`${apiError}; ${mockError}`);
    }
  }
}

export async function triggerIngestionRetry(
  sourceKey: string,
  body: DataSourceActionRequest = {},
): Promise<DataSourceActionResponse> {
  return fetchJson<DataSourceActionResponse>(`${DATA_INGESTION_RETRY_PATH}/${encodeURIComponent(sourceKey)}/retry`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      action: "retry",
      actor: body.actor ?? "frontend",
      reason: body.reason ?? "retry requested from Data Ingestion page",
      request_id: body.request_id ?? `retry-${sourceKey}-${Date.now()}`,
    }),
  });
}

export async function triggerIngestionSourceTest(
  sourceKey: string,
  body: DataSourceTestRequest = {},
): Promise<DataSourceTestResponse> {
  return fetchJson<DataSourceTestResponse>(`${DATA_INGESTION_RETRY_PATH}/${encodeURIComponent(sourceKey)}/test`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      action: "test",
      actor: body.actor ?? "frontend",
      reason: body.reason ?? "manual source test from Data Ingestion page",
      request_id: body.request_id ?? `test-${sourceKey}-${Date.now()}`,
      limit: body.limit ?? 5,
    }),
  });
}

export async function fetchDataSourceStatuses(): Promise<DataSourceStatuses> {
  const payload = await fetchDataIngestionData();
  return payload.statuses;
}
