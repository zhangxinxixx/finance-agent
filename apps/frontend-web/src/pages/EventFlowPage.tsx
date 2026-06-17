import { useMemo } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Loader2, RefreshCw } from "lucide-react";
import { FAFilterBar } from "@/components/shared/FAFilterBar";
import { ErrorState } from "@/components/shared/ErrorState";
import {
  BriefSummaryStrip,
  EventFlowEmptyState,
  EventFlowWeekendBanner,
  FilterDropdown,
} from "@/components/event-flow/EventFlowPageSections";
import { EventFlowImpactAnalysisPanel } from "@/components/event-flow/EventFlowImpactAnalysisPanel";
import { EventFlowLiveBriefsPanel } from "@/components/event-flow/EventFlowLiveBriefsPanel";
import { EventFlowOverviewPanel } from "@/components/event-flow/EventFlowOverviewPanel";
import { EventFlowReportInputsPanel } from "@/components/event-flow/EventFlowReportInputsPanel";
import { EventFlowTimelinePanel } from "@/components/event-flow/EventFlowTimelinePanel";
import { EventFlowTabs, isEventFlowTab, type EventFlowTabKey } from "@/components/event-flow/EventFlowTabs";
import { useEventFlow } from "@/hooks/useEventFlow";
import { isWeekend } from "@/lib/date";

export function EventFlowPage() {
  const navigate = useNavigate();
  const { data, isLoading, isError, error, refetch } = useEventFlow();
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedTab = searchParams.get("tab");
  const activeTab: EventFlowTabKey = isEventFlowTab(requestedTab) ? requestedTab : "overview";

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
          title="Event Flow 加载失败"
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

  const activeEvent = data.timeline[0] ?? null;
  const liveCount = data.article_briefs?.brief_count ?? data.timeline.length;
  const timelineCount = data.timeline.length;

  const tabContent = useMemo(() => {
    switch (activeTab) {
      case "live":
        return (
          <EventFlowLiveBriefsPanel
            bundle={data.article_briefs}
            timeline={data.timeline}
            sourceRefs={data.source_refs ?? []}
          />
        );
      case "timeline":
        return (
          <EventFlowTimelinePanel
            timeline={data.timeline}
            table={data.table}
            updatedAt={data.updated_at}
            onOpenDetail={(id) => navigate(`/event-flow/${id}`)}
          />
        );
      case "impact":
        return (
          <EventFlowImpactAnalysisPanel
            chain={data.chain}
            sentiment={data.sentiment}
            radar={data.radar}
            timeline={data.timeline}
            table={data.table}
          />
        );
      case "inputs":
        return (
          <EventFlowReportInputsPanel
            briefSummary={data.brief_summary}
            articleBriefs={data.article_briefs}
            reportInputItems={data.report_input_items ?? []}
            sourceRefs={data.source_refs ?? []}
          />
        );
      case "overview":
      default:
        return (
          <EventFlowOverviewPanel
            data={data}
            summary={data.brief_summary}
            timeline={data.timeline}
            table={data.table}
            sourceRefs={data.source_refs ?? []}
          />
        );
    }
  }, [activeTab, data, navigate]);

  return (
    <div className="finance-page-shell">
      <FAFilterBar
        left={
          <>
            <FilterDropdown label="资产" value="XAUUSD(黄金/美元)" />
            <FilterDropdown label="区域" value="全球" />
            <FilterDropdown label="事件类型" value="全部" />
            <FilterDropdown label="重要性" value="全部" />
            <div className="flex flex-col gap-0.5">
              <span className="text-[8px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">时间范围</span>
              <div className="flex h-[28px] items-center gap-1.5 rounded-[var(--radius-sm)] border border-[var(--border)] bg-[var(--bg-card-inner)] px-2.5 transition-colors hover:border-[var(--border-strong)]">
                <span className="fa-num text-[11px] text-[var(--fg-2)]">2026-05-22</span>
                <span className="text-[8px] text-[var(--fg-5)]">&rarr;</span>
                <span className="fa-num text-[11px] text-[var(--fg-2)]">2026-06-17</span>
              </div>
            </div>
            <FilterDropdown label="传导方向" value="全部" />
            <FilterDropdown label="定价状态" value="全部" />
            <FilterDropdown label="数据来源" value="全部" />
          </>
        }
        right={
          <button
            type="button"
            onClick={refetch}
            className="inline-flex h-[28px] items-center gap-1.5 rounded-[var(--radius-sm)] border border-[var(--border)] bg-[var(--bg-card-inner)] px-3 text-[10px] font-semibold text-[var(--fg-2)] transition-colors hover:border-[var(--border-strong)] hover:bg-[var(--bg-hover)]"
          >
            <RefreshCw size={10} />
            刷新
          </button>
        }
      />

      {/* Weekend mode banner */}
      {isWeekend() ? <EventFlowWeekendBanner /> : null}

      {data.brief_summary ? (
        <BriefSummaryStrip
          summary={data.brief_summary}
          source={data.source}
          updatedAt={data.updated_at}
          sourceRefs={data.source_refs ?? []}
        />
      ) : null}

      <EventFlowTabs
        value={activeTab}
        onChange={(value) => {
          const next = new URLSearchParams(searchParams);
          next.set("tab", value);
          setSearchParams(next, { replace: true });
        }}
        liveCount={liveCount}
        timelineCount={timelineCount}
      />

      {activeTab === "overview" && activeEvent ? (
        <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-3 py-2 text-[11px] leading-5 text-[var(--fg-3)]">
          当前选中事件：<button type="button" onClick={() => navigate(`/event-flow/${activeEvent.id}`)} className="font-semibold text-[var(--brand-hover)] hover:text-[var(--brand)]">{activeEvent.title}</button>
        </div>
      ) : null}

      <div className="min-h-0">{tabContent}</div>
    </div>
  );
}

export default EventFlowPage;
