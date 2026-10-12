import { ResearchIdentity } from "@/components/shared/ResearchIdentity";
import { Link } from "react-router-dom";
import { Activity, RefreshCw } from "lucide-react";
import { MarkdownViewer } from "@/components/reports/MarkdownViewer";
import { ResearchDetails } from "@/components/shared/ResearchDetails";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { FAWarningBanner } from "@/components/shared/FAWarningBanner";
import { useGoldWorkspace } from "@/hooks/useGoldWorkspace";
import { useGoldAnalysisRefresh } from "@/hooks/useGoldAnalysisRefresh";
import { readableWarning } from "@/lib/researchReading";
import type { GoldWorkspace } from "@/types/gold-workspace";
import type { ResearchPlanConditions } from "@/types/research-trade-plan";
import { GoldEvidenceMatrix } from "./GoldEvidenceMatrix";
import { GoldSpotLevels, GoldCmeLevels, GoldEnvironmentWatch } from "./GoldKeyLevels";
import { GoldMarketHeadline } from "./GoldMarketHeadline";
import { GoldAnalysisHorizons } from "./GoldAnalysisHorizons";
import { GoldResearchTopics } from "./GoldResearchTopics";
import { biasPresentation, scenarioTone } from "./goldPresentation";
import { GoldPriceChart } from "./GoldPriceChart";
import "@/styles/gold-workspace.css";

const conditions = (value: ResearchPlanConditions) => (Array.isArray(value) ? value : [value]).join("；");
const stepLabel = (value: string) => {
  if (/macro|fred|treasury|fedwatch/i.test(value)) return "宏观与利率";
  if (/cme|option/i.test(value)) return "CME 期权结构";
  if (/news|jin10|event/i.test(value)) return "新闻与事件";
  if (/collect|fetch|market/i.test(value)) return "行情与数据采集";
  if (/snapshot|feature|parse/i.test(value)) return "数据校验与特征";
  if (/review|audit/i.test(value)) return "研究复核";
  if (/render|report|output/i.test(value)) return "报告输出";
  if (/strateg|synth|agent|research|analysis/i.test(value)) return "综合分析与策略";
  return "分析步骤";
};
const stepStatus = (value: string) => ({ success: "完成", running: "进行中", pending: "等待", failed: "失败", blocked: "受阻", skipped: "跳过" }[value] ?? "状态待核验");

export function GoldResearchDecision({ data, reviewOnly }: { data: GoldWorkspace; reviewOnly: boolean }) {
  const r = data.research;
  const current = r.status === "current" && !reviewOnly;
  const bias = biasPresentation(r.bias);
  return <section className="fa-card gold-research-decision" aria-label="黄金方向与条件策略">
    <header className="gold-section-header"><div><h2 className="fa-section-title">{current ? "当前研究判断" : r.status === "unavailable" ? "研究判断待生成" : "最近研究判断"}</h2>
      <p className="fa-muted-text">{current ? "综合价格、宏观与资金的研究结论" : "原判断需用最新行情重验"}</p></div>
      <FAStatusPill tone={current ? "info" : "warn"}>{current ? "本次研究" : r.status === "unavailable" ? "待生成" : "历史研究 · 需更新"}</FAStatusPill></header>
    <ResearchIdentity identity={r.research_identity} />
    {r.status === "unavailable" ? <p className="fa-body-text">完整研究尚未可用。先更新数据并生成分析，当前不补造涨跌方向或入场价位。</p> : <>
      <div className="gold-research-summary"><div className="gold-direction-line"><span className="fa-label">{current ? "综合方向" : "报告当时方向"}</span>
        <FAStatusPill tone={reviewOnly ? "warn" : bias.tone}>{reviewOnly ? "等待本次核验" : bias.label}</FAStatusPill></div>
        {r.summary ? <MarkdownViewer content={r.summary} readingMode="full" /> : <p className="fa-muted-text">一句话结论尚未提供，可查看同一报告正文。</p>}</div>
    </>}
  </section>;
}

export function GoldConditionalStrategy({ data, reviewOnly }: { data: GoldWorkspace; reviewOnly: boolean }) {
  const r = data.research, plan = r.trade_plan;
  const current = r.status === "current" && !reviewOnly;
  return <section className="fa-card gold-conditional-strategy" aria-label="黄金条件策略与失效条件">
    <header className="gold-section-header"><div><h2 className="fa-section-title">策略与改判条件</h2><p className="fa-muted-text">未来1—3个交易日 · 以下路径尚未确认触发</p></div>
      <FAStatusPill tone="warn">{current ? "现在怎么做" : "原研究策略"}：{plan?.current_action ?? "等待数据与结构核验"}</FAStatusPill></header>
    <div className="gold-execution-rule"><span className="fa-body-text">4H／1H过滤方向，15m确认结构。</span>
      <strong className="fa-body-text gold-tone--warn">结构止损超过20美元/盎司 → 等待或跳过</strong></div>
    <div className="gold-scenario-grid" aria-label="主路径与方向切换条件">{plan?.scenarios.length ? plan.scenarios.map((path, index) =>
      <article key={index} className={`gold-scenario gold-scenario--${scenarioTone(path.name)}`}><h3 className={`fa-card-title gold-tone--${scenarioTone(path.name)}`}>{path.name}</h3>
        <dl><div><dt>宏观条件</dt><dd>{conditions(path.macro_conditions)}</dd></div>
          <div><dt>价格条件</dt><dd>{conditions(path.price_conditions)}</dd></div>
          <div><dt className="gold-tone--warn">失效条件</dt><dd>{conditions(path.invalidation)}</dd></div></dl></article>)
      : <p className="fa-muted-text">同一研究尚未提供完整情景，不补造主路径或做多／做空价位。</p>}</div>
    {plan?.attention_points.length ? <div className="gold-notice gold-structure-notes"><h3 className="fa-card-title">本研究的结构与事件限制</h3>
      <p className="fa-body-text">{plan.attention_points[0]}</p>
      {plan.attention_points.length > 1 ? <ResearchDetails label="展开其他结构与事件限制"><ul>{plan.attention_points.slice(1).map((point, index) => <li key={index} className="fa-body-text">{point}</li>)}</ul></ResearchDetails> : null}</div> : null}
    {plan && Object.values(plan.position_guidance).some(Boolean) ? <ResearchDetails label="按空仓、多仓、空头持仓查看条件">
      <div className="gold-position-guidance">{([
        ["flat", "空仓"], ["long", "已有多仓"], ["short", "已有空头持仓"],
      ] as const).map(([key, label]) => plan.position_guidance[key] ? <p key={key} className="fa-body-text"><strong className={key === "long" ? "gold-tone--up" : key === "short" ? "gold-tone--down" : ""}>{label}：</strong>{plan.position_guidance[key]}</p> : null)}</div>
    </ResearchDetails> : null}
    <div className="gold-decision-links">{r.report_id && r.status !== "unavailable" ? <Link to={`/reports/${encodeURIComponent(r.report_id)}`}>查看同一研究报告 →</Link> : null}
      <Link to="/strategy">查看策略条件与执行核验 →</Link></div>
    {r.narrative ? <ResearchDetails label="展开本次研究完整正文"><MarkdownViewer content={r.narrative} readingMode="full" /></ResearchDetails> : null}
  </section>;
}

export function GoldWorkspacePanel() {
  const workspace = useGoldWorkspace();
  const analysis = useGoldAnalysisRefresh(async taskId => {
    const next = await workspace.refetch();
    return Boolean(next && next.research.run_id === taskId && next.research.status !== "unavailable");
  });
  const data = workspace.data;
  const reviewOnly = Boolean(data && (workspace.loading || workspace.error));
  return <section className="gold-workspace" aria-label="黄金核心工作台">
    <header className="gold-workspace-header"><div><h1 className="fa-page-title"><Activity size={17} />黄金工作台</h1>
      <p className="fa-muted-text">当前行情 · 短线／长线分析 · 利好利空 · 条件策略</p></div>
      <div className="gold-workspace-actions"><button type="button" className="gold-secondary-button" disabled={workspace.loading}
        onClick={() => void workspace.refetch()}><RefreshCw size={14} />读取最新观测</button>
        <button type="button" className="gold-primary-button" disabled={analysis.busy} onClick={() => void analysis.start()}>
          <RefreshCw size={14} />{analysis.busy ? "分析进行中" : analysis.phase === "uncertain" ? "重新核对任务" : "更新数据并分析"}</button></div></header>
    <div className="gold-workspace-guide"><p className="fa-muted-text">自动读取行情 · 点击“更新数据并分析”生成新判断</p>
      <div className="gold-color-key" aria-label="黄金重点颜色说明"><span className="gold-tone--up">↑ 上涨／利好</span><span className="gold-tone--down">↓ 下跌／利空</span><span className="gold-tone--warn">分歧／待确认</span></div></div>
    <nav className="gold-workspace-navigation" aria-label="黄金工作台阅读导航">
      <a href="#gold-judgment">综合判断</a><a href="#gold-horizons">短线／长线</a><a href="#gold-strategy">策略与改判</a>
      <a href="#gold-levels">现货／CME关键位</a><a href="#gold-environment">环境改判</a><a href="#gold-price">走势</a><a href="#gold-topics">日报全部分析点</a>
    </nav>
    {workspace.error ? <FAWarningBanner tone="down" title="最新观测读取失败" description="暂保留上次成功结果，以下历史读数和原判断不能确认当前入场；可重新读取观测。" /> : null}
    {reviewOnly && !workspace.error ? <p className="gold-notice fa-body-text" role="status">正在读取最新观测，暂保留上次结果；等待本次核验。</p> : null}
    {analysis.message ? <div className="gold-analysis-progress" role="status" aria-live="polite"><p className="fa-body-text">{analysis.message}</p>
      {analysis.task?.steps.length ? <ol>{analysis.task.steps.map((step, index) => <li key={index} className={`gold-step gold-step--${step.status}`}>
        <span>{stepLabel(step.name)}</span><span>{stepStatus(step.status)}</span>
        {step.error ? <small>{readableWarning(step.error)}</small> : null}</li>)}</ol> : null}
      {["blocked", "failed", "uncertain"].includes(analysis.phase) || analysis.lookupError ? <div className="gold-decision-links"><Link to="/scheduler">查看分析记录 →</Link><Link to="/data-ingestion">查看数据缺口 →</Link></div> : null}
      {analysis.phase === "uncertain" ? <button type="button" className="gold-text-button" onClick={analysis.clearUncertain}>已核对分析记录，恢复分析按钮</button> : null}
    </div> : null}
    {!data ? <div className="fa-card gold-empty"><p className="fa-body-text">{workspace.loading ? "正在读取黄金行情、宏观证据和研究结果…" : "黄金观测尚未可用。可以重新读取，或启动数据更新与分析。"}</p></div> : <>
      <GoldMarketHeadline data={data} reviewOnly={reviewOnly} />
      {data.research.latest_status === "unavailable" ? <FAWarningBanner tone="warn" title="本次研究未完成，等待确认" description={data.research.status === "historical" ? "以下保留已核验的历史研究供查阅，原判断和价位需用最新行情重验。" : "当前判断尚未生成，请更新分析后再确认方向。"} /> : null}
      <div id="gold-judgment"><GoldResearchDecision data={data} reviewOnly={reviewOnly} /></div>
      <div id="gold-horizons"><GoldAnalysisHorizons data={data} reviewOnly={reviewOnly} /></div>
      <div id="gold-levels" className="gold-key-level-grid"><GoldSpotLevels data={data} /><GoldCmeLevels data={data} /></div>
      <GoldEvidenceMatrix factors={data.factors} reviewOnly={reviewOnly} />
      <div id="gold-environment"><GoldEnvironmentWatch data={data} reviewOnly={reviewOnly} /></div>
      <div id="gold-strategy"><GoldConditionalStrategy data={data} reviewOnly={reviewOnly} /></div>
    </>}
    <div id="gold-price"><GoldPriceChart /></div>
    {data ? <div id="gold-topics"><GoldResearchTopics data={data} reviewOnly={reviewOnly} /></div> : null}
  </section>;
}
