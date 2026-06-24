import { List } from "lucide-react";
import { FACard } from "@/components/shared/FACard";
import { FAEmptyState } from "@/components/shared/FAEmptyState";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import type { EventFlowTableRow } from "@/types/event-flow";
import {
  formatEventFlowHeadlineSummary,
  formatEventFlowSourceLabel,
  getImpactLabel,
  translateEventFlowValue,
} from "./eventFlowFormat";

const TABLE_HEADERS = ["时间", "事件", "类型", "来源", "资产", "黄金影响", "定价", "周期", "重要度"];
const STATUS_PILL_CLASS_NAME = "px-[5px] py-[1px] text-[9px]";

interface EventTableProps {
  table: EventFlowTableRow[];
}

function StarRating({ stars }: { stars: number }) {
  return (
    <span className="text-[10px] tracking-[0.8px] text-[var(--warn)]">
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
      eyebrow="事件表"
      accent="brand"
    >
      {table.length === 0 ? (
        <FAEmptyState title="暂无事件" description="当前时间范围内没有事件数据。" className="p-4" />
      ) : (
        <div className="overflow-x-auto">
          <div
            className="grid min-w-[780px] items-center gap-1 border-b border-[var(--border)] bg-[var(--bg-card-inner)] px-3 py-[6px]"
            style={{ gridTemplateColumns: "112px minmax(0,1.2fr) 70px 84px minmax(0,1fr) 82px 66px 62px 52px" }}
          >
            {TABLE_HEADERS.map((header) => (
              <span key={header} className="text-[10px] font-semibold tracking-[0.04em] text-[var(--fg-5)]">{header}</span>
            ))}
          </div>

          {table.map((row, i) => (
            <div
              key={i}
              className={`grid min-w-[780px] items-center gap-1 border-b border-[var(--border-faint)] px-3 py-[7px] ${
                i % 2 ? "bg-[rgba(255,255,255,0.012)]" : "bg-transparent"
              }`}
              style={{ gridTemplateColumns: "112px minmax(0,1.2fr) 70px 84px minmax(0,1fr) 82px 66px 62px 52px" }}
            >
              <span className="fa-num text-[10px] text-[var(--fg-5)]">{row.time}</span>
              {(() => {
                const headline = formatEventFlowHeadlineSummary(row.title, 56);
                const titleText = headline.foreign ? "原文事件" : headline.raw || headline.lead;
                return (
                  <span className="min-w-0 space-y-0.5" title={titleText}>
                    <span className="block truncate text-[11px] font-semibold leading-5 text-[var(--fg-2)]">{headline.lead}</span>
                    {headline.subline ? <span className="block truncate text-[10px] leading-4 text-[var(--fg-4)]">{headline.subline}</span> : null}
                  </span>
                );
              })()}
              <FAStatusPill status={row.type} domain="event" dot={false} className={STATUS_PILL_CLASS_NAME}>{translateEventFlowValue(row.type)}</FAStatusPill>
              <span className="truncate text-[10px] text-[var(--fg-4)]" title={row.source}>{formatEventFlowSourceLabel(row.source, 12).text}</span>
              <span className="fa-num truncate text-[10px] text-[var(--fg-4)]" title={row.assets}>{row.assets}</span>
              <FAStatusPill status={row.impact} domain="event" dot={false} className={STATUS_PILL_CLASS_NAME}>{getImpactLabel(row.impact)}</FAStatusPill>
              <FAStatusPill status={row.pricing} domain="event" dot={false} className={STATUS_PILL_CLASS_NAME}>{translateEventFlowValue(row.pricing)}</FAStatusPill>
              <span className="truncate text-[10px] text-[var(--fg-5)]" title={row.period}>{row.period}</span>
              <StarRating stars={row.stars} />
            </div>
          ))}

      <div className="flex justify-center py-2">
        <button
          type="button"
          className="flex items-center gap-1 rounded-[var(--radius-pill)] border border-[var(--border)] bg-transparent px-[18px] py-[5px] text-[11px] text-[var(--fg-4)] transition-colors hover:bg-[var(--bg-hover)]"
        >
          查看更多事件
        </button>
      </div>
        </div>
      )}
    </FACard>
  );
}
