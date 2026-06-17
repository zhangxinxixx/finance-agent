import { Link } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { EmptyState as SharedEmptyState } from "@/components/shared/EmptyState";
import { ErrorState } from "@/components/shared/ErrorState";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";
import { FACard } from "@/components/shared/FACard";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { DashboardComposite } from "@/components/dashboard/DashboardComposite";
import { useDashboard } from "@/hooks/useDashboard";

export function DashboardAnalysisPage() {
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
        <ErrorState
          title="综合分析详情加载失败"
          message={dashboard.error?.message ?? "未知 Dashboard 错误"}
          onRetry={dashboard.refetch}
        />
      </div>
    );
  }

  if (!dashboard.data.has_data || dashboard.data.summary === null) {
    return (
      <div className="finance-page-shell">
        <SharedEmptyState title="暂无综合分析详情" description="当前交易日没有可展示的 dashboard summary。" />
      </div>
    );
  }

  const { summary, view_model: viewModel } = dashboard.data;
  const dataDate = summary.cme_options.trade_date ?? viewModel?.trade_date ?? summary.generated_at?.slice(0, 10) ?? "—";

  return (
    <div className="finance-page-shell">
      <FACard
        title="综合分析详情"
        eyebrow="Dashboard Analysis"
        accent="warn"
        action={
          <div className="flex items-center gap-2">
            <FAStatusPill tone="info">{dataDate}</FAStatusPill>
            <Link
              to="/dashboard"
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
          当前页承接 Dashboard 主页面拆出的完整综合分析内容，包括结论、价位共振、交易剧本和改判条件。
        </div>
      </FACard>

      <DashboardComposite summary={summary} viewModel={viewModel} />
    </div>
  );
}

export default DashboardAnalysisPage;
