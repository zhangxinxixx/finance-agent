import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  ReportDetailHero,
  ReportGenerationTraceCard,
  ReportGoldMacroOverviewCard,
  ReportMarketObservationCard,
} from "@/components/reports/ReportDetailSections";
import { FACard } from "@/components/shared/FACard";
import { FAEmptyState } from "@/components/shared/FAEmptyState";
import { FAWarningBanner } from "@/components/shared/FAWarningBanner";
import { ReportAnalysisInputsPanel } from "@/components/reports/ReportAnalysisInputsPanel";
import { ReportMarketOddsMatrix } from "@/components/reports/ReportMarketOddsMatrix";
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
  const qualityBlocked = data.data_status === "unavailable" && data.meta.lifecycle_status === "needs_review";
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
          tabs={qualityBlocked ? [] : tabOptions}
          activeTab={activeTab}
          onTabChange={setActiveTab}
          summaryChips={summaryChips}
        />

        {!qualityBlocked ? <ReportGoldMacroOverviewCard data={data} /> : null}
        {!qualityBlocked ? <ReportMarketOddsMatrix data={data} /> : null}
        {!qualityBlocked ? <ReportMarketObservationCard data={data} /> : null}
        <ReportGenerationTraceCard data={data} onTabChange={setActiveTab} />

        {qualityBlocked ? (
          <FAWarningBanner
            title="报告未通过质量审核"
            description="正文与图表没有识别出足够的可用证据，系统已停止展示降级分析稿。请修复解析或模型调用后重跑，再进入人工复核。"
            tone="down"
          />
        ) : null}

        {data.llm_audits.length > 0 ? (
          <section className="rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card)] p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <div className="text-[12px] font-semibold text-[var(--fg-2)]">LLM 调用审计</div>
                <div className="mt-1 text-[11px] text-[var(--fg-4)]">本报告关联 {data.llm_audits.length} 次 Gateway 调用；可查看实际配置、Prompt、输入、输出和重试链。</div>
              </div>
              <Link className="rounded-[var(--radius-md)] border border-[var(--border)] px-3 py-1.5 text-[11px] text-[var(--accent)]" to={`/settings/llm-audit?report_id=${encodeURIComponent(data.report_id)}`}>打开完整审计页 →</Link>
            </div>
            <div className="mt-3 grid gap-2 lg:grid-cols-2">
              {data.llm_audits.slice(0, 6).map((audit) => <Link key={audit.audit_id} to={`/settings/llm-audit?audit_id=${encodeURIComponent(audit.audit_id)}&report_id=${encodeURIComponent(data.report_id)}`} className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-3 py-2 text-[10px] text-[var(--fg-3)]"><div className="font-semibold">{audit.caller} · {audit.status}</div><div className="mt-1 text-[var(--fg-5)]">{audit.model_resolved ?? "-"} · Prompt {audit.prompt_char_count} 字符 · 输出 {audit.response_char_count} 字符 · {audit.created_at ?? "-"}</div></Link>)}
            </div>
          </section>
        ) : null}

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
          {qualityBlocked ? (
            <section className="rounded-[var(--radius-lg)] border border-[var(--down-border)] bg-[var(--down-soft)] p-4">
              <FAEmptyState title="本次报告不可用" description="失败产物仅保留用于审计，不作为正式报告展示。" />
            </section>
          ) : tabs.length > 0 ? (
            activeTab === "inputs" ? (
              <ReportAnalysisInputsPanel model={data.analysis_inputs} />
            ) : (
              <ReportArtifactPanel tab={currentTab} />
            )
          ) : (
            <section className="rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card)] p-4">
              <FAEmptyState title="暂无可用内容页签" description="后端未返回可展示的分析稿、来源稿、可视稿或证据包。" />
            </section>
          )}
        </div>
      </div>
    </div>
  );
}

export default ReportDetailPage;
