import { textOrDash } from "@/components/market-monitor/format";
import { formatDateTime } from "@/lib/date";
import type { MarketMonitorMockFile } from "@/types/market-monitor";
import type { Jin10CalendarFreshness, Jin10CalendarStats } from "@/hooks/useJin10Calendar";

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

export function OverviewEntryGrid({
  latestDate,
  historySummary,
  sourceLabel,
  realtimeRegime,
  primaryDriver,
}: {
  latestDate: string;
  historySummary: string | null;
  sourceLabel: string;
  realtimeRegime: MarketMonitorMockFile["realtime_regime"] | null | undefined;
  primaryDriver: MarketMonitorMockFile["primary_driver"] | null | undefined;
}) {
  return (
    <div className="market-monitor-overview-entry-layout">
      <div className="market-monitor-overview-entry-grid">
        {[
          { title: "定价链", meta: `历史 ${historySummary ?? "不可用"}` },
          { title: "跨资产", meta: `最新 ${latestDate}` },
          { title: "日历 / 事件", meta: `主驱动 ${textOrDash(primaryDriver?.driver ?? null)}` },
        ].map((entry) => (
          <article key={entry.title} className="market-monitor-overview-entry-card">
            <div className="market-monitor-overview-entry-title">{entry.title}</div>
            <div className="market-monitor-overview-entry-meta">{entry.meta}</div>
          </article>
        ))}
      </div>
      <div className="market-monitor-overview-side-grid">
        <div className="market-monitor-overview-side-card">
          <div className="market-monitor-overview-entry-title">实时状态</div>
          <div className="market-monitor-overview-entry-meta">
            {textOrDash(realtimeRegime?.regime ?? null)}
          </div>
          <div className="market-monitor-overview-entry-meta">
            置信度 {typeof realtimeRegime?.confidence === "number" ? `${(realtimeRegime.confidence * 100).toFixed(0)}%` : "—"}
          </div>
        </div>
        <div className="market-monitor-overview-side-card">
          <div className="market-monitor-overview-entry-title">主驱动</div>
          <div className="market-monitor-overview-entry-meta">{textOrDash(primaryDriver?.secondary ?? null)}</div>
        </div>
        <div className="market-monitor-overview-side-card">
          <div className="market-monitor-overview-entry-title">来源上下文</div>
          <div className="market-monitor-overview-entry-meta">overview 只保留诊断摘要，详细数据转入分区查看</div>
        </div>
      </div>
    </div>
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
    { label: "待公布", value: String(calendarStats?.upcoming ?? 0) },
    { label: "已公布", value: String(calendarStats?.released ?? 0) },
    { label: "高影响", value: String(calendarStats?.high_impact ?? 0) },
    { label: "溯源", value: `${sourceTraceCount}` },
  ];
  const freshnessText = calendarFreshness?.is_stale
    ? "当前窗口偏旧，优先看下方事件列表。"
    : "优先看事件列表，摘要只保留扫描信息。";
  const freshnessTone = calendarFreshness?.is_stale || calendarStatus === "stale" ? "text-[var(--warn)]" : "text-[var(--fg-4)]";

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
          <span className="market-monitor-calendar-brief-chip-label">实时状态</span>
          <span className="market-monitor-calendar-brief-chip-value">{textOrDash(realtimeRegime?.regime ?? null)}</span>
        </div>
      </div>
      <div className={`market-monitor-calendar-brief-footnote ${freshnessTone}`}>
        置信度 {typeof realtimeRegime?.confidence === "number" ? `${(realtimeRegime.confidence * 100).toFixed(0)}%` : "—"} · {sourceLabel} · {sourceTraceCount} 条溯源{generatedAt ? ` · 缓存 ${formatDateTime(generatedAt)}` : ""}
      </div>
    </section>
  );
}
