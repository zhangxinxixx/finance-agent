import { useEffect, useRef, useState, useCallback } from "react";
import {
  fetchStrategyAssetSummaries,
  fetchStrategyCardById,
  fetchStrategyCardsOverview,
  fetchStrategySourceTraceByCardId,
} from "@/adapters/strategy";
import type { StrategyAssetSummaryViewModel, StrategyViewModel } from "@/types/strategy";

const DEFAULT_STRATEGY_ASSET = "XAUUSD";

interface StrategyState {
  data: StrategyViewModel | null;
  isLoading: boolean;
  isError: boolean;
  error: Error | null;
  selectedStrategyCardId: string | null;
  isDetailLoading: boolean;
  isTraceLoading: boolean;
  traceError: Error | null;
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
  const [isTraceLoading, setIsTraceLoading] = useState(false);
  const [traceError, setTraceError] = useState<Error | null>(null);
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
      setIsTraceLoading(false);
      setTraceError(null);
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

  useEffect(() => {
    if (!selectedId) {
      setIsTraceLoading(false);
      setTraceError(null);
      return;
    }

    const selectedSnapshotId = data?.selected_strategy_card_id === selectedId
      ? data.hero.snapshot_id
      : data?.history.find((item) => item.strategy_card_id === selectedId)?.snapshot_id;
    if (!selectedSnapshotId) {
      setIsTraceLoading(false);
      setTraceError(null);
      setData((prev) => (prev ? { ...prev, source_trace: null } : prev));
      return;
    }

    let cancelled = false;
    const requestedAsset = assetRef.current;

    setIsTraceLoading(true);
    setTraceError(null);

    fetchStrategySourceTraceByCardId(selectedId)
      .then((trace) => {
        if (cancelled || !mountedRef.current || assetRef.current !== requestedAsset) return;
        setData((prev) => {
          if (!prev || prev.selected_strategy_card_id !== selectedId) return prev;
          return {
            ...prev,
            source_trace: trace,
          };
        });
      })
      .catch((cause) => {
        if (cancelled || !mountedRef.current || assetRef.current !== requestedAsset) return;
        setTraceError(cause instanceof Error ? cause : new Error("加载策略溯源失败"));
        setData((prev) => (prev ? { ...prev, source_trace: null } : prev));
      })
      .finally(() => {
        if (!cancelled && mountedRef.current && assetRef.current === requestedAsset) {
          setIsTraceLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  // Select a specific strategy card by id
  const selectStrategyCard = useCallback(
    (id: string) => {
      if (!data) return;
      // If already selected, skip
      if (selectedId === id) return;

      const requestedAsset = assetRef.current;
      setSelectedId(id);
      setIsDetailLoading(true);
      setTraceError(null);
      setData((prev) => (prev ? { ...prev, source_trace: null } : prev));

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
                source_trace: prev.source_trace ?? null,
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
    isTraceLoading,
    traceError,
    assetOptions,
    selectStrategyCard,
    refetch: () => setReloadToken((value) => value + 1),
  };
}

export default useStrategy;
