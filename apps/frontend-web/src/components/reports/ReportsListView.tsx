import { useMemo } from "react";
import type { ReportIndexItem } from "@/types/reports";
import { canOpenReport, CATEGORY_MAP, formatGeneratedAt, getReportTitle, inferAssetLabel, matchesReportSearch, shortRunId } from "@/components/reports/reportListMeta";
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
          gridTemplateColumns: "88px minmax(0,2.3fr) 92px 132px 72px 70px 92px 48px",
          padding: "6px 9px",
          background: "color-mix(in srgb, var(--bg-panel) 88%, transparent)",
          borderBottom: "1px solid var(--border)",
          fontSize: 8,
          fontWeight: 600,
          textTransform: "uppercase",
          color: "var(--fg-5)",
          letterSpacing: "0.08em",
          alignItems: "center",
        }}
      >
        <span>分类</span>
        <span>报告</span>
        <span>日期</span>
        <span>生成</span>
        <span>资产</span>
        <span>状态</span>
        <span>Run</span>
        <span>查看</span>
      </div>
      {filtered.map((item, idx) => {
        const cat = CATEGORY_MAP[item.type] ?? {
          label: item.type,
          color: "#94a3b8",
        };
        const isOpenable = canOpenReport(item);
        const assetLabel = inferAssetLabel(item);
        const title = getReportTitle(item);
        const generatedAtLabel = formatGeneratedAt(item.generated_at);
        return (
          <div
            key={`${item.type}-${item.trade_date}-${item.run_id ?? idx}`}
            role={isOpenable ? "button" : undefined}
            tabIndex={isOpenable ? 0 : undefined}
            aria-label={isOpenable ? `查看${cat.label} ${item.trade_date || "未知日期"}报告` : undefined}
            style={{
              display: "grid",
              gridTemplateColumns: "88px minmax(0,2.3fr) 92px 132px 72px 70px 92px 48px",
              padding: "7px 9px",
              borderBottom: "1px solid var(--border-faint)",
              alignItems: "center",
              gap: 6,
              fontSize: 10,
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
                fontSize: 8,
                fontWeight: 600,
                display: "inline-block",
                width: "fit-content",
              }}
            >
              {cat.label}
            </span>
            <span style={{ minWidth: 0 }}>
              <span style={{ display: "block", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontSize: 9.5, color: "var(--fg-2)" }}>
                {title}
              </span>
              <span style={{ display: "block", marginTop: 1, fontSize: 8, color: "var(--fg-5)" }}>
                {item.format}
              </span>
            </span>
            <span style={{ fontFamily: "var(--font-mono)", fontSize: 9 }}>
              {item.trade_date || "-"}
            </span>
            <span style={{ fontFamily: "var(--font-mono)", fontSize: 8.5, color: "var(--fg-4)" }}>
              {generatedAtLabel}
            </span>
            <span
              style={{
                fontSize: 9,
                color: "var(--fg-4)",
              }}
            >
              {assetLabel}
            </span>
            <span
              style={{
                fontSize: 9,
                color: item.available ? "#10b981" : "#f59e0b",
              }}
            >
              {item.available ? "已发布" : "草稿"}
            </span>
            <span
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 8,
                color: "var(--fg-5)",
              }}
            >
              {shortRunId(item.run_id)}
            </span>
            <span style={{ fontSize: 9, color: "var(--fg-4)" }}>
              {isOpenable ? "进入" : "-"}
            </span>
          </div>
        );
      })}
    </div>
  );
}
