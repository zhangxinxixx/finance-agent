import type { LiveStrategyAvailability, LiveStrategyMarket, LiveStrategyResponse, LiveStrategyStatus } from "@/types/live-strategy";

/**
 * A live strategy response can remain on screen while its next read is in
 * flight.  That response is still useful for review, but it is not evidence
 * that the current market satisfies the same conditions.  Keep this state in
 * one presentation helper so the current page and daily scenario cards use
 * the same fail-closed rule.
 */
export type LiveStrategyTrustState = "current" | "refreshing" | "unavailable";

export function getLiveStrategyTrustState({
  isLoading,
  error,
}: {
  isLoading: boolean;
  error: Error | null;
}): LiveStrategyTrustState {
  if (isLoading) return "refreshing";
  if (error) return "unavailable";
  return "current";
}

export function isLiveStrategyCurrent(state: LiveStrategyTrustState): boolean {
  return state === "current";
}

/**
 * A strategy status is only actionable when the read model carries the same
 * snapshot's usable market observation.  This is deliberately a narrow
 * presentation gate: it consumes the backend status and price as provided,
 * without deriving a trigger or recalculating any strategy condition.
 */
export function isLiveStrategyMarketUsable(
  market: Pick<LiveStrategyMarket, "status" | "price"> | null | undefined,
): boolean {
  return market?.status === "available"
    && typeof market.price === "number"
    && Number.isFinite(market.price);
}

export function getDisplayLiveStrategyStatus({
  status,
  availability,
  dataReady,
  market,
  trustState,
  goldBaselineVerified,
}: {
  status: LiveStrategyStatus;
  availability: LiveStrategyAvailability;
  dataReady: boolean;
  market: Pick<LiveStrategyMarket, "status" | "price"> | null | undefined;
  trustState: LiveStrategyTrustState;
  goldBaselineVerified: boolean;
}): LiveStrategyStatus {
  // This is a presentation-only gate. It never mutates or persists the
  // backend response; the original strategy_status remains available in the
  // evidence view for provenance.
  if (![
    "WAITING",
    "WATCHING",
    "ARMED",
    "TRIGGERED",
    "SUSPENDED_DATA",
  ].includes(status)) return "SUSPENDED_DATA";
  if (trustState !== "current" || availability !== "available" || !dataReady) return "SUSPENDED_DATA";
  if (!isLiveStrategyMarketUsable(market)) return "SUSPENDED_DATA";
  if (!goldBaselineVerified) return "WAITING";
  return status;
}

export interface DashboardStrategyPresentation {
  dataGateBlocked: boolean;
  ready: boolean;
  displayStatus: LiveStrategyStatus;
}

/**
 * The dashboard has to use the same availability gate as the strategy page.
 * This only controls presentation; it never changes the backend response or
 * decides whether a trigger exists.
 */
export function getDashboardStrategyPresentation({
  data,
  trustState,
  goldBaselineVerified,
}: {
  data: LiveStrategyResponse | null | undefined;
  trustState: LiveStrategyTrustState;
  goldBaselineVerified: boolean;
}): DashboardStrategyPresentation {
  const dataGateBlocked = !data
    || trustState !== "current"
    || data.status !== "available"
    || !data.feasibility.data_ready
    || !isLiveStrategyMarketUsable(data.live_market);
  const displayStatus = data
    ? getDisplayLiveStrategyStatus({
        status: data.strategy_status,
        availability: data.status,
        dataReady: data.feasibility.data_ready,
        market: data.live_market,
        trustState,
        goldBaselineVerified,
      })
    : "SUSPENDED_DATA";
  return {
    dataGateBlocked,
    ready: Boolean(data && !dataGateBlocked && goldBaselineVerified && data.feasibility.execution_ready),
    displayStatus,
  };
}

export function liveStrategyTrustLabel(state: LiveStrategyTrustState): string {
  if (state === "refreshing") return "正在刷新，当前条件无法核验";
  if (state === "unavailable") return "刷新失败，当前条件无法核验";
  return "本次读取成功";
}

export function liveStrategyTrustMessage(state: LiveStrategyTrustState): string {
  if (state === "refreshing") return "前端当前核验状态已暂停。保留上次成功结果供复盘；刷新完成前不把旧触发、价格或风险条件当作当前判断。";
  if (state === "unavailable") return "前端当前核验状态已暂停。保留上次成功结果供复盘；当前请求失败，不把旧触发、价格或风险条件当作当前判断。";
  return "已读取策略结果；行情、分析与参考资格须分别核对。";
}

export function liveStrategyScenarioStatusLabel(value: string | null | undefined): string {
  const labels: Record<string, string> = {
    watching: "观察中",
    armed: "待确认",
    ready: "条件已就绪",
    triggered: "已触发",
    blocked: "数据阻断",
    blocked_data: "数据阻断",
    blocked_rr: "收益风险阻断",
    unavailable: "不可用",
  };
  return labels[value ?? ""] ?? "状态未知";
}
