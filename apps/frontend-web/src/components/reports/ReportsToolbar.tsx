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
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        padding: "6px 10px",
        borderBottom: "1px solid var(--border)",
        flexShrink: 0,
      }}
    >
      {/* Search input */}
      <div
        style={{
          position: "relative",
          maxWidth: 360,
          width: "100%",
        }}
      >
        <Search
          size={11}
          style={{
            position: "absolute",
            left: 10,
            top: "50%",
            transform: "translateY(-50%)",
            color: "var(--fg-5)",
            pointerEvents: "none",
          }}
        />
        <input
          type="text"
          aria-label="搜索报告"
          placeholder="搜索报告..."
          value={searchQuery}
          onChange={(e) => onSearchChange(e.target.value)}
          style={{
            width: "100%",
            padding: "5px 10px 5px 28px",
            background: "var(--bg-card-inner)",
            border: "1px solid var(--border)",
            borderRadius: 4,
            fontSize: 11,
            color: "var(--fg-2)",
            outline: "none",
            transition: "border-color 120ms",
          }}
          onFocus={(e) => {
            e.currentTarget.style.borderColor = "var(--brand)";
          }}
          onBlur={(e) => {
            e.currentTarget.style.borderColor = "var(--border)";
          }}
        />
      </div>

      {/* View toggle */}
      <div
        style={{
          display: "flex",
          borderRadius: 4,
          overflow: "hidden",
          border: "1px solid var(--border)",
          flexShrink: 0,
        }}
      >
        {([
          { mode: "grid" as ViewMode, icon: LayoutGrid, label: "Grid" },
          { mode: "list" as ViewMode, icon: List, label: "List" },
          { mode: "timeline" as ViewMode, icon: Clock, label: "Timeline" },
        ]).map(({ mode, icon: Icon, label }) => (
          <button
            key={mode}
            type="button"
            aria-label={`切换到${label}视图`}
            aria-pressed={viewMode === mode}
            onClick={() => onViewModeChange(mode)}
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: 4,
              padding: "5px 10px",
              fontSize: 10,
              background: viewMode === mode ? "var(--brand-dim)" : "transparent",
              color: viewMode === mode ? "var(--brand-hover)" : "var(--fg-4)",
              border: "none",
              cursor: "pointer",
              transition: "all 120ms",
            }}
          >
            <Icon size={11} />
          </button>
        ))}
      </div>
    </div>
  );
}

export default ReportsToolbar;
