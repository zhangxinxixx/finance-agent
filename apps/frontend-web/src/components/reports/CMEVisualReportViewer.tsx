import { ReportArtifactPanel } from "./ReportArtifactPanel";
import { FACard } from "@/components/shared/FACard";
import { FAEmptyState } from "@/components/shared/FAEmptyState";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { FAWarningBanner } from "@/components/shared/FAWarningBanner";
import type { VisualReportView } from "@/types/reports";
import { readingErrorMessage } from "@/components/reading/readingFormat";

interface CMEVisualReportViewerProps {
  report: VisualReportView | null;
  isLoading: boolean;
  error: Error | null;
  onRetry: () => void;
}

export function CMEVisualReportViewer({
  report,
  isLoading,
  error,
  onRetry,
}: CMEVisualReportViewerProps) {
  if (isLoading) {
    return (
      <section className="fa-card flex min-h-0 flex-1 flex-col">
        <div className="fa-card-header">
          <div className="h-4 w-40 animate-pulse rounded bg-[var(--bg-hover)]" />
        </div>
        <div className="flex-1 p-4">
          <div className="h-full animate-pulse rounded-xl bg-[color-mix(in_srgb,var(--bg-hover)_70%,transparent)]" />
        </div>
      </section>
    );
  }

  if (error) {
    return (
      <FACard title="CME 图文报告加载失败" eyebrow="图文报告" accent="down">
        <FAWarningBanner
          title="HTML 视觉产物暂时不可用"
          description={readingErrorMessage(error, "图文报告读取失败，请稍后重试。")}
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
      <FACard title="暂无 CME 图文报告" eyebrow="图文报告" accent="warn">
        <FAEmptyState
          title="当前没有 HTML 视觉报告"
          description="需要先生成可用的 CME 图文研究产物后才能在此阅读。"
        />
      </FACard>
    );
  }

  return (
    <FACard
      title="CME期权研究报告"
      eyebrow="图文报告"
      accent="info"
      action={
        <div className="flex flex-wrap items-center gap-2">
          <FAStatusPill tone="dim" dot={false} className="fa-num">
            {report.trade_date}
          </FAStatusPill>
        </div>
      }
      className="flex min-h-0 flex-1 flex-col"
      bodyClassName="min-h-0 flex-1 overflow-hidden"
    >
      <ReportArtifactPanel tab={{ key: "analysis", source_endpoint: "", available: true, format: "html", content: report.content, label: "研究正文", asset_base_url: null, path: null }} />
    </FACard>
  );
}

export default CMEVisualReportViewer;
