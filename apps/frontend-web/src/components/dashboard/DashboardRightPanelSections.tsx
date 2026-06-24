import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, Calendar, Newspaper } from "lucide-react";
import { ContextPanelSectionHeader } from "@/components/shared/ContextPanel";
import type { Jin10CalendarEvent } from "@/hooks/useJin10Calendar";
import type { EventFlowLiveFlashItem } from "@/hooks/useEventFlowLiveFlash";
import {
  calendarPanelValue,
  DashboardPanelCard,
  DashboardPanelEmptyState,
  DashboardPanelStack,
  compactPanelText,
  formatPanelDate,
  formatPanelTime,
} from "./DashboardRightPanelPrimitives";

function SectionActionLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link
      to={to}
      className="inline-flex items-center gap-1 text-[9px] font-semibold text-[var(--brand-hover)] transition-colors hover:text-[var(--brand)]"
    >
      <span>{children}</span>
      <ArrowRight size={10} />
    </Link>
  );
}

function eventSignalText(item: EventFlowLiveFlashItem): string | null {
  const tags = item.signal_tags?.filter(Boolean).slice(0, 2) ?? [];
  return tags.length > 0 ? tags.join(" / ") : null;
}

export function RealtimeFlashSection({
  items,
  overflowCount,
  isLoading,
  isError,
}: {
  items: EventFlowLiveFlashItem[];
  overflowCount: number;
  isLoading: boolean;
  isError: boolean;
}) {
  return (
    <div>
      <ContextPanelSectionHeader
        icon={Newspaper}
        title="当日重点事件 Top 5"
        meta={items.length > 0 ? `Top ${items.length}` : isLoading ? "加载中" : "暂无"}
        className="mb-2"
      />
      <div className="mb-2 flex items-center justify-end">
        <SectionActionLink to="/event-flow">{overflowCount > 0 ? "查看更多" : "进入事件流"}</SectionActionLink>
      </div>
      <DashboardPanelStack>
        {items.length > 0 ? (
          items.map((item, i) => {
            const timeStr = formatPanelTime(item.time);
            return (
              <DashboardPanelCard
                key={item.id || i}
                background={i === 0 ? "rgba(59,130,246,0.06)" : "var(--bg-card-inner)"}
                border={i === 0 ? "1px solid rgba(59,130,246,0.18)" : "1px solid var(--border-faint)"}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 2 }}>
                  <span className="fa-num" style={{ fontSize: 9, fontWeight: 600, color: i === 0 ? "#3b82f6" : "var(--fg-5)" }}>{timeStr}</span>
                  {item.channel?.length ? (
                    <span style={{ padding: "1px 4px", borderRadius: 2, fontSize: 8, background: "var(--bg-panel)", color: "var(--fg-5)" }}>
                      {item.channel[0]}
                    </span>
                  ) : null}
                </div>
                <div style={{ fontSize: 9.5, color: "var(--fg-2)", lineHeight: 1.5 }}>
                  {compactPanelText(item.content, 56)}
                </div>
                {eventSignalText(item) ? (
                  <div style={{ marginTop: 3, fontSize: 8, color: "var(--fg-5)", lineHeight: 1.3 }}>
                    {eventSignalText(item)}
                  </div>
                ) : null}
              </DashboardPanelCard>
            );
          })
        ) : (
          <DashboardPanelEmptyState>
            {isError ? "当日重点事件加载失败" : isLoading ? "当日重点事件加载中" : "暂无当日重点事件"}
          </DashboardPanelEmptyState>
        )}
      </DashboardPanelStack>
    </div>
  );
}

export function EconomicCalendarSection({
  events,
  visibleEvents,
  mode,
  overflowCount,
  isLoading,
  isError,
}: {
  events: Jin10CalendarEvent[];
  visibleEvents: Jin10CalendarEvent[];
  mode: "upcoming" | "recent";
  overflowCount: number;
  isLoading: boolean;
  isError: boolean;
}) {
  const metaText = events.length > 0
    ? mode === "upcoming"
      ? `未来7天 ${visibleEvents.length} / ${events.length}`
      : `最近已公布 ${visibleEvents.length} / ${events.length}`
    : isLoading
      ? "加载中"
      : "暂无";

  return (
    <div>
      <ContextPanelSectionHeader
        icon={Calendar}
        title="重点经济日历 Top 5"
        meta={metaText}
        className="mb-2"
      />
      <div className="mb-2 flex items-center justify-end">
        <SectionActionLink to="/market-monitor?tab=calendar">{overflowCount > 0 ? `查看更多 ${overflowCount} 条` : "进入市场监控"}</SectionActionLink>
      </div>
      <DashboardPanelStack>
        {events.length > 0 ? (
          visibleEvents.map((ev, i) => {
            const hasReleasedValue = ev.actual !== null && ev.actual !== "";
            const isFuture = !hasReleasedValue;
            const stars = "★".repeat(Math.min(ev.star ?? 0, 4));
            const dateStr = formatPanelDate(ev.pub_time);
            const timeStr = formatPanelTime(ev.pub_time);
            const impactColor = ev.affect_txt === "利多" ? "var(--up)" : ev.affect_txt === "利空" ? "var(--down)" : "var(--fg-5)";
            const statusLabel = isFuture ? "未公布" : (ev.affect_txt || "已公布");
            return (
              <DashboardPanelCard
                key={`${ev.pub_time}-${ev.title}-${i}`}
                background={isFuture ? "rgba(59,130,246,0.04)" : "var(--bg-card-inner)"}
                border={isFuture ? "1px solid rgba(59,130,246,0.15)" : "1px solid var(--border-faint)"}
              >
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "68px 1fr 42px",
                    gap: 6,
                    alignItems: "center",
                  }}
                >
                  <span className="fa-num" style={{ fontSize: 9, fontWeight: 600, color: "var(--fg-5)" }}>{dateStr} {timeStr}</span>
                  <span style={{ fontSize: 9.5, color: isFuture ? "var(--fg-2)" : "var(--fg-3)", fontWeight: isFuture ? 600 : 400, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {stars} {ev.title}
                  </span>
                  <span style={{ fontSize: 8, color: isFuture ? "#3b82f6" : impactColor, fontWeight: 600, textAlign: "center" }}>
                    {statusLabel}
                  </span>
                </div>
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(3,minmax(0,1fr))",
                    gap: 4,
                    marginTop: 4,
                    fontSize: 8.5,
                    color: "var(--fg-5)",
                  }}
                >
                  <span>实际 {calendarPanelValue(ev.actual)}</span>
                  <span>预期 {calendarPanelValue(ev.consensus)}</span>
                  <span>前值 {calendarPanelValue(ev.previous)}</span>
                </div>
              </DashboardPanelCard>
            );
          })
        ) : (
          <DashboardPanelEmptyState border="1px solid transparent" background="transparent">
            {isError ? "日历加载失败" : isLoading ? "重点日历加载中" : "暂无重点宏观事件"}
          </DashboardPanelEmptyState>
        )}
      </DashboardPanelStack>
    </div>
  );
}
