import { List } from "lucide-react";
import { FACard } from "@/components/shared/FACard";
import { FAEmptyState } from "@/components/shared/FAEmptyState";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import type { EventFlowTableRow } from "@/types/event-flow";
import { getImpactLabel } from "./eventFlowFormat";

const TABLE_HEADERS = ["时间", "事件", "类型", "来源", "影响资产", "黄金方向", "定价状态", "影响期限", "可信度"];
const STATUS_PILL_CLASS_NAME = "px-[5px] py-[1px] text-[9px]";

interface EventTableProps {
  table: EventFlowTableRow[];
}

function StarRating({ stars }: { stars: number }) {
  return (
    <span className="text-[11px] tracking-[1px] text-[var(--warn)]">
      {"★".repeat(stars)}
      {"☆".repeat(5 - stars)}
    </span>
  );
}

export function EventTable({ table }: EventTableProps) {
  return (
    <FACard
      title={
        <div className="flex items-center gap-2">
          <List size={12} className="text-[var(--brand-hover)]" />
          <span>近期事件列表</span>
        </div>
      }
      eyebrow="Event Table"
      accent="brand"
    >
      {table.length === 0 ? (
        <FAEmptyState title="暂无事件" description="当前时间范围内没有事件数据。" className="p-4" />
      ) : (
        <div className="overflow-x-auto">
          {/* Header */}
          <div
            className="grid min-w-[720px] items-center gap-1 border-b border-[var(--border)] bg-[var(--bg-card-inner)] px-3 py-[6px]"
            style={{ gridTemplateColumns: "112px 1fr 70px 72px 132px 60px 68px 52px 72px" }}
          >
            {TABLE_HEADERS.map((header) => (
              <span key={header} className="text-[10px] font-semibold tracking-[0.04em] text-[var(--fg-5)]">{header}</span>
            ))}
          </div>

          {/* Rows */}
          {table.map((row, i) => (
            <div
              key={i}
              className={`grid min-w-[720px] items-center gap-1 border-b border-[var(--border-faint)] px-3 py-[7px] ${
                i % 2 ? "bg-[rgba(255,255,255,0.012)]" : "bg-transparent"
              }`}
              style={{ gridTemplateColumns: "112px 1fr 70px 72px 132px 60px 68px 52px 72px" }}
            >
              <span className="fa-num text-[10px] text-[var(--fg-5)]">{row.time}</span>
              <span className="truncate text-[11px] text-[var(--fg-2)]" title={row.title}>{row.title}</span>
              <FAStatusPill status={row.type} domain="event" dot={false} className={STATUS_PILL_CLASS_NAME}>{row.type}</FAStatusPill>
              <span className="text-[10px] text-[var(--fg-5)]">{row.source}</span>
              <span className="fa-num truncate text-[10px] text-[var(--fg-4)]">{row.assets}</span>
              <FAStatusPill status={row.impact} domain="event" dot={false} className={STATUS_PILL_CLASS_NAME}>{getImpactLabel(row.impact)}</FAStatusPill>
              <FAStatusPill status={row.pricing} domain="event" dot={false} className={STATUS_PILL_CLASS_NAME}>{row.pricing}</FAStatusPill>
              <span className="text-[10px] text-[var(--fg-5)]">{row.period}</span>
              <StarRating stars={row.stars} />
            </div>
          ))}

          {/* Footer */}
          <div className="flex justify-center py-2">
            <button
              type="button"
              className="flex items-center gap-1 rounded-[3px] border border-[var(--border)] bg-transparent px-[18px] py-[5px] text-[11px] text-[var(--fg-4)] transition-colors hover:bg-[var(--bg-hover)]"
            >
              查看更多事件
            </button>
          </div>
        </div>
      )}
    </FACard>
  );
}
