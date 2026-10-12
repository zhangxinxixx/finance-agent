import { Clock3, CalendarRange } from "lucide-react";
import { MarkdownViewer } from "@/components/reports/MarkdownViewer";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { ResearchDetails } from "@/components/shared/ResearchDetails";
import type { GoldResearchHorizon, GoldWorkspace } from "@/types/gold-workspace";

function HorizonCard({ kind, value, reviewOnly, dataAsOf }: { dataAsOf?: string | null; kind: "short" | "long"; value: GoldResearchHorizon; reviewOnly: boolean }) {
  const short = kind === "short", available = value.status !== "unavailable";
  const current = value.status === "current" && !reviewOnly;
  const label = available ? reviewOnly ? "等待本次核验" : value.basis === "report_excerpt" && !short ? "宏观背景" : current ? "本次研究" : "历史研究" : "待生成";
  return <section className={`fa-card gold-horizon gold-horizon--${kind}`} aria-label={short ? "黄金短线分析" : "黄金长线分析"}>
    <header className="gold-section-header"><div><h2 className="fa-section-title">{short ? <Clock3 size={16} /> : <CalendarRange size={16} />}{short ? "短线分析" : "长线分析"}</h2>
      <p className="fa-muted-text">{short ? "日内—未来1至3个交易日" : "周／月 · 利率、美元与配置资金"}</p></div>
      <FAStatusPill tone={current && value.basis === "report_explicit" ? "info" : "warn"}>{label}</FAStatusPill></header>
    {available ? <><div className="gold-horizon-judgment">
      {value.basis === "report_excerpt" ? <h3 className="fa-card-title">{value.sections[0]?.title}</h3>
        : <MarkdownViewer content={value.summary} readingMode="full" />}</div>
      <p className="fa-muted-text">{value.note}</p>
      <ResearchDetails label={short ? "展开短线依据与改判条件" : "展开长线宏观依据"}>
        <p className="fa-muted-text">研究数据时点 {dataAsOf ?? "未知"}</p>
        <div className="gold-detail-copy">{value.sections.map((section, index) => <div key={index}><h3 className="fa-card-title">{section.title}</h3><MarkdownViewer content={section.content} readingMode="full" /></div>)}</div>
      </ResearchDetails>
      {!current ? <p className="fa-faint-text">原判断需用最新行情重验</p> : null}
    </> : <div className="gold-horizon-empty"><strong className="fa-card-title">{short ? "短线判断尚未生成" : "长线判断尚未生成"}</strong>
      <p className="fa-body-text">{short ? "更新分析后展示价格结构、反弹／回落条件和失效位。" : "更新分析后展示长期资金成本、政策和配置需求的支持与制约。"}</p>
      <p className="fa-muted-text">{value.note}</p></div>}
  </section>;
}

export function GoldAnalysisHorizons({ data, reviewOnly }: { data: GoldWorkspace; reviewOnly: boolean }) {
  return <div className="gold-horizon-grid" aria-label="黄金短线与长线研究">
    <HorizonCard kind="short" value={data.research.horizons.short_term} reviewOnly={reviewOnly} dataAsOf={data.research.research_identity?.data_as_of} />
    <HorizonCard kind="long" value={data.research.horizons.long_term} reviewOnly={reviewOnly} dataAsOf={data.research.research_identity?.data_as_of} />
  </div>;
}
