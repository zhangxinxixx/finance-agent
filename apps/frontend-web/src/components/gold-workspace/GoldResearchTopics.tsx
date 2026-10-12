import { useId, useState } from "react";
import { MarkdownViewer } from "@/components/reports/MarkdownViewer";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { ResearchDetails } from "@/components/shared/ResearchDetails";
import type { GoldFact, GoldResearchTopic, GoldTopicGroup, GoldWorkspace } from "@/types/gold-workspace";
import { factChange, factStatus, goldNumber, GoldImpactReading } from "./GoldEvidenceMatrix";

const GROUPS: Array<{ key: GoldTopicGroup; label: string; description: string }> = [
  { key: "changes", label: "更新与主线", description: "新增事实是否改变前序日报、周报的判断" },
  { key: "macro", label: "政策与利率", description: "就业、通胀 → Fed路径 → 名义／实际利率 → 美元 → 黄金" },
  { key: "funds", label: "能源与资金", description: "能源成本、避险、配置需求、杠杆仓位与融资环境" },
  { key: "price", label: "价格与策略", description: "黄金承接、关键位、三条路径与4H／1H／15m执行条件" },
  { key: "risk", label: "事件与风险", description: "事件不同结果的传导、改判开关与无法确认的结论" },
];
const FACT_KEYS: Record<string, string[]> = {
  curve_policy: ["US02Y", "US10Y", "US30Y"], treasury_turn: ["US10Y", "US30Y"],
  real_rates: ["REAL10Y", "T10YIE"], dollar: ["DXY"], oil: ["WTI_SPOT", "BRENT_SPOT"],
  flows: ["GLD_HOLDINGS", "COT_GOLD_NET"], liquidity: ["SOFR", "TGA", "RESERVES"], credit: ["HY_OAS"],
};
const FIELD_LABELS = [
  ["facts", "关键依据"], ["transmission", "如何传导到黄金"],
  ["response", "价格是否接受这一解释"], ["alternatives", "竞争解释与反证"],
  ["falsification", "观察、改判与失效条件"],
] as const;
const unit = (value: string) => ({ "%": "%", percent: "%", percentage_points: "%", index: "点", tonnes: "吨", contracts: "手", "USD/bbl": "美元/桶", B: "十亿美元" }[value] ?? value);

export function GoldTopicMetrics({ facts, reviewOnly }: { facts: GoldFact[]; reviewOnly: boolean }) {
  if (!facts.length) return null;
  return <div className="gold-topic-metrics" aria-label="该主题最近采集观测">
    <p className="fa-label">最近观测 · 长期与短线分别判断</p>
    {facts.map(fact => <div className="gold-topic-metric" key={fact.key}>
      <span className="fa-body-text">{fact.label}</span>
      <strong className="fa-body-text">{goldNumber(fact.value)} {unit(fact.unit)}</strong>
      <span className="fa-label">{factChange(fact)}</span>
      <span className="fa-faint-text">{reviewOnly ? "等待核验" : factStatus[fact.status]}</span>
      <GoldImpactReading fact={fact} reviewOnly={reviewOnly} />
    </div>)}
  </div>;
}

function TopicCard({ topic, factors, reviewOnly, dataAsOf }: { topic: GoldResearchTopic; factors: GoldFact[]; reviewOnly: boolean; dataAsOf?: string | null }) {
  const available = topic.status !== "unavailable", current = topic.status === "current" && !reviewOnly;
  const observations = factors.filter(fact => FACT_KEYS[topic.key]?.includes(fact.key));
  return <article className={`fa-card gold-topic gold-topic--${topic.group}`} aria-label={topic.label} data-gold-topic={topic.key}>
    <header className="gold-section-header"><h3 className="fa-card-title">{topic.label}</h3>
      <FAStatusPill tone={current && !topic.pending.length ? "info" : "warn"} dot={false}>{!available ? "待补分析" : reviewOnly ? "等待核验" : topic.pending.length ? `含${topic.pending.length}项证据缺口` : current ? "本次研究" : "历史研究"}</FAStatusPill></header>
    {!available ? <div className="gold-topic-empty"><p className="fa-body-text">{topic.note}</p>
      <p className="fa-muted-text">补齐该主题的事实、传导、黄金响应与反证后，再给独立判断。</p></div>
      : topic.basis === "report_excerpt" ? <div className="gold-topic-excerpts">{topic.sections.map((section, index) =>
        <div key={index}><h4 className="fa-card-title">{section.title}</h4><MarkdownViewer content={section.content} readingMode="full" /></div>)}</div>
      : <><div className="gold-topic-judgment"><p className="fa-label">研究判断</p><MarkdownViewer content={topic.judgment} readingMode="full" /></div>
        <div className="gold-topic-invalidation"><strong className="fa-label gold-tone--warn">改判与失效条件</strong>
          <MarkdownViewer content={topic.falsification} readingMode="full" /></div>
        <ResearchDetails label="展开依据、传导、市场响应与反证">
        <dl className="gold-topic-reasoning">{FIELD_LABELS.slice(0, 4).map(([key, label]) => <div key={key}>
          <dt className="fa-label">{label}</dt>
          <dd><MarkdownViewer content={topic[key]} readingMode="full" /></dd></div>)}</dl>
        {topic.pending.length ? <div className="gold-topic-pending"><strong className="fa-label gold-tone--warn">这部分仍需核验</strong>
          <ul>{topic.pending.slice(0, 2).map((point, index) => <li className="fa-muted-text" key={index}>{point}</li>)}</ul>
          {topic.pending.length > 2 ? <ResearchDetails label="展开其余证据缺口"><ul>{topic.pending.slice(2).map((point, index) => <li className="fa-muted-text" key={index}>{point}</li>)}</ul></ResearchDetails> : null}</div> : null}
        <p className="fa-faint-text">研究数据时点 {dataAsOf ?? "未知"}{!current ? " · 原判断需重验" : ""}</p>
        </ResearchDetails></>}
    <GoldTopicMetrics facts={observations} reviewOnly={reviewOnly} />
  </article>;
}

export function GoldResearchTopics({ data, reviewOnly, groups, initialGroup = "changes" }: {
  data: GoldWorkspace; reviewOnly: boolean; groups?: GoldTopicGroup[]; initialGroup?: GoldTopicGroup;
}) {
  const [selected, setSelected] = useState<GoldTopicGroup>(initialGroup);
  const id = useId();
  const choices = groups ? GROUPS.filter(group => groups.includes(group.key)) : GROUPS;
  const active = choices.find(group => group.key === selected) ?? choices[0];
  const topics = data.research.topics;
  const shown = topics.filter(topic => topic.group === active?.key);
  return <section className="gold-research-topics" aria-label="黄金日报完整分析要点">
    <header className="gold-section-header"><div><h2 className="fa-section-title">日报分析要点</h2>
      <p className="fa-muted-text">判断 → 依据 → 传导 → 黄金响应 → 反证 → 改判条件</p></div>
      <FAStatusPill tone="info" dot={false}>{topics.length ? `${topics.length}项分析点` : "等待主题研究"}</FAStatusPill></header>
    {choices.length > 1 ? <nav className="gold-topic-navigation" aria-label="黄金日报分析模块">{choices.map(group => <button key={group.key}
      type="button" aria-pressed={active?.key === group.key} aria-controls={id} onClick={() => setSelected(group.key)}>
      {group.label}<span>{topics.filter(topic => topic.group === group.key).length}</span></button>)}</nav> : null}
    <div id={id}><p className="gold-topic-group-description fa-body-text">{active?.description}</p>
      {shown.length ? <div className="gold-topic-grid">{shown.map(topic => <TopicCard dataAsOf={data.research.research_identity?.data_as_of} key={topic.key} topic={topic} factors={data.factors} reviewOnly={reviewOnly} />)}</div>
        : <p className="gold-notice fa-body-text">这一组的主题分析尚未取得。完整原报告仍可查阅，更新分析后再展示。</p>}</div>
  </section>;
}
