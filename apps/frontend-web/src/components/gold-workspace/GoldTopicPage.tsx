import { ResearchIdentity } from "@/components/shared/ResearchIdentity";
import { useEffect, type ReactNode } from "react";
import { Link, useOutletContext } from "react-router-dom";
import { RefreshCw } from "lucide-react";
import type { AppShellOutletContext } from "@/components/AppShell";
import { HeaderBreadcrumb } from "@/components/shared/HeaderBreadcrumb";
import { FAWarningBanner } from "@/components/shared/FAWarningBanner";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { ResearchDetails } from "@/components/shared/ResearchDetails";
import { useGoldWorkspace } from "@/hooks/useGoldWorkspace";
import type { GoldTopicGroup } from "@/types/gold-workspace";
import { GoldResearchTopics } from "./GoldResearchTopics";
import { GoldRatesVisual } from "./GoldRatesVisual";
import { GoldFactorCard } from "./GoldEvidenceMatrix";
import "@/styles/gold-workspace.css";

export function GoldTopicPage({ title, description, group, evidence }: { title: string; description: string; group: GoldTopicGroup; evidence?: ReactNode }) {
  const workspace = useGoldWorkspace();
  const shell = useOutletContext<AppShellOutletContext | null>();
  useEffect(() => { shell?.setHeaderContent(<HeaderBreadcrumb title={title} />); return () => shell?.setHeaderContent(null); }, [shell, title]);
  const data = workspace.data, reviewOnly = Boolean(workspace.loading || workspace.error);
  return <div className="finance-page-shell gold-workspace gold-topic-page">
    <header className="gold-workspace-header"><div><h1 className="fa-page-title">{title}</h1><p className="fa-muted-text">{description}</p></div>
      <div className="gold-workspace-actions"><button className="gold-secondary-button" type="button" disabled={workspace.loading} onClick={() => void workspace.refetch()}><RefreshCw size={14} />读取最新观测</button>
        <Link className="gold-text-button" to="/dashboard">返回黄金工作台 · 更新分析 →</Link></div></header>
    {workspace.error ? <FAWarningBanner tone="down" title="本次观测读取失败" description="保留上次研究与数据，等待重新核验。" /> : null}
    {data ? <><div className="gold-topic-page-context"><FAStatusPill tone={data.research.status === "current" && !reviewOnly ? "info" : "warn"}>{data.research.status === "unavailable" ? "研究待生成" : data.research.status === "current" && !reviewOnly ? "本次研究" : "历史研究 · 需更新"}</FAStatusPill>
      <ResearchIdentity identity={data.research.research_identity} />
      {data.research.report_id && data.research.status !== "unavailable" ? <Link className="gold-text-button" to={`/reports/${encodeURIComponent(data.research.report_id)}`}>查看同一完整报告 →</Link> : null}</div>
      {group === "macro" ? <GoldRatesVisual data={data} /> : null}
      {group === "funds" ? <section className="fa-card"><h2 className="fa-section-title">原油：成本压力与避险传导</h2>
        <div className="gold-oil-grid">{data.factors.filter(fact => ["WTI_SPOT", "BRENT_SPOT"].includes(fact.key)).map(fact => <GoldFactorCard key={fact.key} fact={fact} reviewOnly={reviewOnly} />)}</div></section> : null}
      <GoldResearchTopics data={data} reviewOnly={reviewOnly} groups={[group]} initialGroup={group} />
    </> : <p className="fa-card fa-body-text">{workspace.loading ? "正在读取同一研究与最新观测…" : "研究尚未可用，请读取观测或在黄金工作台更新分析。"}</p>}
    {evidence ? <ResearchDetails label="查看专题主线的原始归因与证据记录">{evidence}</ResearchDetails> : null}
  </div>;
}
