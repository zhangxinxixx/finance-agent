import { Link, useLocation } from "react-router-dom";
import { useState } from "react";
import type { DashboardDataResponse } from "@/types/dashboard";
import { ArrowLeft } from "lucide-react";
import { EmptyState as SharedEmptyState } from "@/components/shared/EmptyState";
import { ErrorState } from "@/components/shared/ErrorState";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";
import { FACard } from "@/components/shared/FACard";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { DashboardComposite } from "@/components/dashboard/DashboardComposite";
import { useDashboard } from "@/hooks/useDashboard";
import { dashboardResearchDate } from "@/components/dashboard/DashboardIntegratedMacroModel";

export function DashboardAnalysisPage() {
  const location = useLocation();
  const [frozen, setFrozen] = useState<DashboardDataResponse | null>(() => location.state?.dashboardResult ?? null);
  const request = useDashboard(undefined, !frozen);
  const dashboard = frozen ? { ...request, data: frozen, isLoading: false, isError: false } : request;

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
        <ErrorState
          title="综合分析详情加载失败"
          message={dashboard.error?.message ?? "综合结果读取失败"}
          onRetry={dashboard.refetch}
        />
      </div>
    );
  }

  if (!dashboard.data.has_data || dashboard.data.summary === null) {
    return (
      <div className="finance-page-shell">
        <SharedEmptyState title="暂无综合分析详情" description="当前交易日没有可展示的综合研究结果。" />
      </div>
    );
  }

  const { summary, view_model: viewModel } = dashboard.data;
  const dataDate = dashboardResearchDate(summary, viewModel);

  return (
    <div className="finance-page-shell">
      <FACard
        title="综合分析详情"
        eyebrow="综合研究"
        accent="warn"
        action={
          <div className="flex items-center gap-2">
            <FAStatusPill tone="info">研究基线 {dataDate}</FAStatusPill>
            <FAStatusPill tone="dim">CME 公告 {summary.cme_options.trade_date || "未提供"}</FAStatusPill>
            <Link
              to="/dashboard"
              state={{ dashboardResult: dashboard.data }}
              className="inline-flex h-8 items-center gap-1.5 rounded-full border border-[var(--border)] bg-[var(--bg-card)] px-3 text-[11px] font-semibold text-[var(--fg-2)] transition-colors hover:border-[var(--border-strong)] hover:bg-[var(--bg-hover)]"
            >
              <ArrowLeft size={12} />
              返回总览
            </Link>
          </div>
        }
        bodyClassName="space-y-3"
      >
        <div className="text-[11px] leading-5 text-[var(--fg-4)]">
          本页展示已有综合分析及结构证据。研究基线与CME公告分别标时点；缺少情景或影响分析时不补造结论。
          {frozen ? " 当前沿用首页进入时的同一结果。" : null}
          <button type="button" className="ml-2 fa-label text-[var(--brand)]" onClick={() => { setFrozen(null); request.refetch(); }}>读取最新结果</button>
        </div>
      </FACard>

      <DashboardComposite summary={summary} viewModel={viewModel} dashboardResult={dashboard.data} />
    </div>
  );
}

export default DashboardAnalysisPage;
