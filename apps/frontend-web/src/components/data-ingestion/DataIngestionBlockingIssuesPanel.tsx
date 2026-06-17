import { formatDateTime } from "@/lib/date";
import type { DataIngestionSystemStatusViewModel, DataSourceStatusViewModel } from "@/types/data-ingestion";
import { AlertTriangle, CheckCircle2 } from "lucide-react";

type BlockingIssue = {
  severity: "error" | "warn";
  title: string;
  desc: string;
  meta: string;
};

export function BlockingIssuesPanel({
  sources,
  systemStatus,
}: {
  sources: DataSourceStatusViewModel[];
  systemStatus: DataIngestionSystemStatusViewModel | null;
}) {
  const issues = buildBlockingIssues(sources, systemStatus);
  const hasErrors = issues.some((issue) => issue.severity === "error");

  return (
    <div
      className="flex min-h-0 flex-col overflow-hidden rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card)]"
      style={{ maxHeight: "min(34vh, 320px)" }}
    >
      <div className="flex items-center justify-between border-b border-[var(--border)] bg-[var(--bg-panel)] px-3 py-2">
        <span className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--fg-2)]">阻断问题</span>
        <span
          className="rounded-full px-1.5 py-px text-[9px] font-bold"
          style={{
            background: hasErrors ? "var(--down-soft)" : issues.length > 0 ? "var(--warn-soft)" : "var(--up-soft)",
            color: hasErrors ? "var(--down)" : issues.length > 0 ? "var(--warn)" : "var(--up)",
          }}
        >
          {issues.length} 个问题
        </span>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        <BlockingIssueList issues={issues} />
      </div>
    </div>
  );
}

function buildBlockingIssues(
  sources: DataSourceStatusViewModel[],
  systemStatus: DataIngestionSystemStatusViewModel | null,
): BlockingIssue[] {
  const issues: BlockingIssue[] = [];

  for (const source of sources) {
    if (source.raw_status === "error" || source.status === "error") {
      issues.push({
        severity: "error",
        title: source.label,
        desc: source.error_message || source.status_reason || "数据源异常",
        meta: source.latest_raw_time ? formatDateTime(source.latest_raw_time) : "no update",
      });
    } else if (source.raw_status === "warn" || source.status === "partial") {
      issues.push({
        severity: "warn",
        title: source.label,
        desc: source.status_reason || "部分可用",
        meta: source.latest_raw_time ? formatDateTime(source.latest_raw_time) : "no update",
      });
    }
  }

  if (systemStatus?.missing_sources.length) {
    for (const name of systemStatus.missing_sources) {
      issues.push({
        severity: "error",
        title: name,
        desc: "后端配置缺失",
        meta: systemStatus.data_date ?? "—",
      });
    }
  }

  return issues;
}

function BlockingIssueList({ issues }: { issues: BlockingIssue[] }) {
  if (issues.length === 0) {
    return (
      <div className="flex flex-col items-center gap-1.5 py-4">
        <CheckCircle2 size={16} className="text-[var(--up)]" />
        <span className="text-[10px] text-[var(--fg-4)]">未检测到阻断问题</span>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-1.5">
      {issues.map((issue, index) => (
        <BlockingIssueItem key={`${issue.title}-${index}`} issue={issue} />
      ))}
    </div>
  );
}

function BlockingIssueItem({ issue }: { issue: BlockingIssue }) {
  const isError = issue.severity === "error";

  return (
    <div
      className="rounded-[var(--radius-md)] border px-2.5 py-2"
      style={{
        borderColor: isError ? "var(--down-border)" : "var(--warn-border)",
        background: isError ? "var(--down-soft)" : "var(--warn-soft)",
      }}
    >
      <div className="flex items-center gap-1.5">
        {isError ? (
          <AlertTriangle size={10} className="shrink-0 text-[var(--down)]" />
        ) : (
          <CheckCircle2 size={10} className="shrink-0 text-[var(--warn)]" />
        )}
        <span className="text-[10px] font-semibold text-[var(--fg-2)]">{issue.title}</span>
      </div>
      <div className="mt-0.5 text-[9px] leading-relaxed text-[var(--fg-4)]">{issue.desc}</div>
      <div className="mt-0.5 font-mono text-[8px] text-[var(--fg-5)]">{issue.meta}</div>
    </div>
  );
}
