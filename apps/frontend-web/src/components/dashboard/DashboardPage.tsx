import { EmptyState as SharedEmptyState } from "@/components/shared/EmptyState";
import { ErrorState } from "@/components/shared/ErrorState";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";
import { JudgmentBanner } from "./JudgmentBanner";
import { CompactKPICard } from "./CompactKPICard";
import { DashboardAnalysisPanel } from "./DashboardAnalysisPanel";
import { buildDashboardKpiMetrics } from "./DashboardKpiModel";
import { CMEOptionsSummary } from "./CMEOptionsSummary";
import { DashboardRightPanel } from "./DashboardRightPanel";
import { useDashboard } from "@/hooks/useDashboard";
import { isWeekend, getLatestTradeDate } from "@/lib/date";
import { Calendar, RefreshCw } from "lucide-react";

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
  const strategyDirection = dashboardBiasLabel(summary.strategy.direction);
  const reportReadyCount = summary.latest_reports.filter((item) => item.status === "ready").length;

  return (
    <div className="finance-page-shell">
      <div className="dashboard-overview-grid">
        {/* Main content */}
        <div className="dashboard-overview-main">
          <section className="dashboard-command-strip">
            <div className="min-w-0">
              <div className="text-[9px] font-semibold uppercase tracking-[0.14em] text-[var(--fg-5)]">实时总览</div>
              <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-[var(--fg-4)]">
                <span className="font-semibold text-[var(--fg-2)]">黄金分析驾驶舱</span>
                <span className="text-[var(--fg-6)]">/</span>
                <span>偏向 {strategyDirection}</span>
                <span className="text-[var(--fg-6)]">/</span>
                <span>{reportReadyCount} 份可读报告</span>
              </div>
            </div>
            <button
              type="button"
              onClick={dashboard.refetch}
              className="dashboard-command-button"
              title="刷新总览数据"
            >
              <RefreshCw size={13} />
              <span>刷新</span>
            </button>
          </section>

          {/* Weekend mode banner */}
          {isWeekend() ? (
            <div
              className="flex items-center gap-2 rounded-[var(--radius-sm)] px-3 py-1.5"
              style={{ background: "rgba(59,130,246,0.06)", border: "1px solid rgba(59,130,246,0.15)" }}
            >
              <Calendar size={12} color="#3b82f6" />
              <span className="text-[10px] font-medium text-[#3b82f6]">
                周末模式 — 市场数据展示最近交易日（{getLatestTradeDate()}），新闻事件实时更新
              </span>
            </div>
          ) : null}

          {/* Judgment Banner */}
          <JudgmentBanner
            summary={summary}
            viewModel={dashboard.data.view_model}
            agentCoordinator={agentSummary?.coordinator ?? null}
            agentSynthesis={agentSummary?.synthesis ?? null}
          />

          {/* KPI Strip: 6 columns */}
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
            <CMEOptionsSummary options={options} />
          </div>
        </div>

        {/* Right panel */}
        <DashboardRightPanel summary={summary} />
      </div>
    </div>
  );
}

export default DashboardPage;
