import { Clock3, ExternalLink, List } from "lucide-react";
import { FACard } from "@/components/shared/FACard";
import { FAEmptyState } from "@/components/shared/FAEmptyState";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { FASourceTraceBadge } from "@/components/shared/FASourceTraceBadge";
import type { EventFlowRelatedNewsItem, EventFlowTableRow, EventFlowTimelineItem } from "@/types/event-flow";
import {
  formatEventFlowHeadlineSummary,
  formatEventFlowSourceLabel,
  getImpactLabel,
  translateEventFlowValue,
} from "./eventFlowFormat";
import { formatGoldMainlineLabel, formatTransmissionPathLabel } from "@/components/shared/goldMainlineFormat";
import { EventGoldMainlineTrace } from "./EventGoldMainlineTrace";

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
  mainlineLabel: string | null;
  pathLabel: string | null;
}

function sourceCount(event: EventFlowTimelineItem): number {
  return Math.max(event.source_refs?.length ?? 0, event.related_news_items?.length ?? 0);
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
    verificationStatus: translateEventFlowValue(event.verification_status ?? "unavailable"),
    sourceCount: sourceCount(event),
    mainlineLabel: event.primary_mainline ? formatGoldMainlineLabel(event.primary_mainline) : null,
    pathLabel: event.transmission_chains?.[0] ? formatTransmissionPathLabel(event.transmission_chains[0]) : null,
  };
}

function RelatedNewsItems({ items }: { items?: EventFlowRelatedNewsItem[] }) {
  const visible = (items ?? []).slice(0, 3);
  if (visible.length === 0) return null;

  return (
    <div className="mt-3 rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2.5 py-2">
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <span className="text-[10px] font-semibold text-[var(--fg-5)]">相关快讯</span>
        <span className="font-mono text-[10px] text-[var(--fg-5)]">{visible.length}/{items?.length ?? visible.length}</span>
      </div>
      <div className="space-y-1.5">
        {visible.map((item) => {
          const content = (
            <>
              <span className="shrink-0 rounded-[4px] border border-[var(--border)] px-1.5 py-[1px] text-[9px] font-semibold text-[var(--fg-4)]">
                {item.source_label || item.source}
              </span>
              <span className="min-w-0 flex-1 truncate text-[10px] leading-4 text-[var(--fg-2)]">{item.title || "未命名快讯"}</span>
              <span className="hidden shrink-0 text-[9px] text-[var(--fg-5)] sm:inline">
                {item.published_at?.slice(0, 16).replace("T", " ") || item.domain || "待评估"}
              </span>
            </>
          );
          const key = item.news_item_id || item.source_ref || item.url || item.title;
          return item.url ? (
            <a
              key={key}
              href={item.url}
              target="_blank"
              rel="noreferrer"
              className="flex min-w-0 items-center gap-2 rounded-[4px] px-1 py-1 transition-colors hover:bg-[var(--bg-hover)]"
              title={item.title}
            >
              {content}
            </a>
          ) : (
            <div key={key} className="flex min-w-0 items-center gap-2 rounded-[4px] px-1 py-1" title={item.title}>
              {content}
            </div>
          );
        })}
      </div>
    </div>
  );
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
    verificationStatus: translateEventFlowValue(row.verification_status ?? "unavailable"),
    sourceCount: Math.max(row.source_refs?.length ?? 0, row.related_news_items?.length ?? 0),
    mainlineLabel: null,
    pathLabel: null,
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
      {timeline.map((event) => {
        const headline = formatEventFlowHeadlineSummary(event.title, 68);
        return (
        <article
          key={event.id}
          className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3"
        >
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-1.5">
                <FAStatusPill status={event.status} domain="event" dot={false} className={STATUS_PILL_CLASS_NAME}>
                  {translateEventFlowValue(event.status)}
                </FAStatusPill>
                <FAStatusPill status={event.importance} domain="event" dot={false} className={STATUS_PILL_CLASS_NAME}>
                  {translateEventFlowValue(event.importance)}
                </FAStatusPill>
                <FAStatusPill status={event.impact} domain="event" dot={false} className={STATUS_PILL_CLASS_NAME}>
                  {getImpactLabel(event.impact)}
                </FAStatusPill>
                <FAStatusPill status={event.pricing ?? "未定价"} domain="event" dot={false} className={STATUS_PILL_CLASS_NAME}>
                  {translateEventFlowValue(event.pricing ?? "未定价")}
                </FAStatusPill>
              </div>
              <div className="mt-2 space-y-1">
                <div className="text-[13px] font-semibold leading-5 text-[var(--fg-1)]">{headline.lead}</div>
                {headline.subline ? <div className="line-clamp-1 text-[11px] leading-5 text-[var(--fg-4)]">{headline.subline}</div> : null}
              </div>
              <div className="mt-1 line-clamp-2 text-[11px] leading-5 text-[var(--fg-3)]">{event.desc || "暂无事件摘要。"}</div>
              <div className="mt-2">
                <EventGoldMainlineTrace event={event} />
              </div>
              <RelatedNewsItems items={event.related_news_items} />
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

          <div className="mt-3 flex flex-wrap gap-x-4 gap-y-2 text-[11px]">
            <div className="inline-flex items-baseline gap-1.5">
              <span className="text-[var(--fg-5)]">验证</span>
              <span className="font-semibold text-[var(--fg-2)]">{translateEventFlowValue(event.verification_status ?? "unavailable")}</span>
            </div>
            <div className="inline-flex items-baseline gap-1.5">
              <span className="text-[var(--fg-5)]">黄金影响</span>
              <span className="font-semibold text-[var(--fg-2)]">{event.gold_impact ?? getImpactLabel(event.impact)}</span>
            </div>
            <div className="inline-flex items-baseline gap-1.5">
              <span className="text-[var(--fg-5)]">来源数</span>
              <span className="font-mono font-semibold text-[var(--fg-1)]">{sourceCount(event)}</span>
            </div>
          </div>

          <div className="mt-3 flex flex-wrap gap-2">
            <FASourceTraceBadge source={event.time || event.date || "未返回时间"} status="updated_at" tone="info" />
            <FASourceTraceBadge source={formatEventFlowSourceLabel(event.source ?? "事件流", 16).text} status="来源" tone="dim" />
            {event.assets ? <FASourceTraceBadge source={event.assets} status="asset" tone="info" /> : null}
          </div>
        </article>
        );
      })}
    </div>
  );
}

function TimelineTable({
  rows,
  onOpenDetail,
}: {
  rows: TimelineDisplayRow[];
  onOpenDetail?: (id: string) => void;
}) {
  const columnTemplate = "128px minmax(0,1.55fr) 86px 72px 88px 108px 84px 60px";

  return (
    <div className="overflow-x-auto">
      <div
        className="grid min-w-[980px] items-center gap-2 border-b border-[var(--border)] bg-[var(--bg-card-inner)] px-3 py-[6px]"
        style={{ gridTemplateColumns: columnTemplate }}
      >
        {["时间", "事件", "状态", "重要性", "黄金影响", "定价", "验证", "来源数"].map((header) => (
          <span key={header} className="text-[10px] font-semibold tracking-[0.04em] text-[var(--fg-5)]">{header}</span>
        ))}
      </div>
      {rows.map((row) => {
        const headline = formatEventFlowHeadlineSummary(row.title, 62);
        return (
        <button
          type="button"
          key={row.id}
          onClick={onOpenDetail ? () => onOpenDetail(row.id) : undefined}
          className="grid min-w-[980px] items-center gap-2 border-b border-[var(--border-faint)] px-3 py-[7px] text-left transition-colors hover:bg-[var(--bg-hover)] disabled:cursor-default"
          style={{ gridTemplateColumns: columnTemplate }}
          disabled={!onOpenDetail}
        >
          <span className="fa-num text-[10px] text-[var(--fg-5)]">{row.time}</span>
          <span className="min-w-0 space-y-0.5" title={row.title}>
            <span className="block truncate text-[11px] font-semibold leading-5 text-[var(--fg-2)]">{headline.lead}</span>
            {headline.subline ? <span className="block truncate text-[10px] leading-4 text-[var(--fg-4)]">{headline.subline}</span> : null}
            {row.mainlineLabel || row.pathLabel ? (
              <span className="block truncate text-[10px] leading-4 text-[var(--fg-5)]">
                {[row.mainlineLabel, row.pathLabel].filter(Boolean).join(" / ")}
              </span>
            ) : null}
          </span>
          <FAStatusPill status={row.status} domain="event" dot={false} className={STATUS_PILL_CLASS_NAME}>
            {translateEventFlowValue(row.status)}
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
        </button>
        );
      })}
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
            <span>时间线</span>
          </div>
        }
        eyebrow="事件高亮"
        accent="brand"
        action={updatedAt ? <FASourceTraceBadge source={updatedAt} status="updated_at" tone="info" /> : null}
        bodyClassName="space-y-3"
      >
        {timeline.length === 0 ? (
          <FAEmptyState title="暂无事件流" description="当前读模型没有返回时间线事件。" className="py-6" />
        ) : (
          <TimelineHighlights timeline={timeline} onOpenDetail={onOpenDetail} />
        )}
      </FACard>

      <FACard
        title={
          <div className="flex items-center gap-2">
            <List size={12} className="text-[var(--brand-hover)]" />
            <span>事件表</span>
          </div>
        }
        eyebrow="时间线表"
        accent="brand"
      >
        {displayRows.length === 0 ? (
          <FAEmptyState title="暂无表格数据" description="timeline 和 table 都没有可展示的事件摘要。" className="py-6" />
        ) : (
          <TimelineTable rows={displayRows} onOpenDetail={onOpenDetail} />
        )}
      </FACard>
    </div>
  );
}
