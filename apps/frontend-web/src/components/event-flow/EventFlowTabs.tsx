import { FATabBar } from "@/components/shared/FATabBar";

export type EventFlowTabKey = "overview" | "live" | "timeline" | "impact" | "inputs";

export const EVENT_FLOW_TABS: Array<{ value: EventFlowTabKey; label: string; count?: number }> = [
  { value: "overview", label: "总览" },
  { value: "live", label: "快讯" },
  { value: "timeline", label: "时间线" },
  { value: "impact", label: "影响" },
  { value: "inputs", label: "输入" },
];

export function isEventFlowTab(value: string | null): value is EventFlowTabKey {
  return EVENT_FLOW_TABS.some((tab) => tab.value === value);
}

export function EventFlowTabs({
  value,
  onChange,
  liveCount,
  timelineCount,
  onOpenActiveEvent,
}: {
  value: EventFlowTabKey;
  onChange: (value: EventFlowTabKey) => void;
  liveCount?: number;
  timelineCount?: number;
  onOpenActiveEvent?: () => void;
}) {
  const tabs = EVENT_FLOW_TABS.map((tab) => {
    if (tab.value === "live") return { ...tab, count: liveCount };
    if (tab.value === "timeline") return { ...tab, count: timelineCount };
    return tab;
  });

  return (
    <div className="event-flow-tabs-strip">
      <FATabBar tabs={tabs} value={value} onChange={onChange} ariaLabel="事件流层级切换" />
      {onOpenActiveEvent ? (
        <button type="button" onClick={onOpenActiveEvent} className="event-flow-active-anchor">
          <span className="event-flow-selection-label">主线</span>
          <span className="text-[11px] font-semibold text-[var(--brand-hover)]">查看详情</span>
        </button>
      ) : null}
    </div>
  );
}
