import { FileJson, FileText, SearchCheck, ShieldAlert } from "lucide-react";
import { FACard } from "@/components/shared/FACard";
import { FASourceTraceBadge } from "@/components/shared/FASourceTraceBadge";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import type { EventFlowBriefSummary, EventFlowDailyBrief } from "@/types/event-flow";

export function EventFlowDailyBriefCard({
  brief,
}: {
  brief: EventFlowDailyBrief;
}) {
  return (
    <FACard
      title="稳定日报"
      eyebrow="Daily Brief"
      accent="brand"
      action={<FAStatusPill tone={brief.status === "available" ? "up" : brief.status === "empty" ? "warn" : "info"}>{brief.reportMode}</FAStatusPill>}
      bodyClassName="space-y-3"
    >
      <div className="grid gap-2 sm:grid-cols-4">
        <BriefMetric label="核心事件" value={brief.structured.coreEventCount} />
        <BriefMetric label="重点文章" value={brief.structured.keyArticleCount} />
        <BriefMetric label="行情验证" value={brief.structured.marketReactionCount} />
        <BriefMetric label="风险标记" value={brief.structured.riskFlagCount} />
      </div>

      {brief.structured.oneLineInputs.length > 0 ? (
        <div className="space-y-1.5">
          <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">
            <FileText size={11} />
            Inputs
          </div>
          <ul className="space-y-1 text-[11px] leading-5 text-[var(--fg-2)]">
            {brief.structured.oneLineInputs.slice(0, 3).map((item) => (
              <li key={`daily-brief-input-${item}`}>{item}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {brief.markdownPreview ? (
        <div className="rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2.5 py-2 text-[11px] leading-5 text-[var(--fg-3)]">
          {brief.markdownPreview}
        </div>
      ) : null}

      <div className="flex flex-wrap gap-1.5">
        <FAStatusPill tone={brief.status === "available" ? "up" : "warn"}>{brief.status}</FAStatusPill>
        {brief.qualityFlags.slice(0, 4).map((flag) => (
          <FAStatusPill key={`daily-brief-quality-${flag}`} tone={flag.includes("missing") || flag.includes("single_source") ? "warn" : "info"}>
            {flag}
          </FAStatusPill>
        ))}
      </div>

      <div className="flex flex-wrap gap-2">
        <FASourceTraceBadge source={`${brief.date}/${brief.runId}`} status="run" tone="info" />
        {brief.artifactPath ? <FASourceTraceBadge source={brief.artifactPath} status="markdown" tone="dim" /> : null}
        {brief.inputSnapshotPath ? <FASourceTraceBadge source={brief.inputSnapshotPath} status="snapshot" tone="dim" /> : null}
        {brief.jsonPath ? <FASourceTraceBadge source={brief.jsonPath} status="json" tone="dim" /> : null}
      </div>

      {brief.sourceRefs.length > 0 ? (
        <div className="flex items-center gap-1.5 text-[10px] text-[var(--fg-5)]">
          <FileJson size={11} />
          <span>{brief.sourceRefs.length} source refs retained in read model</span>
        </div>
      ) : null}
    </FACard>
  );
}

function BriefMetric({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2.5 py-2">
      <div className="text-[9px] uppercase tracking-[0.08em] text-[var(--fg-5)]">{label}</div>
      <div className="mt-1 fa-num text-[15px] font-semibold text-[var(--fg-1)]">{value}</div>
    </div>
  );
}

export function EventFlowBriefInputsCard({
  summary,
}: {
  summary: EventFlowBriefSummary;
}) {
  return (
    <FACard title="报告输入" eyebrow="Brief Inputs" accent="warn">
      <div className="space-y-3 text-[11px] text-[var(--fg-3)]">
        {summary.newsHighlights.length > 0 ? (
          <div className="space-y-1.5">
            <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">
              <FileText size={11} />
              News Highlights
            </div>
            <ul className="space-y-1.5">
              {summary.newsHighlights.slice(0, 2).map((item) => (
                <li key={`highlight-${item}`} className="leading-5 text-[var(--fg-2)]">
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
              Watchlist
            </div>
            <ul className="space-y-1.5">
              {summary.watchlist.slice(0, 2).map((item) => (
                <li key={`watch-${item}`} className="leading-5 text-[var(--fg-2)]">
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
              Risk Points
            </div>
            <ul className="space-y-1.5">
              {summary.riskPoints.slice(0, 2).map((item) => (
                <li key={`risk-${item}`} className="leading-5 text-[var(--fg-2)]">
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
    <FACard title="详情下钻" eyebrow="Drilldown" accent="brand">
      <div className="space-y-2 text-[11px] text-[var(--fg-4)]">
        <div>主页面只保留事件时间线、传导链、情绪概览与风险摘要。</div>
        <div>点击左侧事件进入详情页，查看事件事实、定价证据占位和相关资产。</div>
      </div>
    </FACard>
  );
}
