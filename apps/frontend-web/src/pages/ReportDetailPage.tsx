import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ReportDetailHero } from "@/components/reports/ReportDetailSections";
import { FACard } from "@/components/shared/FACard";
import { FAEmptyState } from "@/components/shared/FAEmptyState";
import { FAWarningBanner } from "@/components/shared/FAWarningBanner";
import { ReportAnalysisInputsPanel } from "@/components/reports/ReportAnalysisInputsPanel";
import { ReportArtifactPanel } from "@/components/reports/ReportArtifactPanel";
import { shortId } from "@/components/reports/reportDetailMeta";
import { useReportDetail } from "@/hooks/useReportDetail";
import type { ReportDetailTabKey } from "@/types/reports";

function reportTabLabel(tab: ReportDetailTabKey, fallback?: string | null): string {
  if (fallback) return fallback;
  if (tab === "analysis") return "分析稿";
  if (tab === "source") return "来源稿";
  if (tab === "visual") return "可视稿";
  if (tab === "evidence") return "证据包";
  return "分析输入";
}

export function ReportDetailPage() {
  const { reportId } = useParams<{ reportId: string }>();
  const { data, isLoading, error, refetch } = useReportDetail(reportId);
  const [activeTab, setActiveTab] = useState<ReportDetailTabKey>("analysis");

  const tabs = useMemo(
    () => data?.available_tabs ?? ([] as ReportDetailTabKey[]),
    [data?.available_tabs],
  );

  useEffect(() => {
    if (tabs.length === 0) return;
    if (!tabs.includes(activeTab)) {
      setActiveTab(tabs[0]);
    }
  }, [activeTab, tabs]);

  if (isLoading) {
    return (
      <div className="finance-page-shell">
        <div className="space-y-4">
          <div className="fa-card h-28 animate-pulse" />
          <div className="grid gap-3 lg:grid-cols-2 2xl:grid-cols-4">
            {Array.from({ length: 8 }).map((_, index) => (
              <div key={index} className="fa-card h-20 animate-pulse" />
            ))}
          </div>
          <div className="fa-card h-[480px] animate-pulse" />
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="finance-page-shell">
        <FACard title="报告详情加载失败" eyebrow="报告详情" accent="down">
          <FAWarningBanner
            title="标准详情页当前不可用"
            description={error?.message ?? "未知错误"}
            tone="down"
            action={
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={refetch}
                  className="rounded-[var(--radius-md)] border border-[var(--down-border)] px-3 py-1.5 text-[11px] font-semibold text-[var(--down)]"
                >
                  重试
                </button>
                <Link
                  to="/reports"
                  className="rounded-[var(--radius-md)] border border-[var(--border)] px-3 py-1.5 text-[11px] font-semibold text-[var(--fg-3)]"
                >
                  返回报告中心
                </Link>
              </div>
            }
          />
        </FACard>
      </div>
    );
  }

  const currentTab = activeTab === "inputs" ? null : data.tabs[activeTab] ?? null;
  const tabOptions = tabs.map((tab) => ({
    value: tab,
    label: reportTabLabel(tab, tab === "inputs" ? "分析输入" : data.tabs[tab]?.label),
  }));
  const metrics = [
    { label: "资产", value: data.meta.asset ?? "-" },
    { label: "日期", value: data.meta.trade_date ?? "-" },
    { label: "运行", value: shortId(data.meta.run_id) },
    { label: "快照", value: shortId(data.meta.snapshot_id) },
  ];
  const summaryChips =
    activeTab === "inputs" && data.analysis_inputs
      ? [
          `输入 ${data.analysis_inputs.deterministic_inputs.length}`,
          `输出 ${data.analysis_inputs.agent_outputs.length}`,
          `审查 ${data.analysis_inputs.fact_reviews.length}`,
          `综合 ${data.analysis_inputs.synthesis_outputs.length}`,
        ]
      : [];

  return (
    <div className="finance-page-shell">
      <div className="flex min-h-full flex-col gap-4">
        <ReportDetailHero
          data={data}
          metrics={metrics}
          onRefresh={refetch}
          tabs={tabOptions}
          activeTab={activeTab}
          onTabChange={setActiveTab}
          summaryChips={summaryChips}
        />

        {data.warnings.length > 0 ? (
          <div className="space-y-2">
            {data.warnings.map((warning) => (
              <FAWarningBanner
                key={`${warning.code}-${warning.message}`}
                title={warning.code}
                description={warning.message}
                tone="warn"
              />
            ))}
          </div>
        ) : null}

        <div className="min-h-0 flex-1">
          <div className="flex min-h-0 flex-col gap-4">
            <FACard
              title="报告产物工作台"
              eyebrow="报告产物"
              accent="info"
              className="flex min-h-[78vh] flex-col"
              bodyClassName="flex flex-1 flex-col gap-3"
            >
              {tabs.length > 0 ? (
                <div className="flex-1">
                  {activeTab === "inputs" ? (
                    <ReportAnalysisInputsPanel model={data.analysis_inputs} />
                  ) : (
                    <ReportArtifactPanel tab={currentTab} />
                  )}
                </div>
              ) : (
                <FAEmptyState title="暂无可用内容页签" description="后端未返回可展示的分析稿、来源稿、可视稿或证据包。" />
              )}
            </FACard>
          </div>
        </div>
      </div>
    </div>
  );
}

export default ReportDetailPage;
