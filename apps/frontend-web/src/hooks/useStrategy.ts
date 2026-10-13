import { useEffect, useRef, useState, useCallback } from "react";
import {
  fetchStrategyAssetSummaries,
  fetchStrategyCardById,
  fetchStrategyCardsOverview,
  fetchStrategySourceTraceByCardId,
} from "@/adapters/strategy";
import { mapStrategyResponse, type StrategyAssetSummaryViewModel, type StrategyViewModel } from "@/types/strategy";

const DEFAULT_STRATEGY_ASSET = "XAUUSD";
const STRATEGY_OVERVIEW_REFRESH_MS = 15 * 60_000;

interface StrategyState {
  data: StrategyViewModel | null;
  isLoading: boolean;
  isError: boolean;
  error: Error | null;
  selectedStrategyCardId: string | null;
  isDetailLoading: boolean;
  detailError: Error | null;
  isTraceLoading: boolean;
  traceError: Error | null;
  assetOptions: StrategyAssetSummaryViewModel[];
  selectStrategyCard: (id: string) => void;
  refetch: () => void;
}

interface SelectionKey {
  asset: string;
  id: string;
  generation: number;
}

export function useStrategy(asset = DEFAULT_STRATEGY_ASSET, traceEnabled = true): StrategyState {
  const [data, setData] = useState<StrategyViewModel | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [isDetailLoading, setIsDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<Error | null>(null);
  const [isTraceLoading, setIsTraceLoading] = useState(false);
  const [traceError, setTraceError] = useState<Error | null>(null);
  const [assetOptions, setAssetOptions] = useState<StrategyAssetSummaryViewModel[]>([]);
  const [stateAsset, setStateAsset] = useState(asset);
  const [reloadToken, setReloadToken] = useState(0);
  const [selectionGeneration, setSelectionGeneration] = useState(0);

  const mountedRef = useRef(true);
  const dataRef = useRef<StrategyViewModel | null>(null);
  const assetRef = useRef(asset);
  const selectedIdRef = useRef<string | null>(null);
  const latestStrategyCardIdRef = useRef<string | null>(null);
  const historyPinnedRef = useRef(false);
  const generationRef = useRef(0);
  const traceGenerationRef = useRef(0);
  const traceEnabledRef = useRef(traceEnabled);
  const detailPendingRef = useRef(false);
  const detailErrorRef = useRef<Error | null>(null);
  // Reject old asset responses even before the new asset's effects run.
  assetRef.current = asset;
  traceEnabledRef.current = traceEnabled;

  const commitData = (next: StrategyViewModel | null) => {
    dataRef.current = next;
    setData(next);
  };
  const isCurrentSelection = (key: SelectionKey) => mountedRef.current
    && assetRef.current === key.asset
    && selectedIdRef.current === key.id
    && generationRef.current === key.generation;

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      generationRef.current += 1;
      traceGenerationRef.current += 1;
    };
  }, []);

  useEffect(() => {
    setStateAsset(asset);
    generationRef.current += 1;
    traceGenerationRef.current += 1;
    selectedIdRef.current = null;
    latestStrategyCardIdRef.current = null;
    historyPinnedRef.current = false;
    detailPendingRef.current = false;
    detailErrorRef.current = null;
    commitData(null);
    setSelectedId(null);
    setSelectionGeneration(generationRef.current);
    setIsDetailLoading(false);
    setDetailError(null);
    setIsTraceLoading(false);
    setTraceError(null);
  }, [asset]);

  // Overview refresh may update history, but cannot replace a selected detail
  // or clear its error/loading/trace state while that request is in progress.
  useEffect(() => {
    let cancelled = false;
    const requestedGeneration = generationRef.current;
    async function load() {
      setIsLoading(true);
      setError(null);
      try {
        const [nextData, nextAssetOptions] = await Promise.all([
          fetchStrategyCardsOverview(asset),
          fetchStrategyAssetSummaries(),
        ]);
        if (cancelled || !mountedRef.current || assetRef.current !== asset) return;
        setAssetOptions(nextAssetOptions);
        const latestId = nextData.selected_strategy_card_id ?? nextData.history[0]?.strategy_card_id ?? null;
        latestStrategyCardIdRef.current = latestId;
        if (selectedIdRef.current && (historyPinnedRef.current || detailPendingRef.current
          || detailErrorRef.current || generationRef.current !== requestedGeneration)) {
          const previous = dataRef.current;
          if (previous) commitData({ ...previous, history: nextData.history, sample_size: nextData.sample_size });
        } else {
          generationRef.current += 1;
          traceGenerationRef.current += 1;
          commitData({ ...nextData, source_trace: null });
          selectedIdRef.current = latestId;
          setSelectedId(latestId);
          setSelectionGeneration(generationRef.current);
          setIsTraceLoading(false);
          setTraceError(null);
        }
      } catch (cause) {
        if (!cancelled && mountedRef.current && assetRef.current === asset && !dataRef.current) {
          commitData(null);
          setAssetOptions([]);
          setError(cause instanceof Error ? cause : new Error("加载策略数据失败"));
        }
      } finally {
        if (!cancelled && mountedRef.current && assetRef.current === asset) setIsLoading(false);
      }
    }
    void load();
    return () => { cancelled = true; };
  }, [asset, reloadToken]);

  useEffect(() => {
    const intervalId = window.setInterval(() => {
      setReloadToken((value) => value + 1);
    }, STRATEGY_OVERVIEW_REFRESH_MS);
    return () => window.clearInterval(intervalId);
  }, [asset]);

  const selectedSnapshotId = data?.selected_strategy_card_id === selectedId ? data.hero.snapshot_id : null;
  const selectedRunId = data?.selected_strategy_card_id === selectedId ? data.hero.run_id : null;
  useEffect(() => {
    const traceGeneration = ++traceGenerationRef.current;
    const key = { asset, id: selectedId ?? "", generation: selectionGeneration };
    let cancelled = false;
    const isCurrentTrace = () => !cancelled && isCurrentSelection(key)
      && traceEnabledRef.current && traceGenerationRef.current === traceGeneration;
    // Evidence must wait for the matching body; history metadata alone is not
    // a license to attach a trace to a pending or failed detail.
    if (!traceEnabled || !selectedId || !selectedSnapshotId || isDetailLoading || detailError) {
      setIsTraceLoading(false);
      setTraceError(null);
      if (dataRef.current?.source_trace) commitData({ ...dataRef.current, source_trace: null });
      return () => { cancelled = true; };
    }
    setIsTraceLoading(true);
    setTraceError(null);
    if (dataRef.current?.source_trace) commitData({ ...dataRef.current, source_trace: null });
    fetchStrategySourceTraceByCardId(selectedId, { run_id: selectedRunId, snapshot_id: selectedSnapshotId })
      .then((trace) => {
        if (!isCurrentTrace()) return;
        if (trace && ((trace.target_id && trace.target_id !== key.id)
          || (trace.run_id && selectedRunId && trace.run_id !== selectedRunId)
          || (trace.snapshot_id && trace.snapshot_id !== selectedSnapshotId))) {
          throw new Error("策略依据身份核验失败：响应与所选记录不匹配。");
        }
        const previous = dataRef.current;
        if (previous?.selected_strategy_card_id === key.id) commitData({ ...previous, source_trace: trace });
      })
      .catch((cause) => {
        if (!isCurrentTrace()) return;
        setTraceError(cause instanceof Error ? cause : new Error("加载策略溯源失败"));
        if (dataRef.current) commitData({ ...dataRef.current, source_trace: null });
      })
      .finally(() => { if (isCurrentTrace()) setIsTraceLoading(false); });
    return () => { cancelled = true; };
  }, [asset, selectedId, selectionGeneration, traceEnabled, selectedSnapshotId, selectedRunId, isDetailLoading, detailError]);

  const selectStrategyCard = useCallback((id: string) => {
    const previous = dataRef.current;
    if (!mountedRef.current || !previous || previous.asset !== assetRef.current) return;
    if (selectedIdRef.current === id && (detailPendingRef.current || !detailErrorRef.current)) return;
    const key = { asset: assetRef.current, id, generation: ++generationRef.current };
    const expected = previous.history.find((item) => item.strategy_card_id === id);
    historyPinnedRef.current = id !== latestStrategyCardIdRef.current;
    selectedIdRef.current = id;
    traceGenerationRef.current += 1;
    detailPendingRef.current = true;
    detailErrorRef.current = null;
    setSelectedId(id);
    setSelectionGeneration(key.generation);
    setIsDetailLoading(true);
    setDetailError(null);
    setIsTraceLoading(false);
    setTraceError(null);
    // Clear all body/identity/evidence fields synchronously with selection,
    // retaining only the independent history list and its denominator.
    commitData({
      ...mapStrategyResponse({ asset: key.asset, strategy_card_id: id }, "api"),
      history: previous.history,
      sample_size: previous.sample_size,
    });
    fetchStrategyCardById(id, key.asset, expected)
      .then((detail) => {
        if (!isCurrentSelection(key)) return;
        if (!detail) throw new Error("所选策略详情读取失败，请重试。");
        // The adapter checks explicit raw card ID before normalization; a
        // legacy model may expose run/snapshot as its selected-ID fallback.
        const allowedIds = [id, expected?.run_id, expected?.snapshot_id].filter(Boolean);
        const identityMatches = allowedIds.includes(detail.selected_strategy_card_id)
          || (!detail.selected_strategy_card_id && Boolean(
            (expected?.run_id && detail.hero.run_id === expected.run_id)
            || (expected?.snapshot_id && detail.hero.snapshot_id === expected.snapshot_id)));
        if (detail.asset !== key.asset || !identityMatches
          || (expected?.run_id && detail.hero.run_id && expected.run_id !== detail.hero.run_id)
          || (expected?.snapshot_id && detail.hero.snapshot_id && expected.snapshot_id !== detail.hero.snapshot_id)) {
          throw new Error("策略详情身份核验失败：响应与所选记录不匹配。");
        }
        const current = dataRef.current;
        if (!current) return;
        commitData({ ...detail, history: current.history, sample_size: current.sample_size,
          selected_strategy_card_id: id, source_trace: null });
      })
      .catch((cause) => {
        if (!isCurrentSelection(key)) return;
        const nextError = cause instanceof Error ? cause : new Error("加载策略详情失败");
        detailErrorRef.current = nextError;
        setDetailError(nextError);
      })
      .finally(() => {
        if (!isCurrentSelection(key)) return;
        detailPendingRef.current = false;
        setIsDetailLoading(false);
      });
  }, []);

  const contextMatches = stateAsset === asset;
  const assetMatches = contextMatches && data?.asset === asset;
  return {
    data: assetMatches ? data : null,
    isLoading: !contextMatches || Boolean(data && !assetMatches) || isLoading,
    isError: contextMatches && error !== null,
    error: contextMatches ? error : null,
    selectedStrategyCardId: assetMatches ? selectedId : null,
    isDetailLoading: assetMatches && isDetailLoading,
    detailError: assetMatches ? detailError : null,
    isTraceLoading: assetMatches && isTraceLoading,
    traceError: assetMatches ? traceError : null,
    assetOptions,
    selectStrategyCard,
    refetch: () => setReloadToken((value) => value + 1),
  };
}

export default useStrategy;
