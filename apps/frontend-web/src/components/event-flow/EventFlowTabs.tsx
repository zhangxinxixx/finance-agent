import { FATabBar } from "@/components/shared/FATabBar";

export type EventFlowTabKey = "overview" | "live" | "timeline" | "impact" | "inputs";

export const EVENT_FLOW_TABS: Array<{ value: EventFlowTabKey; label: string; count?: number }> = [
  { value: "overview", label: "总览" },
  { value: "live", label: "当日快讯" },
  { value: "timeline", label: "事件流" },
  { value: "impact", label: "影响分析" },
  { value: "inputs", label: "报告输入" },
];

export function isEventFlowTab(value: string | null): value is EventFlowTabKey {
  return EVENT_FLOW_TABS.some((tab) => tab.value === value);
}

export function EventFlowTabs({
  value,
  onChange,
  liveCount,
  timelineCount,
}: {
  value: EventFlowTabKey;
  onChange: (value: EventFlowTabKey) => void;
  liveCount?: number;
  timelineCount?: number;
}) {
  const tabs = EVENT_FLOW_TABS.map((tab) => {
    if (tab.value === "live") return { ...tab, count: liveCount };
    if (tab.value === "timeline") return { ...tab, count: timelineCount };
    return tab;
  });

  return (
    <div className="flex items-center justify-between gap-3 rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card)] px-3 py-2">
      <FATabBar tabs={tabs} value={value} onChange={onChange} ariaLabel="事件流层级切换" />
      <div className="hidden text-[10px] text-[var(--fg-5)] lg:block">
        只读分层视图 · 来源、影响路径和行情验证均来自后端 read model
      </div>
    </div>
  );
}
