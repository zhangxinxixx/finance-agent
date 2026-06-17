import { Activity } from "lucide-react";
import { FACard } from "@/components/shared/FACard";
import { FAEmptyState } from "@/components/shared/FAEmptyState";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import type { EventFlowTimelineItem } from "@/types/event-flow";
import { getImpactLabel } from "./eventFlowFormat";

interface EventTimelineProps {
  timeline: EventFlowTimelineItem[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onOpenDetail?: (id: string) => void;
}

const STATUS_PILL_CLASS_NAME = "px-[5px] py-[1px] text-[9px]";

function EventCard({ event, isActive, onClick, onOpenDetail }: { event: EventFlowTimelineItem; isActive: boolean; onClick: () => void; onOpenDetail?: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      onDoubleClick={() => onOpenDetail?.()}
      className={`flex w-full gap-2 rounded-[4px] border p-[9px] text-left transition-colors ${
        isActive
          ? "border-[var(--border-strong)] bg-[var(--bg-active)]"
          : "border-[var(--border)] bg-[var(--bg-card)] hover:border-[var(--border-strong)] hover:bg-[var(--bg-hover)]"
      }`}
    >
      <div
        className={`flex h-[30px] w-[30px] shrink-0 items-center justify-center rounded-full border`}
        style={{
          background: isActive ? "var(--brand-dim)" : "var(--bg-card-inner)",
          borderColor: isActive ? "var(--brand)" : "var(--border)",
        }}
      >
        <Activity size={12} className={isActive ? "text-[var(--brand-hover)]" : "text-[var(--fg-5)]"} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="mb-[2px] flex items-center justify-between">
          <span className="fa-num text-[10px] font-semibold text-[var(--fg-4)]">{event.time}</span>
          <span className="text-[9px] text-[var(--fg-6)]">{event.date}</span>
        </div>
        <div className="mb-[3px] truncate text-[12px] font-semibold leading-[1.3] text-[var(--fg-2)]">{event.title}</div>
        <div className="mb-[5px] line-clamp-2 text-[10px] leading-[1.45] text-[var(--fg-5)]">{event.desc}</div>
        <div className="flex flex-wrap gap-[3px]">
          <FAStatusPill status={event.type} domain="event" dot={false} className={STATUS_PILL_CLASS_NAME}>{event.type}</FAStatusPill>
          <FAStatusPill status={event.importance} domain="event" dot={false} className={STATUS_PILL_CLASS_NAME}>{event.importance}</FAStatusPill>
          <FAStatusPill status={event.status} domain="event" dot={false} className={STATUS_PILL_CLASS_NAME}>{event.status}</FAStatusPill>
          <FAStatusPill status={event.impact} domain="event" dot={false} className={STATUS_PILL_CLASS_NAME}>{getImpactLabel(event.impact)}</FAStatusPill>
        </div>
        <div className="mt-2 text-[10px] font-semibold text-[var(--brand-hover)]">
          {onOpenDetail ? "双击进入详情页" : "点击查看传导链"}
        </div>
      </div>
    </button>
  );
}

export function EventTimeline({ timeline, activeId, onSelect, onOpenDetail }: EventTimelineProps) {
  return (
    <FACard
      title="事件时间线"
      eyebrow="Timeline"
      accent="brand"
      className="flex min-h-0 flex-col"
      bodyClassName="min-h-0 flex-1 space-y-[5px] overflow-y-auto"
    >
      {timeline.length === 0 ? (
        <FAEmptyState title="暂无事件" description="当前时间范围内没有事件数据。" className="p-4" />
      ) : (
        <>
          <div className="flex items-center gap-2 pb-1">
            <span className="h-1.5 w-1.5 rounded-full bg-[var(--up)] shadow-[0_0_4px_rgba(16,185,129,0.5)]" />
            <span className="text-[10px] font-semibold text-[var(--up)]">实时</span>
          </div>
          {timeline.map((event) => (
            <EventCard
              key={event.id}
              event={event}
              isActive={activeId === event.id}
              onClick={() => onSelect(event.id)}
              onOpenDetail={onOpenDetail ? () => onOpenDetail(event.id) : undefined}
            />
          ))}
          <div className="mt-1 flex w-full items-center justify-center gap-1 rounded-[3px] border border-[var(--border)] bg-transparent py-[7px] text-[11px] text-[var(--fg-5)]">
            当前已展示全部事件
          </div>
        </>
      )}
    </FACard>
  );
}
