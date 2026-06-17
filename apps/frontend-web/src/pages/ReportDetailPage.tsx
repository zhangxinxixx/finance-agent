import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ReportDetailHero, ReportDetailSourceSidebar } from "@/components/reports/ReportDetailSections";
import { FACard } from "@/components/shared/FACard";
import { FAEmptyState } from "@/components/shared/FAEmptyState";
import { FASourceTraceBadge } from "@/components/shared/FASourceTraceBadge";
import { FATabBar } from "@/components/shared/FATabBar";
import { FAWarningBanner } from "@/components/shared/FAWarningBanner";
import { ReportAnalysisInputsPanel } from "@/components/reports/ReportAnalysisInputsPanel";
import { ReportArtifactPanel } from "@/components/reports/ReportArtifactPanel";
import { reportFamilyLabel, shortId } from "@/components/reports/reportDetailMeta";
import { useReportDetail } from "@/hooks/useReportDetail";
import type { ReportDetailTabKey } from "@/types/reports";

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
  const sourceRefs = data.source_trace?.source_refs?.length ? data.source_trace.source_refs : data.source_refs;
  const tabOptions = tabs.map((tab) => ({
    value: tab,
    label: tab === "inputs" ? "分析输入" : data.tabs[tab]?.label ?? tab,
  }));
  const metrics = [
    { label: "报告族", value: reportFamilyLabel(data.meta.family) },
    { label: "资产", value: data.meta.asset ?? "-" },
    { label: "日期", value: data.meta.trade_date ?? "-" },
    { label: "运行", value: shortId(data.meta.run_id) },
    { label: "快照", value: shortId(data.meta.snapshot_id) },
    { label: "截至", value: data.meta.asOf ?? "-" },
    { label: "产物数", value: String(data.meta.artifact_count) },
    { label: "输入数", value: String(data.meta.input_snapshot_ids.length) },
  ];

  return (
    <div className="finance-page-shell">
      <div className="flex min-h-full flex-col gap-4">
        <ReportDetailHero data={data} sourceRefs={sourceRefs} metrics={metrics} onRefresh={refetch} />

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

        <div className="grid min-h-0 flex-1 gap-4 2xl:grid-cols-[minmax(0,1.6fr)_340px]">
          <div className="flex min-h-0 flex-col gap-4">
            <FACard
              title="报告产物工作台"
              eyebrow="报告产物"
              accent="info"
              className="flex min-h-0 flex-col"
              bodyClassName="min-h-0 flex flex-1 flex-col gap-4"
            >
              {tabs.length > 0 ? (
                <FATabBar tabs={tabOptions} value={activeTab} onChange={setActiveTab} ariaLabel="报告产物切换" />
              ) : (
                <FAEmptyState title="暂无可用内容页签" description="后端未返回可展示的分析稿、来源稿、可视稿或证据包。" />
              )}

              {activeTab === "inputs" && data.analysis_inputs ? (
                <div className="flex flex-wrap items-center gap-2 text-[11px] text-[var(--fg-4)]">
                  {data.analysis_inputs.source_endpoint ? (
                    <FASourceTraceBadge source={data.analysis_inputs.source_endpoint} status="analysis-inputs" tone="info" />
                  ) : null}
                  <FASourceTraceBadge source={`${data.analysis_inputs.deterministic_inputs.length} deterministic`} status="inputs" tone="dim" />
                  <FASourceTraceBadge source={`${data.analysis_inputs.agent_outputs.length} agent outputs`} status="outputs" tone="dim" />
                  <FASourceTraceBadge source={`${data.analysis_inputs.fact_reviews.length} fact reviews`} status="reviews" tone="dim" />
                  <FASourceTraceBadge source={`${data.analysis_inputs.synthesis_outputs.length} synthesis`} status="synthesis" tone="dim" />
                </div>
              ) : null}

              {currentTab ? (
                <div className="flex flex-wrap items-center gap-2 text-[11px] text-[var(--fg-4)]">
                  <FASourceTraceBadge source={currentTab.source_endpoint} status={currentTab.format} tone="info" />
                  {currentTab.path ? <FASourceTraceBadge source={currentTab.path} status="path" tone="dim" /> : null}
                </div>
              ) : null}

              <div className="min-h-0 flex-1">
                {activeTab === "inputs" ? (
                  <ReportAnalysisInputsPanel model={data.analysis_inputs} />
                ) : (
                  <ReportArtifactPanel tab={currentTab} />
                )}
              </div>
            </FACard>
          </div>

          <div className="flex min-h-0 flex-col gap-4">
            <ReportDetailSourceSidebar data={data} sourceRefs={sourceRefs} />
          </div>
        </div>
      </div>
    </div>
  );
}

export default ReportDetailPage;
