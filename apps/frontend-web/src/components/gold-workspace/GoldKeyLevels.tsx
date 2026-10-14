import { beijingTime } from "@/components/dashboard/DashboardResearchBriefModel";
import { ResearchIdentity } from "@/components/shared/ResearchIdentity";
import { useState } from "react";
import { Link } from "react-router-dom";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { ResearchDetails } from "@/components/shared/ResearchDetails";
import { MarkdownViewer } from "@/components/reports/MarkdownViewer";
import type { GoldWorkspace } from "@/types/gold-workspace";
import { goldNumber } from "./GoldEvidenceMatrix";

const role = (value: unknown) => ({ support: "支撑观察", resistance: "阻力观察", confirmation: "收复关口",
  trigger: "触发观察", invalidation: "失效观察", reclaim: "收复关口" }[String(value)] ?? "结构观察位");

function LevelValidity({ value }: { value: unknown }) {
  const validity = value && typeof value === "object" ? value as Record<string, unknown> : {};
  const label = ({ active: "有效", expired: "已失效", historical: "历史参考", unavailable: "不可用" } as Record<string, string>)[String(validity.status)] ?? "未知";
  return <p className="fa-muted-text">点位状态：{label} · 有效截止：{typeof validity.valid_until === "string" ? beijingTime(validity.valid_until) : "未知"}</p>;
}

export function NumericCondition({ text }: { text: string }) {
  return <>{text.split(/(\d[\d,]*(?:\.\d+)?)/g).map((part, index) => /^\d/.test(part)
    ? <strong key={index} className="gold-condition-number">{part}</strong> : part)}</>;
}

export function GoldSpotLevels({ data, reviewOnly = false }: { data: GoldWorkspace; reviewOnly?: boolean }) {
  const r = data.research;
  const topic = r.topics.find(row => row.key === "levels" && row.status !== "unavailable");
  // Retain explicit spot sentences verbatim; never turn numbers in prose into
  // calculated support walls, nor copy GC-only sentences into a spot ladder.
  const spotSentences = (value: string) => value.split(/(?<=[。！？\n])/).filter(sentence => /XAUUSD|现货/i.test(sentence) && !/\bGC\b/i.test(sentence)).join("");
  const facts = topic ? spotSentences(topic.facts || topic.judgment) : "";
  const invalidation = topic ? spotSentences(topic.falsification) : "";
  return <section className="fa-card gold-level-map" aria-label="黄金现货关键位地图">
    <header className="gold-section-header"><h2 className="fa-section-title">现货关键点位 <span className="fa-label">XAUUSD</span></h2>
      <FAStatusPill tone={r.status === "current" && !reviewOnly ? "info" : "warn"}>{r.status === "current" && !reviewOnly ? "研究观察" : "原研究 · 需重验"}</FAStatusPill></header>
    {reviewOnly ? <p className="gold-notice fa-body-text">以下为读取时的点位状态；不确认当前有效性或触发。</p> : null}
    <ResearchIdentity identity={r.research_identity} />
    {r.key_levels.length ? <ol className="gold-price-ladder">{r.key_levels.map((row, index) => <li key={index}>
      <span className="gold-level-marker" /><strong>{goldNumber(row.price as number)}</strong><span>{role(row.role)}</span>
      <p className="fa-body-text">{typeof row.activation === "string" ? row.activation : "等待价格接近、收复或突破后的结构确认。"}</p>
      <LevelValidity value={row.validity} />
      <ResearchDetails label="查看该位失效与依据"><p>{typeof row.invalidation === "string" ? row.invalidation : "失效条件尚未提供。"}</p>
        <p>来源观测日：{String(row.source_date ?? "未提供")}</p></ResearchDetails></li>)}</ol>
      : facts ? <div className="gold-spot-prose"><p className="fa-body-text"><NumericCondition text={facts} /></p>
        {invalidation ? <p className="fa-body-text gold-tone--warn"><strong>改判条件：</strong><NumericCondition text={invalidation} /></p> : null}
        <span className="fa-muted-text">原研究点位需重验，当前尚未确认触发。</span></div>
      : <p className="fa-body-text">本研究未提供可核验的现货点位，等待结构更新。</p>}
    {topic ? <ResearchDetails label="查看点位的完整研究依据"><p>研究数据时点：{r.research_identity?.data_as_of ? beijingTime(r.research_identity.data_as_of) : "未知"}</p>
      <MarkdownViewer content={[topic.judgment, topic.facts, topic.falsification].join("\n\n")} readingMode="full" /></ResearchDetails> : null}
  </section>;
}

export function GoldCmeLevels({ data, reviewOnly = false }: { data: GoldWorkspace; reviewOnly?: boolean }) {
  const cme = data.cme_structure;
  const [expanded, setExpanded] = useState(false);
  const priority = cme.levels.filter(level => ["primary_support", "primary_resistance", "gamma_flip"].includes(level.role));
  const others = cme.levels.filter(level => !priority.includes(level));
  const shown = expanded ? [...priority, ...others] : [...priority, ...others].slice(0, 6);
  return <section className="fa-card gold-level-map gold-cme-levels" aria-label="CME黄金期货关键价位">
    <header className="gold-section-header"><h2 className="fa-section-title">CME关键价位 <span className="fa-label">GC期货</span></h2>
      <FAStatusPill tone="warn">{cme.status === "unavailable" ? "结构待核验" : cme.status === "historical" ? "历史结构" : cme.version_type === "FINAL" ? "终版结构" : "初步版结构"}</FAStatusPill></header>
    <p className="fa-body-text">OI／模型GEX结构参考；GC价位不直接用于现货执行。</p>
    {reviewOnly ? <p className="gold-notice fa-body-text">以下保留上次读取的GC结构；当前资格与期现基差需核验。</p> : null}
    {shown.length ? <ol className="gold-price-ladder">{shown.map((level, index) => <li key={index}>
      <span className="gold-level-marker" /><strong>{level.price !== null ? goldNumber(level.price) : `${goldNumber(level.lower)}—${goldNumber(level.upper)}`}</strong>
      <span>{level.label}{level.expiry ? ` · ${level.expiry === "aggregate" ? "合并模型" : level.expiry}` : ""}</span>
      <p className="fa-body-text">{level.meaning}</p></li>)}</ol> : <p className="fa-muted-text">当前CME结构读数未能核验，待来源恢复后展示。</p>}
    {cme.levels.length > 6 ? <button className="gold-text-button" type="button" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>
      {expanded ? "收起次级点位" : `展开其余${cme.levels.length - 6}个点位`}</button> : null}
    <ResearchDetails label="查看CME模型口径与来源"><p>公报交易日：{cme.trade_date ?? "未提供"} · {cme.version_type ?? "版本未核验"}</p>
      <p>报告参考锚：{goldNumber(cme.reference_price)}美元/盎司，属于报告模型参考，非当前GC报价。</p>
      <p>{cme.note}</p><p>GEX为模型估算，不是交易商真实库存；期现基差尚未核验。</p></ResearchDetails>
    <Link to="/cme-options" className="gold-text-button">查看CME结构全图与来源 →</Link>
  </section>;
}

export function GoldEnvironmentWatch({ data, reviewOnly }: { data: GoldWorkspace; reviewOnly: boolean }) {
  const watch = data.environment_watch;
  return <section className="fa-card gold-environment-watch" aria-label="黄金环境改判具体数值">
    <header className="gold-section-header"><h2 className="fa-section-title">环境改判：具体观察值</h2><FAStatusPill tone="warn">{reviewOnly ? "等待核验" : "下一轮比较基准"}</FAStatusPill></header>
    <p className="fa-body-text">利率和美元共同改善才支持修复；同时恶化则增加下行压力。</p>
    {watch.conditions.length ? <div className="gold-impact-balance">{(["supportive", "pressure"] as const).map(direction =>
      <div key={direction} className={`gold-impact-group gold-impact-group--${direction === "supportive" ? "up" : "down"}`}>
        <h3 className={`fa-card-title gold-tone--${direction === "supportive" ? "up" : "down"}`}>{direction === "supportive" ? "利好变化：修复条件改善" : "利空变化：下行压力增加"}</h3>
        <ul>{watch.conditions.map(condition => <li key={condition.key}><span>{condition.label}：</span>
          <span><NumericCondition text={direction === "supportive" ? condition.supportive_condition : condition.pressure_condition} /></span></li>)}</ul></div>)}</div>
      : <p className="fa-muted-text">需要可核验的利率与美元读数才能给出具体比较值。</p>}
    <p className="fa-muted-text">比较基准用于观察下一轮变化，不代表已确认反转；仍需配合现货关键位的收复或跌破。</p>
    <ResearchDetails label="查看改判条件的依据与限制"><p>{watch.note}</p>
      {watch.conditions.map(row => <p key={row.key}>{row.label} · {beijingTime(row.observed_at)} · 基准{goldNumber(row.value)}{row.unit}</p>)}</ResearchDetails>
  </section>;
}
