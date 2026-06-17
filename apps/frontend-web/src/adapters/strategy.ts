import { fetchJson } from "@/adapters/apiClient";
import type {
  StrategyCardRawResponse,
  StrategyAssetListRawResponse,
  StrategyAssetSummaryViewModel,
  StrategyCardsListRawResponse,
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
