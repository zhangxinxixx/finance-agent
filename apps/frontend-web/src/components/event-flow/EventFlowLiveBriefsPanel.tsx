import { ExternalLink } from "lucide-react";
import { FACard } from "@/components/shared/FACard";
import { FAEmptyState } from "@/components/shared/FAEmptyState";
import { FASourceTraceBadge } from "@/components/shared/FASourceTraceBadge";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { formatDateTime } from "@/lib/date";
import { compactSourceLabel } from "@/lib/sourceRefs";
import type {
  EventFlowProgressTriggerBundle,
  EventFlowRelatedNewsItem,
  EventFlowTimelineItem,
} from "@/types/event-flow";
import { formatEventFlowHeadlineSummary, formatEventFlowSourceLabel } from "./eventFlowFormat";

interface EventFlowLiveBriefsPanelProps {
  progressBundle?: EventFlowProgressTriggerBundle | null;
  timeline?: EventFlowTimelineItem[];
}

function priorityTone(priority: string | null | undefined): "warn" | "info" | "dim" {
  const normalized = String(priority ?? "").trim().toLowerCase();
  if (normalized === "high" || normalized === "高") return "warn";
  if (normalized === "medium" || normalized === "中") return "info";
  return "dim";
}

function priorityLabel(priority: string | null | undefined): string {
  const normalized = String(priority ?? "").trim().toLowerCase();
  if (normalized === "high" || normalized === "高") return "高";
  if (normalized === "medium" || normalized === "中") return "中";
  if (normalized === "normal" || normalized === "low" || normalized === "低") return "低";
  return "待判定";
}

function isSameTradeDate(value: string | null | undefined, date: string | null | undefined): boolean {
  if (!date) return true;
  if (!value) return false;
  return value.startsWith(date);
}

function relatedNewsKey(item: EventFlowRelatedNewsItem): string {
  return item.news_item_id || item.source_ref || item.url || `${item.source}:${item.title}:${item.published_at ?? ""}`;
}

function isJinshiRelatedNews(item: EventFlowRelatedNewsItem): boolean {
  const text = [
    item.source,
    item.source_label,
    item.source_ref,
    item.url,
    item.domain,
    item.raw_path,
    item.parsed_path,
  ].join(" ").toLowerCase();
  return text.includes("jin10") || text.includes("xnews.jin10.com") || text.includes("flash.jin10.com") || text.includes("金十");
}

function isValuableRelatedNews(item: EventFlowRelatedNewsItem): boolean {
  const title = (item.title ?? "").trim();
  if (!title) return false;
  if (title === "重点事件持续发酵" || title === "未命名快讯") return false;
  if (isJinshiRelatedNews(item)) return false;
  return Boolean(item.url || item.domain || item.source_ref);
}

function collectRelatedNewsItems(timeline: EventFlowTimelineItem[] | undefined, date: string | null | undefined): EventFlowRelatedNewsItem[] {
  const seen = new Set<string>();
  const items: EventFlowRelatedNewsItem[] = [];

  for (const event of timeline ?? []) {
    for (const item of event.related_news_items ?? []) {
      if (!isValuableRelatedNews(item)) continue;
      if (date && item.published_at && !isSameTradeDate(item.published_at, date)) continue;
      const key = relatedNewsKey(item);
      if (seen.has(key)) continue;
      seen.add(key);
      items.push(item);
    }
  }

  return items.sort((a, b) => (b.published_at ?? "").localeCompare(a.published_at ?? ""));
}

function RelatedNewsCard({ item }: { item: EventFlowRelatedNewsItem }) {
  const headline = formatEventFlowHeadlineSummary(item.title, 58);
  const meta = [item.source_label || item.source, item.published_at ? formatDateTime(item.published_at) : null, item.domain].filter(Boolean);
  const summary = (item.summary ?? "").trim();

  const content = (
    <>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-1.5 text-[10px] text-[var(--fg-5)]">
          <FAStatusPill tone="info">{item.source_label || item.source || "新闻源"}</FAStatusPill>
          {item.importance ? <FAStatusPill tone={priorityTone(item.importance)}>{priorityLabel(item.importance)}</FAStatusPill> : null}
          {item.published_at ? <span>{formatDateTime(item.published_at)}</span> : null}
          {item.domain ? <span>{item.domain}</span> : null}
        </div>
        <div className="mt-2 space-y-1">
          <div className="text-[12px] font-semibold leading-5 text-[var(--fg-1)]" title={headline.raw}>
            {headline.lead}
          </div>
          {headline.subline ? <div className="line-clamp-1 text-[11px] leading-5 text-[var(--fg-4)]">{headline.subline}</div> : null}
          {summary ? <div className="line-clamp-2 text-[11px] leading-5 text-[var(--fg-3)]">{summary}</div> : null}
        </div>
        {item.source_ref ? (
          <div className="mt-3 flex flex-wrap gap-1.5">
            <FASourceTraceBadge
              source={formatEventFlowSourceLabel(item.source_ref, 20).text}
              status={item.status ?? "ok"}
              tone="info"
            />
          </div>
        ) : null}
      </div>

      {item.url ? (
        <span className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-[var(--radius-sm)] border border-[var(--border)] text-[var(--fg-4)]">
          <ExternalLink size={13} />
        </span>
      ) : null}
    </>
  );

  return item.url ? (
    <a
      href={item.url}
      target="_blank"
      rel="noreferrer"
      className="flex items-start justify-between gap-3 rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3 transition-colors hover:bg-[var(--bg-hover)]"
      title={meta.join(" · ")}
    >
      {content}
    </a>
  ) : (
    <article className="flex items-start justify-between gap-3 rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3" title={meta.join(" · ")}>
      {content}
    </article>
  );
}

function ProgressTriggerCard({ item }: { item: EventFlowProgressTriggerBundle["triggers"][number] }) {
  const headline = formatEventFlowHeadlineSummary(item.source_title, 58);
  const summary = item.evidence_text?.trim() && item.evidence_text.trim() !== item.source_title.trim() ? item.evidence_text.trim() : "";
  const meta = [
    item.published_at ? formatDateTime(item.published_at) : item.created_at ? formatDateTime(item.created_at) : null,
    item.source_domain,
  ].filter(Boolean);

  const content = (
    <>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-1.5 text-[10px] text-[var(--fg-5)]">
          <FAStatusPill tone={priorityTone(item.priority)}>{priorityLabel(item.priority)}</FAStatusPill>
          <FAStatusPill tone="warn">重点快讯</FAStatusPill>
          {meta.map((value) => (
            <span key={String(value)}>{value}</span>
          ))}
        </div>
        <div className="mt-2 space-y-1">
          <div className="text-[12px] font-semibold leading-5 text-[var(--fg-1)]" title={headline.raw}>
            {headline.lead}
          </div>
          {headline.subline ? <div className="line-clamp-1 text-[11px] leading-5 text-[var(--fg-4)]">{headline.subline}</div> : null}
          {summary ? <div className="line-clamp-2 text-[11px] leading-5 text-[var(--fg-3)]">{summary}</div> : null}
        </div>
        <div className="mt-3 flex flex-wrap gap-1.5">
          {item.source_url ? (
            <FASourceTraceBadge
              source={`来源 ${formatEventFlowSourceLabel(item.source_url, 18).text}`}
              status="source_url"
              tone="info"
            />
          ) : null}
          {(item.source_refs ?? []).slice(0, 3).map((ref) => (
            <FASourceTraceBadge
              key={[ref.source_ref, ref.endpoint ?? "", ref.artifact_path ?? ""].join("|")}
              source={formatEventFlowSourceLabel(compactSourceLabel(ref), 20).text}
              status={ref.status ?? "available"}
            />
          ))}
        </div>
      </div>

      {item.source_url ? (
        <span className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-[var(--radius-sm)] border border-[var(--border)] text-[var(--fg-4)]">
          <ExternalLink size={13} />
        </span>
      ) : null}
    </>
  );

  return item.source_url ? (
    <a
      href={item.source_url}
      target="_blank"
      rel="noreferrer"
      className="flex items-start justify-between gap-3 rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3 transition-colors hover:bg-[var(--bg-hover)]"
      title={meta.join(" · ")}
    >
      {content}
    </a>
  ) : (
    <article className="flex items-start justify-between gap-3 rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3" title={meta.join(" · ")}>
      {content}
    </article>
  );
}

export function EventFlowLiveBriefsPanel({ progressBundle, timeline }: EventFlowLiveBriefsPanelProps) {
  const date = progressBundle?.date ?? null;
  const triggerItems = (progressBundle?.triggers ?? []).slice(0, 6);
  const relatedNewsItems = collectRelatedNewsItems(timeline, date);
  const displayCount = triggerItems.length + relatedNewsItems.length;

  return (
    <FACard
      title="当日相关新闻"
      eyebrow="事件快讯"
      accent="warn"
      className="event-flow-live-card"
      action={<FAStatusPill tone={displayCount > 0 ? "warn" : "dim"}>{displayCount} 条</FAStatusPill>}
      bodyClassName="space-y-2"
    >
      <div className="flex flex-wrap items-center gap-2 text-[10px] text-[var(--fg-5)]">
        <span>日期：{date ?? "未返回"}</span>
        <span>更新：{progressBundle?.as_of ? formatDateTime(progressBundle.as_of) : "未返回"}</span>
        <span>优先展示重点快讯与外部新闻源</span>
      </div>

      {displayCount === 0 ? (
        <FAEmptyState
          title="当日没有可展示的快讯"
          description="当前事件流没有返回可展示的重点快讯或外部新闻快讯。"
        />
      ) : (
        <div className="space-y-2">
          {triggerItems.length > 0 ? (
            <section className="space-y-2">
              <div className="flex items-center justify-between gap-2 text-[10px] text-[var(--fg-5)]">
                <span>重点快讯</span>
                <span>{triggerItems.length} 条</span>
              </div>
              {triggerItems.map((item) => (
                <ProgressTriggerCard key={item.trigger_id} item={item} />
              ))}
            </section>
          ) : null}

          {relatedNewsItems.length > 0 ? (
            <section className="space-y-2">
              <div className="flex items-center justify-between gap-2 text-[10px] text-[var(--fg-5)]">
                <span>外部相关新闻</span>
                <span>{relatedNewsItems.length} 条</span>
              </div>
              {relatedNewsItems.map((item) => (
                <RelatedNewsCard key={relatedNewsKey(item)} item={item} />
              ))}
            </section>
          ) : null}
        </div>
      )}
    </FACard>
  );
}
