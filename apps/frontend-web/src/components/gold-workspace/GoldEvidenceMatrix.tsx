import { useState } from "react";
import { FAStatusPill, type FAStatusTone } from "@/components/shared/FAStatusPill";
import { ResearchDetails } from "@/components/shared/ResearchDetails";
import { beijingTime } from "@/components/dashboard/DashboardResearchBriefModel";
import { readerSource } from "@/lib/readerLabels";
import type { GoldFact, GoldFactStatus, GoldImpact } from "@/types/gold-workspace";
import { goldSourceLabel } from "./goldPresentation";

export const factStatus: Record<GoldFactStatus, string> = {
  fresh: "近期行情", recent: "最近披露", stale: "历史观测", unverified: "待核验", unavailable: "缺失",
};
export const impactPresentation: Record<GoldImpact, { label: string; tone: FAStatusTone }> = {
  supportive: { label: "利好", tone: "up" }, pressure: { label: "利空", tone: "down" },
  mixed: { label: "多空传导分歧", tone: "warn" }, neutral: { label: "变化有限", tone: "neutral" },
  unconfirmed: { label: "影响待确认", tone: "dim" },
};
export function goldNumber(value: number | null, digits = 2): string {
  return value === null ? "未提供" : new Intl.NumberFormat("zh-CN", { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(value);
}
const unitLabel = (unit: string): string => ({ bp: "基点", index: "点", tonnes: "吨", contracts: "手", B: "十亿美元",
  "USD/bbl": "美元/桶", "USD/oz": "美元/盎司", percent: "%", percentage_points: "%" }[unit] ?? unit);
const observationTime = (value: string | null): string => value && /^\d{4}-\d{2}-\d{2}$/.test(value)
  ? `${value}（观测日）` : beijingTime(value);
export function factChange(fact: GoldFact): string {
  if (fact.change === null) return "暂无可比变动";
  const window = fact.change_window === "1d" ? "日变动" : fact.change_window === "1w" ? "周变动" : "窗口待核验";
  return `${window} ${fact.change > 0 ? "+" : ""}${goldNumber(fact.change)} ${unitLabel(fact.change_unit)}`;
}
function referenceUrl(ref: Record<string, unknown>): string | null {
  const value = ref.source_url ?? ref.reference;
  if (typeof value !== "string") return null;
  try {
    const url = new URL(value);
    if (!["http:", "https:"].includes(url.protocol) || url.username || url.password) return null;
    for (const key of url.searchParams.keys()) if (/key|token|secret|auth/i.test(key)) return null;
    return url.href;
  } catch { return null; }
}

export function GoldImpactReading({ fact, reviewOnly }: { fact: GoldFact; reviewOnly: boolean }) {
  const usable = !reviewOnly && ["fresh", "recent"].includes(fact.status);
  const macro = usable ? impactPresentation[fact.macro_effect.impact] : impactPresentation.unconfirmed;
  const short = usable ? impactPresentation[fact.impact] : impactPresentation.unconfirmed;
  const window = fact.change_window === "1d" ? "日度" : fact.change_window === "1w" ? "周度" : fact.frequency === "intraday" ? "日内" : "变动待核验";
  return <div className="gold-impact-readings" aria-label={`${fact.label}长期与短线影响`}>
    <div className="gold-impact-reading" data-impact-horizon="macro"><span className="fa-label">长期宏观</span><FAStatusPill tone={macro.tone} dot={false}>{macro.label}</FAStatusPill>
      <p className="fa-body-text">{reviewOnly ? "等待本次核验。" : fact.macro_effect.summary}</p></div>
    <div className="gold-impact-reading" data-impact-horizon="short"><span className="fa-label">短线影响 · {window}</span><FAStatusPill tone={short.tone} dot={false}>{short.label}</FAStatusPill>
      <p className="fa-body-text">{reviewOnly ? "等待本次核验。" : fact.short_term_summary}</p></div>
  </div>;
}

export function GoldFactorCard({ fact, reviewOnly }: { fact: GoldFact; reviewOnly: boolean }) {
  return <article className="gold-factor" data-gold-factor={fact.key}>
    <div className="gold-factor-heading"><h3 className="fa-card-title">{fact.label}</h3>
      <FAStatusPill tone={["fresh", "recent"].includes(fact.status) && !reviewOnly ? "neutral" : "warn"} dot={false}>{reviewOnly ? "上次观测" : factStatus[fact.status]}</FAStatusPill></div>
    <div className="gold-factor-value"><strong>{goldNumber(fact.value)} <span className="fa-label">{unitLabel(fact.unit)}</span></strong>
      <span className="fa-label">{factChange(fact)}{fact.change !== null ? ` · ${fact.change > 0 ? "上升" : fact.change < 0 ? "下降" : "持平"}` : ""}</span></div>
    <GoldImpactReading fact={fact} reviewOnly={reviewOnly} />
    <ResearchDetails label="查看依据与数据口径"><p className="fa-body-text">{fact.interpretation}</p><p>观测：{observationTime(fact.observed_at)} · 来源：{goldSourceLabel(fact.source)}</p>
      {fact.change_window === "1d" && fact.frequency === "daily" ? <p>这项变化来自日度披露，尚未核验盘中涨跌；不能代替日内行情。</p> : null}
      <p>长期颜色表示资金成本等宏观约束；短线颜色表示该观测窗口的边际变化。二者可以相反，均不是已确认的涨跌贡献。</p>
      {fact.source_refs.map((ref, i) => { const url = referenceUrl(ref); return url ? <p key={i}><a href={url} target="_blank" rel="noopener noreferrer">{readerSource(typeof ref.source === "string" ? ref.source : fact.source)} · 原始来源</a></p> : null; })}
    </ResearchDetails>
  </article>;
}

export function GoldEvidenceMatrix({ factors, reviewOnly }: { factors: GoldFact[]; reviewOnly: boolean }) {
  const [expanded, setExpanded] = useState(false);
  const visible = expanded ? factors : factors.slice(0, 8);
  const valid = reviewOnly ? [] : factors.filter(fact => ["fresh", "recent"].includes(fact.status));
  return <section className="fa-card gold-evidence" aria-label="黄金宏观驱动证据">
    <header className="gold-section-header"><div><h2 className="fa-section-title">利好利空：宏观与资金驱动</h2>
      <p className="fa-muted-text">长期压力与短线缓冲分别判断；日度变化不等于已核验的日内行情。</p></div>
      <button className="gold-text-button" type="button" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>
        {expanded ? "收起扩展证据" : "展开流动性与配置资金"}</button></header>
    <div className="gold-impact-balance" aria-label="黄金利好与利空参考">
      {(["macro", "short"] as const).map(horizon => {
        const rows = valid.filter(fact => ["supportive", "pressure"].includes(horizon === "macro" ? fact.macro_effect.impact : fact.impact));
        return <div key={horizon} className="gold-impact-group"><strong className="fa-card-title">{horizon === "macro" ? "长期宏观 · 成本与趋势约束" : "短线驱动 · 最新可比变化"}</strong>
          {rows.length ? <ul>{rows.map(fact => {
            const impact = impactPresentation[horizon === "macro" ? fact.macro_effect.impact : fact.impact];
            return <li key={fact.key}><span>{fact.label}</span><strong className={`gold-tone--${impact.tone}`}>{impact.label}</strong>
              <span className="fa-label">{horizon === "macro" ? fact.macro_effect.change !== null ? `近月变动 ${goldNumber(fact.macro_effect.change)} ${unitLabel(fact.macro_effect.unit)}` : "收益水平约束" : factChange(fact)}</span></li>;
          })}</ul>
            : <p className="fa-muted-text">{reviewOnly ? "等待本次观测核验" : "暂无可核验的同窗口方向证据"}</p>}</div>;
      })}
    </div>
    {factors.length === 0 ? <p className="fa-body-text">宏观数据尚未返回，等待采集后再判断驱动。</p> :
      <div className="gold-factor-grid">{visible.map((fact, index) => <GoldFactorCard key={`${fact.key}-${index}`} fact={fact} reviewOnly={reviewOnly} />)}</div>}
  </section>;
}
