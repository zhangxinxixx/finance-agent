import type { DashboardSummary, DashboardViewModel } from "@/types/dashboard";
import { DashboardCompositeBody, DashboardCompositeHeader } from "./DashboardCompositeSections";
import { translateText } from "./judgmentFormat";

interface DashboardCompositeProps {
  summary: DashboardSummary;
  viewModel?: DashboardViewModel | null;
}

export function DashboardComposite({ summary, viewModel }: DashboardCompositeProps) {
  const dataDate = viewModel?.trade_date ?? summary.cme_options.trade_date ?? summary.generated_at?.slice(0, 10) ?? "—";
  const sourceTrace = summary.source_trace.slice(0, 3);
  const hasFullReport = summary.latest_reports.some((r) => r.status === "ready");
  const strategyView = viewModel?.strategy_card ?? null;
  const confidence = strategyView?.confidence ?? viewModel?.market_state.confidence ?? null;
  const confidencePct = confidence == null ? null : Math.round(Math.max(0, Math.min(1, confidence)) * 100);

  const rawCompositeSummary =
    strategyView?.scenario_summary?.trim() ||
    viewModel?.market_state.summary?.trim() ||
    summary.agent_summary?.synthesis?.summary?.trim() ||
    summary.agent_summary?.coordinator?.summary?.trim() ||
    summary.conclusion.options_summary ||
    "等待后端生成综合分析摘要。";
  const compositeSummary = translateText(rawCompositeSummary);

  const rawRevision =
    strategyView?.invalid_conditions.find((item) => item.trim().length > 0) ||
    strategyView?.risk_points.find((item) => item.trim().length > 0) ||
    summary.risk_alerts[0] ||
    "当前未提供明确改判条件。";
  const revision = translateText(rawRevision);

  const resonanceItems = [
    ...summary.cme_options.lower_support_walls.slice(0, 2).map((item, index) => ({
      px: `${item.strike}`,
      macro: index === 0 ? viewModel?.macro_summary?.phase || "宏观阶段待确认" : "下方支撑观察位",
      options: `下方支撑墙，score ${item.score.toFixed(2)}`,
      verdict: index === 0 ? "优先观察支撑有效性" : "次级支撑位",
      kind: "support" as const,
      core: index === 0,
    })),
    ...(summary.cme_options.gamma_zero != null
      ? [{
          px: summary.cme_options.gamma_zero.toFixed(1),
          macro: "期权中性带",
          options: "Gamma Zero / Pin 参考位",
          verdict: "作为盘中多空转换观察位",
          kind: "pivot" as const,
          core: true,
        }]
      : []),
    ...summary.cme_options.upper_resistance_walls.slice(0, 2).map((item, index) => ({
      px: `${item.strike}`,
      macro: "上方阻力观察位",
      options: `上方阻力墙，score ${item.score.toFixed(2)}`,
      verdict: index === 0 ? "优先观察突破确认" : "次级阻力位",
      kind: "resist" as const,
      core: index === 0,
    })),
  ];

  return (
    <div className="fa-card">
      <DashboardCompositeHeader dataDate={dataDate} hasFullReport={hasFullReport} sourceTrace={sourceTrace} />
      <DashboardCompositeBody
        compositeSummary={compositeSummary}
        revision={revision}
        confidencePct={confidencePct}
        resonanceItems={resonanceItems}
      />
    </div>
  );
}
