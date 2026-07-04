import { useEffect, useMemo, useState } from "react";
import type { FATabOption } from "@/components/shared/FATabBar";
import { strategyValueLabel } from "@/components/strategy/strategyFormat";
import type { StrategyAssetSummaryViewModel, StrategyHistoryItemViewModel } from "@/types/strategy";

export type StrategyWindowKey = "7d" | "30d" | "90d" | "all";

export const DEFAULT_STRATEGY_ASSET = "XAUUSD";
export const STRATEGY_REGIME_ALL = "all";

const KNOWN_STRATEGY_ASSETS: FATabOption[] = [
  { value: "XAUUSD", label: "XAUUSD" },
  { value: "BTCUSD", label: "BTCUSD" },
  { value: "EURUSD", label: "EURUSD" },
  { value: "DXY", label: "DXY" },
  { value: "US10Y", label: "US10Y" },
];

export const STRATEGY_WINDOW_TABS: FATabOption<StrategyWindowKey>[] = [
  { value: "7d", label: "7D" },
  { value: "30d", label: "30D" },
  { value: "90d", label: "90D" },
  { value: "all", label: "全部" },
];

export function useStrategyPageState(
  selectedAsset: string,
  assetOptions: StrategyAssetSummaryViewModel[],
  history: StrategyHistoryItemViewModel[],
) {
  const [selectedWindow, setSelectedWindow] = useState<StrategyWindowKey>("30d");
  const [selectedRegime, setSelectedRegime] = useState<string>(STRATEGY_REGIME_ALL);

  useEffect(() => {
    setSelectedWindow("30d");
    setSelectedRegime(STRATEGY_REGIME_ALL);
  }, [selectedAsset]);

  const assetTabs = useMemo(() => {
    const tabs = buildAssetTabs(assetOptions);
    if (selectedAsset && !tabs.some((tab) => tab.value === selectedAsset)) {
      tabs.push({ value: selectedAsset, label: selectedAsset, count: 0 });
    }
    return tabs;
  }, [assetOptions, selectedAsset]);

  const selectedAssetSummary = useMemo(
    () => assetOptions.find((item) => item.asset === selectedAsset) ?? null,
    [assetOptions, selectedAsset],
  );

  const historyInWindow = useMemo(
    () => filterHistoryByWindow(history, selectedWindow),
    [history, selectedWindow],
  );

  const regimeTabs = useMemo(() => {
    const items = uniqueRegimes(historyInWindow);
    const tabs: FATabOption<string>[] = [{ value: STRATEGY_REGIME_ALL, label: "全部", count: historyInWindow.length }];
    tabs.push(
      ...items.map((regime) => ({
        value: regime,
        label: strategyValueLabel(regime),
        count: historyInWindow.filter((item) => item.market_regime?.trim() === regime).length,
      })),
    );
    return tabs;
  }, [historyInWindow]);

  useEffect(() => {
    if (!regimeTabs.some((tab) => tab.value === selectedRegime)) {
      setSelectedRegime(STRATEGY_REGIME_ALL);
    }
  }, [regimeTabs, selectedRegime]);

  const activeRegime = regimeTabs.some((tab) => tab.value === selectedRegime) ? selectedRegime : STRATEGY_REGIME_ALL;
  const visibleHistory = useMemo(
    () =>
      activeRegime === STRATEGY_REGIME_ALL
        ? historyInWindow
        : historyInWindow.filter((item) => item.market_regime?.trim() === activeRegime),
    [activeRegime, historyInWindow],
  );

  const selectedWindowLabel = (STRATEGY_WINDOW_TABS.find((tab) => tab.value === selectedWindow)?.label ?? selectedWindow) as string;
  const selectedRegimeLabel = activeRegime === STRATEGY_REGIME_ALL ? "全部" : strategyValueLabel(activeRegime);

  return {
    selectedWindow,
    setSelectedWindow,
    setSelectedRegime,
    assetTabs,
    selectedAssetSummary,
    regimeTabs,
    activeRegime,
    visibleHistory,
    selectedWindowLabel,
    selectedRegimeLabel,
  };
}

function buildAssetTabs(assetOptions: StrategyAssetSummaryViewModel[]): FATabOption<string>[] {
  const optionMap = new Map(assetOptions.map((item) => [item.asset, item]));
  const tabs = KNOWN_STRATEGY_ASSETS.flatMap((asset) => {
    const matched = optionMap.get(asset.value);
    if (!matched || matched.sample_size <= 0) return [];
    return [{
      value: asset.value,
      label: asset.label,
      count: matched.sample_size,
    }];
  });

  for (const item of assetOptions) {
    if (tabs.some((tab) => tab.value === item.asset)) continue;
    if (item.sample_size <= 0) continue;
    tabs.push({
      value: item.asset,
      label: item.asset,
      count: item.sample_size,
    });
  }

  return tabs;
}

function parseTradeDate(value: string): number | null {
  const date = new Date(`${value}T00:00:00Z`);
  const timestamp = date.getTime();
  return Number.isFinite(timestamp) ? timestamp : null;
}

function filterHistoryByWindow(items: StrategyHistoryItemViewModel[], window: StrategyWindowKey): StrategyHistoryItemViewModel[] {
  if (window === "all") return items;
  const days = window === "7d" ? 7 : window === "30d" ? 30 : 90;
  const cutoff = new Date();
  cutoff.setHours(0, 0, 0, 0);
  cutoff.setDate(cutoff.getDate() - days + 1);
  const cutoffValue = cutoff.getTime();
  return items.filter((item) => {
    const itemValue = parseTradeDate(item.trade_date);
    return itemValue !== null && itemValue >= cutoffValue;
  });
}

function uniqueRegimes(items: StrategyHistoryItemViewModel[]): string[] {
  return Array.from(new Set(items.map((item) => item.market_regime?.trim()).filter((item): item is string => Boolean(item)))).sort((a, b) => a.localeCompare(b));
}
