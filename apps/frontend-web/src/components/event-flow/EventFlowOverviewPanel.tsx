import {
  AlertTriangle,
  FileStack,
  GitBranch,
  Layers3,
  Radar,
  ShieldAlert,
  Sparkles,
  Target,
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

interface EventFlowOverviewPanelProps {
  data: EventFlowViewModel;
  summary?: EventFlowBriefSummary | null;
  timeline?: EventFlowTimelineItem[];
  table?: EventFlowTableRow[];
  sourceRefs?: SourceRef[];
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
      source: "Jin10 Article Briefs",
      assets: brief.asset_tags.join(", "),
      pricing: "未定价",
      source_refs: [],
      affected_assets: brief.asset_tags,
    }));
}

function buildCounts(summary: EventFlowBriefSummary | null | undefined, timeline: EventFlowTimelineItem[]) {
  if (summary) return summary.counts;

  return timeline.reduce(
    (acc, event) => {
      if (event.event_kind === "confirmed_event") acc.confirmedEventCount += 1;
      else if (event.event_kind === "calendar") acc.calendarEventCount += 1;
      else if (event.event_kind === "unconfirmed_risk") acc.unconfirmedRiskCount += 1;
      else acc.candidateEventCount += 1;
      acc.sourceRefCount += event.source_refs?.length ?? 0;
      return acc;
    },
    {
      confirmedEventCount: 0,
      candidateEventCount: 0,
      unconfirmedRiskCount: 0,
      calendarEventCount: 0,
      sourceRefCount: 0,
    },
  );
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
    return { label: "Error", tone: "down", description: "当前视图存在接口或映射错误，仅保留只读摘要。" };
  }
  if (data.status === "unavailable" || source.includes("unavailable")) {
    return { label: "Unavailable", tone: "dim", description: "事件流接口当前不可用，面板不输出真实市场结论。" };
  }
  if (source.includes("mock")) {
    return { label: "Mock", tone: "warn", description: "当前视图含模拟数据，只用于占位展示。" };
  }
  if (data.status === "partial" || source.includes("fallback")) {
    return { label: "Partial", tone: "warn", description: "当前只返回部分输入，总览按已到达数据只读展示。" };
  }
  return { label: "Live", tone: "up", description: "当前总览基于已返回的事件流读模型。" };
}

function resolveRadarStatus(data: EventFlowViewModel): OverviewStatusMeta {
  if (data.event_impact_summary?.riskRadar && Object.keys(data.event_impact_summary.riskRadar).length > 0) {
    return { label: "Derived", tone: "info", description: "风险雷达为当前读模型的摘要视图。" };
  }
  if (data.radar.length > 0) {
    return { label: "Mock", tone: "warn", description: "风险雷达当前仍是占位/回退数据，不能视为真实风控结论。" };
  }
  return { label: "Unavailable", tone: "dim", description: "当前没有可展示的风险雷达数据。" };
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

export function EventFlowOverviewPanel({
  data,
  summary: summaryProp,
  timeline: timelineProp,
  table: tableProp,
  sourceRefs: sourceRefsProp,
  className = "",
}: EventFlowOverviewPanelProps) {
  const summary = summaryProp ?? data.brief_summary ?? null;
  const timeline = timelineProp ?? data.timeline;
  const table = tableProp ?? data.table;
  const sourceRefs = sourceRefsProp ?? data.source_refs ?? [];

  const overviewStatus = resolveOverviewStatus(data);
  const radarStatus = resolveRadarStatus(data);
  const counts = buildCounts(summary, timeline);
  const topEvents = collectTopEvents(data, timeline);
  const radarSummary = summarizeRadar(data);
  const assets = aggregateAssets(table, timeline);
  const traceRefs = collectSourceRefs(data, sourceRefs, timeline, table);
  const inputSummaryItems = uniqueStrings(
    [
      ...(summary?.newsHighlights ?? []),
      ...(summary?.watchlist ?? []),
      ...(summary?.riskPoints ?? []),
    ],
    6,
  );

  if (!data.has_data && !summary && topEvents.length === 0) {
    return (
      <FACard
        title="Overview"
        eyebrow="Event Flow"
        accent="brand"
        action={<FAStatusPill tone={overviewStatus.tone}>{overviewStatus.label}</FAStatusPill>}
        className={className}
      >
        <FAEmptyState
          title="暂无可展示总览"
          description={`${overviewStatus.description} Source: ${data.source} · Updated: ${formatDateTime(data.updated_at)}`}
          className="py-6"
        />
      </FACard>
    );
  }

  return (
    <div className={`grid gap-3 xl:grid-cols-12 ${className}`}>
      <FACard
        title="今日事件主线"
        eyebrow="Overview"
        accent="brand"
        action={<FAStatusPill tone={overviewStatus.tone}>{overviewStatus.label}</FAStatusPill>}
        className="xl:col-span-8"
        bodyClassName="space-y-3"
      >
        <div className="space-y-1.5">
          <div className="text-[13px] font-semibold text-[var(--fg-1)]">
            {summary?.headline ?? topEvents[0]?.title ?? "事件主线待补充"}
          </div>
          <div className="text-[11px] leading-5 text-[var(--fg-3)]">
            {summary?.summary ?? topEvents[0]?.desc ?? overviewStatus.description}
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          {summary?.status ? <FAStatusPill tone="info">{summary.status}</FAStatusPill> : null}
          {summary?.verificationStatus ? <FAStatusPill tone={pillTone(summary.verificationStatus)}>{summary.verificationStatus}</FAStatusPill> : null}
          {summary?.pricingStatus ? <FAStatusPill tone={pillTone(summary.pricingStatus)}>{summary.pricingStatus}</FAStatusPill> : null}
          {summary?.riskLevel ? <FAStatusPill tone={pillTone(summary.riskLevel)}>{summary.riskLevel}</FAStatusPill> : null}
        </div>
        <div className="flex flex-wrap gap-2">
          <FASourceTraceBadge source={data.source} status="data_source" tone={SECTION_TONE[data.status] ?? "info"} />
          <FASourceTraceBadge source={formatDateTime(data.updated_at)} status="updated_at" tone="info" />
          {summary?.artifactPath ? <FASourceTraceBadge source={summary.artifactPath} status="artifact" tone="dim" /> : null}
        </div>
        {overviewStatus.tone !== "up" ? (
          <div className="rounded-[var(--radius-sm)] border border-[var(--warn-border)] bg-[var(--warn-soft)] px-3 py-2 text-[10px] leading-5 text-[var(--warn)]">
            {overviewStatus.description}
          </div>
        ) : null}
      </FACard>

      <FACard title="事件分层" eyebrow="Counts" accent="info" className="xl:col-span-4" bodyClassName="grid grid-cols-2 gap-2">
        {[
          ["已确认", counts.confirmedEventCount],
          ["候选事件", counts.candidateEventCount],
          ["待验证风险", counts.unconfirmedRiskCount],
          ["未来日历", counts.calendarEventCount],
          ["来源引用", counts.sourceRefCount],
          ["主线候选", topEvents.length],
        ].map(([label, value]) => (
          <div
            key={label}
            className="rounded-[var(--radius-sm)] border border-[var(--border)] bg-[var(--bg-card-inner)] px-3 py-2"
          >
            <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">{label}</div>
            <div className="mt-1 fa-num text-[18px] font-semibold text-[var(--fg-1)]">{value}</div>
          </div>
        ))}
      </FACard>

      <FACard
        title={
          <div className="flex items-center gap-2">
            <Layers3 size={12} className="text-[var(--brand-hover)]" />
            <span>近期重点事件</span>
          </div>
        }
        eyebrow="Top 5"
        accent="brand"
        className="xl:col-span-6"
      >
        {topEvents.length === 0 ? (
          <FAEmptyState title="暂无重点事件" description="当前没有可汇总的事件主线候选。" className="py-5" />
        ) : (
          <div className="space-y-2">
            {topEvents.map((event, index) => (
              <div
                key={event.id}
                className="grid grid-cols-[20px_minmax(0,1fr)] gap-2 rounded-[var(--radius-sm)] border border-[var(--border)] bg-[var(--bg-card-inner)] px-3 py-2"
              >
                <div className="fa-num pt-0.5 text-[11px] font-semibold text-[var(--fg-5)]">{index + 1}</div>
                <div className="min-w-0 space-y-1">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="truncate text-[11px] font-semibold text-[var(--fg-2)]">{event.title}</span>
                    <FAStatusPill tone={pillTone(event.risk_level)}>{event.risk_level ?? event.importance}</FAStatusPill>
                  </div>
                  <div className="line-clamp-2 text-[10px] leading-5 text-[var(--fg-4)]">{event.desc || "暂无摘要。"}</div>
                  <div className="flex flex-wrap items-center gap-2 text-[10px] text-[var(--fg-5)]">
                    <span>{event.date || formatDateTime(event.time)}</span>
                    <span>{event.source ?? "事件流"}</span>
                    {event.assets ? <span>{event.assets}</span> : null}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </FACard>

      <FACard
        title={
          <div className="flex items-center gap-2">
            <Radar size={12} className="text-[var(--brand-hover)]" />
            <span>风险雷达摘要</span>
          </div>
        }
        eyebrow="Risk Radar"
        accent="warn"
        action={<FAStatusPill tone={radarStatus.tone}>{radarStatus.label}</FAStatusPill>}
        className="xl:col-span-6"
        bodyClassName="space-y-3"
      >
        {radarSummary ? (
          <>
            <div className="grid grid-cols-3 gap-2">
              <div className="rounded-[var(--radius-sm)] border border-[var(--border)] bg-[var(--bg-card-inner)] px-3 py-2">
                <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">平均风险</div>
                <div className="mt-1 fa-num text-[18px] font-semibold text-[var(--fg-1)]">{radarSummary.average}</div>
              </div>
              <div className="rounded-[var(--radius-sm)] border border-[var(--border)] bg-[var(--bg-card-inner)] px-3 py-2">
                <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">最高轴</div>
                <div className="mt-1 text-[11px] font-semibold text-[var(--fg-2)]">{radarSummary.primary.label}</div>
              </div>
              <div className="rounded-[var(--radius-sm)] border border-[var(--border)] bg-[var(--bg-card-inner)] px-3 py-2">
                <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">次高轴</div>
                <div className="mt-1 text-[11px] font-semibold text-[var(--fg-2)]">{radarSummary.secondary?.label ?? "—"}</div>
              </div>
            </div>
            <div className="space-y-1.5">
              {[radarSummary.primary, radarSummary.secondary].filter(Boolean).map((axis) => (
                <div key={axis!.label} className="space-y-1">
                  <div className="flex items-center justify-between gap-3 text-[10px] text-[var(--fg-4)]">
                    <span>{axis!.label}</span>
                    <span className="fa-num text-[var(--fg-2)]">{axis!.value}/100</span>
                  </div>
                  <div className="h-1.5 overflow-hidden rounded-full bg-[var(--bg-card-inner)]">
                    <div className="h-full rounded-full bg-[var(--warn)]" style={{ width: `${axis!.value}%` }} />
                  </div>
                </div>
              ))}
            </div>
            <div className="rounded-[var(--radius-sm)] border border-[var(--warn-border)] bg-[var(--warn-soft)] px-3 py-2 text-[10px] leading-5 text-[var(--warn)]">
              {radarStatus.description}
            </div>
          </>
        ) : (
          <FAEmptyState title="暂无风险雷达摘要" description={radarStatus.description} className="py-5" />
        )}
      </FACard>

      <FACard
        title={
          <div className="flex items-center gap-2">
            <Target size={12} className="text-[var(--brand-hover)]" />
            <span>影响资产摘要</span>
          </div>
        }
        eyebrow="Assets"
        accent="brand"
        className="xl:col-span-6"
      >
        {assets.length === 0 ? (
          <FAEmptyState title="暂无资产摘要" description="当前事件流没有稳定的资产映射。" className="py-5" />
        ) : (
          <div className="space-y-2">
            {assets.map((asset) => (
              <div
                key={asset.name}
                className="flex items-center gap-2 rounded-[var(--radius-sm)] border border-[var(--border)] bg-[var(--bg-card-inner)] px-3 py-2"
              >
                <span className="min-w-0 flex-1 truncate text-[11px] font-semibold text-[var(--fg-2)]">{asset.name}</span>
                <span className={`text-[10px] font-semibold ${impactTone(asset.dominant)}`}>{asset.dominant}</span>
                <span className="fa-num text-[10px] text-[var(--fg-5)]">{asset.count} 事件</span>
              </div>
            ))}
          </div>
        )}
      </FACard>

      <FACard
        title={
          <div className="flex items-center gap-2">
            <FileStack size={12} className="text-[var(--brand-hover)]" />
            <span>报告输入 / Source Refs</span>
          </div>
        }
        eyebrow="Inputs"
        accent="info"
        className="xl:col-span-6"
        bodyClassName="space-y-3"
      >
        {inputSummaryItems.length > 0 ? (
          <div className="space-y-2">
            {inputSummaryItems.map((item, index) => (
              <div key={`${index}-${item}`} className="flex items-start gap-2 text-[10px] leading-5 text-[var(--fg-3)]">
                <Sparkles size={11} className="mt-[3px] shrink-0 text-[var(--brand-hover)]" />
                <span>{item}</span>
              </div>
            ))}
          </div>
        ) : (
          <div className="rounded-[var(--radius-sm)] border border-[var(--border)] bg-[var(--bg-card-inner)] px-3 py-2 text-[10px] text-[var(--fg-4)]">
            暂无可用的报告输入摘要，改为展示来源引用摘要。
          </div>
        )}

        <div className="flex items-center justify-between gap-3 border-t border-[var(--border-faint)] pt-3">
          <div className="flex items-center gap-2 text-[10px] text-[var(--fg-5)]">
            <GitBranch size={11} />
            <span>source refs</span>
          </div>
          <FAStatusPill tone={traceRefs.length > 0 ? "info" : "dim"} dot={false}>
            {traceRefs.length} refs
          </FAStatusPill>
        </div>

        {traceRefs.length > 0 ? (
          <div className="flex flex-wrap gap-2">
            {traceRefs.slice(0, 4).map((ref) => (
              <FASourceTraceBadge
                key={[ref.source_ref, ref.snapshot_id, ref.artifact_path, ref.run_id].filter(Boolean).join("|")}
                source={ref.label ?? ref.source_ref}
                status={ref.status ?? "trace"}
                snapshotId={ref.snapshot_id ?? undefined}
              />
            ))}
          </div>
        ) : (
          <div className="flex items-start gap-2 rounded-[var(--radius-sm)] border border-[var(--warn-border)] bg-[var(--warn-soft)] px-3 py-2 text-[10px] leading-5 text-[var(--warn)]">
            <AlertTriangle size={11} className="mt-[2px] shrink-0" />
            <span>当前 overview 没有返回可追溯 source refs，不能把该摘要视为完整输入面。</span>
          </div>
        )}
      </FACard>
    </div>
  );
}

export default EventFlowOverviewPanel;
