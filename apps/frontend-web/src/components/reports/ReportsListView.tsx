import { useMemo } from "react";
import type { ReportIndexItem } from "@/types/reports";
import { canOpenReport, CATEGORY_MAP, matchesReportSearch, shortRunId } from "@/components/reports/reportListMeta";
import { handleSelectKeyDown } from "@/components/reports/reportLibraryViewCommon";

export function ListView({
  items,
  onSelect,
  searchQuery,
}: {
  items: ReportIndexItem[];
  onSelect: (item: ReportIndexItem) => void;
  searchQuery: string;
}) {
  const filtered = useMemo(() => items.filter((item) => matchesReportSearch(item, searchQuery)), [items, searchQuery]);

  return (
    <div
      style={{
        background: "var(--bg-card)",
        border: "1px solid var(--border)",
        borderRadius: "var(--radius-lg)",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "110px 1.8fr 1fr 1fr 90px 90px 70px",
          padding: "8px 14px",
          background: "var(--bg-panel)",
          borderBottom: "1px solid var(--border)",
          fontSize: 9,
          fontWeight: 600,
          textTransform: "uppercase",
          color: "var(--fg-5)",
          letterSpacing: "0.08em",
          alignItems: "center",
        }}
      >
        <span>类型</span>
        <span>日期</span>
        <span>格式</span>
        <span>Run ID</span>
        <span>状态</span>
        <span>资产</span>
        <span>操作</span>
      </div>
      {filtered.map((item, idx) => {
        const cat = CATEGORY_MAP[item.type] ?? {
          label: item.type,
          color: "#94a3b8",
        };
        const isOpenable = canOpenReport(item);
        return (
          <div
            key={`${item.type}-${item.trade_date}-${item.run_id ?? idx}`}
            role={isOpenable ? "button" : undefined}
            tabIndex={isOpenable ? 0 : undefined}
            aria-label={isOpenable ? `查看${cat.label} ${item.trade_date || "未知日期"}报告` : undefined}
            style={{
              display: "grid",
              gridTemplateColumns: "110px 1.8fr 1fr 1fr 90px 90px 70px",
              padding: "10px 14px",
              borderBottom: "1px solid var(--border-faint)",
              alignItems: "center",
              gap: 10,
              fontSize: 11,
              color: "var(--fg-3)",
              cursor: isOpenable ? "pointer" : "default",
              transition: "background 120ms",
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.background = "var(--bg-hover)";
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.background = "transparent";
            }}
            onClick={() => isOpenable && onSelect(item)}
            onKeyDown={(event) => {
              if (isOpenable) handleSelectKeyDown(event, () => onSelect(item));
            }}
          >
            <span
              style={{
                padding: "1px 5px",
                background: `${cat.color}1f`,
                color: cat.color,
                borderRadius: 2,
                fontSize: 9,
                fontWeight: 600,
                display: "inline-block",
                width: "fit-content",
              }}
            >
              {cat.label}
            </span>
            <span style={{ fontFamily: "var(--font-mono)", fontSize: 10 }}>
              {item.trade_date || "-"}
            </span>
            <span style={{ fontSize: 10, color: "var(--fg-4)" }}>
              {item.format}
            </span>
            <span
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 9,
                color: "var(--fg-5)",
              }}
            >
              {shortRunId(item.run_id)}
            </span>
            <span
              style={{
                fontSize: 10,
                color: item.available ? "#10b981" : "#f59e0b",
              }}
            >
              {item.available ? "已发布" : "草稿"}
            </span>
            <span style={{ fontSize: 10, color: "var(--fg-4)" }}>-</span>
            <span style={{ fontSize: 10, color: "var(--fg-4)" }}>
              {isOpenable ? "查看" : "-"}
            </span>
          </div>
        );
      })}
    </div>
  );
}
