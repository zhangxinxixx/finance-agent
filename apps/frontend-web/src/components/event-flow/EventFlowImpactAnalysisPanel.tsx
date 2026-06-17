import { Activity, AlertTriangle, ShieldAlert, Target, Waves } from "lucide-react";
import { FACard } from "@/components/shared/FACard";
import { FAEmptyState } from "@/components/shared/FAEmptyState";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import type {
  EventFlowChainStep,
  EventFlowRadarAxis,
  EventFlowSentimentItem,
  EventFlowTableRow,
  EventFlowTimelineItem,
} from "@/types/event-flow";
import { EventChainAnalysis } from "./EventChainAnalysis";
import { ImpactAssets } from "./ImpactAssets";
import { RiskRadar } from "./RiskRadar";
import { SentimentMetrics } from "./SentimentMetrics";

function asRecord(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  return value as Record<string, unknown>;
}

function stringifyValue(value: unknown): string {
  if (typeof value === "string" && value.trim()) return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return "";
}

function toRows(timeline: EventFlowTimelineItem[]): EventFlowTableRow[] {
  return timeline.map((event) => ({
    id: event.id,
    time: [event.date, event.time].filter(Boolean).join(" ").trim() || event.time,
    title: event.title,
    type: event.type,
    source: event.source ?? "事件流",
    assets: event.assets ?? event.affected_assets?.join(", ") ?? "—",
    impact: event.impact,
    pricing: event.pricing ?? "未定价",
    period: event.period ?? "主线",
    stars: event.importance === "高" ? 5 : event.importance === "中" ? 3 : 1,
    verification_status: event.verification_status,
    risk_level: event.risk_level,
    event_kind: event.event_kind,
    source_refs: event.source_refs,
  }));
}

function marketValidationRows(events: EventFlowTimelineItem[]) {
  return events.flatMap((event) => {
    const validation = asRecord(event.market_validation);
    const snapshot = asRecord(event.market_snapshot ?? validation.market_snapshot);
    const confirmation = asRecord(validation.confirmation_summary);
    const primaryWindow = stringifyValue(snapshot.primary_window) || "unavailable";
    const pricing = event.pricing ?? (stringifyValue(validation.pricing_status) || "未标注");
    const observedAssets = Array.isArray(snapshot.observed_assets) ? snapshot.observed_assets.map(String) : [];
    const missingAssets = Array.isArray(snapshot.missing_assets) ? snapshot.missing_assets.map(String) : [];
    const hasValidation = Object.keys(validation).length > 0 || Object.keys(snapshot).length > 0;

    return [{
      id: event.id,
      title: event.title,
      pricing,
      primaryWindow,
      confirmation: confirmation,
      observedAssets,
      missingAssets,
      hasValidation,
      verificationStatus: event.verification_status ?? "unavailable",
    }];
  });
}

function MarketValidationSummary({ events }: { events: EventFlowTimelineItem[] }) {
  const rows = marketValidationRows(events);
  const availableRows = rows.filter((row) => row.hasValidation);

  return (
    <FACard
      title={
        <div className="flex items-center gap-2">
          <Waves size={12} className="text-[var(--warn)]" />
          <span>行情验证摘要</span>
        </div>
      }
      eyebrow="Market Validation"
      accent="warn"
      bodyClassName="space-y-3"
    >
      {rows.length === 0 ? (
        <FAEmptyState title="暂无验证对象" description="当前没有事件可用于行情验证摘要。" className="py-6" />
      ) : availableRows.length === 0 ? (
        <>
          <div className="rounded-[var(--radius-md)] border border-[rgba(245,158,11,0.18)] bg-[rgba(245,158,11,0.06)] p-3 text-[11px] leading-5 text-[var(--fg-2)]">
            当前没有真实 `market_validation` 或 `market_snapshot` 数据。这里明确保留 unavailable 占位，不把缺失字段包装成市场结论。
          </div>
          <div className="grid gap-2 sm:grid-cols-3">
            {rows.slice(0, 3).map((row) => (
              <div key={row.id} className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
                <div className="text-[11px] font-semibold text-[var(--fg-2)]">{row.title}</div>
                <div className="mt-2 text-[10px] text-[var(--fg-4)]">pricing: {row.pricing}</div>
                <div className="mt-1 text-[10px] text-[var(--fg-4)]">verification: {row.verificationStatus}</div>
                <div className="mt-1 text-[10px] text-[var(--warn)]">market validation unavailable</div>
              </div>
            ))}
          </div>
        </>
      ) : (
        <div className="space-y-2">
          {availableRows.map((row) => {
            const confirmed = typeof row.confirmation.confirmed_count === "number" ? row.confirmation.confirmed_count : 0;
            const contradicted = typeof row.confirmation.contradicted_count === "number" ? row.confirmation.contradicted_count : 0;
            const observed = typeof row.confirmation.observed_count === "number" ? row.confirmation.observed_count : 0;

            return (
              <article
                key={row.id}
                className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="min-w-0">
                    <div className="text-[11px] font-semibold text-[var(--fg-2)]">{row.title}</div>
                    <div className="mt-1 text-[10px] text-[var(--fg-4)]">主窗口：{row.primaryWindow}</div>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    <FAStatusPill tone="info" dot={false}>{row.pricing}</FAStatusPill>
                    <FAStatusPill tone="neutral" dot={false}>{row.verificationStatus}</FAStatusPill>
                  </div>
                </div>
                <div className="mt-3 grid gap-2 sm:grid-cols-3">
                  {[
                    { label: "确认", value: confirmed },
                    { label: "背离", value: contradicted },
                    { label: "观测", value: observed },
                  ].map((item) => (
                    <div key={`${row.id}-${item.label}`} className="rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-panel)] px-2.5 py-2">
                      <div className="text-[9px] uppercase tracking-[0.08em] text-[var(--fg-5)]">{item.label}</div>
                      <div className="mt-1 font-mono text-[12px] font-semibold text-[var(--fg-1)]">{item.value}</div>
                    </div>
                  ))}
                </div>
                <div className="mt-3 grid gap-2 text-[10px] text-[var(--fg-4)] sm:grid-cols-2">
                  <div>已观测资产：{row.observedAssets.length > 0 ? row.observedAssets.join(" / ") : "unavailable"}</div>
                  <div>缺失资产：{row.missingAssets.length > 0 ? row.missingAssets.join(" / ") : "unavailable"}</div>
                </div>
              </article>
            );
          })}
        </div>
      )}
    </FACard>
  );
}

function SummaryTiles({
  timeline,
  sentiment,
  radar,
}: {
  timeline: EventFlowTimelineItem[];
  sentiment: EventFlowSentimentItem[];
  radar: EventFlowRadarAxis[];
}) {
  const highImportanceCount = timeline.filter((event) => event.importance === "高").length;
  const watchCount = timeline.filter((event) => (event.verification_status ?? "").includes("verification")).length;
  const radarAverage = radar.length > 0
    ? Math.round(radar.reduce((sum, item) => sum + item.value, 0) / radar.length)
    : null;
  const sentimentSummary = sentiment[0]?.label ?? "unavailable";

  return (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
      {[
        { icon: AlertTriangle, label: "重点事件", value: String(highImportanceCount), hint: "高重要性 timeline 事件" },
        { icon: Activity, label: "情绪主指标", value: sentimentSummary, hint: "来自 sentiment 第一个指标" },
        { icon: ShieldAlert, label: "风险均值", value: radarAverage === null ? "unavailable" : `${radarAverage}/100`, hint: "risk radar 平均值" },
        { icon: Target, label: "待验证", value: String(watchCount), hint: "verification 含 needs_verification 的事件数" },
      ].map((item) => (
        <div key={item.label} className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
          <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">
            <item.icon size={11} className="text-[var(--brand-hover)]" />
            <span>{item.label}</span>
          </div>
          <div className="mt-2 text-[13px] font-semibold text-[var(--fg-1)]">{item.value}</div>
          <div className="mt-1 text-[10px] leading-4 text-[var(--fg-4)]">{item.hint}</div>
        </div>
      ))}
    </div>
  );
}

export function EventFlowImpactAnalysisPanel({
  chain,
  sentiment,
  radar,
  timeline,
  table,
}: {
  chain: EventFlowChainStep[];
  sentiment: EventFlowSentimentItem[];
  radar: EventFlowRadarAxis[];
  timeline: EventFlowTimelineItem[];
  table?: EventFlowTableRow[];
}) {
  const assetRows = table && table.length > 0 ? table : toRows(timeline);
  const activeEvent = timeline[0] ?? null;

  return (
    <div className="space-y-4">
      <SummaryTiles timeline={timeline} sentiment={sentiment} radar={radar} />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.2fr)_minmax(0,0.8fr)]">
        <div className="space-y-4">
          <EventChainAnalysis chain={chain} activeEvent={activeEvent} />
          <SentimentMetrics sentiment={sentiment} />
          <MarketValidationSummary events={timeline} />
        </div>
        <div className="space-y-4">
          <RiskRadar radar={radar} />
          {assetRows.length === 0 ? (
            <FACard title="影响资产" eyebrow="Impact Assets" accent="brand">
              <FAEmptyState title="暂无影响资产" description="timeline / table 均未返回可聚合资产。" className="py-6" />
            </FACard>
          ) : (
            <ImpactAssets table={assetRows} />
          )}
        </div>
      </div>
    </div>
  );
}
