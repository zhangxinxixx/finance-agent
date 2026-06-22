import { Search, LayoutGrid, List, Clock } from "lucide-react";

export type ViewMode = "grid" | "list" | "timeline";

interface ReportsToolbarProps {
  searchQuery: string;
  onSearchChange: (query: string) => void;
  viewMode: ViewMode;
  onViewModeChange: (mode: ViewMode) => void;
}

export function ReportsToolbar({
  searchQuery,
  onSearchChange,
  viewMode,
  onViewModeChange,
}: ReportsToolbarProps) {
  return (
    <div className="mb-1.5 flex flex-wrap items-center gap-2 rounded-[var(--radius-lg)] border border-[var(--border-faint)] bg-[var(--bg-card)] px-2.5 py-1.5">
      <div className="relative min-w-[220px] flex-1">
        <Search
          size={11}
          className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[var(--fg-5)]"
        />
        <input
          type="text"
          aria-label="搜索报告"
          placeholder="搜索报告..."
          value={searchQuery}
          onChange={(e) => onSearchChange(e.target.value)}
          className="h-8 w-full rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-card-inner)] pl-8 pr-3 text-[11px] text-[var(--fg-2)] outline-none transition-colors placeholder:text-[var(--fg-5)] focus:border-[var(--brand-border)]"
        />
      </div>

      <div className="flex shrink-0 overflow-hidden rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-card-inner)]">
        {([
          { mode: "grid" as ViewMode, icon: LayoutGrid, label: "网格" },
          { mode: "list" as ViewMode, icon: List, label: "列表" },
          { mode: "timeline" as ViewMode, icon: Clock, label: "时间线" },
        ]).map(({ mode, icon: Icon, label }) => (
          <button
            key={mode}
            type="button"
            aria-label={`切换到${label}视图`}
            aria-pressed={viewMode === mode}
            onClick={() => onViewModeChange(mode)}
            title={label}
            className={`inline-flex h-8 w-9 items-center justify-center border-r border-[var(--border)] text-[10px] transition-colors last:border-r-0 ${
              viewMode === mode
                ? "bg-[var(--brand-soft)] text-[var(--brand)]"
                : "text-[var(--fg-4)] hover:bg-[var(--bg-panel)] hover:text-[var(--fg-2)]"
            }`}
          >
            <Icon size={11} />
          </button>
        ))}
      </div>
    </div>
  );
}

export default ReportsToolbar;
