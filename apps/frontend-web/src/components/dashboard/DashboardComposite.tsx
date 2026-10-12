import type { DashboardDataResponse, DashboardSummary, DashboardViewModel } from "@/types/dashboard";
import { DashboardCompositeBody, DashboardCompositeHeader } from "./DashboardCompositeSections";
import { translateText } from "./judgmentFormat";
import { dashboardResearchAsOf, dashboardResearchDate } from "./DashboardIntegratedMacroModel";
import { buildDashboardStrategyNavigationState } from "@/components/strategy/StrategyEntryContext";

interface DashboardCompositeProps {
  summary: DashboardSummary;
  viewModel?: DashboardViewModel | null;
  dashboardResult?: DashboardDataResponse | null;
}

export function DashboardComposite({ summary, viewModel, dashboardResult }: DashboardCompositeProps) {
  const dataDate = dashboardResearchDate(summary, viewModel);
  const sourceTrace = summary.source_trace.slice(0, 3);
  const hasFullReport = summary.latest_reports.some((r) => r.status === "ready");
  const research = summary.integrated_macro;
  const agent = summary.agent_summary?.synthesis ?? summary.agent_summary?.coordinator;
  const confidence = research ? research.confidence : agent?.confidence;
  const confidencePct = typeof confidence === "number" && Number.isFinite(confidence)
    ? Math.round(Math.max(0, Math.min(1, confidence)) * 100) : null;

  const rawCompositeSummary =
    (research ? research.reasoning?.trim() || research.trade_implication?.trim() : agent?.summary?.trim()) ||
    "本次研究尚未提供综合分析摘要。";
  const compositeSummary = translateText(rawCompositeSummary);

  const rawRevision =
    (research ? research.invalidation : agent?.invalidConditions)?.filter((item) => item.trim()).join("；") ||
    "当前未提供明确改判条件。";
  const revision = translateText(rawRevision);

  const resonanceItems = [
    ...summary.cme_options.lower_support_walls.slice(0, 2).map((item, index) => ({
      px: `${item.strike}`,
      macro: `GC 期货结构 · ${summary.cme_options.trade_date || "日期未提供"}`,
      options: `下方支撑墙，结构评分 ${item.score.toFixed(2)}`,
      verdict: "结构参考，现货触发未核验",
      kind: "support" as const,
      core: index === 0,
    })),
    ...(typeof summary.cme_options.gamma_zero === "number" && Number.isFinite(summary.cme_options.gamma_zero)
      ? [{
          px: summary.cme_options.gamma_zero.toFixed(1),
          macro: "GC 期货代理坐标",
          options: "所选到期窗口的估算Gamma转换带",
          verdict: "按持仓量估算的Gamma敞口；做市商方向未知",
          kind: "pivot" as const,
          core: true,
        }]
      : []),
    ...summary.cme_options.upper_resistance_walls.slice(0, 2).map((item, index) => ({
      px: `${item.strike}`,
      macro: `GC 期货结构 · ${summary.cme_options.trade_date || "日期未提供"}`,
      options: `上方阻力墙，结构评分 ${item.score.toFixed(2)}`,
      verdict: "结构参考，现货触发未核验",
      kind: "resist" as const,
      core: index === 0,
    })),
  ];

  return (
    <div className="fa-card">
      <DashboardCompositeHeader dataDate={dataDate} hasFullReport={hasFullReport} sourceTrace={sourceTrace}
        strategyNavigation={buildDashboardStrategyNavigationState({ summary, viewModel, dashboardResult, researchDate: dataDate, researchAsOf: dashboardResearchAsOf(summary, viewModel), returnTo: "/dashboard/analysis" })} />
      <DashboardCompositeBody
        compositeSummary={compositeSummary}
        revision={revision}
        confidencePct={confidencePct}
        resonanceItems={resonanceItems}
      />
      <div className="px-3 pb-3 fa-muted-text">
        <p>期权结构独立标注 GC 坐标与公告日期，不代表与本研究同一数据时点，也不作为 XAUUSD 现货触发条件。</p>
        {(research?.risks ?? agent?.riskPoints ?? []).map((risk, index) => <p key={index}>风险：{translateText(risk)}</p>)}
      </div>
    </div>
  );
}
