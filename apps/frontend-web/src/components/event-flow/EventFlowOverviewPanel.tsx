import {
  AlertTriangle,
  FileStack,
  GitBranch,
  Layers3,
  Radar,
  ShieldAlert,
} from "lucide-react";
import { FACard } from "@/components/shared/FACard";
import { FAEmptyState } from "@/components/shared/FAEmptyState";
import { FASourceTraceBadge } from "@/components/shared/FASourceTraceBadge";
import { FAStatusPill, type FAStatusTone } from "@/components/shared/FAStatusPill";
import { formatDateTime } from "@/lib/date";
import type { SourceRef } from "@/types/common";
import type {
  EventFlowBriefSummary,
  EventFlowTableRow,
  EventFlowTimelineItem,
  EventFlowViewModel,
} from "@/types/event-flow";
import {
  formatEventFlowHeadline,
  formatEventFlowHeadlineSummary,
  formatEventFlowSourceLabel,
  formatEventFlowTagLabel,
  translateEventFlowValue,
} from "./eventFlowFormat";

interface EventFlowOverviewPanelProps {
  data: EventFlowViewModel;
  summary?: EventFlowBriefSummary | null;
  timeline?: EventFlowTimelineItem[];
  table?: EventFlowTableRow[];
  sourceRefs?: SourceRef[];
  onOpenDetail?: (id: string) => void;
  className?: string;
}

interface OverviewStatusMeta {
  label: string;
  tone: FAStatusTone;
  description: string;
}

interface OverviewAssetItem {
  name: string;
  count: number;
  dominant: string;
}

interface ResearchLine {
  body: string;
  tags: string[];
}

interface OngoingMainlineItem {
  key: string;
  title: ReturnType<typeof formatEventFlowHeadlineSummary>;
  desc: ReturnType<typeof formatEventFlowHeadline>;
  source: string;
  meta: string;
  tone: FAStatusTone;
  label: string;
  impact?: string | null;
  eventId?: string;
}

const SECTION_TONE: Record<string, FAStatusTone> = {
  available: "up",
  partial: "warn",
  error: "down",
  unavailable: "dim",
  mock: "warn",
  fallback: "warn",
};

function eventTimestamp(event: EventFlowTimelineItem): number {
  const candidates = [event.time, event.date].filter(Boolean);
  for (const candidate of candidates) {
    const parsed = Date.parse(candidate);
    if (Number.isFinite(parsed)) return parsed;
  }
  return -1;
}

function eventWeight(event: EventFlowTimelineItem): number {
  let score = 0;
  if (event.importance === "高") score += 40;
  else if (event.importance === "中") score += 24;
  else score += 8;
  if (event.risk_level === "high") score += 18;
  else if (event.risk_level === "medium") score += 10;
  if (event.pricing === "未定价") score += 12;
  else if (event.pricing === "部分定价") score += 6;
  if (event.verification_status === "needs_verification") score += 4;
  if (event.event_kind === "confirmed_event") score += 8;
  return score + Math.max(eventTimestamp(event), 0) / 1_000_000_000_000;
}

function uniqueStrings(values: Array<string | null | undefined>, limit: number): string[] {
  const result: string[] = [];
  const seen = new Set<string>();
  for (const value of values) {
    const normalized = value?.trim();
    if (!normalized) continue;
    if (seen.has(normalized)) continue;
    seen.add(normalized);
    result.push(normalized);
    if (result.length >= limit) break;
  }
  return result;
}

function parseResearchLine(value: string): ResearchLine {
  const segments = value
    .split("|")
    .map((segment) => segment.trim())
    .filter(Boolean);

  if (segments.length === 0) {
    return { body: value, tags: [] };
  }

  const [body, ...tags] = segments;
  return {
    body,
    tags: uniqueStrings(tags.map(formatEventFlowTagLabel), 3),
  };
}

function collectResearchItems(
  values: Array<string | null | undefined>,
  limit: number,
  seenDisplayKeys: Set<string>,
): string[] {
  const result: string[] = [];
  for (const value of values) {
    const normalized = value?.trim();
    if (!normalized) continue;

    const parsed = parseResearchLine(normalized);
    const display = formatEventFlowHeadline(parsed.body, 96);
    const displayText = display.foreign ? display.raw : display.text;
    const key = normalizedMainlineKey(displayText);
    if (!key || seenDisplayKeys.has(key)) continue;

    seenDisplayKeys.add(key);
    result.push(normalized);
    if (result.length >= limit) break;
  }
  return result;
}

function collectTopEvents(data: EventFlowViewModel, timeline: EventFlowTimelineItem[]): EventFlowTimelineItem[] {
  if (timeline.length > 0) {
    return [...timeline]
      .sort((a, b) => eventWeight(b) - eventWeight(a))
      .slice(0, 5);
  }

  return (data.article_briefs?.briefs ?? [])
    .slice(0, 5)
    .map((brief) => ({
      id: `brief_${brief.brief_id}`,
      time: brief.created_at ?? "",
      date: brief.created_at?.slice(0, 10) ?? "",
      title: brief.headline,
      desc: brief.analysis_summary || brief.original_excerpt,
      type: "市场事件",
      importance: "中",
      status: "发展中",
      impact: "混合",
      source: "金十快讯摘要",
      assets: brief.asset_tags.join(", "),
      pricing: "未定价",
      source_refs: [],
      affected_assets: brief.asset_tags,
    }));
}

function aggregateAssets(table: EventFlowTableRow[], timeline: EventFlowTimelineItem[]): OverviewAssetItem[] {
  const map = new Map<string, { count: number; impacts: Record<string, number> }>();
  const rows = table.length > 0
    ? table
    : timeline.map((event) => ({
      assets: event.assets ?? event.affected_assets?.join(", ") ?? "",
      impact: event.impact,
    }));

  for (const row of rows) {
    const names = row.assets.split(",").map((item) => item.trim()).filter(Boolean);
    for (const name of names) {
      const existing = map.get(name) ?? { count: 0, impacts: {} };
      existing.count += 1;
      existing.impacts[row.impact] = (existing.impacts[row.impact] ?? 0) + 1;
      map.set(name, existing);
    }
  }

  return Array.from(map.entries())
    .map(([name, item]) => {
      const dominant =
        (item.impacts["利空黄金"] ?? 0) > (item.impacts["利多黄金"] ?? 0)
          ? "利空黄金"
          : (item.impacts["利多黄金"] ?? 0) > (item.impacts["利空黄金"] ?? 0)
            ? "利多黄金"
            : "混合";
      return { name, count: item.count, dominant };
    })
    .sort((a, b) => b.count - a.count)
    .slice(0, 5);
}

function summarizeRadar(data: EventFlowViewModel) {
  const axes = data.radar ?? [];
  if (axes.length === 0) return null;
  const sorted = [...axes].sort((a, b) => b.value - a.value);
  const average = Math.round(sorted.reduce((sum, axis) => sum + axis.value, 0) / sorted.length);
  return {
    average,
    primary: sorted[0],
    secondary: sorted[1] ?? null,
  };
}

function resolveOverviewStatus(data: EventFlowViewModel): OverviewStatusMeta {
  const source = data.source.toLowerCase();
  if (data.status === "error") {
    return { label: "异常", tone: "down", description: "当前视图存在接口或映射错误，仅保留只读摘要。" };
  }
  if (data.status === "unavailable" || source.includes("unavailable")) {
    return { label: "不可用", tone: "dim", description: "事件流接口当前不可用，面板不输出真实市场结论。" };
  }
  if (source.includes("mock")) {
    return { label: "占位", tone: "warn", description: "当前视图含模拟数据，只用于占位展示。" };
  }
  if (data.status === "partial" || source.includes("fallback")) {
    return { label: "部分返回", tone: "warn", description: "当前只返回部分输入，总览按已到达数据只读展示。" };
  }
  return { label: "实时", tone: "up", description: "当前总览基于已返回的事件流读模型。" };
}

function resolveRadarStatus(data: EventFlowViewModel): OverviewStatusMeta {
  if (data.event_impact_summary?.riskRadar && Object.keys(data.event_impact_summary.riskRadar).length > 0) {
    return { label: "推导", tone: "info", description: "风险雷达为当前读模型的摘要视图。" };
  }
  if (data.radar.length > 0) {
    return { label: "占位", tone: "warn", description: "风险雷达当前仍是占位/回退数据，不能视为真实风控结论。" };
  }
  return { label: "不可用", tone: "dim", description: "当前没有可展示的风险雷达数据。" };
}

function collectSourceRefs(
  data: EventFlowViewModel,
  sourceRefs: SourceRef[],
  timeline: EventFlowTimelineItem[],
  table: EventFlowTableRow[],
): SourceRef[] {
  const merged = [
    ...sourceRefs,
    ...data.source_refs ?? [],
    ...timeline.flatMap((event) => event.source_refs ?? []),
    ...table.flatMap((row) => row.source_refs ?? []),
  ];
  const seen = new Set<string>();
  return merged.filter((ref) => {
    const key = [ref.source_ref, ref.snapshot_id, ref.artifact_path, ref.run_id].filter(Boolean).join("|");
    if (!key || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function pillTone(value: string | null | undefined): FAStatusTone {
  const normalized = value?.toLowerCase();
  if (!normalized) return "neutral";
  if (normalized.includes("high") || normalized.includes("error")) return "down";
  if (normalized.includes("medium") || normalized.includes("partial") || normalized.includes("warn")) return "warn";
  if (normalized.includes("low") || normalized.includes("ok") || normalized.includes("available")) return "up";
  return "info";
}

function impactTone(impact: string): string {
  if (impact === "利多黄金") return "text-[var(--up)]";
  if (impact === "利空黄金") return "text-[var(--down)]";
  return "text-[var(--warn)]";
}

function isOpenMainline(event: EventFlowTimelineItem): boolean {
  if (event.importance === "高" && (event.pricing === "未定价" || event.pricing === "部分定价")) return true;
  if (event.risk_level === "high" && event.pricing !== "已定价") return true;
  return false;
}

function normalizedMainlineKey(value: string): string {
  return value
    .toLowerCase()
    .replace(/\s+/g, "")
    .replace(/[，。,.、:：/|()[\]（）]/g, "")
    .slice(0, 42);
}

function collectOngoingMainlines(
  timeline: EventFlowTimelineItem[],
  watchItems: string[],
  riskItems: string[],
): OngoingMainlineItem[] {
  const items: OngoingMainlineItem[] = [];
  const seen = new Set<string>();

  const addItem = (item: OngoingMainlineItem) => {
    if (!item.key || seen.has(item.key)) return;
    seen.add(item.key);
    items.push(item);
  };

  for (const event of [...timeline].filter(isOpenMainline).sort((a, b) => eventWeight(b) - eventWeight(a)).slice(0, 5)) {
    const title = formatEventFlowHeadlineSummary(event.title, 54);
    addItem({
      key: normalizedMainlineKey(title.raw),
      title,
      desc: formatEventFlowHeadline(event.desc || "等待后续数据、政策文本或市场价格继续验证。", 58),
      source: formatEventFlowSourceLabel(event.source ?? "事件流", 16).text,
      meta: event.date || formatDateTime(event.time),
      tone: pillTone(event.pricing ?? event.risk_level),
      label: translateEventFlowValue(event.pricing ?? "待落地"),
      impact: event.impact,
      eventId: event.id,
    });
  }

  for (const [index, raw] of watchItems.entries()) {
    const parsed = parseResearchLine(raw);
    const title = formatEventFlowHeadlineSummary(parsed.body, 54);
    addItem({
      key: normalizedMainlineKey(title.raw),
      title,
      desc: formatEventFlowHeadline(parsed.body, 58),
      source: "跟踪清单",
      meta: parsed.tags[0] ?? "待验证",
      tone: "info",
      label: index === 0 ? "待落地" : "跟踪中",
    });
  }

  for (const raw of riskItems) {
    const parsed = parseResearchLine(raw);
    const title = formatEventFlowHeadlineSummary(parsed.body, 54);
    addItem({
      key: normalizedMainlineKey(title.raw),
      title,
      desc: formatEventFlowHeadline(parsed.body, 58),
      source: "风险清单",
      meta: parsed.tags[0] ?? "条件未落地",
      tone: "warn",
      label: "待定价",
    });
  }

  return items.slice(0, 5);
}

function traceTitle(ref: SourceRef): string {
  const raw = ref.label?.trim() || ref.provider?.trim() || ref.source_ref?.trim() || ref.endpoint?.trim() || "未命名来源";
  return formatEventFlowSourceLabel(raw).text;
}

function traceMeta(ref: SourceRef): string[] {
  return [
    ref.provider?.trim(),
    ref.trade_date?.trim() || ref.dataDate?.trim() || ref.asOf?.trim(),
    ref.snapshot_id?.trim(),
  ].filter((value): value is string => Boolean(value));
}

function ResearchList({
  title,
  items,
  emptyText,
  warn = false,
}: {
  title: string;
  items: string[];
  emptyText: string;
  warn?: boolean;
}) {
  return (
    <section className="space-y-2">
      <div className={`text-[10px] font-semibold tracking-[0.04em] ${warn ? "text-[var(--warn)]" : "text-[var(--fg-5)]"}`}>
        {title}
      </div>
      {items.length > 0 ? (
        <div className={warn ? "space-y-2" : "space-y-0.5"}>
          {items.map((item, index) => {
            const parsed = parseResearchLine(item);
            return (
              <div
                key={`${title}-${index}`}
                className={
                  warn
                    ? "rounded-[var(--radius-sm)] border border-[var(--border)] bg-[rgba(17,33,54,0.58)] px-3 py-2.5"
                    : "border-b border-[var(--border-faint)] px-0 py-2.5 last:border-b-0"
                }
              >
                {(() => {
                  const body = formatEventFlowHeadline(parsed.body, warn ? 88 : 96);
                  return (
                    <div className="text-[11px] leading-5 text-[var(--fg-2)]" title={body.raw}>
                      {body.foreign ? "原文条目（见来源）" : body.text}
                    </div>
                  );
                })()}
                {parsed.tags.length > 0 ? (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {parsed.tags.map((tag) => (
                      <span
                        key={`${title}-${index}-${tag}`}
                        className={`rounded-[var(--radius-pill)] border px-2 py-0.5 text-[9px] font-semibold ${
                          warn
                            ? "border-[var(--warn-border)] bg-[var(--warn-soft)] text-[var(--warn)]"
                            : "border-[var(--border-faint)] bg-[rgba(15,29,48,0.72)] text-[var(--fg-5)]"
                        }`}
                      >
                        {tag}
                      </span>
                    ))}
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      ) : (
        <div className="px-0 py-2 text-[10px] leading-5 text-[var(--fg-4)]">
          {emptyText}
        </div>
      )}
    </section>
  );
}

export function EventFlowOverviewPanel({
  data,
  summary: summaryProp,
  timeline: timelineProp,
  table: tableProp,
  sourceRefs: sourceRefsProp,
  onOpenDetail,
  className = "",
}: EventFlowOverviewPanelProps) {
  const summary = summaryProp ?? data.brief_summary ?? null;
  const timeline = timelineProp ?? data.timeline;
  const table = tableProp ?? data.table;
  const sourceRefs = sourceRefsProp ?? data.source_refs ?? [];

  const overviewStatus = resolveOverviewStatus(data);
  const radarStatus = resolveRadarStatus(data);
  const topEvents = collectTopEvents(data, timeline);
  const radarSummary = summarizeRadar(data);
  const assets = aggregateAssets(table, timeline).slice(0, 5);
  const traceRefs = collectSourceRefs(data, sourceRefs, timeline, table);
  const researchDisplayKeys = new Set<string>();
  const highlightItems = collectResearchItems(summary?.newsHighlights ?? [], 3, researchDisplayKeys);
  const watchItems = collectResearchItems(summary?.watchlist ?? [], 3, researchDisplayKeys);
  const riskItems = collectResearchItems(summary?.riskPoints ?? [], 3, researchDisplayKeys);
  const mainHeadline = formatEventFlowHeadlineSummary(summary?.headline ?? topEvents[0]?.title ?? "事件主线待补充", 72);
  const mainSummary = formatEventFlowHeadline(summary?.summary ?? topEvents[0]?.desc ?? overviewStatus.description, 92);
  const mainSource = formatEventFlowSourceLabel(data.source, 18);
  const ongoingMainlines = collectOngoingMainlines(timeline, watchItems, riskItems);
  const topEventTitles = topEvents.map((event) => ({
    ...event,
    displayTitle: formatEventFlowHeadlineSummary(event.title, 58),
    displaySource: formatEventFlowSourceLabel(event.source ?? "事件流", 18),
    displayDesc: formatEventFlowHeadline(event.desc || "暂无摘要。", 72),
  }));

  if (!data.has_data && !summary && topEvents.length === 0) {
    return (
      <FACard
        title="总览"
        eyebrow="事件流"
        accent="brand"
        action={<FAStatusPill tone={overviewStatus.tone}>{overviewStatus.label}</FAStatusPill>}
        className={className}
      >
        <FAEmptyState
          title="暂无可展示总览"
          description={`${overviewStatus.description} 数据源：${data.source} · 更新时间：${formatDateTime(data.updated_at)}`}
          className="py-6"
        />
      </FACard>
    );
  }

  return (
    <div className={`grid gap-3 xl:grid-cols-12 ${className}`}>
      <FACard
        title="当前重点主线"
        eyebrow="总览"
        accent="brand"
        action={<FAStatusPill tone={overviewStatus.tone}>{overviewStatus.label}</FAStatusPill>}
        className="xl:col-span-12"
        bodyClassName="space-y-3"
      >
        <div className="grid items-start gap-3 xl:grid-cols-[minmax(0,1.05fr)_minmax(320px,0.95fr)]">
          <div className="self-start space-y-2 rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[rgba(17,33,54,0.28)] px-3 py-3">
            <div className="flex items-start justify-between gap-2">
              <div className="space-y-1 min-w-0">
                <div className="text-[10px] font-semibold tracking-[0.04em] text-[var(--fg-5)]">主导主线</div>
                <div className="min-w-0 text-[12px] font-semibold leading-5 text-[var(--fg-1)]" title={mainHeadline.raw}>
                  {mainHeadline.foreign ? "原文事件主线" : mainHeadline.lead}
                </div>
                {mainHeadline.subline ? (
                  <div className="line-clamp-1 text-[10px] leading-4 text-[var(--fg-4)]" title={mainHeadline.raw}>
                    {mainHeadline.subline}
                  </div>
                ) : null}
              </div>
              {mainHeadline.foreign ? (
                <span className="inline-flex h-5 shrink-0 items-center rounded-[var(--radius-pill)] border border-[var(--border-faint)] px-1.5 text-[8px] font-medium text-[var(--fg-5)]">
                  原文
                </span>
              ) : null}
            </div>
            <div className="line-clamp-2 text-[11px] leading-5 text-[var(--fg-3)]" title={mainSummary.raw}>
              {mainSummary.foreign ? "当前主线摘要来自英文原文，详情请进入事件或快讯查看。" : mainSummary.text}
            </div>
            <div className="flex flex-wrap gap-2">
              {summary?.status ? <FAStatusPill tone="info">{translateEventFlowValue(summary.status)}</FAStatusPill> : null}
              {summary?.verificationStatus ? <FAStatusPill tone={pillTone(summary.verificationStatus)}>{translateEventFlowValue(summary.verificationStatus)}</FAStatusPill> : null}
              {summary?.pricingStatus ? <FAStatusPill tone={pillTone(summary.pricingStatus)}>{translateEventFlowValue(summary.pricingStatus)}</FAStatusPill> : null}
              {summary?.riskLevel ? <FAStatusPill tone={pillTone(summary.riskLevel)}>{translateEventFlowValue(summary.riskLevel)}</FAStatusPill> : null}
            </div>
          </div>
          <div className="space-y-2 rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[rgba(17,33,54,0.22)] px-3 py-3">
            <div className="flex items-center justify-between gap-3">
              <div className="text-[10px] font-semibold tracking-[0.04em] text-[var(--fg-5)]">持续跟踪主线</div>
              <FAStatusPill tone={ongoingMainlines.length > 0 ? "warn" : "dim"} dot={false}>{ongoingMainlines.length} 条</FAStatusPill>
            </div>
            {ongoingMainlines.length > 0 ? (
              <div className="space-y-2">
                {ongoingMainlines.map((item) => (
                  <button
                    type="button"
                    key={`mainline-${item.key}`}
                    onClick={item.eventId && onOpenDetail ? () => onOpenDetail(item.eventId as string) : undefined}
                    disabled={!item.eventId || !onOpenDetail}
                    className="grid w-full grid-cols-[minmax(0,1fr)_auto] items-start gap-2 rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[rgba(12,23,40,0.6)] px-2.5 py-2 text-left transition-colors hover:bg-[rgba(26,45,70,0.52)] disabled:cursor-default"
                  >
                    <div className="min-w-0 space-y-1">
                      <div className="text-[11px] font-semibold leading-5 text-[var(--fg-2)]" title={item.title.raw}>
                        {item.title.foreign ? "原文事件主线" : item.title.lead}
                      </div>
                      <div className="line-clamp-1 text-[10px] leading-4 text-[var(--fg-4)]" title={item.desc.raw}>
                        {item.desc.foreign ? "详情请进入事件查看原文与来源。" : item.desc.text}
                      </div>
                      <div className="flex flex-wrap items-center gap-1.5 text-[9px] text-[var(--fg-5)]">
                        <span>{item.source}</span>
                        <span>·</span>
                        <span>{item.meta}</span>
                      </div>
                    </div>
                    <div className="flex flex-col items-end gap-1">
                      <FAStatusPill tone={item.tone}>{item.label}</FAStatusPill>
                      {item.impact ? (
                        <span className={`text-[10px] font-semibold ${impactTone(item.impact)}`}>{translateEventFlowValue(item.impact)}</span>
                      ) : null}
                    </div>
                  </button>
                ))}
              </div>
            ) : (
              <div className="text-[10px] leading-5 text-[var(--fg-4)]">当前高价值主线已基本完成定价，首屏暂无额外待跟踪主线。</div>
            )}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-[10px] leading-5 text-[var(--fg-4)]">
          <span className="inline-flex items-center gap-1.5">
            <span className="text-[var(--fg-5)]">来源</span>
            <span>{mainSource.text}</span>
          </span>
          <span className="text-[var(--fg-5)]">·</span>
          <span className="inline-flex items-center gap-1.5">
            <span className="text-[var(--fg-5)]">更新时间</span>
            <span>{formatDateTime(data.updated_at)}</span>
          </span>
          <FASourceTraceBadge source={mainSource.text} status="data_source" tone={SECTION_TONE[data.status] ?? "info"} className="ml-1" />
        </div>
        {overviewStatus.tone !== "up" ? (
          <div className="rounded-[var(--radius-sm)] border border-[var(--warn-border)] bg-[var(--warn-soft)] px-3 py-2 text-[10px] leading-5 text-[var(--warn)]">
            {overviewStatus.description}
          </div>
        ) : null}
      </FACard>

      <FACard
        title={
          <div className="flex items-center gap-2">
            <Layers3 size={12} className="text-[var(--brand-hover)]" />
            <span>近期重点事件</span>
          </div>
        }
        eyebrow="重点"
        accent="brand"
        className="xl:col-span-7"
      >
        {topEvents.length === 0 ? (
          <FAEmptyState title="暂无重点事件" description="当前没有可汇总的事件主线候选。" className="py-5" />
        ) : (
          <div className="overflow-hidden rounded-[var(--radius-sm)] border border-[var(--border)] bg-[rgba(17,33,54,0.38)]">
            {topEventTitles.map((event, index) => (
              <button
                type="button"
                key={event.id}
                onClick={onOpenDetail ? () => onOpenDetail(event.id) : undefined}
                className="grid w-full grid-cols-[92px_minmax(0,1fr)] gap-0 border-b border-[var(--border-faint)] text-left transition-colors last:border-b-0 hover:bg-[rgba(26,45,70,0.52)] disabled:cursor-default"
                disabled={!onOpenDetail}
              >
                <div className="flex flex-col gap-1 border-r border-[var(--border-faint)] px-3 py-3">
                  <span className="fa-num text-[10px] font-semibold text-[var(--fg-5)]">{String(index + 1).padStart(2, "0")}</span>
                  <span className="fa-num text-[10px] text-[var(--fg-4)]">{event.date || formatDateTime(event.time)}</span>
                </div>
                <div className="min-w-0 space-y-1 px-3 py-3">
                  <div className="flex flex-wrap items-start gap-1.5">
                    <div className="min-w-0 flex-1 space-y-0.5">
                      <span className="block line-clamp-2 text-[10.5px] font-semibold leading-5 text-[var(--fg-2)]" title={event.displayTitle.raw}>
                        {event.displayTitle.foreign ? "原文事件" : event.displayTitle.lead}
                      </span>
                      {event.displayTitle.subline ? (
                        <span className="block line-clamp-1 text-[10px] leading-4 text-[var(--fg-4)]" title={event.displayTitle.raw}>
                          {event.displayTitle.foreign ? "详情请查看来源链接" : event.displayTitle.subline}
                        </span>
                      ) : null}
                    </div>
                    {event.displayTitle.foreign ? (
                      <span className="inline-flex h-5 items-center rounded-[var(--radius-pill)] border border-[var(--border-faint)] px-1.5 text-[8px] font-medium text-[var(--fg-5)]">
                        原文
                      </span>
                    ) : null}
                    <FAStatusPill tone={pillTone(event.risk_level)}>{translateEventFlowValue(event.risk_level ?? event.importance)}</FAStatusPill>
                  </div>
                  <div className="line-clamp-2 text-[10px] leading-5 text-[var(--fg-4)]" title={event.displayDesc.raw}>
                    {event.displayDesc.foreign ? "当前仅返回英文原文，详情请查看来源或进入事件详情。" : event.displayDesc.text}
                  </div>
                  <div className="flex flex-wrap items-center gap-2 text-[10px] text-[var(--fg-5)]">
                    <span title={event.displaySource.raw}>来源：{event.displaySource.text}</span>
                    <span>·</span>
                    <span>{event.date || formatDateTime(event.time)}</span>
                    {event.assets ? <span>· {event.assets}</span> : null}
                  </div>
                </div>
              </button>
            ))}
          </div>
        )}
      </FACard>

      <FACard
        title={
          <div className="flex items-center gap-2">
            <Radar size={12} className="text-[var(--brand-hover)]" />
            <span>市场影响摘要</span>
          </div>
        }
        eyebrow="影响"
        accent="warn"
        action={<FAStatusPill tone={radarStatus.tone}>{radarStatus.label}</FAStatusPill>}
        className="xl:col-span-5"
        bodyClassName="space-y-3"
      >
        {radarSummary ? (
          <>
            <div className="grid gap-3 lg:grid-cols-[96px_minmax(0,1fr)]">
              <div className="rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[rgba(17,33,54,0.34)] px-3 py-3">
                <div className="text-[9px] font-semibold tracking-[0.08em] text-[var(--fg-5)]">均值</div>
                <div className="mt-1 fa-num text-[19px] font-semibold text-[var(--fg-1)]">{radarSummary.average}</div>
              </div>
              <div className="space-y-2">
                <div className="flex items-center justify-between gap-3 text-[10px] text-[var(--fg-5)]">
                  <span>主导风险轴</span>
                  <span className="text-[var(--fg-4)]">{radarSummary.secondary?.label ?? "暂无次高轴"}</span>
                </div>
                <div className="text-[12px] font-semibold text-[var(--fg-2)]">{radarSummary.primary.label}</div>
                <div className="space-y-1.5">
                  {[radarSummary.primary, radarSummary.secondary].filter(Boolean).map((axis) => (
                    <div key={axis!.label} className="space-y-1">
                      <div className="flex items-center justify-between gap-3 text-[10px] text-[var(--fg-4)]">
                        <span>{axis!.label}</span>
                        <span className="fa-num text-[var(--fg-2)]">{axis!.value}/100</span>
                      </div>
                      <div className="h-1.5 overflow-hidden rounded-full bg-[rgba(17,33,54,0.56)]">
                        <div className="h-full rounded-full bg-[var(--warn)]" style={{ width: `${axis!.value}%` }} />
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
            <div className="space-y-2 border-t border-[var(--border-faint)] pt-3">
              <div className="flex items-center justify-between gap-3">
                <div className="text-[10px] font-semibold tracking-[0.04em] text-[var(--fg-5)]">影响资产</div>
                <FAStatusPill tone={assets.length > 0 ? "info" : "dim"} dot={false}>
                  {assets.length} 项
                </FAStatusPill>
              </div>
              {assets.length > 0 ? (
                <div className="overflow-hidden rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[rgba(17,33,54,0.34)]">
                  {assets.map((asset) => (
                    <div
                      key={asset.name}
                      className="flex items-center gap-2 border-b border-[var(--border-faint)] px-3 py-2.5 last:border-b-0"
                    >
                      <span className="min-w-0 flex-1 truncate text-[11px] font-semibold text-[var(--fg-2)]">{asset.name}</span>
                      <span className={`text-[10px] font-semibold ${impactTone(asset.dominant)}`}>{asset.dominant}</span>
                      <span className="fa-num text-[10px] text-[var(--fg-5)]">{asset.count}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-[10px] leading-5 text-[var(--fg-4)]">当前事件流没有稳定的资产映射。</div>
              )}
            </div>
            <div className="text-[10px] leading-5 text-[var(--fg-4)]">{radarStatus.description}</div>
          </>
        ) : (
          <FAEmptyState title="暂无风险雷达摘要" description={radarStatus.description} className="py-5" />
        )}
      </FACard>

      <FACard
        title={
          <div className="flex items-center gap-2">
            <FileStack size={12} className="text-[var(--brand-hover)]" />
            <span>研究输入与溯源</span>
          </div>
        }
        eyebrow="输入"
        accent="info"
        className="xl:col-span-12"
        bodyClassName="space-y-3"
      >
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,0.9fr)_minmax(280px,0.86fr)]">
          <div className="space-y-4">
            <ResearchList title="新闻要点" items={highlightItems} emptyText="当前未返回新闻要点。" />
            <div className="border-t border-[var(--border-faint)] pt-3">
              <ResearchList title="观察清单" items={watchItems} emptyText="当前未返回观察清单。" />
            </div>
          </div>

          <div className="space-y-3 rounded-[var(--radius-sm)] border border-[var(--warn-border)] bg-[rgba(57,40,10,0.18)] px-3 py-3">
            <ResearchList title="风险提示" items={riskItems} emptyText="当前未返回风险提示。" warn />
            <div className="border-t border-[var(--warn-border)] pt-3 text-[10px] leading-5 text-[var(--warn)]">
              高风险提示保留在首屏，其余原始引用已下沉到快讯、输入和详情页。
            </div>
          </div>

          <div className="space-y-3 rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[rgba(17,33,54,0.34)] px-3 py-3">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2 text-[10px] text-[var(--fg-5)]">
                <GitBranch size={11} />
                <span>来源覆盖</span>
              </div>
              <FAStatusPill tone={traceRefs.length > 0 ? "info" : "dim"} dot={false}>
                {traceRefs.length} 条
              </FAStatusPill>
            </div>

            {traceRefs.length > 0 ? (
              <div className="space-y-0.5">
                {traceRefs.slice(0, 4).map((ref) => (
                  <div key={`${ref.source_ref}-${ref.snapshot_id ?? ref.artifact_path ?? ""}`} className="border-b border-[var(--border-faint)] py-2.5 last:border-b-0">
                    <div className="flex items-center gap-2">
                      <span className="min-w-0 flex-1 truncate text-[11px] font-semibold text-[var(--fg-2)]">{traceTitle(ref)}</span>
                      <FAStatusPill status={ref.status ?? "available"} domain="source" dot={false}>
                        {translateEventFlowValue(ref.status ?? "available")}
                      </FAStatusPill>
                    </div>
                    {traceMeta(ref).length > 0 ? (
                      <div className="mt-1 flex flex-wrap gap-2 text-[10px] text-[var(--fg-5)]">
                        {traceMeta(ref).map((item) => (
                          <span key={`${traceTitle(ref)}-${item}`}>{item}</span>
                        ))}
                      </div>
                    ) : null}
                  </div>
                ))}
              </div>
            ) : (
              <div className="flex items-start gap-2 rounded-[var(--radius-sm)] border border-[var(--warn-border)] bg-[var(--warn-soft)] px-3 py-2 text-[10px] leading-5 text-[var(--warn)]">
                <AlertTriangle size={11} className="mt-[2px] shrink-0" />
                <span>当前总览没有返回可追溯来源引用，不能把该摘要视为完整输入面。</span>
              </div>
            )}

            <div className="text-[10px] leading-5 text-[var(--fg-4)]">
              总览只保留来源覆盖摘要，详细引用下沉到快讯、报告输入和事件详情。
            </div>
          </div>
        </div>
      </FACard>
    </div>
  );
}

export default EventFlowOverviewPanel;
