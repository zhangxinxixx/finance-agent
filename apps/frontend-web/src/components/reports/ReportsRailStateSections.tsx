import { RotateCcw } from "lucide-react";
import { REPORTS_RAIL_PANEL_STYLE } from "./reportsRailOptions";

export function ReportsRailLoadingState() {
  return (
    <aside style={REPORTS_RAIL_PANEL_STYLE}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
        <span style={{ fontSize: 11, fontWeight: 600, color: "var(--fg-3)" }}>筛选</span>
      </div>
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} style={{ height: 28, marginBottom: 6, borderRadius: 3, background: "var(--bg-hover)", opacity: 0.4 }} />
      ))}
    </aside>
  );
}

export function ReportsRailErrorState({ message }: { message: string }) {
  return (
    <aside style={REPORTS_RAIL_PANEL_STYLE}>
      <div style={{ fontSize: 10, color: "var(--down)" }}>{message}</div>
    </aside>
  );
}

export function ReportsRailHeader({
  hasActiveFilters,
  onReset,
}: {
  hasActiveFilters: boolean;
  onReset: () => void;
}) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
      <span style={{ fontSize: 11, fontWeight: 600, color: "var(--fg-3)" }}>筛选</span>
      {hasActiveFilters ? (
        <button
          type="button"
          onClick={onReset}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 3,
            background: "none",
            border: "none",
            cursor: "pointer",
            fontSize: 10,
            color: "var(--brand-hover)",
            padding: 0,
          }}
        >
          <RotateCcw size={9} />
          重置
        </button>
      ) : null}
    </div>
  );
}

export function ReportsRailFooter({ filteredCount, totalCount }: { filteredCount: number; totalCount: number }) {
  return (
    <div style={{ paddingTop: 10, borderTop: "1px solid var(--border-faint)", display: "flex", flexDirection: "column", gap: 4 }}>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, color: "var(--fg-5)" }}>
        <span>已筛选</span>
        <span style={{ color: "var(--fg-2)", fontWeight: 600 }}>
          {filteredCount} / {totalCount}
        </span>
      </div>
    </div>
  );
}
