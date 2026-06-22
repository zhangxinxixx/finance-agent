import { ApiError, fetchJson } from "@/adapters/apiClient";
import { normalizeDataAvailability, normalizeDataStatus } from "@/lib/status";
import type { ArtifactRef } from "@/types/artifact";
import type { SourceRef } from "@/types/common";
import type { SnapshotRef } from "@/types/snapshot";
import type {
  StrategyCardRawResponse,
  StrategyAssetListRawResponse,
  StrategyAssetSummaryViewModel,
  StrategyCardsListRawResponse,
  StrategySourceTraceRawArtifactRef,
  StrategySourceTraceRawResponse,
  StrategySourceTraceRawSnapshotRef,
  StrategySourceTraceRawSourceRef,
  StrategySourceTraceViewModel,
  StrategyViewModel,
  StrategyHistoryItemViewModel,
} from "@/types/strategy";
import { mapStrategyResponse, mapHistoryItem, mapStrategyAssetSummary } from "@/types/strategy";

// ── Paths ──

const DEFAULT_STRATEGY_ASSET = "XAUUSD";
const STRATEGY_HISTORY_LIMIT = 60;

const STRATEGY_CARDS_LATEST_PATH = "/api/strategy-cards/latest";
const STRATEGY_CARDS_LIST_PATH = "/api/strategy-cards";
const STRATEGY_CARDS_ASSETS_PATH = "/api/strategy-cards/assets";
const STRATEGY_SOURCE_TRACE_PATH = "/api/source-trace/by-strategy";

function mapTraceSourceRef(source: StrategySourceTraceRawSourceRef): SourceRef {
  return {
    source_ref: source.source_name || source.source_id,
    label: source.source_name,
    endpoint: source.endpoint,
    artifact_path: source.file_path,
    trade_date: source.data_date,
    dataDate: source.data_date,
    asOf: source.captured_at,
    generated_at: source.captured_at,
    provider: source.source_type,
    source_url: source.url,
    status: normalizeDataStatus(source.status),
  };
}

function mapTraceArtifactRef(artifact: StrategySourceTraceRawArtifactRef): ArtifactRef {
  return {
    artifact_id: artifact.artifact_id,
    artifact_type: artifact.artifact_type,
    file_path: artifact.file_path,
    path: artifact.file_path,
    asOf: artifact.generated_at,
  };
}

function mapTraceSnapshotRef(snapshot: StrategySourceTraceRawSnapshotRef): SnapshotRef {
  return {
    snapshot_id: snapshot.snapshot_id,
    dataDate: snapshot.data_date ?? null,
    asOf: snapshot.created_at ?? null,
    run_id: snapshot.run_id ?? null,
    status: normalizeDataStatus(snapshot.data_status),
    availability: normalizeDataAvailability(snapshot.data_status),
    input_snapshot_ids: snapshot.input_snapshot_ids ?? [],
  };
}

function mapStrategySourceTrace(strategyCardId: string, raw: StrategySourceTraceRawResponse): StrategySourceTraceViewModel {
  return {
    target_type: "strategy",
    target_id: strategyCardId,
    status: normalizeDataStatus(raw.data_status),
    availability: normalizeDataAvailability(raw.data_status),
    run_id: raw.run_id ?? null,
    snapshot_id: raw.snapshot_id ?? null,
    dataDate: raw.snapshot?.data_date ?? null,
    asOf: raw.snapshot?.created_at ?? null,
    source_refs: (raw.source_refs ?? []).map(mapTraceSourceRef),
    artifact_refs: (raw.artifact_refs ?? []).map(mapTraceArtifactRef),
    input_snapshots: (raw.input_snapshots ?? []).map(mapTraceSnapshotRef),
    related_artifacts: (raw.related_artifacts ?? []).map(mapTraceArtifactRef),
    snapshot: raw.snapshot ? mapTraceSnapshotRef(raw.snapshot) : null,
    error_reason: null,
  };
}

async function fetchOptionalJson<T>(path: string): Promise<T | null> {
  try {
    return await fetchJson<T>(path);
  } catch (cause) {
    if (cause instanceof ApiError && cause.status === 404) {
      return null;
    }
    throw cause;
  }
}

function buildUnavailableStrategy(asset: string, reason: string): StrategyViewModel {
  return {
    status: "unavailable",
    source: "unavailable",
    asset,
    sample_size: 0,
    unavailable_reason: reason,
    updated_at: null,
    trade_date: null,
    hero: {
      status: "unavailable",
      bias: "",
      direction: "unknown",
      confidence: null,
      market_regime: undefined,
      trade_date: null,
      run_id: null,
      snapshot_id: null,
      source_refs: [],
    },
    scenario: null,
    module_signals: [],
    playbook_matches: [],
    source_refs: [],
    artifact_refs: [],
    source_trace: null,
    has_data: false,
    history: [],
    selected_strategy_card_id: null,
  };
}

// ── Plural read-model fetches ──

/** Fetch latest detail from plural endpoint. Returns null on failure. */
async function fetchLatestDetail(asset: string): Promise<StrategyViewModel | null> {
  try {
    const raw = await fetchJson<StrategyCardRawResponse>(`${STRATEGY_CARDS_LATEST_PATH}?asset=${encodeURIComponent(asset)}`);
    return mapStrategyResponse(raw, "api", asset);
  } catch {
    return null;
  }
}

/** Fetch history list from plural endpoint. Returns empty on failure. */
async function fetchHistoryList(asset: string, limit = STRATEGY_HISTORY_LIMIT): Promise<StrategyHistoryItemViewModel[]> {
  try {
    const raw = await fetchJson<StrategyCardsListRawResponse>(
      `${STRATEGY_CARDS_LIST_PATH}?asset=${encodeURIComponent(asset)}&limit=${limit}`,
    );
    return (raw.items ?? []).map(mapHistoryItem);
  } catch {
    return [];
  }
}

/** Fetch a single strategy card detail by id. Returns null on failure. */
export async function fetchStrategyCardById(
  strategyCardId: string,
  asset = DEFAULT_STRATEGY_ASSET,
): Promise<StrategyViewModel | null> {
  try {
    const raw = await fetchJson<StrategyCardRawResponse>(
      `${STRATEGY_CARDS_LIST_PATH}/${encodeURIComponent(strategyCardId)}?asset=${encodeURIComponent(asset)}`,
    );
    return mapStrategyResponse(raw, "api", asset);
  } catch {
    return null;
  }
}

/** Fetch discovered strategy assets with sample counts. Returns empty on failure. */
export async function fetchStrategyAssetSummaries(): Promise<StrategyAssetSummaryViewModel[]> {
  try {
    const raw = await fetchJson<StrategyAssetListRawResponse>(STRATEGY_CARDS_ASSETS_PATH);
    return (raw.items ?? []).map(mapStrategyAssetSummary);
  } catch {
    return [];
  }
}

/** Fetch source-trace drilldown for a strategy card. Returns null when the trace endpoint has no row yet. */
export async function fetchStrategySourceTraceByCardId(
  strategyCardId: string,
): Promise<StrategySourceTraceViewModel | null> {
  const raw = await fetchOptionalJson<StrategySourceTraceRawResponse>(
    `${STRATEGY_SOURCE_TRACE_PATH}/${encodeURIComponent(strategyCardId)}`,
  );
  if (!raw) {
    return null;
  }
  return mapStrategySourceTrace(strategyCardId, raw);
}

/**
 * Fetch full strategy overview: latest detail + history list.
 *
 * Strategy 页面只消费后端 StrategyCard read model：
 * 1. /api/strategy-cards/latest + /api/strategy-cards?asset=...&limit=60
 * 2. 若 latest 缺失但 history 非空，则按 history[0] 回查 detail
 * 3. 若 detail 仍缺失，则显式 unavailable，并保留 history 供校准视图消费
 */
export async function fetchStrategyCardsOverview(asset = DEFAULT_STRATEGY_ASSET): Promise<StrategyViewModel> {
  const requestedAsset = asset.trim() || DEFAULT_STRATEGY_ASSET;

  // Try plural endpoints in parallel
  const [detail, history] = await Promise.all([fetchLatestDetail(requestedAsset), fetchHistoryList(requestedAsset)]);

  if (detail) {
    return {
      ...detail,
      asset: detail.asset ?? requestedAsset,
      history,
      sample_size: history.length,
      unavailable_reason: null,
      selected_strategy_card_id:
        detail.selected_strategy_card_id ?? history[0]?.strategy_card_id ?? null,
    };
  }

  if (history.length > 0) {
    const latestHistoryId = history[0]?.strategy_card_id;
    if (latestHistoryId) {
      const historyDetail = await fetchStrategyCardById(latestHistoryId, requestedAsset);
      if (historyDetail) {
        return {
          ...historyDetail,
          asset: historyDetail.asset ?? requestedAsset,
          history,
          sample_size: history.length,
          unavailable_reason: null,
          selected_strategy_card_id:
            historyDetail.selected_strategy_card_id ?? latestHistoryId,
        };
      }
    }

    return {
      ...buildUnavailableStrategy(requestedAsset, "当前资产仅返回历史样本，最新 StrategyCard 详情缺失。"),
      source: "api",
      sample_size: history.length,
      history,
      selected_strategy_card_id: latestHistoryId ?? null,
    };
  }

  return buildUnavailableStrategy(requestedAsset, "当前资产暂无可用 StrategyCard read model");
}
