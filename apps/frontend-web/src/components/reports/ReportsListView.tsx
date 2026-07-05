import { useMemo } from "react";
import type { ReportIndexItem } from "@/types/reports";
import {
  canOpenReport,
  CATEGORY_MAP,
  formatGeneratedAt,
  getMarketObservationSubtype,
  getReportTitle,
  inferAssetLabel,
  marketObservationSubtypeLabel,
  matchesReportSearch,
  shortRunId,
} from "@/components/reports/reportListMeta";
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
          gridTemplateColumns: "96px minmax(0,2.3fr) 102px 146px 78px 78px 104px 56px",
          padding: "8px 10px",
          background: "color-mix(in srgb, var(--bg-panel) 88%, transparent)",
          borderBottom: "1px solid var(--border)",
          fontSize: "var(--text-10)",
          fontWeight: 600,
          textTransform: "uppercase",
          color: "var(--fg-5)",
          letterSpacing: 0,
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
        const marketObservationSubtype = getMarketObservationSubtype(item);
        return (
          <div
            key={`${item.type}-${item.trade_date}-${item.run_id ?? idx}`}
            role={isOpenable ? "button" : undefined}
            tabIndex={isOpenable ? 0 : undefined}
            aria-label={isOpenable ? `查看${cat.label} ${item.trade_date || "未知日期"}报告` : undefined}
            style={{
              display: "grid",
              gridTemplateColumns: "96px minmax(0,2.3fr) 102px 146px 78px 78px 104px 56px",
              padding: "9px 10px",
              borderBottom: "1px solid var(--border-faint)",
              alignItems: "center",
              gap: 8,
              fontSize: "var(--text-11)",
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
            <span style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
              <span
                style={{
                  padding: "1px 5px",
                  background: `${cat.color}1f`,
                  color: cat.color,
                  borderRadius: 2,
                  fontSize: "var(--text-10)",
                  fontWeight: 600,
                  display: "inline-block",
                  width: "fit-content",
                }}
              >
                {cat.label}
              </span>
              {marketObservationSubtype ? (
                <span
                  style={{
                    padding: "1px 5px",
                    background: marketObservationSubtype === "odds" ? "rgba(245,158,11,0.12)" : "rgba(6,182,212,0.12)",
                    color: marketObservationSubtype === "odds" ? "#f59e0b" : "#06b6d4",
                    border: marketObservationSubtype === "odds" ? "1px solid rgba(245,158,11,0.28)" : "1px solid rgba(6,182,212,0.28)",
                    borderRadius: 2,
                    fontSize: "var(--text-10)",
                    fontWeight: 700,
                    display: "inline-block",
                    width: "fit-content",
                  }}
                >
                  {marketObservationSubtypeLabel(marketObservationSubtype)}
                </span>
              ) : null}
            </span>
            <span style={{ minWidth: 0 }}>
              <span style={{ display: "block", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontSize: "var(--text-12)", color: "var(--fg-2)", lineHeight: 1.35 }}>
                {title}
              </span>
              <span style={{ display: "block", marginTop: 2, fontSize: "var(--text-10)", color: "var(--fg-5)" }}>
                {item.format}
              </span>
            </span>
            <span style={{ fontFamily: "var(--font-mono)", fontSize: "var(--text-11)" }}>
              {item.trade_date || "-"}
            </span>
            <span style={{ fontFamily: "var(--font-mono)", fontSize: "var(--text-10)", color: "var(--fg-4)" }}>
              {generatedAtLabel}
            </span>
            <span
              style={{
                fontSize: "var(--text-11)",
                color: "var(--fg-4)",
              }}
            >
              {assetLabel}
            </span>
            <span
              style={{
                fontSize: "var(--text-11)",
                color: item.available ? "#10b981" : "#f59e0b",
              }}
            >
              {item.available ? "已发布" : "草稿"}
            </span>
            <span
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: "var(--text-10)",
                color: "var(--fg-5)",
              }}
            >
              {shortRunId(item.run_id)}
            </span>
            <span style={{ fontSize: "var(--text-11)", color: "var(--fg-4)" }}>
              {isOpenable ? "进入" : "-"}
            </span>
          </div>
        );
      })}
    </div>
  );
}
