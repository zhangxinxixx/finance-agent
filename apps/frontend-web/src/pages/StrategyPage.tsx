import { useState } from "react";
import { Loader2 } from "lucide-react";
import { FACard } from "@/components/shared/FACard";
import { FASectionHeader } from "@/components/shared/FASectionHeader";
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
  const { data, isLoading, isError, error, selectedStrategyCardId, isDetailLoading, assetOptions, selectStrategyCard, refetch } = useStrategy(selectedAsset);
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
    <div className="finance-page-shell">
      {/* Hero */}
      <FACard title="策略中心" eyebrow="策略工作台" accent="brand" bodyClassName="space-y-4">
        <FASectionHeader
          title="策略卡片数据聚合与情景分析"
          description="汇总宏观、期权、事件、知识库各模块信号，生成策略卡片与剧本模板匹配。"
          action={
            <div className="flex items-center gap-2">
              <FAStatusPill tone={statusTone(data.status)}>{strategyValueLabel(data.status)}</FAStatusPill>
              <FAStatusPill tone={sourceTone(data.source)}>{sourceLabel(data.source)}</FAStatusPill>
              <FAStatusPill tone="info">{selectedAsset}</FAStatusPill>
            </div>
          }
        />
        <div className="flex flex-wrap items-center gap-2">
          <FASourceTraceBadge source={formatDate(data.updated_at ?? data.trade_date)} status="updated_at" tone="info" />
          <FASourceTraceBadge source={sourceLabel(data.source)} status="data_source" tone={sourceTone(data.source)} />
          <FASourceTraceBadge source={selectedAsset} status="asset" tone="info" />
          {selectedStrategyCardId ? (
            <span className="rounded-[var(--radius-sm)] border border-[var(--info-border)] bg-[var(--info-soft)] px-1.5 py-0.5 text-[9px] font-semibold text-[var(--info)]" title={selectedStrategyCardId}>
              已选策略卡
            </span>
          ) : null}
        </div>
      </FACard>

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

      {/* History list */}
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

      {/* Detail loading indicator */}
      {isDetailLoading ? (
        <div className="finance-panel flex items-center gap-2 p-3 text-[11px] text-[var(--fg-4)]">
          <Loader2 className="h-3.5 w-3.5 animate-spin text-[var(--brand)]" />
          <span>正在加载策略详情...</span>
        </div>
      ) : null}

      {/* Hero section */}
      <StrategyHeroSection hero={data.hero} asset={selectedAsset} sampleSize={data.sample_size} source={data.source} />

      {/* Scenario */}
      {data.scenario ? <StrategyScenarioSection scenario={data.scenario} /> : null}

      {/* Module Signals + Playbook side by side */}
      <div className="grid gap-3 lg:grid-cols-2">
        <StrategyModuleSignalsSection signals={data.module_signals} />
        <StrategyPlaybookMatchesSection matches={data.playbook_matches} />
      </div>

      {/* Data Trace */}
      <StrategyDataTraceSection data={data} />
    </div>
  );
}

export default StrategyPage;
