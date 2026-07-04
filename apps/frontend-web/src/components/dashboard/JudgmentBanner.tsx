import type { DashboardAgentCompactSummary, DashboardSummary, DashboardViewModel, SignalDirection } from "@/types/dashboard";
import { DashboardJudgmentCard } from "@/components/dashboard/DashboardJudgmentCard";
import { directionLabel, translateText } from "@/components/dashboard/judgmentFormat";

interface JudgmentBannerProps {
  summary: DashboardSummary;
  viewModel?: DashboardViewModel | null;
  agentCoordinator?: DashboardAgentCompactSummary | null;
  agentSynthesis?: DashboardAgentCompactSummary | null;
}

export { translateText } from "@/components/dashboard/judgmentFormat";

export function JudgmentBanner({ summary, viewModel, agentCoordinator, agentSynthesis }: JudgmentBannerProps) {
  const { conclusion, strategy } = summary;
  const marketState = viewModel?.market_state;
  const synthesisSummary = agentSynthesis?.summary ? translateText(agentSynthesis.summary) : null;

  const direction = agentSynthesis
    ? (agentSynthesis.bias as SignalDirection)
    : agentCoordinator
      ? (agentCoordinator.bias as SignalDirection)
      : marketState?.bias === "bullish" || marketState?.bias === "bearish" || marketState?.bias === "neutral"
        ? marketState.bias
        : strategy.direction;
  const confidence =
    agentSynthesis?.confidence ??
    agentCoordinator?.confidence ??
    marketState?.confidence ??
    conclusion.confidence ??
    strategy.confidence ??
    null;
  const macroPhase = translateText(strategy.macro_phase || "—");
  const biasLabel = agentSynthesis
    ? translateText(agentSynthesis.bias)
    : agentCoordinator
      ? translateText(agentCoordinator.bias)
      : translateText(marketState?.label || strategy.bias || "—");
  const summaryText = synthesisSummary
    ? synthesisSummary
    : agentCoordinator?.summary
      ? translateText(agentCoordinator.summary)
      : translateText(marketState?.summary || strategy.bias || "—");
  const realtimeHint = summary.realtime_status?.message ? translateText(summary.realtime_status.message) : null;
  const triggers = (agentSynthesis?.keyFindings.length ? agentSynthesis.keyFindings : strategy.triggers)
    .slice(0, 3)
    .map(translateText);
  const invalids = (agentSynthesis?.invalidConditions.length ? agentSynthesis.invalidConditions : strategy.invalid_conditions)
    .slice(0, 3)
    .map(translateText);
  const compactSummary = summaryText.length > 84 ? `${summaryText.slice(0, 84).trim()}...` : summaryText;

  return (
    <DashboardJudgmentCard
      direction={direction}
      confidence={confidence}
      macroPhase={macroPhase}
      biasLabel={biasLabel || directionLabel(direction)}
      compactSummary={compactSummary}
      realtimeHint={realtimeHint}
      triggers={triggers}
      invalids={invalids}
      keyLevels={strategy.key_levels}
      agentSynthesis={agentSynthesis}
    />
  );
}
