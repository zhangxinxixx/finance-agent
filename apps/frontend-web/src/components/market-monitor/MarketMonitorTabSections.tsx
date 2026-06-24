import { Activity, Calendar, Layers3 } from "lucide-react";
import { AssetTable } from "@/components/market-monitor/AssetTable";
import { CorrelationMatrix } from "@/components/market-monitor/CorrelationMatrix";
import { EnvironmentFilterPanel } from "@/components/market-monitor/EnvironmentFilterPanel";
import { Heatmap } from "@/components/market-monitor/Heatmap";
import { MarketPriceCards } from "@/components/market-monitor/MarketPriceCards";
import { MarketRegimePanel } from "@/components/market-monitor/MarketRegimePanel";
import { FactorPanel } from "@/components/market-monitor/FactorPanel";
import { MultiLineChart } from "@/components/market-monitor/MultiLineChart";
import {
  CalendarEventBrief,
  OverviewEntryGrid,
  OverviewHero,
} from "@/components/market-monitor/MarketMonitorOverviewBlocks";
import { RightPanel } from "@/components/market-monitor/RightPanel";
import { SourceTracePanel } from "@/components/market-monitor/SourceTracePanel";
import type { MarketMonitorHistoryResponse } from "@/adapters/marketMonitor";
import { calendarPanelValue, formatPanelDate, formatPanelTime } from "@/components/dashboard/DashboardRightPanelPrimitives";
import { sortDashboardCalendarEvents } from "@/components/dashboard/DashboardRightPanelModel";
import { FAEmptyState } from "@/components/shared/FAEmptyState";
import { FACard } from "@/components/shared/FACard";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import type { Jin10CalendarEvent, Jin10CalendarFreshness, Jin10CalendarStats } from "@/hooks/useJin10Calendar";
import type { MarketMonitorHistoryTimeframe } from "@/hooks/useMarketMonitor";
import { formatDateTime } from "@/lib/date";
import type { MarketMonitorMetric, MarketMonitorMockFile, MarketMonitorSourceTraceItem } from "@/types/market-monitor";
import type { MarketMonitorTab } from "./MarketMonitorHeaderSections";

export function MarketMonitorOverviewSection({
  metrics,
  history,
  activeTimeframe,
  onTimeframeChange,
  marketRegimes,
  agentMarketRegime,
  overviewTitle,
  sourceLabel,
  latestDate,
  overviewSummary,
  historySummary,
  realtimeRegime,
  primaryDriver,
}: {
  metrics: MarketMonitorMetric[];
  history: MarketMonitorHistoryResponse | null;
  activeTimeframe: MarketMonitorHistoryTimeframe;
  onTimeframeChange: (timeframe: MarketMonitorHistoryTimeframe) => void;
  marketRegimes: MarketMonitorMockFile["market_regimes"];
  agentMarketRegime: MarketMonitorMockFile["agent_market_regime"] | null | undefined;
  overviewTitle: string;
  sourceLabel: string;
  latestDate: string;
  overviewSummary: string;
  historySummary: string | null;
  realtimeRegime: MarketMonitorMockFile["realtime_regime"] | null | undefined;
  primaryDriver: MarketMonitorMockFile["primary_driver"] | null | undefined;
}) {
  return (
    <>
      <OverviewHero
        title={overviewTitle}
        meta={`source ${sourceLabel} · latest ${latestDate}`}
        summary={overviewSummary}
      />
      <MarketPriceCards metrics={metrics} />
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1.9fr) minmax(280px,0.95fr)", gap: 10, alignItems: "start" }}>
        <MultiLineChart
          metrics={metrics}
          history={history}
        />
        <RightPanel
          marketRegimes={marketRegimes}
          agentMarketRegime={agentMarketRegime}
        />
      </div>
      <OverviewEntryGrid
        latestDate={latestDate}
        historySummary={historySummary}
        sourceLabel={sourceLabel}
        realtimeRegime={realtimeRegime}
        primaryDriver={primaryDriver}
      />
    </>
  );
}

export function MarketMonitorPricingChainSection({
  metrics,
  history,
  marketRegimes,
  environmentFilters,
}: {
  metrics: MarketMonitorMetric[];
  history: MarketMonitorHistoryResponse | null;
  marketRegimes: MarketMonitorMockFile["market_regimes"];
  environmentFilters: MarketMonitorMockFile["environment_filters"];
}) {
  return (
    <>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 12,
          padding: "2px 2px 0",
        }}
      >
        <div className="flex items-center gap-2">
          <Activity size={12} className="text-[var(--brand-hover)]" />
          <div className="text-[11px] font-semibold text-[var(--fg-3)]">黄金定价链</div>
        </div>
        <div className="text-[10px] text-[var(--fg-5)]">
          XAUUSD / DXY / US10Y / REAL_10Y / T10YIE · Jin10 实时
        </div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1.9fr) minmax(280px,0.95fr)", gap: 10, alignItems: "start" }}>
        <MultiLineChart
          metrics={metrics}
          history={history}
        />
        <FactorPanel />
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)", gap: 10 }}>
        <MarketRegimePanel marketRegimes={marketRegimes} />
        <EnvironmentFilterPanel environmentFilters={environmentFilters} />
      </div>
    </>
  );
}

export function MarketMonitorCrossAssetSection({ metrics }: { metrics: MarketMonitorMetric[] }) {
  return (
    <>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 12,
          padding: "2px 2px 0",
        }}
      >
        <div className="flex items-center gap-2">
          <Layers3 size={12} className="text-[var(--brand-hover)]" />
          <div className="text-[11px] font-semibold text-[var(--fg-3)]">跨资产观察</div>
        </div>
        <div className="text-[10px] text-[var(--fg-5)]">资产分组、热力图与联动矩阵</div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1.7fr) minmax(280px,0.95fr)", gap: 10, alignItems: "start" }}>
        <AssetTable metrics={metrics} />
        <Heatmap metrics={metrics} />
      </div>
      <CorrelationMatrix metrics={metrics} />
    </>
  );
}

export function MarketMonitorCalendarSection({
  sourceLabel,
  latestDate,
  historySummary,
  events,
  generatedAt,
  calendarStatus,
  calendarStats,
  calendarFreshness,
  eventsIsLoading,
  eventsIsError,
  realtimeRegime,
  primaryDriver,
  sourceTrace,
  marketRegimes,
  agentMarketRegime,
}: {
  sourceLabel: string;
  latestDate: string;
  historySummary: string | null;
  events: Jin10CalendarEvent[];
  generatedAt: string | null;
  calendarStatus: string;
  calendarStats: Jin10CalendarStats | null;
  calendarFreshness: Jin10CalendarFreshness | null;
  eventsIsLoading: boolean;
  eventsIsError: boolean;
  realtimeRegime: MarketMonitorMockFile["realtime_regime"] | null | undefined;
  primaryDriver: MarketMonitorMockFile["primary_driver"] | null | undefined;
  sourceTrace: MarketMonitorSourceTraceItem[];
  marketRegimes: MarketMonitorMockFile["market_regimes"];
  agentMarketRegime: MarketMonitorMockFile["agent_market_regime"] | null | undefined;
}) {
  const sortedEvents = sortDashboardCalendarEvents(events);

  return (
    <>
      <CalendarEventBrief
        sourceLabel={sourceLabel}
        latestDate={latestDate}
        historySummary={historySummary}
        generatedAt={generatedAt}
        calendarStatus={calendarStatus}
        calendarStats={calendarStats}
        calendarFreshness={calendarFreshness}
        realtimeRegime={realtimeRegime}
        primaryDriver={primaryDriver}
        sourceTraceCount={sourceTrace.length}
      />
      <div className="grid gap-3 xl:grid-cols-[minmax(0,1.35fr)_300px]">
        <div className="min-w-0">
          <MarketMonitorCalendarEventsPanel
            events={sortedEvents}
            generatedAt={generatedAt}
            calendarStatus={calendarStatus}
            calendarStats={calendarStats}
            calendarFreshness={calendarFreshness}
            isLoading={eventsIsLoading}
            isError={eventsIsError}
          />
        </div>
        <div className="grid min-w-0 gap-3 self-start">
          <RightPanel
            marketRegimes={marketRegimes}
            agentMarketRegime={agentMarketRegime}
          />
          <SourceTracePanel sourceTrace={sourceTrace} />
        </div>
      </div>
    </>
  );
}

function MarketMonitorCalendarEventsPanel({
  events,
  generatedAt,
  calendarStatus,
  calendarStats,
  calendarFreshness,
  isLoading,
  isError,
}: {
  events: Jin10CalendarEvent[];
  generatedAt: string | null;
  calendarStatus: string;
  calendarStats: Jin10CalendarStats | null;
  calendarFreshness: Jin10CalendarFreshness | null;
  isLoading: boolean;
  isError: boolean;
}) {
  const upcomingEvents = events.filter((event) => event.release_state === "upcoming");
  const releasedEvents = events.filter((event) => event.release_state !== "upcoming");
  const upcomingCount = calendarStats?.upcoming ?? upcomingEvents.length;
  const releasedCount = calendarStats?.released ?? releasedEvents.length;
  const isStale = calendarFreshness?.is_stale || calendarStatus === "stale";
  const statusTone = isStale ? "warn" : calendarStatus === "ok" ? "info" : "dim";
  const statusLabel = isStale ? "窗口偏旧" : "实时窗口";

  return (
    <FACard
      title="重点事件列表"
      eyebrow="Calendar Events"
      accent="brand"
      action={(
        <FAStatusPill tone={events.length > 0 ? statusTone : "dim"} dot={false}>
          {events.length > 0 ? `${statusLabel} · ${upcomingCount} 待公布 / ${releasedCount} 已公布` : "暂无事件"}
        </FAStatusPill>
      )}
      bodyClassName="space-y-3"
    >
      <div className="grid gap-2 rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-panel)] px-3 py-3 md:grid-cols-[minmax(0,1fr)_auto] md:items-center">
        <div className="text-[11px] leading-5 text-[var(--fg-4)]">
          这里的事件用于解释黄金短线催化和市场阶段切换。上半段优先看待公布事件，下半段回看刚公布的高影响数据。
        </div>
        <div className="text-[10px] text-[var(--fg-5)]">
          缓存时间 {generatedAt ? formatDateTime(generatedAt) : "—"}
        </div>
      </div>

      {isStale ? (
        <div className="rounded-[var(--radius-md)] border border-[var(--warn-border)] bg-[var(--warn-soft)] px-3 py-2 text-[10px] leading-5 text-[var(--warn)]">
          当前接口没有返回未来事件窗口，页面正在展示最近一批已公布事件。若需要看即将发生的事件，先检查 `jin10_calendar_refresh` 是否已更新。
        </div>
      ) : null}

      {isError ? (
        <FAEmptyState title="日历加载失败" description="`/api/jin10/calendar` 当前不可用，稍后重试。" className="py-6" />
      ) : isLoading ? (
        <div className="grid gap-2">
          {Array.from({ length: 6 }).map((_, index) => (
            <div
              key={`calendar-loading-${index}`}
              className="animate-pulse rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-4 py-4"
            >
              <div className="h-3 w-28 rounded bg-white/10" />
              <div className="mt-3 h-4 w-4/5 rounded bg-white/10" />
              <div className="mt-3 grid grid-cols-3 gap-2">
                <div className="h-3 rounded bg-white/10" />
                <div className="h-3 rounded bg-white/10" />
                <div className="h-3 rounded bg-white/10" />
              </div>
            </div>
          ))}
        </div>
      ) : events.length === 0 ? (
        <FAEmptyState title="暂无重点日历事件" description="当前接口没有返回未来或近期重点事件。" className="py-6" />
      ) : (
        <div className="space-y-5">
          <CalendarEventSection
            title="待公布"
            eyebrow="Upcoming"
            events={upcomingEvents}
            emptyText="当前没有待公布重点事件。"
          />
          <CalendarEventSection
            title="已公布"
            eyebrow="Released"
            events={releasedEvents}
            emptyText="当前没有已公布重点事件。"
          />
        </div>
      )}
    </FACard>
  );
}

function CalendarEventSection({
  title,
  eyebrow,
  events,
  emptyText,
}: {
  title: string;
  eyebrow: string;
  events: Jin10CalendarEvent[];
  emptyText: string;
}) {
  return (
    <section className="space-y-2">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">{eyebrow}</div>
          <div className="mt-1 text-[12px] font-semibold text-[var(--fg-2)]">{title}</div>
        </div>
        <FAStatusPill tone={events.length > 0 ? "neutral" : "dim"} dot={false}>
          {events.length} 条
        </FAStatusPill>
      </div>

      {events.length === 0 ? (
        <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-panel)] px-3 py-4 text-[10px] text-[var(--fg-5)]">
          {emptyText}
        </div>
      ) : (
        <div className="grid gap-2">
          {events.map((event, index) => (
            <CalendarEventCard key={`${title}-${event.pub_time}-${event.title}-${index}`} event={event} />
          ))}
        </div>
      )}
    </section>
  );
}

function CalendarEventCard({ event }: { event: Jin10CalendarEvent }) {
  const isFuture = event.release_state === "upcoming";
  const stars = "★".repeat(Math.min(event.star ?? 0, 4));
  const statusLabel = isFuture ? "未公布" : (event.affect_txt || "已公布");
  const impactTone = event.affect_txt === "利多"
    ? "var(--up)"
    : event.affect_txt === "利空"
      ? "var(--down)"
      : isFuture
        ? "var(--brand)"
        : "var(--fg-4)";

  return (
    <article className="grid gap-3 rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-4 py-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-[var(--fg-5)]">
            <span className="fa-num font-semibold text-[var(--fg-4)]">
              {formatPanelDate(event.pub_time)} {formatPanelTime(event.pub_time)}
            </span>
            <span>{stars || "低影响"}</span>
            {event.is_high_impact ? <FAStatusPill tone="warn" dot={false}>高影响</FAStatusPill> : null}
          </div>
          <div className="mt-2 text-[13px] font-semibold leading-6 text-[var(--fg-1)]">
            {event.title}
          </div>
        </div>
        <div className="shrink-0 text-[11px] font-semibold" style={{ color: impactTone }}>
          {statusLabel}
        </div>
      </div>

      <div className="grid gap-2 sm:grid-cols-3">
        <CalendarMetric label="实际" value={calendarPanelValue(event.actual)} />
        <CalendarMetric label="预期" value={calendarPanelValue(event.consensus)} />
        <CalendarMetric label="前值" value={calendarPanelValue(event.previous)} />
      </div>
    </article>
  );
}

function CalendarMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[var(--radius-sm)] border border-[var(--border)] bg-[var(--bg-panel)] px-3 py-2">
      <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">{label}</div>
      <div className="mt-1 text-[11px] font-medium text-[var(--fg-2)]">{value}</div>
    </div>
  );
}

export type { MarketMonitorTab };
