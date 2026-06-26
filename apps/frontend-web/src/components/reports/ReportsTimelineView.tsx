import { useMemo } from "react";
import type { ReportIndexItem } from "@/types/reports";
import { canOpenReport, CATEGORY_MAP, DOT_COLORS, formatGeneratedAt, getReportTitle, matchesReportSearch, shortRunId } from "@/components/reports/reportListMeta";
import { handleSelectKeyDown } from "@/components/reports/reportLibraryViewCommon";

export function TimelineView({
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
    <div style={{ maxWidth: 720 }}>
      {filtered.map((item, idx) => {
        const cat = CATEGORY_MAP[item.type] ?? {
          label: item.type,
          color: "#94a3b8",
        };
        const dotColor = DOT_COLORS[item.type] ?? "#94a3b8";
        const isOpenable = canOpenReport(item);
        const generatedAtLabel = formatGeneratedAt(item.generated_at);
        return (
          <div
            key={`${item.type}-${item.trade_date}-${item.run_id ?? idx}`}
            style={{
              display: "flex",
              gap: 12,
              marginBottom: 4,
            }}
          >
            <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
              <div
                style={{
                  width: 10,
                  height: 10,
                  borderRadius: "50%",
                  background: dotColor,
                  boxShadow: `0 0 6px ${dotColor}66`,
                  flexShrink: 0,
                }}
              />
              {idx < filtered.length - 1 ? (
                <div
                  style={{
                    width: 1,
                    flex: 1,
                    background: "var(--border-faint)",
                    minHeight: 20,
                    marginTop: 4,
                  }}
                />
              ) : null}
            </div>
            <div
              onClick={() => isOpenable && onSelect(item)}
              onKeyDown={(event) => {
                if (isOpenable) handleSelectKeyDown(event, () => onSelect(item));
              }}
              role={isOpenable ? "button" : undefined}
              tabIndex={isOpenable ? 0 : undefined}
              aria-label={isOpenable ? `查看${cat.label} ${item.trade_date || "未知日期"}报告` : undefined}
              style={{
                flex: 1,
                background: "var(--bg-card)",
                border: "1px solid var(--border)",
                borderRadius: "var(--radius-lg)",
                padding: "10px 12px",
                cursor: isOpenable ? "pointer" : "default",
                transition: "border-color 120ms",
                marginBottom: 8,
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.borderColor = "var(--brand)";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.borderColor = "var(--border)";
              }}
            >
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  marginBottom: 4,
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
                  }}
                >
                  {cat.label}
                </span>
                <span
                  style={{
                    fontSize: 10,
                    color: "var(--fg-5)",
                    fontFamily: "var(--font-mono)",
                  }}
                >
                  {item.trade_date || "-"}
                </span>
              </div>
              <div style={{ fontSize: 11, color: "var(--fg-2)", fontWeight: 500 }}>
                {getReportTitle(item)}
              </div>
              <div
                style={{
                  fontSize: 9,
                  color: "var(--fg-5)",
                  marginTop: 2,
                  fontFamily: "var(--font-mono)",
                }}
              >
                {shortRunId(item.run_id)} · 生成 {generatedAtLabel}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
