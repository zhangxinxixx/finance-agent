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
import { Calendar } from "lucide-react";

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

  return (
    <div className="finance-page-shell">
      <div className="dashboard-overview-grid">
        {/* Main content */}
        <div className="dashboard-overview-main">
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
