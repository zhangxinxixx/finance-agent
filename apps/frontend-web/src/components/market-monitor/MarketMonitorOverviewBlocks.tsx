import { formatDateTime } from "@/lib/date";
import type { MarketMonitorMockFile } from "@/types/market-monitor";
import type { Jin10CalendarFreshness, Jin10CalendarStats } from "@/hooks/useJin10Calendar";
import { textOrDash } from "./format";

const REALTIME_REGIME_LABELS: Record<string, string> = {
  dovish_gold_friendly: "宽松环境，黄金偏友好",
  hawkish_gold_pressure: "鹰派环境，黄金承压",
  neutral_soft: "中性偏宽松",
  neutral_firm: "中性偏紧",
  neutral: "中性阶段",
};

export function formatRealtimeRegimeLabel(
  realtimeRegime: MarketMonitorMockFile["realtime_regime"] | null | undefined,
): string {
  if (realtimeRegime?.available !== true) return "待确认";
  return REALTIME_REGIME_LABELS[realtimeRegime.regime] ?? "阶段待确认";
}

function formatRealtimeConfidence(
  realtimeRegime: MarketMonitorMockFile["realtime_regime"] | null | undefined,
): string {
  if (realtimeRegime?.available !== true || typeof realtimeRegime.confidence !== "number") return "未量化";
  return `${(realtimeRegime.confidence * 100).toFixed(0)}%`;
}

export function OverviewHero({
  title,
  meta,
  summary,
}: {
  title: string;
  meta: string;
  summary: string;
}) {
  return (
    <section className="market-monitor-overview-hero">
      <div className="min-w-0">
        <div className="market-monitor-overview-kicker">市场总览</div>
        <div className="market-monitor-overview-title">{title}</div>
        <div className="market-monitor-overview-summary">{summary}</div>
      </div>
      <div className="market-monitor-overview-context">
        <div className="market-monitor-overview-meta">{meta}</div>
      </div>
    </section>
  );
}

export function CalendarEventBrief({
  sourceLabel,
  latestDate,
  generatedAt,
  calendarStatus,
  calendarStats,
  calendarFreshness,
  realtimeRegime,
  sourceTraceCount,
}: {
  sourceLabel: string;
  latestDate: string;
  generatedAt: string | null;
  calendarStatus: string;
  calendarStats: Jin10CalendarStats | null;
  calendarFreshness: Jin10CalendarFreshness | null;
  realtimeRegime: MarketMonitorMockFile["realtime_regime"] | null | undefined;
  sourceTraceCount: number;
}) {
  const pills = [
    { label: "来源", value: sourceLabel },
    { label: "快照", value: latestDate },
    { label: "缓存", value: generatedAt ? formatDateTime(generatedAt) : "—" },
    { label: "待公布", value: textOrDash(calendarStats?.upcoming) },
    { label: "已公布", value: textOrDash(calendarStats?.released) },
    { label: "高影响", value: textOrDash(calendarStats?.high_impact) },
    { label: "溯源", value: `${sourceTraceCount}` },
  ];
  const freshnessText = calendarFreshness?.is_stale
    ? "当前窗口偏旧，优先看下方事件列表。"
    : "优先看事件列表，摘要只保留扫描信息。";
  const freshnessTone = calendarFreshness?.is_stale || calendarStatus === "stale" ? "text-[var(--warn)]" : "text-[var(--fg-4)]";
  const realtimeRegimeLabel = formatRealtimeRegimeLabel(realtimeRegime);
  const realtimeConfidence = formatRealtimeConfidence(realtimeRegime);

  return (
    <section className="market-monitor-calendar-brief">
      <div className="market-monitor-calendar-brief-row">
        <div className="min-w-0">
          <div className="market-monitor-calendar-brief-kicker">日历摘要</div>
          <div className="market-monitor-calendar-brief-title">事件与阶段</div>
        </div>
        <div className={`market-monitor-calendar-brief-freshness ${freshnessTone}`}>{freshnessText}</div>
      </div>
      <div className="market-monitor-calendar-brief-meta">
        {pills.map((pill) => (
          <div key={pill.label} className="market-monitor-calendar-brief-chip">
            <span className="market-monitor-calendar-brief-chip-label">{pill.label}</span>
            <span className="market-monitor-calendar-brief-chip-value">{pill.value}</span>
          </div>
        ))}
        <div className="market-monitor-calendar-brief-chip market-monitor-calendar-brief-chip--wide">
          <span className="market-monitor-calendar-brief-chip-label">实时阶段</span>
          <span className="market-monitor-calendar-brief-chip-value">{realtimeRegimeLabel}</span>
        </div>
      </div>
      <div className={`market-monitor-calendar-brief-footnote ${freshnessTone}`}>
        阶段把握程度 {realtimeConfidence} · {sourceLabel} · {sourceTraceCount} 条溯源{generatedAt ? ` · 缓存 ${formatDateTime(generatedAt)}` : ""}
      </div>
    </section>
  );
}
