import { useState } from "react";
import { useLocation } from "react-router-dom";
import { Loader2 } from "lucide-react";
import { FAPageScaffold } from "@/components/shared/FAPageScaffold";
import { FATabBar, type FATabOption } from "@/components/shared/FATabBar";
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
import { LiveStrategyDiagnostics, LiveStrategyTrustNotice, LiveStrategyWorkspace } from "@/components/strategy/LiveStrategyWorkspace";
import { LiveStrategyQualificationNotice, LiveStrategyScenarios } from "@/components/strategy/LiveStrategyScenarios";
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
import { LegacyStrategyIdentityNotice, ResultIdentityBar } from "@/components/shared/ResultIdentityBar";
import { hasVerifiedGoldBaseline } from "@/types/live-strategy";
import { getLiveStrategyQualification, getLiveStrategyTrustState, isLiveStrategyMarketUsable } from "@/components/strategy/liveStrategyTrust";
import {
  readStrategyNavigationState,
  StrategyEvaluationScopeNotice,
  StrategySourceNotice,
} from "@/components/strategy/StrategyEntryContext";
import { readingErrorMessage } from "@/components/reading/readingFormat";

// ── Page ──

type StrategyView = "current" | "daily" | "history" | "evaluation" | "evidence";

const STRATEGY_VIEW_TABS: FATabOption<StrategyView>[] = [
  { value: "current", label: "当前策略" },
  { value: "daily", label: "日度研究" },
  { value: "history", label: "策略历史" },
  { value: "evaluation", label: "表现评估" },
  { value: "evidence", label: "数据证据" },
];

export function StrategyPage() {
  const location = useLocation();
  const [selectedAsset, setSelectedAsset] = useState<string>(DEFAULT_STRATEGY_ASSET);
  const [activeView, setActiveView] = useState<StrategyView>("current");
  const strategyNavigation = readStrategyNavigationState(location.state);
  const liveStrategy = useLiveStrategy(selectedAsset === "XAUUSD" ? "XAUUSD" : null);
  const shadowEvaluation = useLatestShadowEvaluation(activeView === "evaluation" && selectedAsset === "XAUUSD");
  const shadowEvaluationHistory = useShadowEvaluationHistory(activeView === "evaluation" && selectedAsset === "XAUUSD");
  const {
    data,
    isLoading,
    isError,
    error,
    selectedStrategyCardId,
    isDetailLoading,
    detailError,
    isTraceLoading,
    traceError,
    assetOptions,
    selectStrategyCard,
    refetch,
  } = useStrategy(selectedAsset, activeView === "evidence");
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
  const hasVerifiedLiveGoldBaseline = liveStrategy.data
    ? hasVerifiedGoldBaseline(liveStrategy.data.data_quality.gold_baseline)
    : false;
  const liveStrategyTrustState = getLiveStrategyTrustState({
    isLoading: liveStrategy.isLoading,
    error: liveStrategy.error,
  });
  const liveStrategyDataGateBlocked = liveStrategy.data
    ? liveStrategy.data.status !== "available"
      || !liveStrategy.data.feasibility.data_ready
      || !isLiveStrategyMarketUsable(liveStrategy.data.live_market)
    : true;
  const liveQualification = liveStrategy.data
    ? getLiveStrategyQualification(liveStrategy.data, liveStrategyTrustState, hasVerifiedLiveGoldBaseline)
    : null;

  if (isLoading && !data) {
    return <StrategyPageLoadingState />;
  }

  if (isError || !data) {
    return <StrategyPageErrorState message={readingErrorMessage(error, "策略页面加载失败，请稍后重试。")} onRetry={refetch} />;
  }

  return (
    <FAPageScaffold
      toolbar={assetTabs.length > 1 ? (
        <StrategyFilterBar
          assetTabs={assetTabs}
          selectedAsset={selectedAsset}
          onAssetChange={setSelectedAsset}
          selectedWindow={selectedWindow}
          onWindowChange={setSelectedWindow}
          regimeTabs={regimeTabs}
          activeRegime={activeRegime}
          onRegimeChange={setSelectedRegime}
          showHistoryFilters={false}
          onRefresh={() => {
            refetch();
            liveStrategy.refetch();
            shadowEvaluation.refetch();
            shadowEvaluationHistory.refetch();
          }}
        />
      ) : undefined}
      bodyClassName="fa-page-stack strategy-page-body"
    >
      {strategyNavigation ? (
        <StrategySourceNotice
          navigation={strategyNavigation}
          currentIdentity={liveStrategy.data?.result_identity}
        />
      ) : null}
      <nav className="strategy-view-nav" aria-label="策略页面内容分页">
        <FATabBar tabs={STRATEGY_VIEW_TABS} value={activeView} onChange={setActiveView} ariaLabel="策略页面分页" />
      </nav>

      {activeView === "current" && selectedAsset === "XAUUSD" ? (
        <>
          <ResultIdentityBar
            identity={liveStrategy.data?.result_identity}
            subjectLabel="策略所用正式结果"
            baselineLabel="当前有效黄金日结基线"
          />
          <LiveStrategyWorkspace
            data={liveStrategy.data}
            isLoading={liveStrategy.isLoading}
            error={liveStrategy.error}
            tradeDate={data.hero.trade_date ?? data.trade_date}
            dailyUpdatedAt={data.updated_at}
            onRefresh={() => {
              refetch();
              liveStrategy.refetch();
            }}
          />
        </>
      ) : null}

      {activeView !== "current" ? <LegacyStrategyIdentityNotice /> : null}

      {(activeView === "daily" || activeView === "history" || activeView === "evidence") && (isDetailLoading || detailError) ? (
        <div className="finance-panel p-3 text-[length:var(--type-body-sm)] text-[var(--fg-3)]" role="status" aria-live="polite">
          {isDetailLoading ? <span>正在加载所选策略详情，正文与依据等待同一记录核验。</span> : (
            <><p>{readingErrorMessage(detailError, "所选策略详情读取失败，请重试。")}</p><button type="button" className="mt-2 text-[var(--brand)]" onClick={() => selectedStrategyCardId && selectStrategyCard(selectedStrategyCardId)}>重试所选记录</button></>
          )}
        </div>
      ) : null}

      {activeView === "daily" ? (
        <section className="strategy-tab-panel" aria-label="日度研究">
          {liveStrategy.data ? (
            <LiveStrategyTrustNotice
              trustState={liveStrategyTrustState}
              error={liveStrategy.error}
              lastResultAt={liveStrategy.data.updated_at}
              dataGateBlocked={liveStrategyDataGateBlocked}
            />
          ) : null}
          {liveStrategy.data && liveQualification ? (
            <LiveStrategyQualificationNotice qualification={liveQualification} recordedStatus={liveStrategy.data.strategy_status} activeScenario={liveStrategy.data.active_scenario} />
          ) : null}
          {liveStrategy.data && liveQualification ? (
            <LiveStrategyScenarios
              activeScenario={liveStrategy.data.active_scenario}
              setups={liveStrategy.data.setups}
              noTrade={liveStrategy.data.no_trade}
              dataBlocked={liveQualification.blocked}
              strategyStatus={liveQualification.displayStatus}
              qualification={liveQualification}
            />
          ) : null}
          {!isDetailLoading && !detailError ? (
            <>
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
              {data.scenario ? <StrategyScenarioSection scenario={data.scenario} /> : null}
              <div className="grid gap-3 lg:grid-cols-2">
                <StrategyModuleSignalsSection signals={data.module_signals} />
                <StrategyPlaybookMatchesSection matches={data.playbook_matches} />
              </div>
            </>
          ) : null}
        </section>
      ) : null}

      {activeView === "history" ? (
        <section className="strategy-tab-panel" aria-label="策略历史">
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
            showAssetTabs={false}
            showRefresh={false}
          />
          <div className="fa-page-grid lg:grid-cols-[minmax(0,1.2fr)_minmax(320px,0.8fr)]">
            <StrategyHistoryListSection items={visibleHistory} selectedId={selectedStrategyCardId} onSelect={selectStrategyCard} isDetailLoading={isDetailLoading} sampleSize={data.sample_size} windowLabel={selectedWindowLabel} regimeLabel={selectedRegimeLabel} />
            <StrategyCalibrationPanel asset={selectedAsset} sampleSize={data.sample_size} visibleCount={visibleHistory.length} windowLabel={selectedWindowLabel} regimeLabel={selectedRegimeLabel} regimeCounts={selectedAssetSummary?.regime_counts ?? []} status={data.status} unavailableReason={unavailableReason} />
          </div>
          {isDetailLoading ? (
            <div className="finance-panel flex items-center gap-2 p-3 text-[length:var(--type-caption)] text-[var(--fg-4)]">
              <Loader2 className="h-3.5 w-3.5 animate-spin text-[var(--brand)]" />
              <span>正在加载策略详情...</span>
            </div>
          ) : null}
        </section>
      ) : null}

      {activeView === "evaluation" ? (
        <section className="strategy-tab-panel" aria-label="表现评估">
          <StrategyEvaluationScopeNotice
            evaluationDate={shadowEvaluation.data?.trade_date}
            currentStrategyDate={data.hero.trade_date ?? data.trade_date}
          />
          <ShadowEvaluationPanel data={shadowEvaluation.data} isLoading={shadowEvaluation.isLoading} isUnavailable={shadowEvaluation.isUnavailable} error={shadowEvaluation.error} />
          <ShadowEvaluationHistoryPanel data={shadowEvaluationHistory.data} isLoading={shadowEvaluationHistory.isLoading} isUnavailable={shadowEvaluationHistory.isUnavailable} error={shadowEvaluationHistory.error} />
        </section>
      ) : null}

      {activeView === "evidence" ? (
        <section className="strategy-tab-panel" aria-label="数据证据">
          {liveStrategy.data ? (
            <LiveStrategyTrustNotice
              trustState={liveStrategyTrustState}
              error={liveStrategy.error}
              lastResultAt={liveStrategy.data.updated_at}
              dataGateBlocked={liveStrategyDataGateBlocked}
            />
          ) : null}
          <LiveStrategyDiagnostics data={liveStrategy.data} />
          {!isDetailLoading && !detailError ? <StrategyDataTraceSection data={data} isTraceLoading={isTraceLoading} traceError={traceError} /> : null}
        </section>
      ) : null}
    </FAPageScaffold>
  );
}

export default StrategyPage;
