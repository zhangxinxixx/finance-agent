import { useNavigate, useSearchParams } from "react-router-dom";
import { GitBranch, Loader2, RefreshCw } from "lucide-react";
import { ErrorState } from "@/components/shared/ErrorState";
import {
  EventFlowEmptyState,
  EventFlowWeekendBanner,
} from "@/components/event-flow/EventFlowPageSections";
import { EventFlowImpactAnalysisPanel } from "@/components/event-flow/EventFlowImpactAnalysisPanel";
import { EventFlowLiveBriefsPanel } from "@/components/event-flow/EventFlowLiveBriefsPanel";
import { EventFlowOverviewPanel } from "@/components/event-flow/EventFlowOverviewPanel";
import { EventFlowReportInputsPanel } from "@/components/event-flow/EventFlowReportInputsPanel";
import { EventFlowTimelinePanel } from "@/components/event-flow/EventFlowTimelinePanel";
import { EventFlowTabs, isEventFlowTab, type EventFlowTabKey } from "@/components/event-flow/EventFlowTabs";
import { useEventFlow } from "@/hooks/useEventFlow";
import { isWeekend } from "@/lib/date";
import type { EventFlowBriefSummary, EventFlowTimelineItem } from "@/types/event-flow";

const EVENT_FLOW_ASSET_LABELS: Record<string, string> = {
  xauusd: "黄金",
  gold: "黄金",
  xagusd: "白银",
  silver: "白银",
  dxy: "美元指数",
  usd: "美元",
  usdjpy: "美元/日元",
  us10y: "10年期美债",
  us02y: "2年期美债",
  wti: "WTI 原油",
  brent: "布伦特原油",
  oil: "原油",
  rates: "利率",
  macro: "宏观",
};

function buildTopCounts(summary: EventFlowBriefSummary | null | undefined, timeline: EventFlowTimelineItem[]) {
  if (summary?.counts) {
    return summary.counts;
  }

  return timeline.reduce(
    (acc, event) => {
      if (event.event_kind === "confirmed_event") acc.confirmedEventCount += 1;
      else if (event.event_kind === "calendar") acc.calendarEventCount += 1;
      else if (event.event_kind === "unconfirmed_risk") acc.unconfirmedRiskCount += 1;
      else acc.candidateEventCount += 1;
      acc.sourceRefCount += event.source_refs?.length ?? 0;
      return acc;
    },
    {
      confirmedEventCount: 0,
      candidateEventCount: 0,
      unconfirmedRiskCount: 0,
      calendarEventCount: 0,
      sourceRefCount: 0,
    },
  );
}

function collectDateRange(view: { timeline: EventFlowTimelineItem[] }): string {
  const dates = new Set<string>();

  for (const event of view.timeline) {
    const candidates = [event.date, event.time];
    for (const candidate of candidates) {
      if (!candidate) continue;
      const match = candidate.trim().match(/(\d{4})-(\d{2})-(\d{2})|(\d{2})-(\d{2})/);
      if (!match) continue;
      if (match[1]) dates.add(`${match[2]}-${match[3]}`);
      else if (match[4]) dates.add(`${match[4]}-${match[5]}`);
    }
  }

  const sorted = Array.from(dates).sort();
  if (sorted.length === 0) return "未返回";
  if (sorted.length === 1) return sorted[0];
  return `${sorted[0]} ~ ${sorted[sorted.length - 1]}`;
}

function normalizeAssetToken(value: string): string[] {
  return value
    .split(/[,\//|]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function displayAssetLabel(value: string): string {
  const normalized = value.trim().toLowerCase().replace(/\s+/g, "");
  return EVENT_FLOW_ASSET_LABELS[normalized] ?? value.trim();
}

function collectFocusAssets(view: {
  timeline: EventFlowTimelineItem[];
  table: Array<{ assets: string }>;
}): string {
  const counts = new Map<string, number>();

  const register = (raw: string | null | undefined) => {
    if (!raw) return;
    for (const token of normalizeAssetToken(raw)) {
      const label = displayAssetLabel(token);
      counts.set(label, (counts.get(label) ?? 0) + 1);
    }
  };

  for (const event of view.timeline) {
    register(event.assets);
    for (const asset of event.affected_assets ?? []) register(asset);
  }
  for (const row of view.table) register(row.assets);
  const topAssets = Array.from(counts.entries())
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], "zh-CN"))
    .slice(0, 4)
    .map(([label]) => label);

  if (topAssets.length === 0) return "未返回";
  return topAssets.join(" / ");
}

function sourceCoverageLabel(count: number): string {
  if (count <= 0) return "待补";
  if (count >= 1000) return `${Math.round(count / 100) / 10}k 引用`;
  return `${count} 条引用`;
}

function isJinshiRelatedNewsSource(item: { source?: string | null; source_label?: string | null; source_ref?: string | null; url?: string | null; domain?: string | null }): boolean {
  const text = [item.source, item.source_label, item.source_ref, item.url, item.domain].join(" ").toLowerCase();
  return text.includes("jin10") || text.includes("xnews.jin10.com") || text.includes("flash.jin10.com") || text.includes("金十");
}

function isSameDatePrefix(value: string | null | undefined, date: string | null | undefined): boolean {
  if (!date) return true;
  if (!value) return false;
  return value.startsWith(date);
}

function collectLiveNewsCount(timeline: EventFlowTimelineItem[], date: string | null | undefined): number {
  const seen = new Set<string>();
  for (const event of timeline) {
    for (const item of event.related_news_items ?? []) {
      const title = item.title?.trim();
      if (!title || title === "重点事件持续发酵" || title === "未命名快讯") continue;
      if (isJinshiRelatedNewsSource(item)) continue;
      if (!isSameDatePrefix(item.published_at, date)) continue;
      const key = item.news_item_id || item.source_ref || item.url || `${item.source}:${title}`;
      seen.add(key);
    }
  }
  return seen.size;
}

function isUnsettledMainline(event: EventFlowTimelineItem): boolean {
  if (event.importance === "高" && (event.pricing === "未定价" || event.pricing === "部分定价")) return true;
  if (event.risk_level === "high" && event.pricing !== "已定价") return true;
  return false;
}

function collectUnsettledMainlineCount(summary: EventFlowBriefSummary | null | undefined, timeline: EventFlowTimelineItem[]): number {
  const eventCount = timeline.filter(isUnsettledMainline).length;
  const followupCount = [
    ...(summary?.watchlist ?? []),
    ...(summary?.riskPoints ?? []),
  ].filter(Boolean).length;
  return eventCount + followupCount;
}

export function EventFlowPage() {
  const navigate = useNavigate();
  const { data, isLoading, isError, error, refetch } = useEventFlow();
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedTab = searchParams.get("tab");
  const activeTab: EventFlowTabKey = isEventFlowTab(requestedTab) ? requestedTab : "overview";
  const openEventDetail = (id: string) => navigate(`/event-flow/${encodeURIComponent(id)}`);

  if (isLoading && !data) {
    return (
      <div className="finance-page-shell">
        <section className="finance-panel p-4">
          <div className="flex items-center gap-3">
            <Loader2 className="h-4 w-4 animate-spin text-[var(--brand)]" />
            <div>
              <div className="text-[13px] font-semibold text-[var(--fg-2)]">正在加载事件流数据</div>
              <div className="mt-1 text-[11px] text-[var(--fg-4)]">请稍候...</div>
            </div>
          </div>
          <div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-6">
            {Array.from({ length: 6 }).map((_, index) => (
              <div key={`loading-${index}`} className="finance-skeleton-card h-24" />
            ))}
          </div>
        </section>
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className="finance-page-shell">
        <ErrorState
          title="事件流加载失败"
          message={error?.message ?? "未知错误"}
          onRetry={refetch}
          retryLabel="重试"
        />
      </div>
    );
  }

  if (!data.has_data) {
    return (
      <div className="finance-page-shell">
        <EventFlowEmptyState source={data.source} updatedAt={data.updated_at} />
      </div>
    );
  }

  const view = data;
  const activeEvent = view.timeline[0] ?? null;
  const liveCount = collectLiveNewsCount(view.timeline, view.daily_analysis_triggers?.date);
  const timelineCount = view.timeline.length;
  const counts = buildTopCounts(view.brief_summary, view.timeline);
  const unsettledMainlineCount = collectUnsettledMainlineCount(view.brief_summary, view.timeline);
  const focusAssets = collectFocusAssets(view);
  const dateRange = collectDateRange(view);
  const sourceCoverage = sourceCoverageLabel(
    Math.max(
      counts.sourceRefCount,
      view.source_refs?.length ?? 0,
    ),
  );

  function renderTabContent() {
    switch (activeTab) {
      case "live":
        return (
          <EventFlowLiveBriefsPanel
            progressBundle={view.daily_analysis_triggers}
            timeline={view.timeline}
          />
        );
      case "timeline":
        return (
          <EventFlowTimelinePanel
            timeline={view.timeline}
            table={view.table}
            updatedAt={view.updated_at}
            onOpenDetail={openEventDetail}
          />
        );
      case "impact":
        return (
          <EventFlowImpactAnalysisPanel
            chain={view.chain}
            sentiment={view.sentiment}
            radar={view.radar}
            timeline={view.timeline}
            table={view.table}
          />
        );
      case "inputs":
        return (
          <EventFlowReportInputsPanel
            briefSummary={view.brief_summary}
            articleBriefs={view.article_briefs}
            reportInputItems={view.report_input_items ?? []}
            sourceRefs={view.source_refs ?? []}
          />
        );
      case "overview":
      default:
        return (
          <EventFlowOverviewPanel
            data={view}
            summary={view.brief_summary}
            timeline={view.timeline}
            table={view.table}
            sourceRefs={view.source_refs ?? []}
            onOpenDetail={openEventDetail}
          />
        );
    }
  }

  return (
    <div className="finance-page-shell event-flow-page-shell">
      <section className="event-flow-top-band">
        <div className="event-flow-top-band-main">
          <div className="event-flow-top-band-title">
            <GitBranch size={14} className="text-[var(--brand-hover)]" />
            <span className="text-[13px] font-semibold text-[var(--fg-1)]">事件流</span>
          </div>

          <EventFlowTabs
            value={activeTab}
            onChange={(value) => {
              const next = new URLSearchParams(searchParams);
              next.set("tab", value);
              setSearchParams(next, { replace: true });
            }}
            liveCount={liveCount}
            timelineCount={timelineCount}
            onOpenActiveEvent={activeTab === "overview" && activeEvent ? () => openEventDetail(activeEvent.id) : undefined}
          />

          <div className="event-flow-top-band-actions">
            <button type="button" onClick={refetch} className="event-flow-toolbar-button">
              <RefreshCw size={12} />
              刷新
            </button>
          </div>
        </div>

        <div className="event-flow-context-strip">
          <div className="event-flow-context-group">
            <span className="event-flow-toolbar-label">事件分层</span>
            {[
              ["已确认", counts.confirmedEventCount],
              ["候选", counts.candidateEventCount],
              ["待验证", counts.unconfirmedRiskCount],
              ["日历", counts.calendarEventCount],
              ["待落地", unsettledMainlineCount],
            ].map(([label, value]) => (
              <span key={label} className="event-flow-context-chip">
                <span className="event-flow-context-chip-label">{label}</span>
                <span className="event-flow-context-chip-value fa-num">{value}</span>
              </span>
            ))}
          </div>

          <div className="event-flow-context-group event-flow-context-group--compact">
            <span className="event-flow-toolbar-label">摘要</span>
            <span className="event-flow-context-chip event-flow-context-chip--summary">
              <span className="event-flow-context-chip-label">资产</span>
              <span className="event-flow-context-chip-value">{focusAssets}</span>
            </span>
            <span className="event-flow-context-chip event-flow-context-chip--summary">
              <span className="event-flow-context-chip-label">时间</span>
              <span className="event-flow-context-chip-value">{dateRange}</span>
            </span>
            <span className="event-flow-context-chip event-flow-context-chip--summary">
              <span className="event-flow-context-chip-label">来源</span>
              <span className="event-flow-context-chip-value">{sourceCoverage}</span>
            </span>
          </div>
        </div>
      </section>

      {isWeekend() ? <EventFlowWeekendBanner /> : null}

      <div className="fa-layout-fill">{renderTabContent()}</div>
    </div>
  );
}

export default EventFlowPage;
