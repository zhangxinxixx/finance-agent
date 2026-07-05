import { FACard } from "@/components/shared/FACard";
import { FAEmptyState } from "@/components/shared/FAEmptyState";
import { FATabBar } from "@/components/shared/FATabBar";
import { FAWarningBanner } from "@/components/shared/FAWarningBanner";
import { MarkdownViewer } from "@/components/reports/MarkdownViewer";
import { formatDateTime } from "@/lib/date";
import type { Jin10ReportBundleView, Jin10Subview } from "@/types/reports";

interface Jin10DailyVisualViewerProps {
  report: Jin10ReportBundleView | null;
  selectedView: Jin10Subview;
  onSelectView: (view: Jin10Subview) => void;
  isLoading: boolean;
  error: Error | null;
  onRetry: () => void;
}

const VIEW_LABELS: Record<Jin10Subview, string> = {
  raw_article: "原文 MD",
  agent_analysis: "LLM 分析",
  daily_visual: "可视化报告",
};

const VIEW_HINTS: Record<Jin10Subview, string> = {
  raw_article: "原文整理后的 Markdown 版本，用于快速核对正文、图表说明与摘录证据。",
  agent_analysis: "基于原文与日报结构生成的 LLM 分析 Markdown，作为研究结论层阅读入口。",
  daily_visual: "基于 LLM/日报分析结果生成的 HTML 可视化报告，用于图文化阅读和展示。",
};

export function Jin10DailyVisualViewer({
  report,
  selectedView,
  onSelectView,
  isLoading,
  error,
  onRetry,
}: Jin10DailyVisualViewerProps) {
  if (isLoading) {
    return (
      <section className="fa-card flex min-h-0 flex-1 flex-col">
        <div className="fa-card-header">
          <div className="h-4 w-48 animate-pulse rounded bg-[var(--bg-hover)]" />
        </div>
        <div className="flex-1 p-4">
          <div className="h-full animate-pulse rounded-xl bg-[color-mix(in_srgb,var(--bg-hover)_70%,transparent)]" />
        </div>
      </section>
    );
  }

  if (error) {
    return (
      <FACard title="Jin10 报告加载失败" eyebrow="Visual Viewer" accent="down">
        <FAWarningBanner
          title="Bundle 产物当前不可用"
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

  if (!report) {
    return (
      <FACard title="暂无 Jin10 报告" eyebrow="Visual Viewer" accent="warn">
        <FAEmptyState
          title="当前没有 Jin10 bundle 产物"
          description="需要先生成 agent_analysis、daily_visual 或 raw_article 任一产物后才能在此阅读。"
        />
      </FACard>
    );
  }

  const activeView = report.views[selectedView];
  const metaItems = [
    { label: "报告日期", value: report.trade_date },
    { label: "生成时间", value: formatDateTime(report.generated_at) },
    { label: "文章 ID", value: report.article_id ? `article ${report.article_id}` : "—" },
    { label: "Run ID", value: report.run_id },
  ];
  const viewTabs = (["agent_analysis", "daily_visual", "raw_article"] as Jin10Subview[]).map((view) => ({
    value: view,
    label: VIEW_LABELS[view],
    disabled: !report.views[view]?.available,
  }));

  return (
    <FACard
      title="Jin10 三产物报告中心"
      eyebrow="Visual Viewer"
      accent="warn"
      action={
        report.source_url ? (
          <a
            href={report.source_url}
            target="_blank"
            rel="noreferrer"
            className="rounded-[var(--radius-sm)] border border-[var(--border)] px-2.5 py-1 text-[11px] font-semibold text-[var(--fg-3)] transition-colors hover:border-[var(--brand)] hover:text-[var(--fg-1)]"
          >
            原文链接
          </a>
        ) : null
      }
      className="flex min-h-0 flex-1 flex-col"
      bodyClassName="min-h-0 flex flex-1 flex-col gap-4"
    >
      {report.title ? <div className="text-[12px] text-[var(--fg-4)]">{report.title}</div> : null}
      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
        {metaItems.map((item) => (
          <div
            key={item.label}
            className="min-w-0 rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-3 py-2"
          >
            <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">{item.label}</div>
            <div className="fa-num mt-1 truncate text-[12px] font-semibold text-[var(--fg-2)]" title={item.value}>
              {item.value}
            </div>
          </div>
        ))}
      </div>
      <div className="grid gap-3 sm:grid-cols-3">
        {([
          { key: "raw_article" as Jin10Subview, eyebrow: "Source MD", title: "原文 Markdown 报告" },
          { key: "agent_analysis" as Jin10Subview, eyebrow: "Analysis MD", title: "LLM 分析报告" },
          { key: "daily_visual" as Jin10Subview, eyebrow: "Visual HTML", title: "LLM 可视化报告" },
        ]).map((card) => {
          const available = report.views[card.key]?.available;
          const selected = selectedView === card.key;
          return (
            <button
              key={card.key}
              type="button"
              onClick={() => available && onSelectView(card.key)}
              aria-disabled={!available}
              className="rounded-[var(--radius-lg)] border p-3 text-left transition-colors"
              style={{
                borderColor: selected ? "var(--brand)" : "var(--border-faint)",
                background: selected ? "var(--brand-dim)" : "var(--bg-card-inner)",
                opacity: available ? 1 : 0.55,
                cursor: available ? "pointer" : "default",
              }}
            >
              <div className="mb-1 text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">
                {card.eyebrow}
              </div>
              <div className="text-[12px] font-semibold text-[var(--fg-2)]">{card.title}</div>
            </button>
          );
        })}
      </div>
      <div className="space-y-3">
        <FATabBar tabs={viewTabs} value={selectedView} onChange={onSelectView} ariaLabel="Jin10 视图切换" />
        <div className="text-[11px] text-[var(--fg-4)]">{VIEW_HINTS[selectedView]}</div>
      </div>

      {!activeView?.available ? (
        <FAEmptyState
          title="当前视图缺少产物"
          description="对应 artifact 尚未生成，建议切换到其他可用视图或回查后端输出。"
        />
      ) : activeView.kind === "html" ? (
        <div className="min-h-[78vh] overflow-hidden rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card-inner)] p-3">
          <iframe
            title={`Jin10 report ${selectedView} ${report.trade_date} ${report.run_id}`}
            srcDoc={activeView.content ?? ""}
            className="min-h-[72vh] w-full rounded-lg border border-[var(--border)] bg-[var(--bg-card)]"
            sandbox="allow-same-origin"
          />
        </div>
      ) : (
        <div className="min-h-[78vh] max-h-[78vh] overflow-y-auto rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card-inner)] p-4">
          <MarkdownViewer content={activeView.content ?? ""} assetBaseUrl={activeView.asset_base_url} />
        </div>
      )}
    </FACard>
  );
}

export default Jin10DailyVisualViewer;
