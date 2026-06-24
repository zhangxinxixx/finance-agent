import { RefreshCw, Search } from "lucide-react";
import { FilterChip } from "@/components/agent-tasks/AgentTasksPageSections";
import type { AgentTaskStatusFilter } from "@/components/agent-tasks/AgentTasksRail";
import { FAFilterBar } from "@/components/shared/FAFilterBar";
import type { AgentTasksDateTab, AgentTasksStatusTab, TaskDateFilter } from "./agentTasksPageModel";

interface AgentTasksFilterBarProps {
  statusTabs: AgentTasksStatusTab[];
  activeStatus: AgentTaskStatusFilter;
  onStatusChange: (value: AgentTaskStatusFilter) => void;
  dateTabs: AgentTasksDateTab[];
  activeDate: TaskDateFilter;
  onDateChange: (value: TaskDateFilter) => void;
  query: string;
  onQueryChange: (value: string) => void;
  onRefresh: () => void;
}

export function AgentTasksFilterBar({
  statusTabs,
  activeStatus,
  onStatusChange,
  dateTabs,
  activeDate,
  onDateChange,
  query,
  onQueryChange,
  onRefresh,
}: AgentTasksFilterBarProps) {
  return (
    <FAFilterBar
      left={
        <div className="flex min-w-0 flex-col gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[9px] font-semibold uppercase tracking-[0.12em] text-[var(--fg-5)]">运行状态</span>
            {statusTabs.map((tab) => (
              <FilterChip
                key={tab.value}
                active={activeStatus === tab.value}
                label={tab.label}
                count={tab.count}
                onClick={() => onStatusChange(tab.value)}
              />
            ))}
          </div>
        </div>
      }
      right={
        <>
          <label className="inline-flex h-8 items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--bg-card)] px-3 text-[11px] text-[var(--fg-4)]">
            <span className="text-[9px] font-semibold uppercase tracking-[0.12em] text-[var(--fg-5)]">日期</span>
            <select
              value={activeDate}
              onChange={(event) => onDateChange(event.target.value as TaskDateFilter)}
              className="min-w-[120px] bg-transparent text-[11px] text-[var(--fg-2)] outline-none"
            >
              {dateTabs.map((tab) => (
                <option key={tab.value} value={tab.value} className="bg-[var(--bg-card)] text-[var(--fg-2)]">
                  {`${tab.label} (${tab.count})`}
                </option>
              ))}
            </select>
          </label>
          <label className="flex h-8 min-w-[220px] items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--bg-card)] px-3 text-[11px] text-[var(--fg-4)]">
            <Search size={12} />
            <input
              value={query}
              onChange={(event) => onQueryChange(event.target.value)}
              placeholder="搜索运行编号 / 任务类型 / 快照..."
              className="w-full bg-transparent text-[11px] text-[var(--fg-2)] outline-none placeholder:text-[var(--fg-5)]"
            />
          </label>
          <button
            type="button"
            onClick={onRefresh}
            className="inline-flex h-8 items-center gap-2 rounded-full border border-[var(--border)] bg-[var(--bg-card)] px-3.5 text-[11px] font-semibold text-[var(--fg-2)] transition-colors hover:border-[var(--border-strong)] hover:bg-[var(--bg-hover)]"
          >
            <RefreshCw size={12} />
            刷新
          </button>
        </>
      }
    />
  );
}
