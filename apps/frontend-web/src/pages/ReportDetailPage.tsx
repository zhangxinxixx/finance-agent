import { ResearchIdentity } from "@/components/shared/ResearchIdentity";
import { ResearchTradePlanCard } from "@/components/shared/ResearchTradePlanCard";
import { readableWarning, uniqueReading } from "@/lib/researchReading";
import { ResearchDetails } from "@/components/shared/ResearchDetails";
import { useEffect, useMemo, useState } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import {
  ReportGoldMacroOverviewCard,
  ReportDetailHero,
  ReportGenerationTraceCard,
  ReportMarketObservationCard,
} from "@/components/reports/ReportDetailSections";
import { FACard } from "@/components/shared/FACard";
import { FAEmptyState } from "@/components/shared/FAEmptyState";
import { FAWarningBanner } from "@/components/shared/FAWarningBanner";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { ReportMarketOddsMatrix } from "@/components/reports/ReportMarketOddsMatrix";
import { ReportArtifactPanel } from "@/components/reports/ReportArtifactPanel";
import { ResultIdentityBar } from "@/components/shared/ResultIdentityBar";
import { getReportDetailStatus, reportNeedsReadingWarning, reportSelectionDifference } from "@/components/reports/reportDetailMeta";
import { isObservationReport, reportAssetLabel } from "@/components/reports/reportListMeta";
import { useReportDetail } from "@/hooks/useReportDetail";
import type { ReportDetailTabKey } from "@/types/reports";
import { reportsReturnTarget } from "@/components/reports/reportsNavigation";
import { auditStatusLabel, auditStatusTone, callerLabel, modelDisplayLabel } from "@/components/llm-audit/llmAuditFormat";
import { readingErrorMessage } from "@/components/reading/readingFormat";

function reportTabLabel(tab: ReportDetailTabKey, fallback?: string | null): string {
  if (fallback) return fallback;
  if (tab === "analysis") return "分析稿";
  if (tab === "source") return "来源稿";
  if (tab === "visual") return "可视稿";
  if (tab === "evidence") return "证据包";
  return "报告内容";
}

function currentMarketContextLines(value: Record<string, unknown>): string[] {
  return ["independent_context", "summary", "quality_status", "status", "as_of", "generated_at"]
    .map((key) => value[key])
    .filter((item): item is string => typeof item === "string" && item.trim().length > 0);
}

export function ReportDetailPage() {
  const { reportId } = useParams<{ reportId: string }>();
  const location = useLocation();
  const returnTo = reportsReturnTarget(location.state);
  const { data, isLoading, isRefreshing, error, refetch } = useReportDetail(reportId);
  const [selection, setSelection] = useState<{ reportId: string | undefined; tab: ReportDetailTabKey }>({ reportId, tab: "analysis" });
  const preferredTab = data?.available_tabs.includes("analysis") ? "analysis" : data?.available_tabs[0] ?? "analysis";
  const activeTab = selection.reportId === reportId ? selection.tab : preferredTab;
  const setActiveTab = (tab: ReportDetailTabKey) => setSelection({ reportId, tab });

  const tabs = useMemo(
    () => data?.available_tabs.filter((tab) => tab !== "inputs") ?? ([] as ReportDetailTabKey[]),
    [data?.available_tabs],
  );

  useEffect(() => {
    if (tabs.length === 0) return;
    if (selection.reportId !== reportId || !tabs.includes(selection.tab)) {
      setSelection({ reportId, tab: preferredTab });
    }
  }, [reportId, preferredTab, selection, tabs]);

  if (isLoading && !data) {
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

  if (!data) {
    return (
      <div className="finance-page-shell">
        <FACard title="报告详情加载失败" eyebrow="报告详情" accent="down">
          <FAWarningBanner
            title="标准详情页当前不可用"
            description={readingErrorMessage(error, "报告详情加载失败，请稍后重试。")}
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
                  to={returnTo}
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
  const hasMarketObservation = data.market_odds_evidence || data.meta.family === "jin10_market_observation_report" || data.structured_payload?.report_type === "market_observation";
  const tabOptions = tabs.map((tab) => ({
    value: tab,
    label: reportTabLabel(tab, tab === "inputs" ? null : data.tabs[tab]?.label),
  }));
  const metrics = [
    { label: "资产", value: reportAssetLabel(data.meta.asset) },
    { label: "日期", value: data.meta.trade_date ?? "-" },
  ];
  const summaryChips: string[] = [];
  const qualification = getReportDetailStatus(data);
  const selectionDifference = reportSelectionDifference(location.state?.reportSelection, data);
  const qualificationPending = isRefreshing || Boolean(error);

  return (
    <div className="finance-page-shell">
      <div className="report-detail-stack min-w-0 flex flex-col gap-4">
        <ReportDetailHero
          data={data}
          metrics={metrics}
          onRefresh={refetch}
          isRefreshing={isRefreshing}
          tabs={qualityBlocked ? [] : tabOptions}
          activeTab={activeTab}
          onTabChange={setActiveTab}
          summaryChips={summaryChips}
          returnTo={returnTo}
          qualificationPending={qualificationPending}
        />

        {reportNeedsReadingWarning(data) || data.warnings.length ? (
          <FAWarningBanner
            title="报告资格与参考限制"
            description={uniqueReading([
              ...(reportNeedsReadingWarning(data) ? [qualification.description] : []),
              ...data.warnings.map((warning) => readableWarning(warning.message)),
            ]).join("；")}
            tone={data.warnings.some((warning) => warning.severity === "error") ? "down" : "warn"}
          />
        ) : null}

        {selectionDifference ? <ResearchDetails label="查看列表与详情差异">
          <p className="fa-muted-text">{selectionDifference}</p>
          <p className="fa-faint-text">列表：{location.state?.reportSelection?.report_id ?? "未提供报告 ID"} / {location.state?.reportSelection?.snapshot_id ?? "未提供快照"}；详情：{data.report_id} / {data.meta.snapshot_id ?? "未提供快照"}。</p>
        </ResearchDetails> : null}

        {!qualityBlocked && hasMarketObservation ? (
          <FAWarningBanner
            title="市场观察仅作单源辅助证据"
            description={[
              readableWarning(String(data.market_odds_evidence?.interpretation.notice ?? "外部观察不独立决定策略方向。")),
              data.market_odds_evidence?.analysis_context && data.market_odds_evidence.analysis_context.quality_status !== "accepted" ? "部分分析，需复核。" : "",
            ].filter(Boolean).join("；")}
            tone="warn"
          />
        ) : null}

        {isRefreshing || error ? (
          <FAWarningBanner
            title={isRefreshing ? "正在重新读取本报告" : "报告刷新失败，保留上次读取结果"}
            description={isRefreshing
              ? "正文与证据暂沿用上次完整读取结果；更新完成后一起替换。"
              : "当前正文与证据来自上次成功读取，仅供复核；此次读取未完成，请重试。"}
            tone="warn"
          />
        ) : null}

        {!qualityBlocked && activeTab === "analysis" && tabs.includes("analysis") && data.report_id === reportId ? <ResearchTradePlanCard
          key={data.report_id} identity={data.research_identity} plan={data.final_trade_plan} tradeDate={data.meta.trade_date} asOf={data.meta.asOf}
          observation={isObservationReport(data.meta)} referenceOnly={qualification.referenceOnly || qualificationPending} /> : null}

        <ResearchIdentity identity={data.research_identity} />
        {data.current_context ? <ResearchDetails label="查看当前背景（独立于原始研究）">
          <p className="fa-muted-text">当前背景时点：{data.current_context.context_as_of ?? "未知"} · 仅作当前背景，不替换报告原始研究。</p>
          <ReportGoldMacroOverviewCard data={{ ...data, gold_macro_overview: data.current_context.gold_macro_overview ?? null }} />
          {data.current_context.market_odds ? (
            <ResearchDetails label="查看当前市场观察摘要">
              {currentMarketContextLines(data.current_context.market_odds).map((line) => <p key={line} className="fa-muted-text">{line}</p>)}
              <p className="fa-faint-text">仅展示后端摘要字段；原始响应 JSON 不进入页面。</p>
            </ResearchDetails>
          ) : null}
        </ResearchDetails> : null}
        <ResultIdentityBar
          identity={data.result_identity}
          subjectLabel="报告自身"
          baselineLabel="当前有效的黄金研究基线"
        />

        {qualityBlocked ? (
          <FAWarningBanner
            title="报告未通过质量审核"
            description="正文与图表缺少足够的可用证据，暂不可参考；需补齐证据并复核。"
            tone="down"
          />
        ) : null}

        <div className="min-h-0 min-w-0 flex-1">
          {qualityBlocked ? (
            <section className="rounded-[var(--radius-lg)] border border-[var(--down-border)] bg-[var(--down-soft)] p-4">
              <FAEmptyState title="本次报告不可用" description="失败产物仅保留用于审计，不作为正式报告展示。" />
            </section>
          ) : tabs.length > 0 ? (
            <ReportArtifactPanel tab={currentTab} />
          ) : (
            <section className="rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card)] p-4">
              <FAEmptyState title="暂无可用内容页签" description="后端未返回可展示的分析稿、来源稿、可视稿或证据包。" />
            </section>
          )}
        </div>
        {!qualityBlocked ? <ResearchDetails label="查看市场比较与观察">
          <ReportMarketOddsMatrix data={data} />
          <ReportMarketObservationCard data={data} />
        </ResearchDetails> : null}
        {data.generation_trace || data.llm_audits.length ? (
        <ResearchDetails label="查看报告记录"><ReportGenerationTraceCard data={data} onTabChange={setActiveTab} />{data.llm_audits.length > 0 ? (
          <section className="rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card)] p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <div className="text-[12px] font-semibold text-[var(--fg-2)]">模型调用审计</div>
                <div className="mt-1 text-[11px] text-[var(--fg-4)]">本报告关联 {data.llm_audits.length} 次模型调用；页面仅展示模型、状态、时间和规模摘要。</div>
              </div>
            </div>
            <div className="mt-3 grid gap-2 lg:grid-cols-2">
              {data.llm_audits.slice(0, 6).map((audit) => <div key={audit.audit_id} className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-3 py-2 text-[10px] text-[var(--fg-3)]"><div className="flex items-center justify-between gap-2"><span className="font-semibold">{callerLabel(audit.caller)}</span><FAStatusPill tone={auditStatusTone(audit.status)}>{auditStatusLabel(audit.status)}</FAStatusPill></div><div className="mt-1 text-[var(--fg-5)]">模型：{modelDisplayLabel(audit.model_resolved)} · 提示词 {audit.prompt_char_count} 字符 · 输出 {audit.response_char_count} 字符 · {audit.created_at ?? "未记录时间"}</div></div>)}
              {data.llm_audits.length > 6 ? <div className="text-[10px] text-[var(--fg-5)]">另有 {data.llm_audits.length - 6} 条调用摘要。</div> : null}
            </div>
          </section>
        ) : null}

        </ResearchDetails>
        ) : null}
      </div>
    </div>
  );
}

export default ReportDetailPage;
