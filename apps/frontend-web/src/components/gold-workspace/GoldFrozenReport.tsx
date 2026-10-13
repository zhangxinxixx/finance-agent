import { useState } from "react";
import { Link } from "react-router-dom";
import { ResearchIdentity } from "@/components/shared/ResearchIdentity";
import { ResearchTradePlanCard } from "@/components/shared/ResearchTradePlanCard";
import { ResultIdentityBar } from "@/components/shared/ResultIdentityBar";
import { ReportArtifactPanel } from "@/components/reports/ReportArtifactPanel";
import { getReportDetailStatus } from "@/components/reports/reportDetailMeta";
import type { ReportArtifactTabKey, ReportDetailView } from "@/types/reports";

/** Uses only the selected report DTO. Missing workspace observations stay missing. */
export function readFrozenGoldReport(value: unknown): ReportDetailView | null {
  if (!value || typeof value !== "object") return null;
  const report = value as ReportDetailView;
  return typeof report.report_id === "string" && report.meta?.asset === "XAUUSD"
    && report.meta.report_id === report.report_id && Array.isArray(report.available_tabs)
    && report.tabs && Array.isArray(report.warnings) ? report : null;
}

export function GoldFrozenReport({ report, onLatest }: { report: ReportDetailView; onLatest: () => void }) {
  const qualityBlocked = report.data_status === "unavailable" && report.meta.lifecycle_status === "needs_review";
  const tabs = qualityBlocked ? [] : report.available_tabs.filter((tab): tab is ReportArtifactTabKey => tab !== "inputs");
  const [tab, setTab] = useState<ReportArtifactTabKey>(tabs.includes("analysis") ? "analysis" : tabs[0] ?? "analysis");
  const qualification = getReportDetailStatus(report);
  return <section className="gold-workspace" aria-label="黄金工作台冻结报告">
    <header className="gold-workspace-header"><h1 className="fa-page-title">黄金工作台 · 冻结研究</h1>
      <button type="button" className="gold-secondary-button" onClick={onLatest}>返回最新黄金工作台</button></header>
    <div className="gold-reading-risk" role="status"><strong className="fa-card-title">历史／冻结报告 · 不是当前执行许可</strong>
      <p className="fa-body-text">仅保留这份报告已读取的内容与证据。对应工作台观测未提供，不补入最新宏观、CME 或行情作为当时依据。</p>
      <p className="fa-body-text">{qualification.label} · {qualification.description}</p></div>
    <ResearchIdentity identity={report.research_identity} />
    <ResearchTradePlanCard identity={report.research_identity} plan={report.final_trade_plan}
      tradeDate={report.meta.trade_date} asOf={report.meta.asOf} referenceOnly />
    <ResultIdentityBar identity={report.result_identity} subjectLabel="所选报告" baselineLabel="报告读取时的黄金基线" />
    <nav className="gold-workspace-navigation" aria-label="冻结报告内容">{tabs.map(key => <button type="button" key={key}
      className="gold-secondary-button" aria-pressed={tab === key} onClick={() => setTab(key)}>{report.tabs[key]?.label ?? key}</button>)}</nav>
    {qualityBlocked ? <p className="gold-notice fa-body-text">报告未通过质量审核，正文与图表不可参考；保留身份供核验。</p>
      : <ReportArtifactPanel tab={report.tabs[tab] ?? null} />}
    <Link to={`/reports/${encodeURIComponent(report.report_id)}`} className="fa-label text-[var(--brand)]">返回所选报告详情与来源 →</Link>
  </section>;
}
