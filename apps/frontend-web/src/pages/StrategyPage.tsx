import { useState } from "react";
import { Loader2 } from "lucide-react";
import { DataModeBanner, type DataMode } from "@/components/shared/DataModeBanner";
import { FAPageScaffold } from "@/components/shared/FAPageScaffold";
import { StrategyFilterBar } from "@/components/strategy/StrategyFilterBar";
import { StrategyCalibrationPanel, StrategyHistoryListSection } from "@/components/strategy/StrategyHistoryCalibration";
import {
  StrategyPageErrorState,
  StrategyPageLoadingState,
} from "@/components/strategy/StrategyPageStates";
import { StrategyHeroSection } from "@/components/strategy/StrategyHeroSection";
import { StrategyScenarioSection } from "@/components/strategy/StrategyScenarioSection";
import { StrategyModuleSignalsSection, StrategyPlaybookMatchesSection } from "@/components/strategy/StrategySignalsPanels";
import { StrategyDataTraceSection } from "@/components/strategy/StrategyTracePanel";
import { LiveStrategyWorkspace } from "@/components/strategy/LiveStrategyWorkspace";
import { ShadowEvaluationPanel } from "@/components/strategy/ShadowEvaluationPanel";
import {
  DEFAULT_STRATEGY_ASSET,
  useStrategyPageState,
} from "@/hooks/useStrategyPageState";
import { useStrategy } from "@/hooks/useStrategy";
import { useLiveStrategy } from "@/hooks/useLiveStrategy";
import { useLatestShadowEvaluation } from "@/hooks/useShadowEvaluation";
import { useShadowEvaluationHistory } from "@/hooks/useShadowEvaluationHistory";
import { ShadowEvaluationHistoryPanel } from "@/components/strategy/ShadowEvaluationHistoryPanel";

// ── Page ──

function strategyDataMode(source: string, status: string): DataMode {
  if (source === "unavailable") return "unavailable";
  const value = status.toLowerCase();
  if (value === "available" || value === "live") return "live";
  if (value === "partial" || value === "stale") return "partial";
  if (value === "error" || value === "unavailable") return "unavailable";
  return "fallback";
}

export function StrategyPage() {
  const [selectedAsset, setSelectedAsset] = useState<string>(DEFAULT_STRATEGY_ASSET);
  const liveStrategy = useLiveStrategy(selectedAsset === "XAUUSD" ? "XAUUSD" : null);
  const shadowEvaluation = useLatestShadowEvaluation(selectedAsset === "XAUUSD");
  const shadowEvaluationHistory = useShadowEvaluationHistory(selectedAsset === "XAUUSD");
  const {
    data,
    isLoading,
    isError,
    error,
    selectedStrategyCardId,
    isDetailLoading,
    isTraceLoading,
    traceError,
    assetOptions,
    selectStrategyCard,
    refetch,
  } = useStrategy(selectedAsset);
  const {
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
  } = useStrategyPageState(selectedAsset, assetOptions, data?.history ?? []);
  const unavailableReason = data?.unavailable_reason ?? null;

  if (isLoading && !data) {
    return <StrategyPageLoadingState />;
  }

  if (isError || !data) {
    return <StrategyPageErrorState message={error?.message ?? "未知错误"} onRetry={refetch} />;
  }

  return (
    <FAPageScaffold
      toolbar={(
        <StrategyFilterBar
          assetTabs={assetTabs}
          selectedAsset={selectedAsset}
          onAssetChange={setSelectedAsset}
          selectedWindow={selectedWindow}
          onWindowChange={setSelectedWindow}
          regimeTabs={regimeTabs}
          activeRegime={activeRegime}
          onRegimeChange={setSelectedRegime}
          onRefresh={() => {
            refetch();
            liveStrategy.refetch();
            shadowEvaluation.refetch();
            shadowEvaluationHistory.refetch();
          }}
        />
      )}
      bodyClassName="fa-page-stack strategy-page-body"
    >
      <DataModeBanner
        mode={strategyDataMode(data.source, data.status)}
        reason={data.unavailable_reason ?? "每日 StrategyCard 与 live_strategy.v1 独立取数；实时链路降级时不会由前端补造。"}
      />

      {selectedAsset === "XAUUSD" ? (
        <>
          <LiveStrategyWorkspace
            data={liveStrategy.data}
            isLoading={liveStrategy.isLoading}
            error={liveStrategy.error}
          />
          <ShadowEvaluationPanel
            data={shadowEvaluation.data}
            isLoading={shadowEvaluation.isLoading}
            isUnavailable={shadowEvaluation.isUnavailable}
            error={shadowEvaluation.error}
          />
          <ShadowEvaluationHistoryPanel
            data={shadowEvaluationHistory.data}
            isLoading={shadowEvaluationHistory.isLoading}
            isUnavailable={shadowEvaluationHistory.isUnavailable}
            error={shadowEvaluationHistory.error}
          />
        </>
      ) : null}

      <StrategyHeroSection
        hero={data.hero}
        scenario={data.scenario}
        dailyUpdate={data.daily_update}
        weekendContext={data.weekend_context}
        asset={selectedAsset}
        sampleSize={data.sample_size}
        source={data.source}
        updatedAt={data.updated_at}
      />

      <div className="fa-page-grid lg:grid-cols-[minmax(0,1.2fr)_minmax(320px,0.8fr)]">
        <StrategyHistoryListSection
          items={visibleHistory}
          selectedId={selectedStrategyCardId}
          onSelect={selectStrategyCard}
          isDetailLoading={isDetailLoading}
          sampleSize={data.sample_size}
          windowLabel={selectedWindowLabel}
          regimeLabel={selectedRegimeLabel}
        />

        <StrategyCalibrationPanel
          asset={selectedAsset}
          sampleSize={data.sample_size}
          visibleCount={visibleHistory.length}
          windowLabel={selectedWindowLabel}
          regimeLabel={selectedRegimeLabel}
          regimeCounts={selectedAssetSummary?.regime_counts ?? []}
          status={data.status}
          unavailableReason={unavailableReason}
        />
      </div>

      {isDetailLoading ? (
        <div className="finance-panel flex items-center gap-2 p-3 text-[11px] text-[var(--fg-4)]">
          <Loader2 className="h-3.5 w-3.5 animate-spin text-[var(--brand)]" />
          <span>正在加载策略详情...</span>
        </div>
      ) : null}

      {data.scenario ? <StrategyScenarioSection scenario={data.scenario} /> : null}

      <div className="grid gap-3 lg:grid-cols-2">
        <StrategyModuleSignalsSection signals={data.module_signals} />
        <StrategyPlaybookMatchesSection matches={data.playbook_matches} />
      </div>

      <StrategyDataTraceSection data={data} isTraceLoading={isTraceLoading} traceError={traceError} />
    </FAPageScaffold>
  );
}

export default StrategyPage;
