import { Clock3, ExternalLink, List } from "lucide-react";
import { FACard } from "@/components/shared/FACard";
import { FAEmptyState } from "@/components/shared/FAEmptyState";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { FASourceTraceBadge } from "@/components/shared/FASourceTraceBadge";
import type { EventFlowTableRow, EventFlowTimelineItem } from "@/types/event-flow";
import { getImpactLabel } from "./eventFlowFormat";

const STATUS_PILL_CLASS_NAME = "px-[5px] py-[1px] text-[9px]";

interface TimelineDisplayRow {
  id: string;
  time: string;
  title: string;
  status: EventFlowTimelineItem["status"];
  importance: EventFlowTimelineItem["importance"];
  goldImpact: string;
  pricing: string;
  verificationStatus: string;
  sourceCount: number;
}

function sourceCount(event: EventFlowTimelineItem): number {
  return event.source_refs?.length ?? 0;
}

function toDisplayRow(event: EventFlowTimelineItem): TimelineDisplayRow {
  return {
    id: event.id,
    time: [event.date, event.time].filter(Boolean).join(" ").trim() || event.time,
    title: event.title,
    status: event.status,
    importance: event.importance,
    goldImpact: event.gold_impact ?? getImpactLabel(event.impact),
    pricing: event.pricing ?? "未定价",
    verificationStatus: event.verification_status ?? "unavailable",
    sourceCount: sourceCount(event),
  };
}

function tableRowToDisplayRow(row: EventFlowTableRow): TimelineDisplayRow {
  return {
    id: row.id ?? `${row.time}-${row.title}`,
    time: row.time,
    title: row.title,
    status: "发展中",
    importance: row.stars >= 5 ? "高" : row.stars >= 3 ? "中" : "低",
    goldImpact: getImpactLabel(row.impact),
    pricing: row.pricing,
    verificationStatus: row.verification_status ?? "unavailable",
    sourceCount: row.source_refs?.length ?? 0,
  };
}

function starLabel(importance: EventFlowTimelineItem["importance"]): string {
  if (importance === "高") return "★★★★★";
  if (importance === "中") return "★★★☆☆";
  return "★☆☆☆☆";
}

function TimelineHighlights({
  timeline,
  onOpenDetail,
}: {
  timeline: EventFlowTimelineItem[];
  onOpenDetail?: (id: string) => void;
}) {
  return (
    <div className="space-y-2">
      {timeline.map((event) => (
        <article
          key={event.id}
          className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3"
        >
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-1.5">
                <FAStatusPill status={event.status} domain="event" dot={false} className={STATUS_PILL_CLASS_NAME}>
                  {event.status}
                </FAStatusPill>
                <FAStatusPill status={event.importance} domain="event" dot={false} className={STATUS_PILL_CLASS_NAME}>
                  {event.importance}
                </FAStatusPill>
                <FAStatusPill status={event.impact} domain="event" dot={false} className={STATUS_PILL_CLASS_NAME}>
                  {getImpactLabel(event.impact)}
                </FAStatusPill>
                <FAStatusPill status={event.pricing ?? "未定价"} domain="event" dot={false} className={STATUS_PILL_CLASS_NAME}>
                  {event.pricing ?? "未定价"}
                </FAStatusPill>
              </div>
              <div className="mt-2 text-[12px] font-semibold leading-5 text-[var(--fg-1)]">{event.title}</div>
              <div className="mt-1 line-clamp-2 text-[11px] leading-5 text-[var(--fg-3)]">{event.desc || "暂无事件摘要。"}</div>
            </div>
            {onOpenDetail ? (
              <button
                type="button"
                onClick={() => onOpenDetail(event.id)}
                className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-[var(--radius-sm)] border border-[var(--border)] text-[var(--fg-4)] transition-colors hover:border-[var(--border-strong)] hover:text-[var(--fg-2)]"
                aria-label={`打开事件 ${event.title} 详情`}
                title="打开事件详情"
              >
                <ExternalLink size={14} />
              </button>
            ) : null}
          </div>

          <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
            <div className="rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-panel)] px-2.5 py-2">
              <div className="text-[9px] uppercase tracking-[0.08em] text-[var(--fg-5)]">verification</div>
              <div className="mt-1 text-[11px] font-semibold text-[var(--fg-2)]">{event.verification_status ?? "unavailable"}</div>
            </div>
            <div className="rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-panel)] px-2.5 py-2">
              <div className="text-[9px] uppercase tracking-[0.08em] text-[var(--fg-5)]">gold impact</div>
              <div className="mt-1 text-[11px] font-semibold text-[var(--fg-2)]">{event.gold_impact ?? getImpactLabel(event.impact)}</div>
            </div>
            <div className="rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-panel)] px-2.5 py-2">
              <div className="text-[9px] uppercase tracking-[0.08em] text-[var(--fg-5)]">source count</div>
              <div className="mt-1 font-mono text-[12px] font-semibold text-[var(--fg-1)]">{sourceCount(event)}</div>
            </div>
            <div className="rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-panel)] px-2.5 py-2">
              <div className="text-[9px] uppercase tracking-[0.08em] text-[var(--fg-5)]">importance</div>
              <div className="mt-1 font-mono text-[11px] text-[var(--warn)]">{starLabel(event.importance)}</div>
            </div>
          </div>

          <div className="mt-3 flex flex-wrap gap-2">
            <FASourceTraceBadge source={event.time || event.date || "未返回时间"} status="updated_at" tone="info" />
            <FASourceTraceBadge source={event.source ?? "事件流"} status="source" tone="dim" />
            {event.assets ? <FASourceTraceBadge source={event.assets} status="asset" tone="info" /> : null}
          </div>
        </article>
      ))}
    </div>
  );
}

function TimelineTable({ rows }: { rows: TimelineDisplayRow[] }) {
  return (
    <div className="overflow-x-auto">
      <div
        className="grid min-w-[980px] items-center gap-2 border-b border-[var(--border)] bg-[var(--bg-card-inner)] px-3 py-[6px]"
        style={{ gridTemplateColumns: "128px 1.5fr 86px 72px 88px 108px 84px 60px" }}
      >
        {["时间", "事件", "状态", "重要性", "黄金影响", "定价", "验证", "来源数"].map((header) => (
          <span key={header} className="text-[10px] font-semibold tracking-[0.04em] text-[var(--fg-5)]">{header}</span>
        ))}
      </div>
      {rows.map((row) => (
        <div
          key={row.id}
          className="grid min-w-[980px] items-center gap-2 border-b border-[var(--border-faint)] px-3 py-[7px]"
          style={{ gridTemplateColumns: "128px 1.5fr 86px 72px 88px 108px 84px 60px" }}
        >
          <span className="fa-num text-[10px] text-[var(--fg-5)]">{row.time}</span>
          <span className="truncate text-[11px] font-semibold text-[var(--fg-2)]" title={row.title}>{row.title}</span>
          <FAStatusPill status={row.status} domain="event" dot={false} className={STATUS_PILL_CLASS_NAME}>
            {row.status}
          </FAStatusPill>
          <span className="font-mono text-[10px] text-[var(--warn)]">{starLabel(row.importance)}</span>
          <FAStatusPill tone="neutral" dot={false} className={STATUS_PILL_CLASS_NAME}>
            {row.goldImpact}
          </FAStatusPill>
          <FAStatusPill status={row.pricing} domain="event" dot={false} className={STATUS_PILL_CLASS_NAME}>
            {row.pricing}
          </FAStatusPill>
          <span className="truncate text-[10px] text-[var(--fg-4)]" title={row.verificationStatus}>
            {row.verificationStatus}
          </span>
          <span className="font-mono text-[10px] text-[var(--fg-4)]">{row.sourceCount}</span>
        </div>
      ))}
    </div>
  );
}

export function EventFlowTimelinePanel({
  timeline,
  table,
  updatedAt,
  onOpenDetail,
}: {
  timeline: EventFlowTimelineItem[];
  table?: EventFlowTableRow[];
  updatedAt?: string | null;
  onOpenDetail?: (id: string) => void;
}) {
  const displayRows = timeline.length > 0
    ? timeline.map(toDisplayRow)
    : (table ?? []).map(tableRowToDisplayRow);

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
      <FACard
        title={
          <div className="flex items-center gap-2">
            <Clock3 size={12} className="text-[var(--brand-hover)]" />
            <span>重点事件流</span>
          </div>
        }
        eyebrow="Timeline Highlights"
        accent="brand"
        action={updatedAt ? <FASourceTraceBadge source={updatedAt} status="updated_at" tone="info" /> : null}
        bodyClassName="space-y-3"
      >
        {timeline.length === 0 ? (
          <FAEmptyState title="暂无事件流" description="当前 read model 没有返回 timeline 事件。" className="py-6" />
        ) : (
          <TimelineHighlights timeline={timeline} onOpenDetail={onOpenDetail} />
        )}
      </FACard>

      <FACard
        title={
          <div className="flex items-center gap-2">
            <List size={12} className="text-[var(--brand-hover)]" />
            <span>事件表格摘要</span>
          </div>
        }
        eyebrow="Timeline Table"
        accent="brand"
      >
        {displayRows.length === 0 ? (
          <FAEmptyState title="暂无表格数据" description="timeline 和 table 都没有可展示的事件摘要。" className="py-6" />
        ) : (
          <TimelineTable rows={displayRows} />
        )}
      </FACard>
    </div>
  );
}
