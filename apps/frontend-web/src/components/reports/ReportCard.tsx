import type { ReportIndexItem } from "@/types/reports";
import {
  canOpenReport,
  CATEGORY_MAP,
  inferAssetLabel,
  shortRunId,
  TYPE_DESCRIPTIONS,
} from "@/components/reports/reportListMeta";
import { handleSelectKeyDown } from "@/components/reports/reportLibraryViewCommon";

export function ReportCard({
  item,
  onSelect,
  searchQuery,
}: {
  item: ReportIndexItem;
  onSelect: () => void;
  searchQuery: string;
}) {
  const cat = CATEGORY_MAP[item.type] ?? {
    label: item.type,
    color: "#94a3b8",
  };

  const dateLabel = item.trade_date || "-";
  const runLabel = shortRunId(item.run_id);
  const statusLabel = item.available ? "已发布" : "草稿";
  const statusColor = item.available ? "#10b981" : "#f59e0b";
  const isOpenable = canOpenReport(item);
  const assetLabel = inferAssetLabel(item);
  const highlightMatch = searchQuery && `${cat.label} ${dateLabel}`.toLowerCase().includes(searchQuery.toLowerCase());
  const meta = TYPE_DESCRIPTIONS[item.type] ?? { summary: cat.label, tags: [cat.label] };

  return (
    <div
      onClick={isOpenable ? onSelect : undefined}
      onKeyDown={isOpenable ? (event) => handleSelectKeyDown(event, onSelect) : undefined}
      role={isOpenable ? "button" : undefined}
      tabIndex={isOpenable ? 0 : undefined}
      aria-label={isOpenable ? `查看${cat.label} ${dateLabel}报告` : undefined}
      style={{
        background: "var(--bg-card)",
        border: `1px solid ${highlightMatch ? "var(--brand)" : "var(--border)"}`,
        borderRadius: "var(--radius-lg)",
        padding: 14,
        cursor: isOpenable ? "pointer" : "default",
        transition: "all 120ms",
        display: "flex",
        flexDirection: "column",
        opacity: isOpenable ? 1 : 0.6,
        position: "relative",
        overflow: "hidden",
      }}
      onMouseEnter={(e) => {
        if (isOpenable) {
          e.currentTarget.style.borderColor = "var(--brand)";
          e.currentTarget.style.transform = "translateY(-1px)";
        }
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.borderColor = highlightMatch ? "var(--brand)" : "var(--border)";
        e.currentTarget.style.transform = "none";
      }}
    >
      <div style={{ display: "flex", gap: 4, flexWrap: "wrap", marginBottom: 6 }}>
        <span style={{ padding: "2px 6px", background: `${cat.color}1f`, color: cat.color, border: `1px solid ${cat.color}33`, borderRadius: 2, fontSize: 9, fontWeight: 600, lineHeight: "14px" }}>
          {cat.label}
        </span>
        <span style={{ padding: "2px 6px", background: `${statusColor}1f`, color: statusColor, border: `1px solid ${statusColor}33`, borderRadius: 2, fontSize: 9, fontWeight: 600, lineHeight: "14px" }}>
          {statusLabel}
        </span>
        {item.type === "options_report" ? (
          <span style={{ padding: "2px 5px", background: "rgba(52,211,153,0.1)", color: "#34d399", border: "1px solid rgba(52,211,153,0.2)", borderRadius: 2, fontSize: 9, fontWeight: 600 }}>
            策略卡
          </span>
        ) : null}
        {item.format ? (
          <span style={{ padding: "2px 6px", background: "var(--bg-panel)", border: "1px solid var(--border)", borderRadius: 2, fontSize: 8, color: "var(--fg-5)", lineHeight: "14px" }}>
            {item.format}
          </span>
        ) : null}
        {meta.tags.map((tag) => (
          <span key={tag} style={{ padding: "2px 6px", background: "rgba(255,255,255,0.04)", border: "1px solid var(--border-faint)", borderRadius: 2, fontSize: 8, color: "var(--fg-5)", lineHeight: "14px" }}>
            {tag}
          </span>
        ))}
      </div>

      <div style={{ fontWeight: 600, fontSize: 13, lineHeight: 1.35, color: "var(--fg-2)", marginBottom: 4 }}>
        {item.type === "options_report"
          ? `黄金期权结构日报 · ${dateLabel}`
          : item.type === "jin10_weekly_report"
            ? `Jin10 黄金周报 · ${dateLabel}`
            : `Jin10 黄金日报 · ${dateLabel}`}
      </div>

      <div style={{ fontSize: 10, color: "var(--fg-4)", lineHeight: 1.55, marginBottom: 8, flex: 1 }}>
        {meta.summary}
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
          gap: 6,
          marginBottom: 8,
        }}
      >
        {[
          { label: "资产", value: assetLabel, color: cat.color },
          { label: "日期", value: dateLabel, color: "var(--fg-2)" },
          { label: "绑定", value: item.run_id ? "Snapshot" : "Unbound", color: item.run_id ? "#60a5fa" : "var(--fg-5)" },
        ].map((metric) => (
          <div
            key={metric.label}
            style={{
              padding: "8px 9px",
              background: "var(--bg-card-inner)",
              border: "1px solid var(--border-faint)",
              borderRadius: 3,
            }}
          >
            <div style={{ fontSize: 8, color: "var(--fg-5)", marginBottom: 3, textTransform: "uppercase", letterSpacing: "0.08em" }}>
              {metric.label}
            </div>
            <div style={{ fontSize: 10, fontWeight: 700, color: metric.color, fontFamily: "var(--font-mono)" }}>
              {metric.value}
            </div>
          </div>
        ))}
      </div>

      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 6, padding: "6px 0", borderTop: "1px solid var(--border-faint)", marginTop: "auto" }}>
        <div className="flex items-center gap-2">
          <span style={{ fontSize: 9, color: "var(--fg-5)", fontFamily: "var(--font-mono)" }}>{runLabel}</span>
        </div>
        {isOpenable ? (
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); onSelect(); }}
            style={{ padding: "4px 12px", background: "rgba(59,130,246,0.12)", color: "var(--brand-hover)", border: "1px solid rgba(59,130,246,0.25)", borderRadius: 3, fontSize: 10, fontWeight: 600, cursor: "pointer", transition: "background 120ms" }}
          >
            查看
          </button>
        ) : (
          <span style={{ fontSize: 10, color: "var(--fg-5)" }}>不可用</span>
        )}
      </div>
    </div>
  );
}
