import { useState } from "react";
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

type CalendarEventView = "priority" | "calendar";

const CALENDAR_EVENT_PAGE_SIZE = 3;

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
      <div className="market-monitor-main-grid">
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
      <div className="market-monitor-pricing-chain-header">
        <div className="market-monitor-tab-section-title-row">
          <Activity size={12} className="market-monitor-tab-section-icon" />
          <div className="market-monitor-tab-section-title">黄金定价链</div>
        </div>
        <div className="market-monitor-tab-section-summary">
          XAUUSD / DXY / US10Y / REAL_10Y / T10YIE · Jin10 实时
        </div>
      </div>
      <div className="market-monitor-pricing-chain-grid">
        <MultiLineChart
          metrics={metrics}
          history={history}
        />
        <FactorPanel />
      </div>
      <div className="market-monitor-pricing-chain-support-grid">
        <MarketRegimePanel marketRegimes={marketRegimes} />
        <EnvironmentFilterPanel environmentFilters={environmentFilters} />
      </div>
    </>
  );
}

export function MarketMonitorCrossAssetSection({ metrics }: { metrics: MarketMonitorMetric[] }) {
  return (
    <>
      <div className="market-monitor-cross-asset-header">
        <div className="market-monitor-tab-section-title-row">
          <Layers3 size={12} className="market-monitor-tab-section-icon" />
          <div className="market-monitor-tab-section-title">跨资产观察</div>
        </div>
        <div className="market-monitor-tab-section-summary">资产分组、热力图与联动矩阵</div>
      </div>
      <div className="market-monitor-cross-asset-grid">
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
        generatedAt={generatedAt}
        calendarStatus={calendarStatus}
        calendarStats={calendarStats}
        calendarFreshness={calendarFreshness}
        realtimeRegime={realtimeRegime}
        sourceTraceCount={sourceTrace.length}
      />
      <div className="market-monitor-calendar-layout">
        <div className="market-monitor-calendar-main">
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
        <div className="market-monitor-calendar-side">
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
  const priorityEvents = events.filter((event) => event.is_high_impact || (event.star ?? 0) >= 4);
  const [activeView, setActiveView] = useState<CalendarEventView>("priority");
  const [priorityPage, setPriorityPage] = useState(1);
  const [calendarPage, setCalendarPage] = useState(1);
  const upcomingCount = calendarStats?.upcoming ?? upcomingEvents.length;
  const releasedCount = calendarStats?.released ?? releasedEvents.length;
  const isStale = calendarFreshness?.is_stale || calendarStatus === "stale";
  const statusTone = isStale ? "warn" : calendarStatus === "ok" ? "info" : "dim";
  const statusLabel = isStale ? "窗口偏旧" : "实时窗口";
  const windowLabel = formatCalendarWindowLabel(calendarStats);
  const activeEvents = activeView === "priority" ? priorityEvents : events;
  const activePage = activeView === "priority" ? priorityPage : calendarPage;
  const pageCount = Math.max(1, Math.ceil(activeEvents.length / CALENDAR_EVENT_PAGE_SIZE));
  const normalizedPage = Math.min(activePage, pageCount);
  const visibleEvents = activeEvents.slice(
    (normalizedPage - 1) * CALENDAR_EVENT_PAGE_SIZE,
    normalizedPage * CALENDAR_EVENT_PAGE_SIZE,
  );
  const activeEmptyTitle = activeView === "priority" ? "暂无重点事件" : "暂无财经日历事件";
  const activeEmptyDescription = activeView === "priority"
    ? "当前窗口内没有四星及以上日历事件。"
    : "当前接口没有返回上一周到未来两周的日历事件。";

  function handleViewChange(nextView: CalendarEventView) {
    setActiveView(nextView);
  }

  function handlePageChange(nextPage: number) {
    const safePage = Math.min(Math.max(nextPage, 1), pageCount);
    if (activeView === "priority") setPriorityPage(safePage);
    else setCalendarPage(safePage);
  }

  return (
    <FACard
      title={activeView === "priority" ? "重点事件" : "财经日历"}
      eyebrow={activeView === "priority" ? "High Impact" : "Calendar Window"}
      accent={activeView === "priority" ? "warn" : "brand"}
      action={(
        <FAStatusPill tone={events.length > 0 ? statusTone : "dim"} dot={false}>
          {events.length > 0 ? `${statusLabel} · ${priorityEvents.length} 重点 / ${events.length} 日历` : "暂无事件"}
        </FAStatusPill>
      )}
      bodyClassName="space-y-3"
    >
      <div className="grid gap-3 rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-panel)] px-3 py-3 md:grid-cols-[minmax(0,1fr)_auto] md:items-center">
        <div className="space-y-1">
          <div className="text-[11px] leading-5 text-[var(--fg-3)]">
            {activeView === "priority"
              ? "先看四星及以上事件，判断本窗口真正可能影响黄金定价的发布。"
              : "查看上一周到未来两周的完整财经日历明细。"}
          </div>
          <div className="text-[10px] text-[var(--fg-5)]">
            {windowLabel} · 缓存时间 {generatedAt ? formatDateTime(generatedAt) : "—"} · {upcomingCount} 待公布 / {releasedCount} 已公布
          </div>
        </div>
        <CalendarEventViewToggle
          activeView={activeView}
          priorityCount={priorityEvents.length}
          calendarCount={events.length}
          onChange={handleViewChange}
        />
      </div>

      {isStale ? (
        <div className="rounded-[var(--radius-md)] border border-[var(--warn-border)] bg-[var(--warn-soft)] px-3 py-2 text-[10px] leading-5 text-[var(--warn)]">
          当前窗口偏旧，先看列表和缓存时间。
        </div>
      ) : null}

      {isError ? (
        <FAEmptyState title="日历加载失败" description="`/api/jin10/calendar` 当前不可用，稍后重试。" className="py-6" />
      ) : isLoading ? (
        <CalendarEventLoadingList />
      ) : activeEvents.length === 0 ? (
        <FAEmptyState title={activeEmptyTitle} description={activeEmptyDescription} className="py-6" />
      ) : (
        <>
          <div className="grid gap-2">
            {visibleEvents.map((event, index) => (
              <CalendarEventCard
                key={`${activeView}-${event.pub_time}-${event.title}-${normalizedPage}-${index}`}
                event={event}
              />
            ))}
          </div>
          <CalendarEventPagination
            currentPage={normalizedPage}
            pageCount={pageCount}
            totalCount={activeEvents.length}
            onPageChange={handlePageChange}
          />
        </>
      )}
    </FACard>
  );
}

function CalendarEventViewToggle({
  activeView,
  priorityCount,
  calendarCount,
  onChange,
}: {
  activeView: CalendarEventView;
  priorityCount: number;
  calendarCount: number;
  onChange: (view: CalendarEventView) => void;
}) {
  const options: Array<{ view: CalendarEventView; label: string; count: number }> = [
    { view: "priority", label: "重点事件", count: priorityCount },
    { view: "calendar", label: "财经日历", count: calendarCount },
  ];

  return (
    <div className="flex shrink-0 rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-card-inner)] p-1">
      {options.map((option) => {
        const isActive = option.view === activeView;
        return (
          <button
            key={option.view}
            type="button"
            onClick={() => onChange(option.view)}
            className={`rounded-[var(--radius-sm)] px-3 py-1.5 text-[11px] font-semibold transition ${
              isActive
                ? "bg-[var(--brand-soft)] text-[var(--brand-strong)] shadow-[var(--shadow-soft)]"
                : "text-[var(--fg-4)] hover:bg-[var(--bg-panel)] hover:text-[var(--fg-2)]"
            }`}
            aria-pressed={isActive}
          >
            {option.label}
            <span className="fa-num ml-1 text-[10px] opacity-75">{option.count}</span>
          </button>
        );
      })}
    </div>
  );
}

function CalendarEventPagination({
  currentPage,
  pageCount,
  totalCount,
  onPageChange,
}: {
  currentPage: number;
  pageCount: number;
  totalCount: number;
  onPageChange: (page: number) => void;
}) {
  if (pageCount <= 1) {
    return (
      <div className="text-right text-[10px] text-[var(--fg-5)]">
        共 {totalCount} 条
      </div>
    );
  }

  return (
    <div className="flex flex-wrap items-center justify-between gap-2 rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-panel)] px-3 py-2">
      <div className="text-[10px] text-[var(--fg-5)]">
        共 {totalCount} 条 · 第 {currentPage} / {pageCount} 页
      </div>
      <div className="flex items-center gap-2">
        <button
          type="button"
          className="rounded-[var(--radius-sm)] border border-[var(--border)] px-2.5 py-1 text-[10px] font-semibold text-[var(--fg-3)] disabled:cursor-not-allowed disabled:opacity-40"
          disabled={currentPage <= 1}
          onClick={() => onPageChange(currentPage - 1)}
        >
          上一页
        </button>
        <button
          type="button"
          className="rounded-[var(--radius-sm)] border border-[var(--border)] px-2.5 py-1 text-[10px] font-semibold text-[var(--fg-3)] disabled:cursor-not-allowed disabled:opacity-40"
          disabled={currentPage >= pageCount}
          onClick={() => onPageChange(currentPage + 1)}
        >
          下一页
        </button>
      </div>
    </div>
  );
}

function formatCalendarWindowLabel(calendarStats: Jin10CalendarStats | null): string {
  if (calendarStats?.window_start_date && calendarStats.window_end_date) {
    return `${calendarStats.window_start_date} → ${calendarStats.window_end_date}`;
  }
  return "上一周 → 未来两周";
}

function CalendarEventLoadingList() {
  return (
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
    <article className="grid gap-2 rounded-[10px] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-3 py-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[9px] text-[var(--fg-5)]">
            <span className="fa-num font-semibold text-[var(--fg-4)]">
              {formatPanelDate(event.pub_time)} {formatPanelTime(event.pub_time)}
            </span>
            <span>{stars || "低"}</span>
            {event.is_high_impact ? <FAStatusPill tone="warn" dot={false}>高</FAStatusPill> : null}
          </div>
          <div className="mt-1 text-[11px] font-semibold leading-5 text-[var(--fg-1)]">
            {event.title}
          </div>
        </div>
        <div className="shrink-0 text-[9px] font-semibold" style={{ color: impactTone }}>
          {statusLabel}
        </div>
      </div>

      <div className="grid gap-1.5 sm:grid-cols-3">
        <CalendarMetric label="实际" value={calendarPanelValue(event.actual)} />
        <CalendarMetric label="预期" value={calendarPanelValue(event.consensus)} />
        <CalendarMetric label="前值" value={calendarPanelValue(event.previous)} />
      </div>
    </article>
  );
}

function CalendarMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[var(--radius-sm)] border border-[var(--border)] bg-[var(--bg-panel)] px-2.5 py-1.25">
      <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">{label}</div>
      <div className="mt-0.5 text-[10px] font-medium text-[var(--fg-2)]">{value}</div>
    </div>
  );
}

export type { MarketMonitorTab };
