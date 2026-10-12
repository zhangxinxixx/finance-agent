import { Link } from "react-router-dom";
import { FACard } from "@/components/shared/FACard";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { useLiveStrategy } from "@/hooks/useLiveStrategy";
import { formatDateTime } from "@/lib/date";
import { getDashboardStrategyPresentation, getLiveStrategyTrustState } from "@/components/strategy/liveStrategyTrust";
import { buildDashboardStrategyNavigationState } from "@/components/strategy/StrategyEntryContext";
import { dashboardResearchAsOf, dashboardResearchDate } from "@/components/dashboard/DashboardIntegratedMacroModel";
import { hasVerifiedGoldBaseline, type LiveStrategyStatus } from "@/types/live-strategy";
import type { DashboardDataResponse } from "@/types/dashboard";

const statusLabels: Record<LiveStrategyStatus, string> = {
  WAITING: "等待中",
  WATCHING: "观察中",
  ARMED: "待确认",
  TRIGGERED: "已触发",
  SUSPENDED_DATA: "数据暂停",
};

const baselineReasons: Record<string, string> = {
  gold_daily_close_prebootstrap_hold: "首个有效日结尚未建立，当前研究仅供观察。",
  gold_direction_authority_unavailable: "等待可核验的日结方向。",
  gold_direction_authority_invalid: "日结基线校验未通过，暂停方向性策略。",
  gold_strategy_status_not_directional: "日结未给出可用方向，保持观察。",
};

/** Displays the same backend authority and feasibility as the strategy page. */
export function DashboardStrategyStatus({ dashboardResult }: { dashboardResult?: DashboardDataResponse | null }) {
  const { data, isLoading, error, refetch } = useLiveStrategy();
  const baseline = data?.data_quality.gold_baseline;
  const verified = baseline ? hasVerifiedGoldBaseline(baseline) : false;
  const trustState = getLiveStrategyTrustState({ isLoading, error });
  const current = Boolean(data && trustState === "current");
  const presentation = getDashboardStrategyPresentation({
    data,
    trustState,
    goldBaselineVerified: verified,
  });
  const { dataGateBlocked, displayStatus, ready } = presentation;
  const sourceNavigation = buildDashboardStrategyNavigationState({
        summary: dashboardResult?.summary,
        viewModel: dashboardResult?.view_model,
        dashboardResult,
        researchDate: dashboardResult?.summary ? dashboardResearchDate(dashboardResult.summary, dashboardResult.view_model) : null,
        researchAsOf: dashboardResult?.summary ? dashboardResearchAsOf(dashboardResult.summary, dashboardResult.view_model) : null,
        returnTo: "/dashboard",
        returnLabel: "返回总览",
      });
  const reason = !current
    ? error ? "策略状态读取失败，暂不能确认执行条件。" : "正在核对日结基线与实时条件。"
    : dataGateBlocked
      ? "行情或实时策略数据未通过当前核验门禁；保留后端上次状态供复盘，不能据此确认当前触发。"
    : !verified
      ? baselineReasons[baseline?.reason_code ?? ""] ?? "尚无可核验的日结方向，保持观察。"
      : data?.update_reason.message ?? "查看策略页核对触发条件和风险约束。";

  return (
    <FACard
      title="正式策略状态"
      density="compact"
      accent={ready ? "info" : "warn"}
      action={<Link to="/strategy" state={sourceNavigation ?? undefined} className="fa-label text-[var(--info)]">查看策略与证据 →</Link>}
    >
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2" aria-live="polite">
        <FAStatusPill tone={ready ? "info" : "warn"}>
          {!current ? error ? "状态不可用" : "核对中" : ready ? "执行条件已满足" : dataGateBlocked ? "当前条件无法核验" : "执行条件未满足"}
        </FAStatusPill>
        {current && data ? <span className="fa-muted-text">{dataGateBlocked ? `上次结果：${statusLabels[data.strategy_status]}` : statusLabels[displayStatus]}</span> : null}
        {current && baseline ? (
          <span className="fa-muted-text">日结方向：{verified ? baseline.gold_head_held ? "沿用已核验基线" : "已核验" : "不可用"}</span>
        ) : null}
        {current && data?.updated_at ? <time className="fa-faint-text">策略结果生成于 {formatDateTime(data.updated_at)}</time> : null}
        {current && data ? <span className="fa-faint-text">行情观测于 {data.live_market.timestamps.canonical ? formatDateTime(data.live_market.timestamps.canonical) : "未提供"}</span> : null}
        <button type="button" onClick={refetch} disabled={isLoading} className="fa-label text-[var(--info)] disabled:opacity-50">
          {isLoading ? "核对中…" : error ? "重试" : "刷新状态"}
        </button>
      </div>
      <p className="fa-muted-text mt-2">{reason}</p>
    </FACard>
  );
}
