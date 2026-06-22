import { RotateCcw } from "lucide-react";
import { REPORTS_RAIL_PANEL_STYLE } from "./reportsRailOptions";

export function ReportsRailLoadingState() {
  return (
    <aside className="reports-rail" style={REPORTS_RAIL_PANEL_STYLE}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
        <span style={{ fontSize: 11, fontWeight: 600, color: "var(--fg-3)" }}>筛选</span>
      </div>
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} style={{ height: 24, marginBottom: 5, borderRadius: 3, background: "var(--bg-hover)", opacity: 0.4 }} />
      ))}
    </aside>
  );
}

export function ReportsRailErrorState({ message }: { message: string }) {
  return (
    <aside className="reports-rail" style={REPORTS_RAIL_PANEL_STYLE}>
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
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8, paddingBottom: 8, borderBottom: "1px solid var(--border-faint)" }}>
      <div>
        <div style={{ fontSize: 8, fontWeight: 600, letterSpacing: "0.12em", textTransform: "uppercase", color: "var(--fg-5)" }}>Report Nav</div>
        <span style={{ fontSize: 11, fontWeight: 600, color: "var(--fg-3)" }}>筛选导航</span>
      </div>
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
    <div style={{ paddingTop: 8, display: "flex", flexDirection: "column", gap: 4 }}>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 9, color: "var(--fg-5)", padding: "4px 6px", borderRadius: 4, background: "rgba(255,255,255,0.02)" }}>
        <span>可见报告</span>
        <span style={{ color: "var(--fg-2)", fontWeight: 600, fontFamily: "var(--font-mono)" }}>
          {filteredCount} / {totalCount}
        </span>
      </div>
    </div>
  );
}
