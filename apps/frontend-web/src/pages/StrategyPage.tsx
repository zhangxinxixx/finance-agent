import { useState } from "react";
import { Loader2 } from "lucide-react";
import { FAPageIntro } from "@/components/shared/FAPageIntro";
import { FAPageScaffold } from "@/components/shared/FAPageScaffold";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { FASourceTraceBadge } from "@/components/shared/FASourceTraceBadge";
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
import { formatDate, sourceLabel, sourceTone, statusTone, strategyValueLabel } from "@/components/strategy/strategyFormat";
import {
  DEFAULT_STRATEGY_ASSET,
  useStrategyPageState,
} from "@/hooks/useStrategyPageState";
import { useStrategy } from "@/hooks/useStrategy";

// ── Page ──

export function StrategyPage() {
  const [selectedAsset, setSelectedAsset] = useState<string>(DEFAULT_STRATEGY_ASSET);
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
      intro={(
        <FAPageIntro
          eyebrow="策略工作台"
          title="策略中心"
          description="汇总宏观、期权、事件与知识库信号，按资产、窗口和市场状态切换策略卡片与情景剧本。"
          meta={(
            <>
              <FASourceTraceBadge source={formatDate(data.updated_at ?? data.trade_date)} status="updated_at" tone="info" />
              <FASourceTraceBadge source={sourceLabel(data.source)} status="data_source" tone={sourceTone(data.source)} />
              <FASourceTraceBadge source={selectedAsset} status="asset" tone="info" />
              {selectedStrategyCardId ? (
                <span className="rounded-[var(--radius-sm)] border border-[var(--info-border)] bg-[var(--info-soft)] px-1.5 py-0.5 text-[9px] font-semibold text-[var(--info)]" title={selectedStrategyCardId}>
                  已选策略卡
                </span>
              ) : null}
            </>
          )}
          action={(
            <div className="flex flex-wrap items-center justify-end gap-2">
              <FAStatusPill tone={statusTone(data.status)}>{strategyValueLabel(data.status)}</FAStatusPill>
              <FAStatusPill tone={sourceTone(data.source)}>{sourceLabel(data.source)}</FAStatusPill>
              <FAStatusPill tone="info">{selectedAsset}</FAStatusPill>
            </div>
          )}
        />
      )}
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
          onRefresh={refetch}
        />
      )}
      bodyClassName="fa-page-stack"
    >
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

      <StrategyHeroSection hero={data.hero} asset={selectedAsset} sampleSize={data.sample_size} source={data.source} />

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
