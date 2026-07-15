import { EmptyState as SharedEmptyState } from "@/components/shared/EmptyState";
import { ErrorState } from "@/components/shared/ErrorState";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";
import { MarketStateOverview } from "./MarketStateOverview";
import { CompactKPICard } from "./CompactKPICard";
import { DashboardAnalysisPanel } from "./DashboardAnalysisPanel";
import { buildDashboardKpiMetrics } from "./DashboardKpiModel";
import { CMEOptionsSummary } from "./CMEOptionsSummary";
import { DashboardRightPanel } from "./DashboardRightPanel";
import { buildIntegratedMacroSummary } from "./DashboardIntegratedMacroModel";
import { useDashboard } from "@/hooks/useDashboard";
import type { AppShellOutletContext } from "@/components/AppShell";
import { HeaderBreadcrumb } from "@/components/shared/HeaderBreadcrumb";
import { useEffect } from "react";
import { useOutletContext } from "react-router-dom";

function dashboardBiasLabel(direction: string | null | undefined): string {
  const value = (direction ?? "").toLowerCase();
  if (value === "bullish" || value === "偏多" || value === "看多") return "偏多";
  if (value === "bearish" || value === "偏空" || value === "看空") return "偏空";
  if (value === "neutral-bullish") return "中性偏多";
  if (value === "neutral-bearish") return "中性偏空";
  if (value === "mixed") return "混合";
  return "中性";
}

export function DashboardPage() {
  const dashboard = useDashboard();
  const shell = useOutletContext<AppShellOutletContext | null>() ?? { setHeaderContent: () => undefined };

  useEffect(() => {
    const summary = dashboard.data?.summary;
    if (!dashboard.data?.has_data || !summary) {
      shell.setHeaderContent(null);
      return;
    }

    const integrated = buildIntegratedMacroSummary(summary, dashboard.data.view_model);
    const strategyDirection = integrated.overallBias || dashboardBiasLabel(integrated.direction);
    const dataMode = integrated.dataCompleteness.label;
    const dominantDriver = integrated.dominantDrivers.slice(0, 2).join(" / ") || "待确认";

    shell.setHeaderContent(
      <HeaderBreadcrumb
        title="黄金宏观交易驾驶舱"
        meta={
          <>
            <span className="dashboard-header-summary-item">综合判断：{strategyDirection}</span>
            <span className="dashboard-header-summary-item">阶段：{integrated.macroRegime}</span>
            <span className="dashboard-header-summary-item">主导变量：{dominantDriver}</span>
            <span className="dashboard-header-summary-item dashboard-header-summary-status">{dataMode}</span>
          </>
        }
      />,
    );

    return () => shell.setHeaderContent(null);
  }, [dashboard.data, shell]);

  if (dashboard.isLoading && !dashboard.data) {
    return (
      <div className="finance-page-shell">
        <LoadingSkeleton variant="page" />
      </div>
    );
  }

  if (dashboard.isError || !dashboard.data) {
    return (
      <div className="finance-page-shell">
        <ErrorState message={dashboard.error?.message ?? "未知 Dashboard 错误"} onRetry={dashboard.refetch} />
      </div>
    );
  }

  if (!dashboard.data.has_data || dashboard.data.summary === null) {
    return (
      <div className="finance-page-shell">
        <SharedEmptyState title="该日期无分析数据" description="当前选择的交易日没有可用的 dashboard summary。请刷新页面或检查数据源。" />
      </div>
    );
  }

  const { summary } = dashboard.data;
  const { cme_options: options } = summary;
  const agentSummary = summary.agent_summary;
  const kpiMetrics = buildDashboardKpiMetrics(summary);

  return (
    <div className="finance-page-shell dashboard-page-shell">
      <div className="dashboard-overview-grid">
        {/* Main content */}
        <div className="dashboard-overview-main">
          {/* Market state overview */}
          <MarketStateOverview
            summary={summary}
            viewModel={dashboard.data.view_model}
          />

          {/* KPI Strip */}
          <div className="dashboard-kpi-strip">
            {kpiMetrics.map((m) => (
              <CompactKPICard
                key={m.label}
                label={m.label}
                value={m.value}
                delta={m.delta}
                trend={m.trend}
                unit={m.unit}
                sparkColor={m.sparkColor}
                accent={m.accent}
                subtitle={m.subtitle}
                impactLabel={m.impactLabel}
                dataStatus={m.dataStatus}
              />
            ))}
          </div>

          {/* Comprehensive analysis + CME Options */}
          <div className="dashboard-summary-grid">
            <DashboardAnalysisPanel
              summary={summary}
              viewModel={dashboard.data.view_model}
              agentSynthesis={agentSummary?.synthesis ?? null}
            />
            <div className="grid gap-2.5">
              <CMEOptionsSummary options={options} summary={summary} />
            </div>
          </div>
        </div>

        {/* Right panel */}
        <DashboardRightPanel summary={summary} />
      </div>
    </div>
  );
}

export default DashboardPage;
