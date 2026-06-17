import { FACard } from "@/components/shared/FACard";
import { FAEmptyState } from "@/components/shared/FAEmptyState";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { FAWarningBanner } from "@/components/shared/FAWarningBanner";
import { MarkdownViewer } from "@/components/reports/MarkdownViewer";
import { ReportMetaStrip } from "@/components/reports/ReportMetaStrip";
import type { FinalReportView } from "@/types/reports";

interface ReportReaderProps {
  report: FinalReportView | { content: string } | null;
  isLoading: boolean;
  error: Error | null;
  onRetry: () => void;
}

export function ReportReader({ report, isLoading, error, onRetry }: ReportReaderProps) {
  if (isLoading) {
    return (
      <section className="fa-card flex min-h-0 flex-1 flex-col">
        <div className="fa-card-header">
          <div className="h-4 w-40 animate-pulse rounded bg-[var(--bg-hover)]" />
        </div>
        <div className="grid gap-2 border-b border-[var(--border)] px-4 py-4 sm:grid-cols-2 xl:grid-cols-6">
          {Array.from({ length: 6 }).map((_, index) => (
            <div key={index} className="h-14 animate-pulse rounded-lg bg-[var(--bg-hover)]" />
          ))}
        </div>
        <div className="flex-1 space-y-3 overflow-hidden px-4 py-4">
          {Array.from({ length: 10 }).map((_, index) => (
            <div key={index} className="h-4 animate-pulse rounded bg-[color-mix(in_srgb,var(--bg-hover)_80%,transparent)]" style={{ width: `${90 - index * 4}%` }} />
          ))}
        </div>
      </section>
    );
  }

  if (error) {
    return (
      <FACard title="完整报告加载失败" eyebrow="Report Reader" accent="down">
        <FAWarningBanner
          title="当前报告内容不可用"
          description={error.message}
          tone="down"
          action={
            <button
              type="button"
              onClick={onRetry}
              className="rounded-[var(--radius-md)] border border-[var(--down-border)] px-3 py-1.5 text-[11px] font-semibold text-[var(--down)]"
            >
              重试
            </button>
          }
        />
      </FACard>
    );
  }

  if (!report || !report.content.trim()) {
    return (
      <FACard title="暂无完整报告" eyebrow="Report Reader" accent="warn">
        <FAEmptyState
          title="当前没有可阅读的正文产物"
          description="需要先生成 final_report、期权分析 markdown 或周报 markdown 产物后才能在此阅读。"
        />
      </FACard>
    );
  }

  const isFinal = "report_type" in report;
  const reportLabel = isFinal ? (report as FinalReportView).report_type : "options_report";
  const finalReport = isFinal ? (report as FinalReportView) : null;
  const contentLength = isFinal ? finalReport?.content_length ?? report.content.length : report.content.length;
  const sectionEstimate = Math.max(1, Math.round(report.content.split(/^##\s+/m).length));

  return (
    <FACard
      title={isFinal ? "综合研究报告" : "结构化报告正文"}
      eyebrow="Report Reader"
      accent="brand"
      action={
        <div className="flex flex-wrap items-center gap-2">
          <FAStatusPill tone="info" dot={false}>
            {reportLabel}
          </FAStatusPill>
          {isFinal ? (
            <FAStatusPill tone="dim" dot={false} className="fa-num">
              {(report as FinalReportView).trade_date}
            </FAStatusPill>
          ) : null}
        </div>
      }
      className="flex min-h-0 flex-1 flex-col"
      bodyClassName="min-h-0 flex flex-1 flex-col gap-4"
    >
      {isFinal ? <ReportMetaStrip report={report as FinalReportView} /> : null}
      <div className="grid min-h-0 flex-1 gap-4 xl:grid-cols-[minmax(0,1fr)_280px]">
        <div className="min-h-0 overflow-y-auto rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card-inner)] p-4">
          <div className="mb-4 flex flex-wrap items-center gap-2 border-b border-[var(--border-faint)] pb-3">
            <FAStatusPill tone="info" dot={false}>
              {isFinal ? "Analysis Markdown" : "Options Markdown"}
            </FAStatusPill>
            <FAStatusPill tone="dim" dot={false}>
              {contentLength} chars
            </FAStatusPill>
            <FAStatusPill tone="dim" dot={false}>
              {sectionEstimate} sections
            </FAStatusPill>
            {finalReport?.warning_count ? (
              <FAStatusPill tone="warn" dot={false}>
                {finalReport.warning_count} warnings
              </FAStatusPill>
            ) : null}
          </div>
          <MarkdownViewer content={report.content} />
        </div>

        <aside className="flex min-h-0 flex-col gap-4">
          <div className="rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card-inner)] p-4">
            <div className="mb-3 text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">
              阅读上下文
            </div>
            <div className="grid gap-3">
              <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-panel)] p-3">
                <div className="text-[9px] uppercase tracking-[0.08em] text-[var(--fg-5)]">报告类型</div>
                <div className="mt-1 text-[12px] font-semibold text-[var(--fg-2)]">{reportLabel}</div>
              </div>
              <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-panel)] p-3">
                <div className="text-[9px] uppercase tracking-[0.08em] text-[var(--fg-5)]">内容规模</div>
                <div className="mt-1 font-mono text-[12px] font-semibold text-[var(--brand-hover)]">{contentLength}</div>
                <div className="mt-1 text-[10px] text-[var(--fg-4)]">字符数 / 用于快速判断正文是否完整</div>
              </div>
              <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-panel)] p-3">
                <div className="text-[9px] uppercase tracking-[0.08em] text-[var(--fg-5)]">结构段数</div>
                <div className="mt-1 font-mono text-[12px] font-semibold text-[var(--fg-2)]">{sectionEstimate}</div>
                <div className="mt-1 text-[10px] text-[var(--fg-4)]">基于 Markdown `##` 标题的粗略估计</div>
              </div>
              {finalReport?.source_endpoint ? (
                <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-panel)] p-3">
                  <div className="text-[9px] uppercase tracking-[0.08em] text-[var(--fg-5)]">读取来源</div>
                  <div className="mt-1 break-all font-mono text-[10px] text-[var(--fg-3)]">{finalReport.source_endpoint}</div>
                </div>
              ) : null}
            </div>
          </div>

          <div className="rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card-inner)] p-4">
            <div className="mb-3 text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">
              关联数据与操作
            </div>
            <div className="space-y-2 text-[10px] text-[var(--fg-4)]">
              <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-panel)] p-3">
                正文阅读态当前保持只读，不在前端重建分析结论。
              </div>
              <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-panel)] p-3">
                如需更强的 source trace / artifact drilldown，应继续走标准 `Report Detail` API，而不是在此页拼业务摘要。
              </div>
            </div>
          </div>
        </aside>
      </div>
    </FACard>
  );
}

export default ReportReader;
