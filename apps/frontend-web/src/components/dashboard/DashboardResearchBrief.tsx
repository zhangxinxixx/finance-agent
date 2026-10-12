import { ResearchIdentity } from "@/components/shared/ResearchIdentity";
import { ResearchTradePlanCard } from "@/components/shared/ResearchTradePlanCard";
import { Link } from "react-router-dom";
import { MarkdownViewer } from "@/components/reports/MarkdownViewer";
import type { DashboardDataResponse } from "@/types/dashboard";
import { buildDashboardResearchBrief } from "./DashboardResearchBriefModel";

export function DashboardResearchBrief({ dashboardResult, today }: { dashboardResult: DashboardDataResponse; today?: string }) {
  const summary = dashboardResult.summary;
  if (!summary) return null;
  const model = buildDashboardResearchBrief(summary, today);
  const research = model.research;
  const reportTarget = research?.final_trade_plan ? `/reports/${encodeURIComponent(research.final_trade_plan.report_id)}` : model.reportTarget;
  const sections = [
    ["主导驱动", research?.dominant_driver], ["交易含义", research?.trade_implication ? [research.trade_implication] : []],
    ["升级条件", research?.trigger_upgrade], ["降级条件", research?.trigger_downgrade],
    ["失效条件", research?.invalidation], ["风险", research?.risks],
  ] as const;
  return <section className="fa-card dashboard-research-brief" aria-label="最新黄金研究">
    <header>
      <h2 className="fa-section-title">最新黄金研究</h2>
      <ResearchIdentity identity={summary.research_context?.research_identity ?? research?.research_identity} />
      {model.stale ? <p className="fa-body-text" role="status">今天尚无更新，当前为历史研究日期 {model.tradeDate}。数据刷新不代表研究已更新。</p> : null}
      {model.observation ? <p className="fa-body-text dashboard-research-notice">研究观察稿，未获正式发布许可，不构成正式交易信号。</p> : null}
    </header>
    <ResearchTradePlanCard identity={summary.research_context?.research_identity ?? research?.research_identity} plan={research?.final_trade_plan} tradeDate={model.tradeDate} asOf={research?.as_of}
      today={today} observation={model.observation} embedded />
    {research?.reasoning?.trim() ? <MarkdownViewer content={research.reasoning} readingMode="full" />
      : <p className="fa-muted-text">选中研究未提供分析正文。</p>}
    <section aria-label="独立市场观测">
      <h3 className="fa-card-title">核心市场指标与证据</h3>
      <p className="fa-muted-text">以下是独立市场观测，各自标时点，不为历史研究补充事实。</p>
      <dl className="dashboard-research-facts">{model.facts.map(fact => <div key={fact.key}>
        <dt className="fa-label">{fact.label}</dt>
        <dd className="fa-body-text">{fact.value === null ? "缺失" : `${fact.value}${fact.unit ? ` ${fact.unit}` : ""}`}</dd>
        <dd className="fa-muted-text">{fact.timing}</dd>
        <dd className="fa-muted-text">来源：{fact.source || "未提供"}</dd>
        {fact.note ? <dd className="fa-muted-text">{fact.note}</dd> : null}
      </div>)}</dl>
    </section>
    {sections.map(([label, items]) => items?.some(item => item.trim()) ? <section key={label} aria-label={label}>
      <h3 className="fa-card-title">{label}</h3>
      {items.filter(item => item.trim()).map((item, index) => <MarkdownViewer key={index} content={item} readingMode="full" />)}
    </section> : null)}
    <footer className="dashboard-research-links">
      {reportTarget ? <Link to={reportTarget} state={{ dashboardResult, returnTo: "/dashboard", returnLabel: "返回同一研究总览" }}>
        {model.observation ? "阅读同一研究完整版（观察稿） →" : "阅读同一研究完整版 →"}</Link> : <span className="fa-muted-text">本研究尚无可定位的完整版报告。</span>}
      <Link to="/dashboard/analysis" state={{ dashboardResult }}>查看本次完整依据 →</Link>
      {research?.source_refs?.map((ref, index) => /^(https?:\/\/|\/api\/)/.test(ref.endpoint || ref.source_ref)
        ? <a key={index} href={ref.endpoint || ref.source_ref}>{ref.name || "研究来源"} · {ref.trade_date}</a> : null)}
    </footer>
  </section>;
}
