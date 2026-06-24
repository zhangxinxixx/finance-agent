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
    <section
      style={{
        border: "1px solid var(--border-faint)",
        borderRadius: "var(--radius-lg)",
        background: "linear-gradient(180deg, rgba(255,255,255,0.02), rgba(255,255,255,0.01)) , var(--bg-panel)",
        padding: "14px 16px",
        display: "grid",
        gridTemplateColumns: "minmax(0,1fr) 220px",
        gap: 16,
        alignItems: "start",
      }}
    >
      <div className="min-w-0">
        <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">市场总览</div>
        <div className="mt-1 text-[15px] font-semibold text-[var(--fg-1)]">{title}</div>
        <div className="mt-2 text-[11px] leading-6 text-[var(--fg-3)]">{summary}</div>
      </div>
      <div
        style={{
          borderLeft: "1px solid var(--border-faint)",
          paddingLeft: 16,
          display: "flex",
          flexDirection: "column",
          gap: 8,
        }}
      >
        <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">交易时段上下文</div>
        <div className="text-[11px] text-[var(--fg-3)]">{meta}</div>
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
  const entries = [
    {
      title: "定价链",
      summary: "查看黄金定价链、关键因子和历史走势。",
      meta: `历史 ${historySummary ?? "不可用"}`,
    },
    {
      title: "跨资产",
      summary: "查看资产分组、热力图和联动矩阵。",
      meta: `最新 ${latestDate}`,
    },
    {
      title: "日历 / 事件",
      summary: "查看事件阶段、driver 和来源溯源摘要。",
      meta: `主驱动 ${textOrDash(primaryDriver?.driver ?? null)}`,
    },
  ];

  return (
    <div className="grid gap-3 xl:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
      <div className="grid gap-3 sm:grid-cols-3">
        {entries.map((entry) => (
          <article key={entry.title} className="rounded-[14px] border border-[var(--border-faint)] bg-[var(--bg-panel)] px-4 py-4">
            <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">{entry.title}</div>
            <div className="mt-2 text-[14px] font-semibold text-[var(--fg-1)]">{entry.summary}</div>
            <div className="mt-2 text-[10px] text-[var(--fg-4)]">{entry.meta}</div>
          </article>
        ))}
      </div>
      <div className="grid gap-3 sm:grid-cols-3 xl:grid-cols-1">
        <div className="rounded-[14px] border border-[var(--border-faint)] bg-[var(--bg-panel)] px-4 py-4">
          <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">实时状态</div>
          <div className="mt-2 text-[14px] font-semibold text-[var(--fg-1)]">{textOrDash(realtimeRegime?.regime ?? null)}</div>
          <div className="mt-1 text-[10px] text-[var(--fg-4)]">
            置信度 {typeof realtimeRegime?.confidence === "number" ? `${(realtimeRegime.confidence * 100).toFixed(0)}%` : "—"}
          </div>
        </div>
        <div className="rounded-[14px] border border-[var(--border-faint)] bg-[var(--bg-panel)] px-4 py-4">
          <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">主驱动</div>
          <div className="mt-2 text-[14px] font-semibold text-[var(--fg-1)]">{textOrDash(primaryDriver?.driver ?? null)}</div>
          <div className="mt-1 text-[10px] text-[var(--fg-4)]">{textOrDash(primaryDriver?.secondary ?? null)}</div>
        </div>
        <div className="rounded-[14px] border border-[var(--border-faint)] bg-[var(--bg-panel)] px-4 py-4">
          <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">来源上下文</div>
          <div className="mt-2 text-[14px] font-semibold text-[var(--fg-1)]">{sourceLabel}</div>
          <div className="mt-1 text-[10px] text-[var(--fg-4)]">overview 只保留诊断摘要，详细数据转入分区查看</div>
        </div>
      </div>
    </div>
  );
}

export function CalendarEventBrief({
  sourceLabel,
  latestDate,
  historySummary,
  generatedAt,
  calendarStatus,
  calendarStats,
  calendarFreshness,
  realtimeRegime,
  primaryDriver,
  sourceTraceCount,
}: {
  sourceLabel: string;
  latestDate: string;
  historySummary: string | null;
  generatedAt: string | null;
  calendarStatus: string;
  calendarStats: Jin10CalendarStats | null;
  calendarFreshness: Jin10CalendarFreshness | null;
  realtimeRegime: MarketMonitorMockFile["realtime_regime"] | null | undefined;
  primaryDriver: MarketMonitorMockFile["primary_driver"] | null | undefined;
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
  const highlights = [
    {
      label: "实时状态",
      value: textOrDash(realtimeRegime?.regime ?? null),
      meta: `置信度 ${typeof realtimeRegime?.confidence === "number" ? `${(realtimeRegime.confidence * 100).toFixed(0)}%` : "—"}`,
    },
    {
      label: "主驱动",
      value: textOrDash(primaryDriver?.driver ?? null),
      meta: textOrDash(primaryDriver?.secondary ?? null),
    },
  ];
  const freshnessText = calendarFreshness?.is_stale
    ? "当前日历窗口缺少未来事件，页面以下方事件列表为准并提示旧数据风险。"
    : "页面以真实日历事件为主视图，右侧仅保留市场状态和溯源上下文。";
  const freshnessTone = calendarFreshness?.is_stale || calendarStatus === "stale" ? "text-[var(--warn)]" : "text-[var(--fg-4)]";

  return (
    <section className="grid gap-4 rounded-[var(--radius-lg)] border border-[var(--border-faint)] bg-[var(--bg-panel)] px-4 py-4 lg:grid-cols-[minmax(0,1.35fr)_minmax(280px,0.92fr)] lg:items-start">
      <div className="min-w-0">
        <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">日历摘要</div>
        <div className="mt-1 text-[14px] font-semibold text-[var(--fg-1)]">事件与阶段摘要</div>
        <div className="mt-2 max-w-[72ch] text-[11px] leading-6 text-[var(--fg-3)]">
          日历页现在直接承接 `Jin10 Calendar` 事件流。上方只给你看来源、缓存时间和事件窗口，真正的事件主体放到下方主列。
        </div>
        <div className={`mt-2 text-[10px] leading-5 ${freshnessTone}`}>{freshnessText}</div>
        <div className="mt-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
          {pills.map((pill) => (
            <div
              key={pill.label}
              className="min-w-0 rounded-[var(--radius-sm)] border border-[var(--border)] bg-[var(--bg-card-inner)] px-3 py-2"
            >
              <div className="text-[8px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">{pill.label}</div>
              <div className="mt-1 truncate text-[10px] font-medium text-[var(--fg-2)]">{pill.value}</div>
            </div>
          ))}
        </div>
      </div>
      <div className="min-w-0 border-t border-[var(--border-faint)] pt-3 lg:border-l lg:border-t-0 lg:pl-4 lg:pt-0">
        <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">关键信号</div>
        <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2">
          {highlights.map((item) => (
            <div key={item.label} className="min-w-0">
              <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">{item.label}</div>
              <div className="mt-1 text-[12px] font-semibold text-[var(--fg-2)]">{item.value}</div>
              <div className="mt-1 text-[10px] leading-5 text-[var(--fg-4)]">{item.meta}</div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
