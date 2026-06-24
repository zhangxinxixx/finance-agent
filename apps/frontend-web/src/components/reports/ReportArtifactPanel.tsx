import { FAEmptyState } from "@/components/shared/FAEmptyState";
import { MarkdownViewer } from "@/components/reports/MarkdownViewer";
import type { ReportArtifactContentView } from "@/types/reports";

export function ReportArtifactPanel({ tab }: { tab: ReportArtifactContentView | null }) {
  const panelClassName = "min-h-0 rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card-inner)]";

  if (!tab || !tab.available) {
    return (
      <FAEmptyState
        title="当前内容暂不可展示"
        description="该报告暂未返回可展示的分析稿、来源稿、可视稿或证据包。"
      />
    );
  }

  if (tab.format === "html") {
    return (
      <div className={`${panelClassName} min-h-[78vh] overflow-hidden p-3`}>
        <iframe
          title={tab.label}
          srcDoc={tab.content}
          className="min-h-[72vh] w-full rounded-lg border border-finance-border bg-white"
        />
      </div>
    );
  }

  if (tab.format === "json") {
    return (
      <pre className="min-h-[78vh] overflow-auto rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-terminal)] p-4 text-[12px] leading-6 text-[var(--fg-3)]">
        {tab.content}
      </pre>
    );
  }

  return (
    <div className={`${panelClassName} p-4`}>
      <MarkdownViewer
        content={tab.content}
        assetBaseUrl={tab.asset_base_url ?? undefined}
        blockListClassName="min-h-[78vh] max-h-none overflow-visible pr-2"
        fallbackClassName="min-h-[78vh] max-h-none overflow-x-auto overflow-y-visible pr-2"
      />
    </div>
  );
}
