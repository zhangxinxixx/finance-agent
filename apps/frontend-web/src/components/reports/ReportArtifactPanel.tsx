import { FAEmptyState } from "@/components/shared/FAEmptyState";
import { MarkdownViewer } from "@/components/reports/MarkdownViewer";
import type { ReportArtifactContentView } from "@/types/reports";

export function ReportArtifactPanel({ tab }: { tab: ReportArtifactContentView | null }) {
  if (!tab || !tab.available) {
    return (
      <FAEmptyState
        title="当前 tab 暂无可展示产物"
        description="标准详情页保留 analysis / source / visual / evidence 四类产物位，但只有后端实际返回的 tab 才会展示内容。"
      />
    );
  }

  if (tab.format === "html") {
    return (
      <div className="max-h-[calc(100vh-260px)] overflow-y-auto rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card-inner)] p-3">
        <iframe
          title={tab.label}
          srcDoc={tab.content}
          className="h-[720px] w-full rounded-lg border border-finance-border bg-white"
        />
      </div>
    );
  }

  if (tab.format === "json") {
    return (
      <pre className="max-h-[calc(100vh-260px)] overflow-auto rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-terminal)] p-4 text-[12px] leading-6 text-[var(--fg-3)]">
        {tab.content}
      </pre>
    );
  }

  return (
    <div className="max-h-[calc(100vh-260px)] overflow-y-auto rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card-inner)] p-4">
      <MarkdownViewer content={tab.content} />
    </div>
  );
}
