import { readerValue } from "@/lib/readerLabels";
import { EvidenceRecordActions } from "@/components/shared/EvidenceRecordActions";
import { ResearchDetails } from "@/components/shared/ResearchDetails";
import type { ReactNode } from "react";
import { RefreshCw } from "lucide-react";

import { FACard } from "@/components/shared/FACard";
import { FAStatusPill, type FAStatusTone } from "@/components/shared/FAStatusPill";
import { FAWarningBanner } from "@/components/shared/FAWarningBanner";
import { getStatusLabel } from "@/components/shared/statusMeta";
import {
  formatGoldMainlineLabel,
  formatGoldNetBiasLabel,
  formatGoldPhaseLabel,
  goldNetBiasTone,
} from "@/components/shared/goldMainlineFormat";
import type { GoldMainlineStatus, GoldNetBias, GoldPhase, GoldReadTimeSourceHealth } from "@/types/gold-mainlines";

export interface GoldTopicMetric {
  label: ReactNode;
  value: ReactNode;
  meta?: ReactNode;
  tone?: FAStatusTone;
}

interface GoldTopicStatusBarProps {
  status: GoldMainlineStatus | string | null | undefined;
  date: string | null | undefined;
  runId?: string | null;
  netBias?: GoldNetBias | string | null;
  phase?: GoldPhase | string | null;
  riskScore?: number | null;
  sourceHealth?: GoldReadTimeSourceHealth | null;
  isRefreshing?: boolean;
  refreshError?: string | null;
  lastSuccessfulAt?: string | null;
  onRefresh: () => void;
}

interface GoldDecisionTrustContext {
  isRefreshing?: boolean;
  refreshError?: string | null;
}

interface GoldTopicOverviewCardProps {
  title: ReactNode;
  eyebrow: ReactNode;
  description: ReactNode;
  accent?: "brand" | "up" | "down" | "warn" | "info" | "emphasis" | "none";
  metrics: GoldTopicMetric[];
  decisionTrustLabel?: string | null;
  decisionTrustNote?: string | null;
}

function statusTone(value: string | null | undefined): FAStatusTone {
  if (value === "available" || value === "ok" || value === "confirmed" || value === "official_confirmed" || value === "multi_source") return "up";
  if (value === "partial" || value === "stale" || value === "pending" || value === "single_source" || value === "report_derived") return "warn";
  if (value === "unavailable" || value === "failed" || value === "error") return "down";
  if (value === "unknown") return "dim";
  return "neutral";
}



function scoreLabel(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "--";
  return value <= 1 ? `${Math.round(value * 100)}` : `${Math.round(value)}`;
}

function metricToneClass(tone: FAStatusTone | undefined): string {
  if (tone === "up") return "text-[var(--up)]";
  if (tone === "down") return "text-[var(--down)]";
  if (tone === "warn") return "text-[var(--warn)]";
  if (tone === "info") return "text-[var(--info)]";
  if (tone === "dim") return "text-[var(--fg-4)]";
  return "text-[var(--fg-2)]";
}

const SOURCE_LABELS: Record<string, string> = {
  xauusd_price: "XAUUSD 价格",
  dxy: "美元指数",
  treasury_2y: "2年期美国国债",
  treasury_10y: "10年期美国国债",
  tips_10y: "10年期 TIPS 实际利率",
  fed_macro_events: "美联储与宏观事件",
  brent_wti: "Brent / WTI 原油",
  geopolitical_news: "地缘政治新闻",
  technical_levels: "黄金技术关键位",
  breakeven_inflation: "通胀盈亏平衡",
  fedwatch_ois: "政策利率预期与掉期",
  gold_etf_flows: "黄金 ETF 资金流",
  comex_cot: "COMEX COT 持仓",
  cme_options: "CME 期权",
  vix_risk_assets: "VIX 与风险资产",
  eia_inventory: "EIA 库存",
  eiainventory: "EIA 库存",
  central_bank_buying: "央行购金",
  pboc_gold_reserves: "中国央行黄金储备",
  shanghai_gold_premium: "上海黄金溢价",
  usdcnh: "美元 / 人民币汇率",
  india_physical_demand: "印度实物需求",
  asia_etf_flows: "亚洲 ETF 资金流",
  cme_daily_bulletin: "芝商所每日公告",
  macro_rates: "宏观利率",
  fedwatch: "美联储利率预期",
};

function sourceLabel(value: string): string {
  const normalized = value.trim().toLowerCase();
  return SOURCE_LABELS[normalized] ?? "未识别的数据来源";
}

function sourceIdsIn(value: string): string[] {
  const normalized = value.toLowerCase();
  return Object.keys(SOURCE_LABELS).filter((sourceId) => normalized.includes(sourceId.toLowerCase()));
}

export function suppressRepeatedSourceReason(value: string, unavailableSourceIds: Set<string>): boolean {
  // Only a repeated per-source absence message may be collapsed. An unknown
  // risk mentioning the same source can carry a different blocking reason.
  if (!/^(?:global p0 source unavailable|mainline-scoped p0 source (?:missing|stale)|p[12] source missing|non-p0 source stale):/i.test(value.trim())) return false;
  const sourceIds = sourceIdsIn(value);
  return sourceIds.length > 0 && sourceIds.every((sourceId) => unavailableSourceIds.has(sourceId));
}

export function sourceHealthStatusLabel(value: string): string {
  const normalized = value.trim().toLowerCase();
  if (normalized === "blocked") return "阻断";
  if (["degraded", "partial", "stale", "waiting_release", "expected_stale"].includes(normalized)) return "降级";
  if (normalized === "ready" || normalized === "healthy" || normalized === "ok" || normalized === "available") return "可用";
  return "未知";
}

export function isGoldDecisionBlocked(health: GoldReadTimeSourceHealth | null | undefined): boolean {
  const status = health?.overall_status?.trim().toLowerCase();
  return status === "blocked" || health?.can_emit_strong_conclusion === false;
}

function isConfirmedCurrentGoldResult(health: GoldReadTimeSourceHealth | null | undefined): boolean {
  const status = health?.overall_status?.trim().toLowerCase();
  return Boolean(
    health
    && ["ready", "healthy", "ok", "available"].includes(status ?? "")
    && health.can_emit_strong_conclusion === true,
  );
}

function isGoldResultDegraded(health: GoldReadTimeSourceHealth | null | undefined): boolean {
  const status = health?.overall_status?.trim().toLowerCase();
  return ["degraded", "partial", "stale", "waiting_release", "expected_stale"].includes(status ?? "");
}

function isRefreshReviewState(context: GoldDecisionTrustContext = {}): boolean {
  return Boolean(context.isRefreshing || context.refreshError);
}

export function goldDecisionTrustLabel(
  health: GoldReadTimeSourceHealth | null | undefined,
  context: GoldDecisionTrustContext = {},
): string {
  if (isRefreshReviewState(context)) return "上次读取结果·仅供复核";
  if (isGoldDecisionBlocked(health)) return "历史复核结果";
  if (isConfirmedCurrentGoldResult(health)) return "当前可用结果";
  if (isGoldResultDegraded(health)) return "降级复核结果";
  return "可信度未确认";
}

export function goldDecisionTrustNote(
  health: GoldReadTimeSourceHealth | null | undefined,
  context: GoldDecisionTrustContext = {},
): string | null {
  if (isRefreshReviewState(context)) return "页面仍展示上次成功读取结果；刷新未完成或失败，不能视为最新判断。";
  if (isGoldDecisionBlocked(health)) return "当前方向、阶段和风险值仅供历史复核；强结论不可用。";
  if (isGoldResultDegraded(health)) return "数据源处于降级状态，当前方向、阶段和风险值仅供复核。";
  if (!isConfirmedCurrentGoldResult(health)) return "源健康状态未完整确认，当前结果不应视为已验证的强结论。";
  return null;
}

function decisionTrustTone(
  health: GoldReadTimeSourceHealth | null | undefined,
  context: GoldDecisionTrustContext = {},
): FAStatusTone {
  if (isRefreshReviewState(context)) return "warn";
  if (isGoldDecisionBlocked(health)) return "down";
  return isConfirmedCurrentGoldResult(health) ? "up" : "warn";
}

function formatReadTime(value: string | null | undefined): string {
  if (!value) return "时间未知";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function shouldShowGoldSourceHealthBanner(
  health: GoldReadTimeSourceHealth | null | undefined,
  warnings: string[] = [],
): boolean {
  if (!health && !warnings.length) return false;
  const status = health?.overall_status?.trim().toLowerCase() ?? "unknown";
  const healthyStatus = ["ready", "healthy", "ok", "available"].includes(status);
  const hasSourceGap = Boolean(
    health?.p0_missing?.length
    || health?.p1_missing?.length
    || health?.p2_missing?.length
    || health?.stale_sources?.length
    || health?.blocked_mainlines?.length
    || health?.degraded_mainlines?.length
    || health?.blocking_reasons?.length
    || health?.warnings?.length
    || warnings.length,
  );
  return !healthyStatus || health?.can_emit_strong_conclusion !== true || hasSourceGap;
}

function sourceHealthReasonLabel(value: string): string | null {
  const normalized = value.trim();
  const lower = normalized.toLowerCase();
  if (normalized.includes("P0 source gap") && normalized.includes("strong GoldMacroOverview")) {
    return "关键源缺失，与强黄金总览结论冲突";
  }
  if (lower.includes("read_time_source_health would block strong")) {
    return "读取时源健康检查阻止强结论";
  }
  if (
    lower.startsWith("source_health_unavailable:")
    || lower.startsWith("source_health unavailable")
    || lower.startsWith("source health unavailable")
  ) {
    return "读取时源健康检查不可用";
  }
  if (lower.startsWith("global p0 source unavailable:")) {
    return "全局关键源不可用";
  }
  if (lower.startsWith("core rate/usd stack unavailable:")) {
    return "核心利率与美元链条不可用";
  }
  if (lower.startsWith("mainline-scoped p0 source missing:")) {
    return "主线所需关键源缺失";
  }
  if (lower.startsWith("mainline-scoped p0 source stale:")) {
    return "主线所需关键源已过期";
  }
  if (lower.startsWith("p1 source missing:")) {
    return "P1 辅助源缺失";
  }
  if (lower.startsWith("p2 source missing:")) {
    return "P2 辅助源缺失";
  }
  if (lower.startsWith("non-p0 source stale:")) {
    return "非核心源已过期";
  }
  return null;
}

export function GoldReadTimeSourceHealthBanner({
  health,
  warnings = [],
}: {
  health: GoldReadTimeSourceHealth | null | undefined;
  warnings?: string[];
}) {
  if (!shouldShowGoldSourceHealthBanner(health, warnings)) return null;

  const healthStatus = health?.overall_status?.trim().toLowerCase() ?? "unknown";
  const blocking = isGoldDecisionBlocked(health);
  const missingIds = [...new Set([...(health?.p0_missing ?? []), ...(health?.p1_missing ?? [])])];
  const staleIds = [...new Set(health?.stale_sources ?? [])];
  const unavailableSourceIds = new Set([...missingIds, ...staleIds]);
  const knownMissing = missingIds.filter((item) => SOURCE_LABELS[item.trim().toLowerCase()]).map(sourceLabel);
  const unknownMissing = missingIds.filter((item) => !SOURCE_LABELS[item.trim().toLowerCase()]);
  const knownStale = staleIds.filter((item) => SOURCE_LABELS[item.trim().toLowerCase()]).map(sourceLabel);
  const unknownStale = staleIds.filter((item) => !SOURCE_LABELS[item.trim().toLowerCase()]);
  const affectedMainlines = [...new Set((health?.blocked_mainlines ?? []).map((item) => formatGoldMainlineLabel(item)))];
  const degradedMainlines = [...new Set((health?.degraded_mainlines ?? []).map((item) => formatGoldMainlineLabel(item)))];
  const translatedReasons: string[] = [];
  const unknownReasonDetails: string[] = [];
  for (const rawReason of [...(health?.blocking_reasons ?? []), ...(health?.warnings ?? []), ...warnings]) {
    const raw = rawReason.trim();
    if (!raw || suppressRepeatedSourceReason(raw, unavailableSourceIds)) continue;
    const translated = sourceHealthReasonLabel(raw);
    if (translated) translatedReasons.push(translated);
    else unknownReasonDetails.push(raw);
  }
  const reasonLabels = [...new Set(translatedReasons)];
  const unknownDetails = [...new Set([
    ...unknownMissing.map((item) => `缺失源：${item}`),
    ...unknownStale.map((item) => `过期源：${item}`),
    ...unknownReasonDetails.map((item) => `未识别检查项：${item}`),
  ])];
  const details = [
    `源检查：${sourceHealthStatusLabel(healthStatus)}`,
    health?.as_of ? `检查时点：${health.as_of}` : null,
    knownMissing.length ? `缺失：${knownMissing.join("、")}` : null,
    unknownMissing.length ? "另有未识别缺失源（见来源检查明细）" : null,
    knownStale.length ? `过期：${knownStale.join("、")}` : null,
    unknownStale.length ? "另有未识别过期源（见来源检查明细）" : null,
    affectedMainlines.length ? `受影响主线：${affectedMainlines.join("、")}` : null,
    degradedMainlines.length ? `降级主线：${degradedMainlines.join("、")}` : null,
    reasonLabels.length ? `检查原因：${reasonLabels.join("；")}` : null,
    blocking ? "当前不能发出强结论；下方结果仅供复盘和证据核对" : null,
    unknownDetails.length ? "存在未识别来源检查项，见来源检查明细" : null,
  ].filter(Boolean);

  const description = (
    <>
      <div>
        {blocking ? "关键数据不足，当前不能形成可靠方向；下方判断仅供历史复核。" : "部分数据不完整，当前判断仍需复核。"}
        {knownMissing.length ? ` 缺失：${knownMissing.join("、")}。` : null}
        {knownStale.length ? ` 已过期：${knownStale.join("、")}。` : null}
        {unknownDetails.length ? "另有未识别限制，参考条件仍待确认。" : null}
      </div>
      <EvidenceRecordActions record={health} label="数据可用性检查记录" />
      <ResearchDetails label="查看数据缺口" className="mt-1">
        <p>{details.join("。") || "数据可用性尚未完整确认。"}</p>
        {unknownDetails.length ? <ul>{unknownDetails.map((item) => <li key={item}>{readerValue(item, "存在尚未解释的来源限制，需要复核。")}</li>)}</ul> : null}
      </ResearchDetails>
    </>
  );

  return (
    <FAWarningBanner
      tone={blocking ? "down" : "warn"}
      title={blocking ? "黄金主线受数据源阻断" : "黄金主线数据源需复核"}
      description={description}
    />
  );
}

export function GoldTopicStatusBar({
  status,
  date,
  netBias,
  phase,
  riskScore,
  sourceHealth,
  isRefreshing = false,
  refreshError = null,
  lastSuccessfulAt = null,
  onRefresh,
}: GoldTopicStatusBarProps) {
  const statusValue = String(status || "unknown");
  const trustContext = { isRefreshing, refreshError };
  const decisionLabel = goldDecisionTrustLabel(sourceHealth, trustContext);
  const decisionNote = goldDecisionTrustNote(sourceHealth, trustContext);
  const decisionValuePrefix = decisionLabel === "当前可用结果" ? "" : `${decisionLabel} · `;

  return (
    <div className="flex min-w-0 flex-wrap items-center justify-between gap-2 rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-card)] px-2.5 py-1.5">
      <div className="flex min-w-0 flex-wrap items-center gap-1.5">
        <FAStatusPill tone={statusTone(statusValue)} dot={false} className="px-1.5 py-[1px] text-[10px]">
          {getStatusLabel(statusValue)}
        </FAStatusPill>
        <FAStatusPill tone="neutral" dot={false} className="px-1.5 py-[1px] text-[10px]">
          {date || "日期未知"}
        </FAStatusPill>
        {netBias ? (
          <FAStatusPill tone={goldNetBiasTone(netBias)} dot={false} className="px-1.5 py-[1px] text-[10px]">
            {decisionValuePrefix}{formatGoldNetBiasLabel(netBias)}
          </FAStatusPill>
        ) : null}
        {phase ? (
          <FAStatusPill tone="dim" dot={false} className="px-1.5 py-[1px] text-[10px]">
            {decisionValuePrefix}{formatGoldPhaseLabel(phase)}
          </FAStatusPill>
        ) : null}
        {typeof riskScore === "number" && Number.isFinite(riskScore) ? (
          <FAStatusPill tone="dim" dot={false} className="px-1.5 py-[1px] text-[10px]">
            {decisionValuePrefix}风险 {scoreLabel(riskScore)}/100
          </FAStatusPill>
        ) : null}
        <FAStatusPill tone={decisionTrustTone(sourceHealth, trustContext)} dot={false} className="px-1.5 py-[1px] text-[10px]">
          {decisionLabel}
        </FAStatusPill>

      </div>
      <button
        type="button"
        onClick={onRefresh}
        disabled={isRefreshing}
        className="inline-flex h-7 shrink-0 items-center gap-1.5 rounded-[var(--radius-pill)] border border-[var(--border)] px-2.5 text-[10px] font-semibold text-[var(--fg-2)] transition-colors hover:bg-[var(--bg-panel)] disabled:cursor-wait disabled:opacity-70"
      >
        <RefreshCw size={12} className={isRefreshing ? "animate-spin" : undefined} />
        <span>{isRefreshing ? "刷新中" : "刷新"}</span>
      </button>
      {decisionNote ? (
        <div className="basis-full text-[length:var(--type-caption)] leading-5 text-[var(--warn)]">{decisionNote}</div>
      ) : null}
      {isRefreshing ? (
        <div className="basis-full text-[length:var(--type-caption)] leading-5 text-[var(--fg-4)]">
          正在刷新；页面保留上次成功读取结果。
        </div>
      ) : null}
      {refreshError ? (
        <div
          className="basis-full text-[length:var(--type-caption)] leading-5 text-[var(--down)]"
          title={refreshError}
        >
          刷新失败；当前仍展示上次成功读取结果（页面上次成功读取于：{formatReadTime(lastSuccessfulAt)}）。
        </div>
      ) : null}
    </div>
  );
}

export function GoldTopicOverviewCard({
  title,
  eyebrow,
  description,
  accent = "brand",
  metrics,
  decisionTrustLabel,
  decisionTrustNote,
}: GoldTopicOverviewCardProps) {
  const showDecisionTrust = Boolean(decisionTrustLabel && decisionTrustLabel !== "当前可用结果");
  const decisionTrustClass = decisionTrustLabel === "历史复核结果" || decisionTrustLabel?.startsWith("上次读取")
    ? "text-[var(--down)]"
    : "text-[var(--warn)]";

  return (
    <FACard
      title={title}
      eyebrow={eyebrow}
      description={(
        <div className="grid gap-0.5">
          {showDecisionTrust ? (
            <div className={`font-semibold ${decisionTrustClass}`}>
              {decisionTrustLabel}{decisionTrustNote ? `：${decisionTrustNote}` : ""}
            </div>
          ) : null}
          <span className="line-clamp-2">{description}</span>
        </div>
      )}
      accent={accent}
      density="compact"
      className="shrink-0"
      bodyClassName="!p-2.5"
    >
      <div className="grid gap-1.5 sm:grid-cols-2 xl:grid-cols-4">
        {metrics.map((metric, index) => (
          <div
            key={index}
            className="min-w-0 rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2.5 py-1.5"
          >
            <div className="truncate text-[10px] font-semibold text-[var(--fg-5)]">{metric.label}</div>
            <div className={`mt-0.5 truncate text-[13px] font-semibold ${metricToneClass(metric.tone)}`}>
              {metric.value}
            </div>
            {metric.meta ? <div className="mt-0.5 truncate text-[10px] text-[var(--fg-5)]">{metric.meta}</div> : null}
          </div>
        ))}
      </div>
    </FACard>
  );
}
