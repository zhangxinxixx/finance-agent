import { ResearchIdentity } from "@/components/shared/ResearchIdentity";
import type { ResearchPlanConditions, ResearchTradePlan } from "@/types/research-trade-plan";
import type { ResearchIdentity as Identity } from "@/types/research-identity";
import { MarkdownViewer } from "@/components/reports/MarkdownViewer";

function Conditions({ value }: { value: ResearchPlanConditions }) {
  return <>{(Array.isArray(value) ? value : [value]).map((line, index) => <p key={index}>{line}</p>)}</>;
}

export function ResearchTradePlanCard({ plan, identity, observation = false, embedded = false, referenceOnly = false }: {
  identity?: Identity | null;
  plan?: ResearchTradePlan | null;
  tradeDate?: string | null;
  asOf?: string | null;
  today?: string;
  observation?: boolean;
  embedded?: boolean;
  referenceOnly?: boolean;
}) {
  const historical = identity?.key_level_validity.status === "historical" || identity?.key_level_validity.status === "expired";
  const title = historical ? "历史做单条件与注意点" : referenceOnly ? "研究条件与注意点（只读参考）" : identity?.key_level_validity.status === "active" ? "当前做单策略与注意点" : "研究做单条件与注意点（有效性待核验）";
  return <section className={`research-trade-plan${embedded ? " research-trade-plan-embedded" : " fa-card"}`} aria-label={title}>
    <header>
      <h2 className="fa-section-title">{title}</h2>
      {!embedded ? <ResearchIdentity identity={identity} /> : null}
      {historical ? <p className="fa-body-text research-trade-plan-status">历史条件，需更新后重新核验。</p> : null}
      {observation && !embedded ? <p className="fa-label">研究观察稿</p> : null}
    </header>
    <p className="fa-card-title research-trade-plan-action">{historical ? "报告当时行动" : !referenceOnly && identity?.key_level_validity.status === "active" ? "当前做单策略" : "本研究行动"}：{plan?.current_action ?? "等待核验"}</p>
    <ul className="research-trade-plan-levels fa-body-text" aria-label="入场止损目标核验状态">
      <li>入场待核验</li><li>止损待核验</li><li>目标未形成</li>
    </ul>
    <p className="fa-muted-text">条件观察计划，不等于执行许可；尚无已核验的入场、止损与目标组合。</p>
    {plan ? <>
      <section aria-label="做单注意点">
        <h3 className="fa-card-title">注意点</h3>
        {plan.attention_points.length ? <ul className="research-trade-plan-attention fa-body-text">{plan.attention_points.map((point, index) => <li key={index}>{point}</li>)}</ul>
          : <p className="fa-muted-text">注意点未提供，等待核验。</p>}
      </section>
      <section aria-label="同报告判断">
        <h3 className="fa-card-title">报告判断与等待原因</h3>
        {plan.summary ? <MarkdownViewer content={plan.summary} readingMode="full" /> : null}
        <p className="fa-body-text">{plan.reason || "确认依据尚未齐备，继续等待。"}</p>
      </section>
      <section aria-label="路径等待条件与失效">
        <h3 className="fa-card-title">各路径分别等什么</h3>
        {plan.scenarios.length ? <div className="research-trade-plan-paths fa-body-text">
          {plan.scenarios.map((scenario, index) => <div className="research-trade-plan-path" key={index}>
            <h4 className="fa-card-title">{scenario.name}</h4>
            <dl>
              <div><dt className="fa-label">宏观条件</dt><dd><Conditions value={scenario.macro_conditions} /></dd></div>
              <div><dt className="fa-label">价格条件</dt><dd><Conditions value={scenario.price_conditions} /></dd></div>
              <div><dt className="fa-label">失效条件</dt><dd><Conditions value={scenario.invalidation} /></dd></div>
            </dl>
          </div>)}
        </div> : <p className="fa-muted-text">该报告未提供完整的条件路径，不补造入场价位。</p>}
      </section>
      <section aria-label="持仓状态参考">
        <h3 className="fa-card-title">持仓状态参考</h3>
        <dl className="research-trade-plan-position fa-body-text">{([
          ["flat", "空仓"], ["long", "已有多仓"], ["short", "已有空仓"],
        ] as const).map(([key, label]) => <div key={key}><dt className="fa-label">{label}</dt><dd>{plan.position_guidance[key] || "该报告未提供，等待核验。"}</dd></div>)}</dl>
      </section>
    </> : <p className="fa-body-text">完整策略未提供或尚未通过核验，请阅读同报告全文；等待核验。</p>}
  </section>;
}
