import { fetchJson } from "@/adapters/apiClient";
import { GOLD_MAINLINE_IDS, GOLD_TRANSMISSION_PATH_IDS } from "@/generated/gold-contract";
import type { ArtifactRef } from "@/types/artifact";
import type { SourceRef } from "@/types/common";
import type { ProcessingStageStatus, ProcessingTrace, ProcessingTraceEntityType } from "@/types/processing-monitor";
import type {
  AnalysisReadiness,
  DriverConflict,
  GoldChainConclusionCode,
  GoldImpactStrength,
  GoldMacroOverview,
  GoldMainline,
  GoldMainlineRanking,
  GoldMainlinesViewModel,
  GoldMainlineStatus,
  GoldMainlineTrend,
  GoldNetBias,
  GoldPhase,
  GoldPricingLayer,
  GoldReadinessStatus,
  GoldSchemaVersion,
  GoldVerificationStatus,
  MainlineRequirement,
  TransmissionChainSummary,
  TransmissionPath,
  VerificationItem,
} from "@/types/gold-mainlines";

const GOLD_MAINLINES_LATEST_PATH = "/api/gold/mainlines/latest";
const GOLD_MAINLINE_SET = new Set<string>(GOLD_MAINLINE_IDS);
const TRANSMISSION_PATH_SET = new Set<string>(GOLD_TRANSMISSION_PATH_IDS);
const GOLD_STATUS_SET = new Set<string>(["available", "partial", "unavailable", "error", "stale", "fallback", "manual_required", "blocked", "unknown"]);
const GOLD_VERIFICATION_STATUS_SET = new Set<string>([
  "official_confirmed",
  "multi_source",
  "report_derived",
  "single_source",
  "unverified",
  "needs_verification",
  "not_applicable",
  "unknown",
]);
const GOLD_NET_BIAS_SET = new Set<string>([
  "strong_bullish",
  "bullish",
  "neutral_bullish",
  "neutral",
  "neutral_bearish",
  "bearish",
  "strong_bearish",
  "mixed",
  "mixed_bullish",
  "mixed_bearish",
  "unknown",
]);
const GOLD_PHASE_SET = new Set<string>([
  "strong_uptrend",
  "high_level_range",
  "weak_repair_watch",
  "correction_escalation",
  "trend_failure",
  "unknown",
]);
const GOLD_PRICING_LAYER_SET = new Set<string>([
  "rate_pricing",
  "currency_pricing",
  "risk_pricing",
  "capital_pricing",
  "regional_demand",
  "pricing_center",
  "external_shock",
  "capital_confirmation",
  "structural_support",
  "price_confirmation",
]);
const GOLD_TREND_SET = new Set<string>(["rising", "falling", "stable", "new", "unknown"]);
const GOLD_IMPACT_STRENGTH_SET = new Set<string>(["high", "medium", "low", "weak", "strong", "unknown"]);
const GOLD_CONCLUSION_CODE_SET = new Set<string>(["A", "B", "C", "D", "unknown"]);
const GOLD_READINESS_SET = new Set<string>(["ready", "partial", "missing", "unknown"]);
const VERIFICATION_ITEM_STATUS_SET = new Set<string>(["confirmed", "pending", "failed", "unavailable", "not_required", "unknown"]);
const PROCESSING_TRACE_ENTITY_TYPE_SET = new Set<string>(["news", "report_input", "event", "analysis_signal", "unknown"]);
const PROCESSING_STAGE_STATUS_SET = new Set<string>(["raw", "parsed", "normalized", "attributed", "validated", "projected", "rendered", "unknown"]);

export interface GoldMainlinesResponse {
  status: GoldMainlineStatus;
  date: string | null;
  run_id: string | null;
  artifact_path: string | null;
  schema_version: string | null;
  input_snapshot_ids: Record<string, unknown>;
  gold_macro_overview: GoldMacroOverview | null;
  gold_mainlines: GoldMainlinesViewModel;
  source_refs: SourceRef[];
  warnings: string[];
}

interface RawGoldMainlinesResponse {
  status?: string;
  date?: string | null;
  run_id?: string | null;
  artifact_path?: string | null;
  schema_version?: string | null;
  input_snapshot_ids?: Record<string, unknown>;
  gold_macro_overview?: unknown;
  gold_mainlines?: unknown;
  source_refs?: SourceRef[];
  warnings?: string[];
}

type RawRecord = Record<string, unknown>;

function asRecord(value: unknown): RawRecord {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as RawRecord) : {};
}

function recordList(value: unknown): RawRecord[] {
  return Array.isArray(value) ? value.filter((item): item is RawRecord => Boolean(item) && typeof item === "object" && !Array.isArray(item)) : [];
}

function stringValue(value: unknown, fallback = ""): string {
  return typeof value === "string" && value.length > 0 ? value : fallback;
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

function normalizeStringList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string" && item.trim().length > 0) : [];
}

function normalizeSourceRefs(value: unknown): SourceRef[] {
  return Array.isArray(value) ? (value.filter((item) => Boolean(item) && typeof item === "object") as SourceRef[]) : [];
}

function normalizeArtifactRefs(value: unknown): ArtifactRef[] {
  return Array.isArray(value) ? (value.filter((item) => Boolean(item) && typeof item === "object") as ArtifactRef[]) : [];
}

function oneOf<T extends string>(value: unknown, allowed: ReadonlySet<string>, fallback: T): T {
  const text = stringValue(value);
  return allowed.has(text) ? (text as T) : fallback;
}

function normalizeGoldStatus(value: unknown, fallback: GoldMainlineStatus = "unknown"): GoldMainlineStatus {
  return oneOf(value, GOLD_STATUS_SET, fallback);
}

function normalizeGoldMainline(value: unknown): GoldMainline | null {
  const text = stringValue(value);
  return GOLD_MAINLINE_SET.has(text) ? (text as GoldMainline) : null;
}

function normalizeTransmissionPath(value: unknown): TransmissionPath {
  const text = stringValue(value);
  return TRANSMISSION_PATH_SET.has(text) ? (text as TransmissionPath) : "inflation_to_real_rates";
}

function normalizeGoldVerificationStatus(value: unknown): GoldVerificationStatus {
  return oneOf(value, GOLD_VERIFICATION_STATUS_SET, "unknown");
}

function normalizeGoldNetBias(value: unknown): GoldNetBias {
  return oneOf(value, GOLD_NET_BIAS_SET, "unknown");
}

function normalizeGoldPhase(value: unknown): GoldPhase {
  return oneOf(value, GOLD_PHASE_SET, "unknown");
}

function normalizeGoldPricingLayer(value: unknown): GoldPricingLayer | "unknown" {
  return oneOf(value, GOLD_PRICING_LAYER_SET, "unknown");
}

function normalizeGoldTrend(value: unknown): GoldMainlineTrend {
  return oneOf(value, GOLD_TREND_SET, "unknown");
}

function normalizeImpactStrength(value: unknown): GoldImpactStrength {
  return oneOf(value, GOLD_IMPACT_STRENGTH_SET, "unknown");
}

function normalizeConclusionCode(value: unknown): GoldChainConclusionCode {
  return oneOf(value, GOLD_CONCLUSION_CODE_SET, "unknown");
}

function normalizeReadinessStatus(value: unknown): GoldReadinessStatus {
  return oneOf(value, GOLD_READINESS_SET, "unknown");
}

function normalizeSchemaVersion(value: unknown): GoldSchemaVersion {
  return value === "gold-event-mainlines-v1" ? "gold-event-mainlines-v1" : "unknown";
}

function normalizeGoldMainlineRanking(value: unknown): GoldMainlineRanking {
  const item = asRecord(value);
  return {
    mainline_id: normalizeGoldMainline(item.mainline_id),
    mainline: normalizeGoldMainline(item.mainline),
    label: stringValue(item.label, "Unknown mainline"),
    pricing_layer: normalizeGoldPricingLayer(item.pricing_layer),
    rank: numberValue(item.rank),
    score: nullableNumber(item.score),
    theme_score: nullableNumber(item.theme_score),
    direction_score: nullableNumber(item.direction_score),
    impact_score: nullableNumber(item.impact_score),
    confidence_score: nullableNumber(item.confidence_score),
    freshness_score: nullableNumber(item.freshness_score),
    direction: normalizeGoldNetBias(item.direction),
    confidence: nullableNumber(item.confidence),
    verification_status: normalizeGoldVerificationStatus(item.verification_status),
    trend: normalizeGoldTrend(item.trend),
    impact_strength: normalizeImpactStrength(item.impact_strength),
    freshness: normalizeGoldStatus(item.freshness),
    evidence_count: nullableNumber(item.evidence_count),
    missing_data: normalizeStringList(item.missing_data),
    related_event_ids: normalizeStringList(item.related_event_ids),
    dominant: item.dominant === true,
    summary: stringValue(item.summary),
    bullish_drivers: normalizeStringList(item.bullish_drivers),
    bearish_drivers: normalizeStringList(item.bearish_drivers),
    event_ids: normalizeStringList(item.event_ids),
    source_refs: normalizeSourceRefs(item.source_refs),
    artifact_refs: normalizeArtifactRefs(item.artifact_refs),
  };
}

function normalizeTransmissionChainSummary(value: unknown): TransmissionChainSummary | null {
  const item = asRecord(value);
  if (Object.keys(item).length === 0) return null;
  return {
    path_id: normalizeTransmissionPath(item.path_id),
    label: stringValue(item.label, "Transmission chain"),
    status: normalizeGoldStatus(item.status),
    conclusion_code: normalizeConclusionCode(item.conclusion_code),
    conclusion_label: nullableString(item.conclusion_label) ?? undefined,
    net_effect: normalizeGoldNetBias(item.net_effect),
    geopolitical_status: normalizeGoldStatus(item.geopolitical_status),
    oil_status: normalizeGoldStatus(item.oil_status),
    inflation_expectation_status: normalizeGoldStatus(item.inflation_expectation_status),
    fed_expectation_status: normalizeGoldStatus(item.fed_expectation_status),
    real_rate_status: normalizeGoldStatus(item.real_rate_status),
    dollar_status: normalizeGoldStatus(item.dollar_status),
    gold_effect: normalizeGoldNetBias(item.gold_effect),
    conclusion: nullableString(item.conclusion),
    verification_needed: normalizeStringList(item.verification_needed),
    dominant_driver: nullableString(item.dominant_driver),
    summary: stringValue(item.summary),
    steps: recordList(item.steps).map((step) => ({
      id: stringValue(step.id),
      label: stringValue(step.label),
      value: typeof step.value === "number" || typeof step.value === "string" ? step.value : null,
      status: normalizeGoldStatus(step.status),
      source_refs: normalizeSourceRefs(step.source_refs),
    })),
    source_refs: normalizeSourceRefs(item.source_refs),
    artifact_refs: normalizeArtifactRefs(item.artifact_refs),
  };
}

function normalizeDriverConflict(value: unknown): DriverConflict | null {
  const item = asRecord(value);
  if (Object.keys(item).length === 0) return null;
  return {
    status: oneOf(item.status, new Set(["aligned", "conflicted", "mixed", "unknown"]), "unknown"),
    dominant_driver: nullableString(item.dominant_driver),
    bullish_drivers: normalizeStringList(item.bullish_drivers),
    bearish_drivers: normalizeStringList(item.bearish_drivers),
    net_effect: normalizeGoldNetBias(item.net_effect),
    explanation: stringValue(item.explanation),
    verification_needed: normalizeStringList(item.verification_needed),
    source_refs: normalizeSourceRefs(item.source_refs),
  };
}

function normalizeVerificationItem(value: unknown): VerificationItem {
  const item = asRecord(value);
  return {
    id: stringValue(item.id),
    label: stringValue(item.label),
    status: oneOf(item.status, VERIFICATION_ITEM_STATUS_SET, "unknown"),
    mainline_id: normalizeGoldMainline(item.mainline_id),
    event_id: nullableString(item.event_id),
    required_source: nullableString(item.required_source),
    reason: nullableString(item.reason),
    source_refs: normalizeSourceRefs(item.source_refs),
  };
}

function normalizeMainlineRequirement(value: unknown): MainlineRequirement {
  const item = asRecord(value);
  return {
    mainline_id: normalizeGoldMainline(item.mainline_id),
    label: stringValue(item.label),
    pricing_layer: normalizeGoldPricingLayer(item.pricing_layer),
    asset_principle: stringValue(item.asset_principle),
    analysis_chain: normalizeStringList(item.analysis_chain),
    required_sources: normalizeStringList(item.required_sources),
    required_fields: normalizeStringList(item.required_fields),
    developed_sources: normalizeStringList(item.developed_sources),
    missing_sources: normalizeStringList(item.missing_sources),
    missing_fields: normalizeStringList(item.missing_fields),
    readiness_status: normalizeReadinessStatus(item.readiness_status),
    page_targets: normalizeStringList(item.page_targets),
    verification_requirements: normalizeStringList(item.verification_requirements),
    development_gaps: normalizeStringList(item.development_gaps),
  };
}

function normalizeAnalysisReadiness(value: unknown): AnalysisReadiness | undefined {
  const item = asRecord(value);
  if (Object.keys(item).length === 0) return undefined;
  return {
    status: normalizeReadinessStatus(item.status),
    ready_count: numberValue(item.ready_count),
    partial_count: numberValue(item.partial_count),
    missing_count: numberValue(item.missing_count),
    total_count: numberValue(item.total_count),
    coverage_ratio: numberValue(item.coverage_ratio),
    next_gaps: normalizeStringList(item.next_gaps),
  };
}

function normalizeProcessingTraceList(value: unknown): ProcessingTrace[] | undefined {
  if (!Array.isArray(value)) return undefined;
  return recordList(value).map((trace) => ({
    trace_id: stringValue(trace.trace_id),
    entity_type: oneOf<ProcessingTraceEntityType>(trace.entity_type, PROCESSING_TRACE_ENTITY_TYPE_SET, "unknown"),
    entity_id: stringValue(trace.entity_id),
    source_refs: normalizeSourceRefs(trace.source_refs),
    artifact_refs: normalizeArtifactRefs(trace.artifact_refs),
    stages: recordList(trace.stages).map((stage) => ({
      stage_id: stringValue(stage.stage_id),
      status: oneOf<ProcessingStageStatus>(stage.status, PROCESSING_STAGE_STATUS_SET, "unknown"),
      started_at: nullableString(stage.started_at),
      finished_at: nullableString(stage.finished_at),
      source_refs: normalizeSourceRefs(stage.source_refs),
      artifact_refs: normalizeArtifactRefs(stage.artifact_refs),
      warnings: normalizeStringList(stage.warnings),
    })),
    current_status: oneOf<ProcessingStageStatus>(trace.current_status, PROCESSING_STAGE_STATUS_SET, "unknown"),
    warnings: normalizeStringList(trace.warnings),
  }));
}

function normalizeGoldMacroOverview(value: unknown): GoldMacroOverview | null {
  const item = asRecord(value);
  if (Object.keys(item).length === 0) return null;
  return {
    status: normalizeGoldStatus(item.status),
    asset: item.asset === "gold" ? "gold" : "XAUUSD",
    as_of: nullableString(item.as_of),
    phase: normalizeGoldPhase(item.phase),
    dominant_mainline: normalizeGoldMainline(item.dominant_mainline),
    priority_regime: nullableString(item.priority_regime) ?? undefined,
    priority_reason: nullableString(item.priority_reason) ?? undefined,
    net_bias: normalizeGoldNetBias(item.net_bias),
    risk_score: nullableNumber(item.risk_score),
    one_line_conclusion: stringValue(item.one_line_conclusion),
    theme_rankings: recordList(item.theme_rankings).map(normalizeGoldMainlineRanking),
    driver_conflict: normalizeDriverConflict(item.driver_conflict),
    war_oil_rate_chain: normalizeTransmissionChainSummary(item.war_oil_rate_chain),
    verification_matrix: recordList(item.verification_matrix).map(normalizeVerificationItem),
    mainline_requirements: recordList(item.mainline_requirements).map(normalizeMainlineRequirement),
    analysis_readiness: normalizeAnalysisReadiness(item.analysis_readiness),
    architecture_gaps: normalizeStringList(item.architecture_gaps),
    key_events: normalizeStringList(item.key_events),
    source_refs: normalizeSourceRefs(item.source_refs),
    artifact_refs: normalizeArtifactRefs(item.artifact_refs),
    processing_traces: normalizeProcessingTraceList(item.processing_traces),
    warnings: normalizeStringList(item.warnings),
  };
}

function unavailableMainlines(): GoldMainlinesViewModel {
  return {
    status: "unavailable",
    schema_version: "gold-event-mainlines-v1",
    asset: "XAUUSD",
    as_of: null,
    mainlines: [],
    event_links: [],
    dominant_forces: [],
    source_refs: [],
    artifact_refs: [],
    warnings: ["gold_event_mainlines artifact unavailable"],
  };
}

function normalizeGoldMainlinesViewModel(value: unknown): GoldMainlinesViewModel {
  const item = asRecord(value);
  if (Object.keys(item).length === 0) return unavailableMainlines();
  return {
    status: normalizeGoldStatus(item.status, "unavailable"),
    schema_version: normalizeSchemaVersion(item.schema_version),
    asset: item.asset === "gold" ? "gold" : "XAUUSD",
    as_of: nullableString(item.as_of),
    mainlines: recordList(item.mainlines).map(normalizeGoldMainlineRanking),
    event_links: recordList(item.event_links).map((link) => ({
      event_id: stringValue(link.event_id),
      mainline_ids: normalizeStringList(link.mainline_ids).map(normalizeGoldMainline).filter((mainline): mainline is GoldMainline => mainline !== null),
      primary_mainline: normalizeGoldMainline(link.primary_mainline),
      transmission_path_ids: normalizeStringList(link.transmission_path_ids).map(normalizeTransmissionPath),
      direction_by_asset: asRecord(link.direction_by_asset) as GoldMainlinesViewModel["event_links"][number]["direction_by_asset"],
      pricing_status: nullableString(link.pricing_status),
      verification_status: normalizeGoldVerificationStatus(link.verification_status),
      market_validation_ref: nullableString(link.market_validation_ref),
      bullish_drivers: normalizeStringList(link.bullish_drivers),
      bearish_drivers: normalizeStringList(link.bearish_drivers),
      dominant_driver: nullableString(link.dominant_driver),
      verification_needed: normalizeStringList(link.verification_needed),
      verification_chain: asRecord(link.verification_chain),
      changed_dominant_theme: link.changed_dominant_theme === true,
      source_refs: normalizeSourceRefs(link.source_refs),
      artifact_refs: normalizeArtifactRefs(link.artifact_refs),
    })),
    dominant_forces: normalizeStringList(item.dominant_forces).map(normalizeGoldMainline).filter((mainline): mainline is GoldMainline => mainline !== null),
    source_refs: normalizeSourceRefs(item.source_refs),
    artifact_refs: normalizeArtifactRefs(item.artifact_refs),
    warnings: normalizeStringList(item.warnings),
  };
}

function normalizeGoldMainlinesResponse(raw: RawGoldMainlinesResponse): GoldMainlinesResponse {
  return {
    status: normalizeGoldStatus(raw.status, "unavailable"),
    date: raw.date ?? null,
    run_id: raw.run_id ?? null,
    artifact_path: raw.artifact_path ?? null,
    schema_version: raw.schema_version ?? null,
    input_snapshot_ids: raw.input_snapshot_ids ?? {},
    gold_macro_overview: normalizeGoldMacroOverview(raw.gold_macro_overview),
    gold_mainlines: normalizeGoldMainlinesViewModel(raw.gold_mainlines),
    source_refs: normalizeSourceRefs(raw.source_refs),
    warnings: normalizeStringList(raw.warnings),
  };
}

export async function fetchGoldMainlinesLatest(): Promise<GoldMainlinesResponse> {
  const raw = await fetchJson<RawGoldMainlinesResponse>(GOLD_MAINLINES_LATEST_PATH);
  return normalizeGoldMainlinesResponse(raw);
}
