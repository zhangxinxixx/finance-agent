import { ResearchIdentity } from "@/components/shared/ResearchIdentity";
import { useEffect } from "react";
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
import { beijingTime } from "@/components/dashboard/DashboardResearchBriefModel";
import { GoldResearchLinks } from "./GoldResearchLinks";
import type { GoldReadingContext } from "./goldReadingNavigation";

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
  const change = r.topics.find(topic => topic.group === "changes" && topic.status !== "unavailable"
    && topic.judgment.trim() && topic.judgment.trim() !== r.summary.trim());
  return <section className="fa-card gold-research-decision" aria-label="黄金方向与条件策略">
    <header className="gold-section-header"><div><h2 className="fa-section-title">{current ? "当前研究判断" : r.status === "unavailable" ? "研究判断待生成" : "最近研究判断"}</h2>
      <p className="fa-muted-text">研究交易日 {r.trade_date ?? "未提供"} · 数据时点 {beijingTime(r.research_identity?.data_as_of)}</p></div>
      <FAStatusPill tone={current ? "info" : "warn"}>{current ? "本次研究" : r.status === "unavailable" ? "待生成" : "历史研究 · 需更新"}</FAStatusPill></header>
    {r.status === "unavailable" ? <p className="fa-body-text">完整研究尚未可用。先更新数据并生成分析，当前不补造涨跌方向或入场价位。</p> : <>
      <div className="gold-research-summary"><div className="gold-direction-line"><span className="fa-label">{current ? "综合方向" : "报告当时方向"}</span>
        <FAStatusPill tone={reviewOnly ? "warn" : bias.tone}>{reviewOnly ? "等待本次核验" : bias.label}</FAStatusPill></div>
        {r.summary ? <><MarkdownViewer content={r.summary.split(/\n\s*\n/)[0]} readingMode="full" />
          {r.summary.split(/\n\s*\n/).length > 1 ? <ResearchDetails label="展开研究摘要全文"><MarkdownViewer content={r.summary} readingMode="full" /></ResearchDetails> : null}</>
          : <p className="fa-muted-text">一句话结论尚未提供，可查看同一报告正文。</p>}</div>
    </>}
    <div className="gold-reading-risk" role="note" aria-label="优先阅读的风险与限制">
      <strong className="fa-card-title">{r.latest_status === "unavailable" ? "本次研究未完成" : reviewOnly ? "上次结果 · 等待本次核验" : r.status === "historical" ? "历史研究 · 原条件需重验" : "研究观察 · 条件未确认触发"}</strong>
      <p className="fa-body-text">{reviewOnly || r.status !== "current" ? "原判断需用最新行情重验；原策略仅供阅读，不能确认当前入场。" : r.trade_plan?.current_action ?? "策略条件未提供，需核验。"}</p>
      <p className="fa-body-text">{r.trade_plan?.attention_points[0] ?? data.warnings[0] ?? "重大风险未提供，进入同一研究报告核验。"}</p>
      <a className="fa-label" href="#gold-strategy">查看失效条件与完整情景 ↓</a>
    </div>
    <div className="gold-research-summary"><span className="fa-label">{current ? "主要变化" : "报告当时变化"}</span>
      {change ? <MarkdownViewer content={change.judgment.split(/\n\s*\n/)[0]} readingMode="full" />
        : <p className="fa-muted-text">未提供独立变化摘要，进入同一报告核验。</p>}</div>
    <GoldResearchLinks data={data} />
    <ResearchDetails label="查看研究身份、点位有效性与其他限制">
      <ResearchIdentity identity={r.research_identity} />
      <p className="fa-body-text">当前研究仅作观察参考，不代表正式交易指令。</p>
      {data.warnings.map((warning, index) => <p key={index} className="fa-body-text">{warning}</p>)}
    </ResearchDetails>
  </section>;
}

export function GoldConditionalStrategy({ data, reviewOnly }: { data: GoldWorkspace; reviewOnly: boolean }) {
  const r = data.research, plan = r.trade_plan;
  const current = r.status === "current" && !reviewOnly;
  return <section className="fa-card gold-conditional-strategy" aria-label="黄金条件策略与失效条件">
    <header className="gold-section-header"><div><h2 className="fa-section-title">策略与改判条件</h2><p className="fa-muted-text">未来1—3个交易日 · 以下路径尚未确认触发</p></div>
      <FAStatusPill tone="warn">{current ? "条件未确认触发" : "原研究策略 · 需重验"}</FAStatusPill></header>
    <div className="gold-execution-rule"><span className="fa-body-text">4H／1H过滤方向，15m确认结构。</span>
      <strong className="fa-body-text gold-tone--warn">结构止损超过20美元/盎司 → 等待或跳过</strong></div>
    {plan?.scenarios[0] ? <p className="fa-body-text"><strong className="gold-tone--warn">{plan.scenarios[0].name}的失效条件：</strong>{conditions(plan.scenarios[0].invalidation)}</p>
      : <p className="fa-muted-text">本研究未提供失效条件，需进入报告核验。</p>}
    <ResearchDetails label="展开完整情景、宏观与价格条件">
    <div className="gold-scenario-grid" aria-label="主路径与方向切换条件">{plan?.scenarios.length ? plan.scenarios.map((path, index) =>
      <article key={index} className={`gold-scenario gold-scenario--${scenarioTone(path.name)}`}><h3 className={`fa-card-title gold-tone--${scenarioTone(path.name)}`}>{path.name}</h3>
        <dl><div><dt>宏观条件</dt><dd>{conditions(path.macro_conditions)}</dd></div>
          <div><dt>价格条件</dt><dd>{conditions(path.price_conditions)}</dd></div>
          <div><dt className="gold-tone--warn">失效条件</dt><dd>{conditions(path.invalidation)}</dd></div></dl></article>)
      : <p className="fa-muted-text">同一研究尚未提供完整情景，不补造主路径或做多／做空价位。</p>}</div>
    {plan?.attention_points.length ? <div className="gold-notice gold-structure-notes"><h3 className="fa-card-title">本研究的结构与事件限制</h3>
      <ul>{plan.attention_points.map((point, index) => <li key={index} className="fa-body-text">{point}</li>)}</ul></div> : null}
    {plan && Object.values(plan.position_guidance).some(Boolean) ? <ResearchDetails label="按空仓、多仓、空头持仓查看条件">
      <div className="gold-position-guidance">{([
        ["flat", "空仓"], ["long", "已有多仓"], ["short", "已有空头持仓"],
      ] as const).map(([key, label]) => plan.position_guidance[key] ? <p key={key} className="fa-body-text"><strong className={key === "long" ? "gold-tone--up" : key === "short" ? "gold-tone--down" : ""}>{label}：</strong>{plan.position_guidance[key]}</p> : null)}</div>
    </ResearchDetails> : null}
    </ResearchDetails>
    {r.narrative ? <ResearchDetails label="展开本次研究完整正文"><MarkdownViewer content={r.narrative} readingMode="full" /></ResearchDetails> : null}
  </section>;
}

export function GoldWorkspacePanel({ frozenReading, onLatest }: { frozenReading?: GoldReadingContext | null; onLatest?: () => void }) {
  const workspace = useGoldWorkspace(!frozenReading);
  const analysis = useGoldAnalysisRefresh(async taskId => {
    const next = await workspace.refetch();
    return Boolean(next && next.research.run_id === taskId && next.research.status !== "unavailable");
  }, !frozenReading);
  const data = frozenReading?.workspace ?? workspace.data;
  const reviewOnly = Boolean(frozenReading || data && (workspace.loading || workspace.error));
  useEffect(() => {
    if (!frozenReading) return;
    // AppShell resets route scroll at 0/150ms. Restore only this page, after lazy details mount.
    const timer = window.setTimeout(() => {
      const root = document.querySelector(".gold-workspace");
      root?.querySelectorAll<HTMLDetailsElement>("details").forEach((details, index) => {
        if (frozenReading.expandedSections.includes(`${index}:${details.querySelector("summary")?.textContent ?? ""}`)) details.open = true;
      });
      window.requestAnimationFrame(() => window.requestAnimationFrame(() => {
        document.querySelector(".app-content")?.scrollTo({ top: frozenReading.scrollTop });
        Array.from(root?.querySelectorAll<HTMLAnchorElement>(".gold-decision-links a") ?? [])
          .find(link => link.textContent === frozenReading.focusLabel)?.focus({ preventScroll: true });
      }));
    }, 220);
    return () => window.clearTimeout(timer);
  }, [frozenReading]);
  return <section className="gold-workspace" aria-label="黄金核心工作台">
    <header className="gold-workspace-header"><div><h1 className="fa-page-title"><Activity size={17} />黄金工作台</h1>
      <p className="fa-muted-text">当前行情 · 短线／长线分析 · 利好利空 · 条件策略</p></div>
      <div className="gold-workspace-actions">{frozenReading ? <button type="button" className="gold-secondary-button" onClick={onLatest}>返回最新黄金工作台</button> : <><button type="button" className="gold-secondary-button" disabled={workspace.loading}
        onClick={() => void workspace.refetch()}><RefreshCw size={14} />读取最新观测</button>
        <button type="button" className="gold-primary-button" disabled={analysis.busy} onClick={() => void analysis.start()}>
          <RefreshCw size={14} />{analysis.busy ? "分析进行中" : analysis.phase === "uncertain" ? "重新核对任务" : "更新数据并分析"}</button></>}</div></header>
    <p className="fa-muted-text" role={frozenReading ? "status" : undefined}>{frozenReading ? "冻结研究 · 不是当前执行许可；保留离开时的研究和观测，不补入最新数据。" : "自动读取行情 · 观测和研究分别更新，读取观测不生成新判断。"}</p>
    {workspace.error ? <FAWarningBanner tone="down" title="最新观测读取失败" description="暂保留上次成功结果，以下历史读数和原判断不能确认当前入场；可重新读取观测。" /> : null}
    {data && workspace.loading && !frozenReading && !workspace.error ? <p className="gold-notice fa-body-text" role="status">正在读取最新观测，暂保留上次结果；等待本次核验。</p> : null}
    {analysis.message ? <div className="gold-analysis-progress" role="status" aria-live="polite"><p className="fa-body-text">{analysis.message}</p>
      {analysis.task?.steps.length ? <ol>{analysis.task.steps.map((step, index) => <li key={index} className={`gold-step gold-step--${step.status}`}>
        <span>{stepLabel(step.name)}</span><span>{stepStatus(step.status)}</span>
        {step.error ? <small>{readableWarning(step.error)}</small> : null}</li>)}</ol> : null}
      {["blocked", "failed", "uncertain"].includes(analysis.phase) || analysis.lookupError ? <div className="gold-decision-links"><Link to="/scheduler">查看分析记录 →</Link><Link to="/data-ingestion">查看数据缺口 →</Link></div> : null}
      {analysis.phase === "uncertain" ? <button type="button" className="gold-text-button" onClick={analysis.clearUncertain}>已核对分析记录，恢复分析按钮</button> : null}
    </div> : null}
    {!data ? <div className="fa-card gold-empty"><p className="fa-body-text">{workspace.loading ? "正在读取黄金行情、宏观证据和研究结果…" : "黄金观测尚未可用。可以重新读取，或启动数据更新与分析。"}</p></div> : <>
      <div id="gold-judgment"><GoldResearchDecision data={data} reviewOnly={reviewOnly} /></div>
      <nav className="gold-workspace-navigation" aria-label="黄金工作台阅读导航">
        <a href="#gold-judgment">综合判断</a><a href="#gold-strategy">风险与条件</a><a href="#gold-horizons">短线／长线</a>
        <a href="#gold-levels">现货／CME关键位</a><a href="#gold-evidence">宏观证据</a><a href="#gold-environment">环境改判</a><a href="#gold-price">走势</a><a href="#gold-topics">日报全部分析点</a>
      </nav>
      <div id="gold-strategy"><GoldConditionalStrategy data={data} reviewOnly={reviewOnly} /></div>
      <div id="gold-horizons"><GoldAnalysisHorizons data={data} reviewOnly={reviewOnly} /></div>
      <GoldMarketHeadline data={data} reviewOnly={reviewOnly} />
      <div id="gold-levels" className="gold-key-level-grid"><GoldSpotLevels data={data} reviewOnly={reviewOnly} /><GoldCmeLevels data={data} reviewOnly={reviewOnly} /></div>
      <div id="gold-evidence"><GoldEvidenceMatrix factors={data.factors} reviewOnly={reviewOnly} /></div>
      <div id="gold-environment"><GoldEnvironmentWatch data={data} reviewOnly={reviewOnly} /></div>
    </>}
    <div id="gold-price">{frozenReading ? <p className="gold-notice fa-body-text">冻结研究不加载实时走势图；返回最新黄金工作台查看独立行情。</p> : <GoldPriceChart />}</div>
    {data ? <div id="gold-topics"><GoldResearchTopics data={data} reviewOnly={reviewOnly} initialGroup={frozenReading?.topicGroup} /></div> : null}
  </section>;
}
