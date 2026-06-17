import { textOrDash } from "@/components/market-monitor/format";
import type { MarketMonitorMockFile } from "@/types/market-monitor";

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
        <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">Market Overview</div>
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
        <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">Session Context</div>
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
      title: "Pricing Chain",
      summary: "查看黄金定价链、关键因子和历史走势。",
      meta: `history ${historySummary ?? "unavailable"}`,
    },
    {
      title: "Cross Asset",
      summary: "查看资产分组、热力图和联动矩阵。",
      meta: `latest ${latestDate}`,
    },
    {
      title: "Calendar / Events",
      summary: "查看事件阶段、driver 和来源溯源摘要。",
      meta: `driver ${textOrDash(primaryDriver?.driver ?? null)}`,
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
          <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">Realtime Regime</div>
          <div className="mt-2 text-[14px] font-semibold text-[var(--fg-1)]">{textOrDash(realtimeRegime?.regime ?? null)}</div>
          <div className="mt-1 text-[10px] text-[var(--fg-4)]">
            conf {typeof realtimeRegime?.confidence === "number" ? `${(realtimeRegime.confidence * 100).toFixed(0)}%` : "—"}
          </div>
        </div>
        <div className="rounded-[14px] border border-[var(--border-faint)] bg-[var(--bg-panel)] px-4 py-4">
          <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">Primary Driver</div>
          <div className="mt-2 text-[14px] font-semibold text-[var(--fg-1)]">{textOrDash(primaryDriver?.driver ?? null)}</div>
          <div className="mt-1 text-[10px] text-[var(--fg-4)]">{textOrDash(primaryDriver?.secondary ?? null)}</div>
        </div>
        <div className="rounded-[14px] border border-[var(--border-faint)] bg-[var(--bg-panel)] px-4 py-4">
          <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">Source Context</div>
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
  realtimeRegime,
  primaryDriver,
  sourceTraceCount,
}: {
  sourceLabel: string;
  latestDate: string;
  historySummary: string | null;
  realtimeRegime: MarketMonitorMockFile["realtime_regime"] | null | undefined;
  primaryDriver: MarketMonitorMockFile["primary_driver"] | null | undefined;
  sourceTraceCount: number;
}) {
  const pills = [
    { label: "source", value: sourceLabel },
    { label: "latest", value: latestDate },
    { label: "history", value: historySummary ?? "unavailable" },
    { label: "refs", value: `${sourceTraceCount}` },
  ];

  return (
    <section
      style={{
        border: "1px solid var(--border-faint)",
        borderRadius: "var(--radius-lg)",
        background: "var(--bg-panel)",
        padding: "14px 16px",
        display: "grid",
        gridTemplateColumns: "minmax(0,1.25fr) minmax(300px,0.9fr)",
        gap: 12,
      }}
    >
      <div className="min-w-0">
        <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">Calendar Brief</div>
        <div className="mt-1 text-[14px] font-semibold text-[var(--fg-1)]">事件与阶段摘要</div>
        <div className="mt-2 text-[11px] leading-6 text-[var(--fg-3)]">
          Calendar / Events 只保留当前市场阶段、驱动因子和数据健康摘要，不在这里重复完整定价链、完整 source trace 或完整 regime 诊断。
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          {pills.map((pill) => (
            <div
              key={pill.label}
              className="rounded-[var(--radius-sm)] border border-[var(--border)] bg-[var(--bg-card-inner)] px-2.5 py-1.5"
            >
              <div className="text-[8px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">{pill.label}</div>
              <div className="mt-1 text-[10px] font-medium text-[var(--fg-2)]">{pill.value}</div>
            </div>
          ))}
        </div>
      </div>
      <div className="grid gap-2">
        <div className="rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-card-inner)] px-3 py-3">
          <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">Realtime Regime</div>
          <div className="mt-1 text-[11px] font-semibold text-[var(--fg-2)]">{textOrDash(realtimeRegime?.regime ?? null)}</div>
          <div className="mt-1 text-[10px] text-[var(--fg-4)]">
            conf {typeof realtimeRegime?.confidence === "number" ? `${(realtimeRegime.confidence * 100).toFixed(0)}%` : "—"}
          </div>
        </div>
        <div className="rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-card-inner)] px-3 py-3">
          <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">Primary Driver</div>
          <div className="mt-1 text-[11px] font-semibold text-[var(--fg-2)]">{textOrDash(primaryDriver?.driver ?? null)}</div>
          <div className="mt-1 text-[10px] text-[var(--fg-4)]">{textOrDash(primaryDriver?.secondary ?? null)}</div>
        </div>
      </div>
    </section>
  );
}
