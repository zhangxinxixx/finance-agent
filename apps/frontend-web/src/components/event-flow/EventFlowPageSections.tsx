import { Calendar, FileText, SearchCheck, ShieldAlert } from "lucide-react";
import { FACard } from "@/components/shared/FACard";
import { FAEmptyState } from "@/components/shared/FAEmptyState";
import { FASourceTraceBadge } from "@/components/shared/FASourceTraceBadge";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { formatDateTime, getLatestTradeDate } from "@/lib/date";
import type { EventFlowBriefSummary } from "@/types/event-flow";
import { formatEventFlowSourceLabel, translateEventFlowValue } from "./eventFlowFormat";

export function FilterDropdown({
  label,
  value,
  compact = false,
}: {
  label: string;
  value: string;
  compact?: boolean;
}) {
  if (compact) {
    return (
      <button type="button" className="event-flow-filter-chip">
        <span className="event-flow-filter-chip-label">{label}</span>
        <span className="event-flow-filter-chip-value">{value}</span>
        <span className="text-[8px] text-[var(--fg-5)]">&#9662;</span>
      </button>
    );
  }

  return (
    <div className="event-flow-filter-item">
      <span className="event-flow-filter-label">{label}</span>
      <div className="event-flow-filter-box">
        <span className="event-flow-filter-value">{value}</span>
        <span className="text-[8px] text-[var(--fg-5)]">&#9662;</span>
      </div>
    </div>
  );
}

function CountMetric({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2.5 py-2">
      <div className="text-[9px] uppercase tracking-[0.08em] text-[var(--fg-5)]">{label}</div>
      <div className="mt-1 fa-num text-[16px] font-semibold text-[var(--fg-1)]">{value}</div>
    </div>
  );
}

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
        <div className="text-[11px] leading-5 text-[var(--fg-4)]">当前主线仍在等待日报输入快照或金十事件快照返回有效事件。</div>
        <div className="flex flex-wrap gap-2">
          <FASourceTraceBadge source={formatDateTime(updatedAt)} status="updated_at" tone="info" />
          <FASourceTraceBadge source={formatEventFlowSourceLabel(source, 18).text} status="data_source" tone="dim" />
        </div>
      </FACard>
      <FAEmptyState title="暂无事件数据" description="当前返回结果为空，页面保留骨架。" />
    </>
  );
}

export function EventFlowWeekendBanner() {
  return (
    <div
      className="flex items-center gap-2 rounded-[var(--radius-sm)] px-3 py-1.5"
      style={{ background: "rgba(59,130,246,0.06)", border: "1px solid rgba(59,130,246,0.15)" }}
    >
      <Calendar size={12} color="#3b82f6" />
      <span className="text-[10px] font-medium text-[#3b82f6]">
        周末模式：市场数据沿用最近交易日（{getLatestTradeDate()}），事件快讯继续实时更新
      </span>
    </div>
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
    <div className="event-flow-summary-grid">
      <FACard
        title="新闻主线"
        eyebrow="每日市场简报"
        accent="brand"
        className="event-flow-summary-card"
        bodyClassName="space-y-3"
      >
        <div className="space-y-1.5">
          <div className="text-[13px] font-semibold text-[var(--fg-1)]">{summary.headline}</div>
          <div className="text-[11px] leading-5 text-[var(--fg-3)]">{summary.summary}</div>
        </div>
        <div className="flex flex-wrap gap-2">
          {summary.verificationStatus ? <FAStatusPill tone="info">{translateEventFlowValue(summary.verificationStatus)}</FAStatusPill> : null}
          {summary.pricingStatus ? <FAStatusPill tone="warn">{translateEventFlowValue(summary.pricingStatus)}</FAStatusPill> : null}
          {summary.riskLevel ? <FAStatusPill tone={summary.riskLevel === "high" ? "down" : summary.riskLevel === "medium" ? "warn" : "up"}>{translateEventFlowValue(summary.riskLevel)}</FAStatusPill> : null}
        </div>
        <div className="flex flex-wrap gap-2">
          <FASourceTraceBadge source={formatDateTime(updatedAt)} status="updated_at" tone="info" />
          <FAStatusPill tone="info">{formatEventFlowSourceLabel(source, 18).text}</FAStatusPill>
        </div>
      </FACard>

      <FACard
        title="事件分层"
        eyebrow="统计"
        accent="info"
        className="event-flow-summary-card"
        bodyClassName="grid grid-cols-2 gap-2"
      >
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
    confidence: number;
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
        <span className="text-[10px] font-semibold text-[var(--fg-5)]">模型事件分析</span>
        <span className="text-[10px] font-mono text-[var(--fg-4)]">
          {summary.bias} · {(summary.confidence * 100).toFixed(0)}%
        </span>
        {summary.llmModel && (
          <span className="text-[9px] text-[var(--fg-5)]">
            {summary.llmModel} · {summary.llmElapsedSeconds?.toFixed(1)}s
          </span>
        )}
      </div>
      <div className="mt-1 text-[11px] text-[var(--fg-3)]">{summary.summary}</div>
    </div>
  );
}

export function EventFlowBriefInputsCard({
  summary,
}: {
  summary: EventFlowBriefSummary;
}) {
  return (
    <FACard title="报告输入" eyebrow="输入摘要" accent="warn">
      <div className="space-y-3 text-[11px] text-[var(--fg-3)]">
        {summary.newsHighlights.length > 0 ? (
          <div className="space-y-1.5">
            <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">
              <FileText size={11} />
              新闻要点
            </div>
            <ul className="space-y-1.5">
              {summary.newsHighlights.map((item, index) => (
                <li key={`highlight-${index}`} className="leading-5 text-[var(--fg-2)]">
                  {item}
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {summary.watchlist.length > 0 ? (
          <div className="space-y-1.5">
            <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">
              <SearchCheck size={11} />
              观察列表
            </div>
            <ul className="space-y-1.5">
              {summary.watchlist.map((item, index) => (
                <li key={`watch-${index}`} className="leading-5 text-[var(--fg-2)]">
                  {item}
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {summary.riskPoints.length > 0 ? (
          <div className="space-y-1.5">
            <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">
              <ShieldAlert size={11} />
              风险点
            </div>
            <ul className="space-y-1.5">
              {summary.riskPoints.map((item, index) => (
                <li key={`risk-${index}`} className="leading-5 text-[var(--fg-2)]">
                  {item}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    </FACard>
  );
}

export function EventFlowDrilldownCard() {
  return (
    <FACard title="详情下钻" eyebrow="下钻" accent="brand">
      <div className="space-y-2 text-[11px] text-[var(--fg-4)]">
        <div>主页面只保留事件时间线、传导链、情绪概览与风险摘要。</div>
        <div>点击左侧事件进入详情页，查看事件事实、定价证据占位和相关资产。</div>
      </div>
    </FACard>
  );
}
