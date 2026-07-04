import type { DataStatus, SourceRef } from "@/types/common";
import type { ArtifactRef } from "@/types/artifact";
import type { SignalDirection } from "@/types/dashboard";
import type { SourceTracePayload } from "@/types/source-trace";

/** Strategy Center — P1-07 MVP ViewModel 口径 */

export type StrategyModuleKey = "market" | "cme" | "event" | "knowledge";

export type StrategyModuleSignalStatus = "available" | "partial" | "unavailable" | "error";

export interface StrategyModuleSignal {
  module: StrategyModuleKey;
  label: string;
  status: StrategyModuleSignalStatus;
  summary?: string;
  source_refs: SourceRef[];
}

export interface StrategyPlaybookMatch {
  playbook_id: string;
  title: string;
  match_score: number;
  rule_id?: string;
  source_refs: SourceRef[];
}

export interface StrategyHeroViewModel {
  status: DataStatus;
  bias: string;
  direction: SignalDirection | "unknown";
  confidence: number | null;
  market_regime?: string;
  trade_date: string | null;
  run_id?: string | null;
  snapshot_id?: string | null;
  source_refs: SourceRef[];
}

export interface StrategyScenarioViewModel {
  main_scenario: string;
  alternative_scenarios: string[];
  key_levels: { resistance: number[]; support: number[] };
  trigger_conditions: string[];
  invalidation_conditions: string[];
  confirmation_conditions: string[];
  risk_points: string[];
  watchlist: string[];
}

export interface StrategyViewModel {
  status: DataStatus;
  source: "api" | "unavailable";
  asset: string;
  sample_size: number;
  unavailable_reason: string | null;
  updated_at?: string | null;
  trade_date: string | null;
  hero: StrategyHeroViewModel;
  scenario: StrategyScenarioViewModel | null;
  module_signals: StrategyModuleSignal[];
  playbook_matches: StrategyPlaybookMatch[];
  source_refs: SourceRef[];
  artifact_refs: ArtifactRef[];
  has_data: boolean;
  daily_update: StrategyDailyUpdateViewModel | null;
  weekend_context: StrategyWeekendContextViewModel | null;
  source_trace?: StrategySourceTraceViewModel | null;
  /** History list from /api/strategy-cards (P1-07b-2) */
  history: StrategyHistoryItemViewModel[];
  /** Currently selected strategy card id (null = latest) */
  selected_strategy_card_id?: string | null;
}

export interface StrategyDailyUpdateItemViewModel {
  title: string;
  priority: string;
  status: string;
  gold_impact?: string | null;
  summary?: string | null;
  source_url?: string | null;
}

export interface StrategyDailyUpdateViewModel {
  status: string;
  date: string | null;
  run_id: string | null;
  anchor_trade_date: string | null;
  queue_count: number;
  high_priority_count: number;
  source_artifact?: string | null;
  artifact_path?: string | null;
  as_of?: string | null;
  message: string;
  items: StrategyDailyUpdateItemViewModel[];
}

export interface StrategyWeekendReportRefViewModel {
  type?: string | null;
  trade_date?: string | null;
  run_id?: string | null;
  report_id?: string | null;
  title?: string | null;
  status?: string | null;
  summary?: string | null;
  anchor_trade_date?: string | null;
}

export interface StrategyWeekendOutlookViewModel {
  direction: string;
  summary: string;
  monday_open_bias: string;
  watch_points: string[];
  invalidation: string[];
}

export interface StrategyWeekendContextViewModel {
  status: string;
  mode: string;
  anchor_trade_date: string | null;
  anchor_run_id: string | null;
  latest_report_date: string | null;
  weekly_report: StrategyWeekendReportRefViewModel | null;
  recent_context: StrategyWeekendReportRefViewModel[];
  monday_outlook: StrategyWeekendOutlookViewModel;
  quality_flags: string[];
  message: string;
}

export type StrategySourceTraceViewModel = SourceTracePayload;

export interface StrategySourceTraceRawSourceRef {
  source_id: string;
  source_name: string;
  source_type: string;
  data_date?: string | null;
  endpoint?: string | null;
  captured_at?: string | null;
  file_path?: string | null;
  sha256?: string | null;
  url?: string | null;
  status?: string | null;
}

export interface StrategySourceTraceRawArtifactRef {
  artifact_id: string;
  artifact_type: string;
  file_path: string;
  storage_backend?: string | null;
  version?: string | null;
  generated_at?: string | null;
  sha256?: string | null;
}

export interface StrategySourceTraceRawSnapshotRef {
  snapshot_id: string;
  snapshot_type: string;
  data_date?: string | null;
  run_id?: string | null;
  data_status?: string | null;
  created_at?: string | null;
  input_snapshot_ids?: string[];
}

export interface StrategySourceTraceRawResponse {
  run_id?: string | null;
  snapshot_id?: string | null;
  data_status?: string | null;
  source_refs?: StrategySourceTraceRawSourceRef[];
  artifact_refs?: StrategySourceTraceRawArtifactRef[];
  snapshot?: StrategySourceTraceRawSnapshotRef | null;
  input_snapshots?: StrategySourceTraceRawSnapshotRef[];
  related_artifacts?: StrategySourceTraceRawArtifactRef[];
}

export interface StrategyAssetSummaryViewModel {
  asset: string;
  sample_size: number;
  latest_trade_date: string | null;
  latest_run_id: string | null;
  latest_snapshot_id: string | null;
  regime_counts: StrategyRegimeSummaryViewModel[];
}

export interface StrategyRegimeSummaryViewModel {
  market_regime: string;
  sample_size: number;
}

// ── Raw API Response Types ──

/** Hero block from GET /api/strategy-card/latest */
export interface StrategyCardRawHero {
  status?: string | null;
  bias?: string;
  direction?: string;
  confidence?: number | null;
  market_regime?: string;
  trade_date?: string | null;
  run_id?: string | null;
  snapshot_id?: string | null;
  source_refs?: SourceRef[];
}

/** Scenario block from strategy card raw response */
export interface StrategyCardRawScenario {
  main_scenario?: string;
  alternative_scenarios?: string[];
  key_levels?: { resistance?: number[]; support?: number[] };
  trigger_conditions?: string[];
  invalidation_conditions?: string[];
  confirmation_conditions?: string[];
  risk_points?: string[];
  watchlist?: string[];
}

/** Module signal entry from raw response */
export interface StrategyCardRawModuleSignal {
  module?: string;
  label?: string;
  status?: string;
  summary?: string;
  source_refs?: SourceRef[];
}

/** Playbook match entry from raw response */
export interface StrategyCardRawPlaybookMatch {
  playbook_id?: string;
  title?: string;
  match_score?: number;
  rule_id?: string;
  source_refs?: SourceRef[];
}

/**
 * Raw response shape from GET /api/strategy-card/latest
 * Fields are optional — backend may omit sections that are not yet generated.
 */
export interface StrategyCardRawResponse {
  asset?: string;
  status?: string | null;
  bias?: string;
  direction?: string;
  confidence?: number | null;
  market_regime?: string;
  updated_at?: string | null;
  trade_date?: string | null;
  strategy_card_id?: string | null;
  run_id?: string | null;
  snapshot_id?: string | null;
  json?: StrategyCardRawPayload | null;
  markdown?: string;
  paths?: {
    json?: string | null;
    markdown?: string | null;
  };
  hero?: StrategyCardRawHero;
  scenario?: StrategyCardRawScenario | null;
  module_signals?: StrategyCardRawModuleSignal[];
  playbook_matches?: StrategyCardRawPlaybookMatch[];
  source_refs?: SourceRef[];
  artifact_refs?: Array<ArtifactRef | string>;
  has_data?: boolean;
  daily_update?: StrategyDailyUpdateViewModel | null;
  weekend_context?: StrategyWeekendContextViewModel | null;
}

/** Current backend payload nested under StrategyCardRawResponse.json */
export interface StrategyCardRawPayload {
  bias?: string;
  confidence?: number | null;
  direction?: string;
  market_regime?: string;
  macro_phase?: string;
  scenario_summary?: string;
  main_scenario?: string;
  alternative_scenarios?: string[];
  key_levels?: { resistance?: number[]; support?: number[] };
  key_levels_from_options?: string[];
  trigger_conditions?: string[];
  triggers?: string[];
  invalidation_conditions?: string[];
  invalid_conditions?: string[];
  confirmation_conditions?: string[];
  risk_points?: string[];
  watchlist?: string[];
  source_refs?: SourceRef[];
  input_snapshot_ids?: Record<string, unknown> | string[] | null;
  created_at?: string | null;
  evidence_refs?: SourceRef[];
  data_quality?: string[];
}

// ── History list types (P1-07b-2) ──

/** Raw item from GET /api/strategy-cards list response */
export interface StrategyHistoryItemRaw {
  strategy_card_id?: string;
  asset?: string;
  trade_date?: string;
  run_id?: string;
  snapshot_id?: string | null;
  status?: string;
  bias?: string;
  confidence?: number | null;
  market_regime?: string;
  paths?: { json?: string | null; markdown?: string | null };
  source_refs?: SourceRef[];
  artifact_refs?: string[];
}

/** Raw response from GET /api/strategy-cards */
export interface StrategyCardsListRawResponse {
  asset?: string;
  count?: number;
  items?: StrategyHistoryItemRaw[];
}

/** Raw item from GET /api/strategy-cards/assets */
export interface StrategyAssetSummaryRaw {
  asset?: string;
  sample_size?: number;
  latest_trade_date?: string | null;
  latest_run_id?: string | null;
  latest_snapshot_id?: string | null;
  regime_counts?: StrategyRegimeSummaryRaw[];
}

export interface StrategyRegimeSummaryRaw {
  market_regime?: string;
  sample_size?: number;
}

/** Raw response from GET /api/strategy-cards/assets */
export interface StrategyAssetListRawResponse {
  count?: number;
  items?: StrategyAssetSummaryRaw[];
}

/** ViewModel for a single history entry in the strategy list */
export interface StrategyHistoryItemViewModel {
  strategy_card_id: string;
  asset: string;
  trade_date: string;
  run_id: string;
  snapshot_id: string | null;
  bias: string;
  confidence: number | null;
  market_regime: string | undefined;
  source_refs: SourceRef[];
  artifact_refs: string[];
}

// ── Source-Trace ──

/** Base path for strategy source-trace lookups (append /{strategy_card_id}) */
export const STRATEGY_SOURCE_TRACE_PATH = "/api/source-trace/by-strategy";

// ── Mapping helpers ──

function toDataStatus(raw?: string | null): DataStatus {
  switch (raw) {
    case "available":
    case "partial":
    case "unavailable":
    case "error":
      return raw;
    default:
      return "unavailable";
  }
}

function toModuleSignalStatus(raw?: string): StrategyModuleSignalStatus {
  switch (raw) {
    case "available":
    case "partial":
    case "unavailable":
    case "error":
      return raw;
    default:
      return "unavailable";
  }
}

function toDirection(raw?: string | null): SignalDirection | "unknown" {
  switch (raw) {
    case "bullish":
    case "bearish":
    case "neutral":
      return raw;
    default:
      return "unknown";
  }
}

function resolveDirection(...candidates: Array<string | null | undefined>): SignalDirection | "unknown" {
  for (const candidate of candidates) {
    const direction = toDirection(candidate);
    if (direction !== "unknown") return direction;
  }
  return "unknown";
}

function toModuleKey(raw?: string): StrategyModuleKey {
  switch (raw) {
    case "market":
    case "cme":
    case "event":
    case "knowledge":
      return raw;
    default:
      return "market";
  }
}

function mapHero(raw?: StrategyCardRawHero): StrategyHeroViewModel {
  return {
    status: toDataStatus(raw?.status),
    bias: raw?.bias ?? "",
    direction: resolveDirection(raw?.direction, raw?.bias),
    confidence: raw?.confidence ?? null,
    market_regime: raw?.market_regime,
    trade_date: raw?.trade_date ?? null,
    run_id: raw?.run_id ?? null,
    snapshot_id: raw?.snapshot_id ?? null,
    source_refs: raw?.source_refs ?? [],
  };
}

function mapLegacyHero(raw: StrategyCardRawResponse): StrategyHeroViewModel {
  const payload = raw.json ?? null;
  const sourceRefs = raw.source_refs ?? payload?.source_refs ?? [];
  const hasTopLevelStrategy = Boolean(raw.bias?.trim() || raw.direction || raw.confidence !== undefined || raw.market_regime);
  return {
    status: payload || hasTopLevelStrategy ? "available" : "unavailable",
    bias: payload?.bias ?? raw.bias ?? "",
    direction: resolveDirection(payload?.direction, raw.direction, payload?.bias, raw.bias),
    confidence: payload?.confidence ?? raw.confidence ?? null,
    market_regime: payload?.market_regime ?? payload?.macro_phase ?? raw.market_regime,
    trade_date: raw.trade_date ?? null,
    run_id: raw.run_id ?? null,
    snapshot_id: raw.snapshot_id ?? null,
    source_refs: sourceRefs,
  };
}

function parseLegacyKeyLevels(raw?: string[]): { resistance: number[]; support: number[] } {
  const values = (raw ?? [])
    .flatMap((item) => item.match(/\d+(?:\.\d+)?/g) ?? [])
    .map((item) => Number(item))
    .filter((item) => Number.isFinite(item));

  return {
    resistance: values,
    support: [],
  };
}

function mapLegacyScenario(raw: StrategyCardRawResponse): StrategyScenarioViewModel | null {
  const payload = raw.json ?? null;
  if (!payload) return null;
  return {
    main_scenario: payload.main_scenario ?? payload.scenario_summary ?? "",
    alternative_scenarios: payload.alternative_scenarios ?? [],
    key_levels: payload.key_levels
      ? {
          resistance: payload.key_levels.resistance ?? [],
          support: payload.key_levels.support ?? [],
        }
      : parseLegacyKeyLevels(payload.key_levels_from_options),
    trigger_conditions: payload.trigger_conditions ?? payload.triggers ?? [],
    invalidation_conditions: payload.invalidation_conditions ?? payload.invalid_conditions ?? [],
    confirmation_conditions: payload.confirmation_conditions ?? [],
    risk_points: payload.risk_points ?? [],
    watchlist: payload.watchlist ?? [],
  };
}

function mapScenario(raw?: StrategyCardRawScenario | null): StrategyScenarioViewModel | null {
  if (!raw) return null;
  return {
    main_scenario: raw.main_scenario ?? "",
    alternative_scenarios: raw.alternative_scenarios ?? [],
    key_levels: {
      resistance: raw.key_levels?.resistance ?? [],
      support: raw.key_levels?.support ?? [],
    },
    trigger_conditions: raw.trigger_conditions ?? [],
    invalidation_conditions: raw.invalidation_conditions ?? [],
    confirmation_conditions: raw.confirmation_conditions ?? [],
    risk_points: raw.risk_points ?? [],
    watchlist: raw.watchlist ?? [],
  };
}

function mapModuleSignals(raw?: StrategyCardRawModuleSignal[]): StrategyModuleSignal[] {
  if (!raw) return [];
  return raw.map((item) => ({
    module: toModuleKey(item.module),
    label: item.label ?? "",
    status: toModuleSignalStatus(item.status),
    summary: item.summary,
    source_refs: item.source_refs ?? [],
  }));
}

function mapPlaybookMatches(raw?: StrategyCardRawPlaybookMatch[]): StrategyPlaybookMatch[] {
  if (!raw) return [];
  return raw.map((item) => ({
    playbook_id: item.playbook_id ?? "",
    title: item.title ?? "",
    match_score: item.match_score ?? 0,
    rule_id: item.rule_id,
    source_refs: item.source_refs ?? [],
  }));
}

function mapArtifactRefs(raw?: Array<ArtifactRef | string>): ArtifactRef[] {
  if (!raw) return [];
  return raw.map((item) => {
    if (typeof item !== "string") return item;
    const filename = item.split("/").pop() ?? item;
    return {
      artifact_type: "strategy_card",
      title: filename,
      format: filename.endsWith(".md") ? "markdown" : filename.endsWith(".json") ? "json" : undefined,
      status: "available",
    } satisfies ArtifactRef;
  });
}

/** Map a single history list item to ViewModel */
export function mapHistoryItem(raw: StrategyHistoryItemRaw): StrategyHistoryItemViewModel {
  return {
    strategy_card_id: raw.strategy_card_id ?? "",
    asset: raw.asset ?? "",
    trade_date: raw.trade_date ?? "",
    run_id: raw.run_id ?? "",
    snapshot_id: raw.snapshot_id ?? null,
    bias: raw.bias ?? "",
    confidence: raw.confidence ?? null,
    market_regime: raw.market_regime,
    source_refs: raw.source_refs ?? [],
    artifact_refs: raw.artifact_refs ?? [],
  };
}

export function mapStrategyAssetSummary(raw: StrategyAssetSummaryRaw): StrategyAssetSummaryViewModel {
  return {
    asset: raw.asset ?? "",
    sample_size: raw.sample_size ?? 0,
    latest_trade_date: raw.latest_trade_date ?? null,
    latest_run_id: raw.latest_run_id ?? null,
    latest_snapshot_id: raw.latest_snapshot_id ?? null,
    regime_counts: (raw.regime_counts ?? [])
      .map((item) => ({
        market_regime: item.market_regime ?? "",
        sample_size: item.sample_size ?? 0,
      }))
      .filter((item) => Boolean(item.market_regime)),
  };
}

/** Map raw API response to StrategyViewModel (normalization only, no computation) */
export function mapStrategyResponse(
  raw: StrategyCardRawResponse,
  source: "api",
  assetOverride?: string,
): StrategyViewModel {
  const selectedId = raw.strategy_card_id ?? raw.run_id ?? raw.snapshot_id ?? null;
  const resolvedAsset = raw.asset ?? assetOverride ?? "XAUUSD";
  const hasExplicitReadModel =
    raw.hero !== undefined ||
    raw.scenario !== undefined ||
    raw.has_data !== undefined ||
    (Array.isArray(raw.module_signals) && raw.module_signals.length > 0) ||
    (Array.isArray(raw.playbook_matches) && raw.playbook_matches.length > 0);

  if (hasExplicitReadModel) {
    return {
      status: toDataStatus(raw.status),
      source,
      asset: resolvedAsset,
      sample_size: 0,
      unavailable_reason: null,
      updated_at: raw.updated_at ?? null,
      trade_date: raw.trade_date ?? null,
      hero: mapHero(raw.hero),
      scenario: mapScenario(raw.scenario),
      module_signals: mapModuleSignals(raw.module_signals),
      playbook_matches: mapPlaybookMatches(raw.playbook_matches),
      source_refs: raw.source_refs ?? [],
      artifact_refs: mapArtifactRefs(raw.artifact_refs),
      has_data: raw.has_data ?? false,
      daily_update: raw.daily_update ?? null,
      weekend_context: raw.weekend_context ?? null,
      history: [],
      selected_strategy_card_id: selectedId,
    };
  }

  if (raw.json || raw.markdown || raw.paths) {
    const sourceRefs = raw.source_refs ?? raw.json?.source_refs ?? [];
    const hasTopLevelStrategy = Boolean(raw.bias?.trim() || raw.direction || raw.confidence !== undefined || raw.market_regime);
    return {
      status: raw.status ? toDataStatus(raw.status) : raw.json || hasTopLevelStrategy ? "available" : "partial",
      source,
      asset: resolvedAsset,
      sample_size: 0,
      unavailable_reason: null,
      updated_at: raw.updated_at ?? raw.json?.created_at ?? null,
      trade_date: raw.trade_date ?? null,
      hero: mapLegacyHero(raw),
      scenario: mapLegacyScenario(raw),
      module_signals: mapModuleSignals(raw.module_signals),
      playbook_matches: mapPlaybookMatches(raw.playbook_matches),
      source_refs: sourceRefs,
      artifact_refs: mapArtifactRefs(raw.artifact_refs),
      has_data: Boolean(raw.json || raw.markdown),
      daily_update: raw.daily_update ?? null,
      weekend_context: raw.weekend_context ?? null,
      history: [],
      selected_strategy_card_id: selectedId,
    };
  }

  return buildEmptyStrategyReadModel(resolvedAsset, selectedId, raw.trade_date ?? null);
}

function buildEmptyStrategyReadModel(asset: string, selectedId: string | null, tradeDate: string | null): StrategyViewModel {
  return {
    status: "unavailable",
    source: "api",
    asset,
    sample_size: 0,
    unavailable_reason: null,
    updated_at: null,
    trade_date: tradeDate,
    hero: {
      status: "unavailable",
      bias: "",
      direction: "unknown",
      confidence: null,
      market_regime: undefined,
      trade_date: tradeDate,
      run_id: null,
      snapshot_id: null,
      source_refs: [],
    },
    scenario: null,
    module_signals: [],
    playbook_matches: [],
    source_refs: [],
    artifact_refs: [],
    has_data: false,
    daily_update: null,
    weekend_context: null,
    history: [],
    selected_strategy_card_id: selectedId,
  };
}
