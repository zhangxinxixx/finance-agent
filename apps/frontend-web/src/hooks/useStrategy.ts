import { useEffect, useRef, useState, useCallback } from "react";
import { fetchStrategyAssetSummaries, fetchStrategyCardsOverview, fetchStrategyCardById } from "@/adapters/strategy";
import type { StrategyAssetSummaryViewModel, StrategyViewModel } from "@/types/strategy";

const DEFAULT_STRATEGY_ASSET = "XAUUSD";

interface StrategyState {
  data: StrategyViewModel | null;
  isLoading: boolean;
  isError: boolean;
  error: Error | null;
  selectedStrategyCardId: string | null;
  isDetailLoading: boolean;
  assetOptions: StrategyAssetSummaryViewModel[];
  selectStrategyCard: (id: string) => void;
  refetch: () => void;
}

export function useStrategy(asset = DEFAULT_STRATEGY_ASSET): StrategyState {
  const [data, setData] = useState<StrategyViewModel | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [isDetailLoading, setIsDetailLoading] = useState(false);
  const [assetOptions, setAssetOptions] = useState<StrategyAssetSummaryViewModel[]>([]);
  const [reloadToken, setReloadToken] = useState(0);

  // Keep a stable ref for cancellation in callbacks
  const mountedRef = useRef(true);
  const assetRef = useRef(asset);
  useEffect(() => {
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    assetRef.current = asset;
  }, [asset]);

  // Initial load: fetch overview (latest + history)
  useEffect(() => {
    let cancelled = false;

    async function load() {
      setIsLoading(true);
      setError(null);
      setIsDetailLoading(false);
      setData(null);
      setSelectedId(null);
      try {
        const [nextData, nextAssetOptions] = await Promise.all([
          fetchStrategyCardsOverview(asset),
          fetchStrategyAssetSummaries(),
        ]);
        if (!cancelled) {
          setData(nextData);
          setAssetOptions(nextAssetOptions);
          setSelectedId(nextData.selected_strategy_card_id ?? nextData.history[0]?.strategy_card_id ?? null);
        }
      } catch (cause) {
        if (!cancelled) {
          setData(null);
          setAssetOptions([]);
          setError(cause instanceof Error ? cause : new Error("加载策略数据失败"));
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    }

    void load();

    return () => {
      cancelled = true;
    };
  }, [asset, reloadToken]);

  // Select a specific strategy card by id
  const selectStrategyCard = useCallback(
    (id: string) => {
      if (!data) return;
      // If already selected, skip
      if (selectedId === id) return;

      const requestedAsset = assetRef.current;
      setSelectedId(id);
      setIsDetailLoading(true);

      fetchStrategyCardById(id, requestedAsset)
        .then((detail) => {
          if (!mountedRef.current || assetRef.current !== requestedAsset) return;
          if (detail) {
            setData((prev) => {
              if (!prev) return prev;
              return {
                ...detail,
                history: prev.history,
                selected_strategy_card_id: id,
                source: detail.source,
              };
            });
          }
          // If detail is null (fetch failed), keep current data unchanged
        })
        .catch(() => {
          // On error, keep current detail — don't clear history
        })
        .finally(() => {
          if (mountedRef.current && assetRef.current === requestedAsset) {
            setIsDetailLoading(false);
          }
        });
    },
    [data, selectedId],
  );

  return {
    data,
    isLoading,
    isError: error !== null,
    error,
    selectedStrategyCardId: selectedId,
    isDetailLoading,
    assetOptions,
    selectStrategyCard,
    refetch: () => setReloadToken((value) => value + 1),
  };
}

export default useStrategy;
