import { formatEventFlowHeadlineSummary, translateEventFlowValue } from "./eventFlowFormat";
import { readableWarning } from "@/lib/researchReading";
import { FACard } from "@/components/shared/FACard";
import { FAEmptyState } from "@/components/shared/FAEmptyState";
import { FASourceTraceBadge } from "@/components/shared/FASourceTraceBadge";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { formatDateTime } from "@/lib/date";
import type { EventFlowBriefSummary } from "@/types/event-flow";
import { CountMetric } from "./EventFlowSectionHelpers";
import { formatEventFlowArtifactLabel } from "./eventFlowFormat";

export function EventFlowEmptyState({
  source,
  updatedAt,
}: {
  source: string;
  updatedAt: string;
}) {
  return (
    <>
      <FACard title="事件流" eyebrow="事件链路" accent="brand" bodyClassName="space-y-2">
        <div className="text-[12px] font-semibold text-[var(--fg-2)]">当前未返回可展示的事件流数据</div>
        <div className="text-[11px] leading-5 text-[var(--fg-4)]">当前暂无有效事件，等待已归档的日报或金十事件材料。</div>
        <div className="flex flex-wrap gap-2">
          <FASourceTraceBadge source={formatDateTime(updatedAt)} status="updated_at" tone="info" />
          <FASourceTraceBadge source={source} status="data_source" tone="dim" />
        </div>
      </FACard>
      <FAEmptyState title="暂无事件数据" description="当前返回结果为空，页面保留骨架。" />
    </>
  );
}

export function BriefSummaryStrip({
  summary,
  source,
  updatedAt,
  sourceRefs,
}: {
  summary: EventFlowBriefSummary;
  source: string;
  updatedAt: string;
  sourceRefs: Array<{ source_ref?: string | null; label?: string | null; status?: string | null }>;
}) {
  return (
    <div className="grid gap-3 xl:grid-cols-[minmax(0,1.7fr)_minmax(260px,0.9fr)]">
      <FACard
        title="新闻主线"
        eyebrow="每日市场简报"
        accent="brand"
        action={<FAStatusPill tone="info">{source}</FAStatusPill>}
        bodyClassName="space-y-3"
      >
        <div className="space-y-1.5">
          <div className="text-[13px] font-semibold text-[var(--fg-1)]">{formatEventFlowHeadlineSummary(summary.headline).lead}</div>
          <div className="text-[11px] leading-5 text-[var(--fg-3)]">{readableWarning(summary.summary)}</div>
        </div>
        <div className="flex flex-wrap gap-2">
          {summary.verificationStatus ? <FAStatusPill tone="info">{summary.verificationStatus}</FAStatusPill> : null}
          {summary.pricingStatus ? <FAStatusPill tone="warn">{summary.pricingStatus}</FAStatusPill> : null}
          {summary.riskLevel ? <FAStatusPill tone={summary.riskLevel === "high" ? "down" : summary.riskLevel === "medium" ? "warn" : "up"}>{summary.riskLevel}</FAStatusPill> : null}
        </div>
        <div className="flex flex-wrap gap-2">
          <FASourceTraceBadge source={formatDateTime(updatedAt)} status="updated_at" tone="info" />
          {summary.artifactPath ? <FASourceTraceBadge source={formatEventFlowArtifactLabel(summary.artifactPath)} status="artifact" tone="dim" /> : null}
          {sourceRefs.slice(0, 3).map((ref) => (
            <FASourceTraceBadge
              key={`${ref.source_ref ?? ref.label ?? "source-ref"}`}
              source={ref.label ?? ref.source_ref ?? "source_ref"}
              status={ref.status ?? "ok"}
            />
          ))}
        </div>
      </FACard>

      <FACard title="事件分层" eyebrow="Counts" accent="info" bodyClassName="grid grid-cols-2 gap-2">
        <CountMetric label="已确认" value={summary.counts.confirmedEventCount} />
        <CountMetric label="候选事件" value={summary.counts.candidateEventCount} />
        <CountMetric label="待验证风险" value={summary.counts.unconfirmedRiskCount} />
        <CountMetric label="未来日历" value={summary.counts.calendarEventCount} />
      </FACard>
    </div>
  );
}

export function EventImpactBanner({
  summary,
}: {
  summary: {
    bias: string;
    confidence: number | null;
    llmModel?: string | null;
    llmElapsedSeconds?: number | null;
    summary: string;
  };
}) {
  return (
    <div
      className="rounded-[var(--radius-md)] px-3 py-2"
      style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
    >
      <div className="flex items-center gap-2">
        <span className="text-[10px] font-semibold text-[var(--fg-5)]">已有事件分析</span>
        <span className="text-[10px] font-mono text-[var(--fg-4)]">
          {translateEventFlowValue(summary.bias)} · 判断把握程度 {typeof summary.confidence === "number" && Number.isFinite(summary.confidence) ? `${(summary.confidence * 100).toFixed(0)}/100（非胜率）` : "未提供"}
        </span>
        {summary.llmModel && (
          <span className="text-[9px] text-[var(--fg-5)]">
            模型调用记录已登记{typeof summary.llmElapsedSeconds === "number" && Number.isFinite(summary.llmElapsedSeconds) ? ` · 分析用时 ${summary.llmElapsedSeconds.toFixed(1)} 秒` : ""}
          </span>
        )}
      </div>
      <div className="mt-1 text-[11px] text-[var(--fg-3)]">{readableWarning(summary.summary)}</div>
    </div>
  );
}
