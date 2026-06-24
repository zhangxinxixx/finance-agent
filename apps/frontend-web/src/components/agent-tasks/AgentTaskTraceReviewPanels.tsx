import { Bot } from "lucide-react";
import { FAEmptyState } from "@/components/shared/FAEmptyState";
import { FASourceTraceBadge } from "@/components/shared/FASourceTraceBadge";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { SourceTrace } from "@/components/shared/SourceTrace";
import { compactId } from "@/lib/format";
import type { TaskReviewViewModel, TaskRunViewModel } from "@/types/agent-task";

export function TracePanel({ selectedRun }: { selectedRun: TaskRunViewModel }) {
  return (
    <div className="space-y-3">
      <div className="rounded-[14px] border border-[var(--border)] bg-[var(--bg-card)] p-4">
        <div className="mb-4 flex items-center gap-2 text-[11px] font-semibold text-[var(--fg-2)]">
          <Bot size={14} className="text-[var(--brand)]" />
          <span>数据来源</span>
        </div>
        <SourceTrace sourceRefs={selectedRun.source_refs} emptyText="当前运行未返回来源引用" />
      </div>
      {selectedRun.artifact_refs.length > 0 ? (
        <div className="rounded-[14px] border border-[var(--border)] bg-[var(--bg-card)] p-4">
          <div className="mb-3 text-[11px] font-semibold text-[var(--fg-2)]">产物引用</div>
          <div className="max-h-[360px] overflow-y-auto">
            <div className="flex flex-wrap gap-2">
              {selectedRun.artifact_refs.map((artifact) => (
                <FASourceTraceBadge
                  key={`${artifact.artifact_id}-${artifact.file_path}`}
                  source={artifact.artifact_type || "artifact"}
                  status={artifact.file_path || artifact.path || "-"}
                  tone="dim"
                />
              ))}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

export function ReviewPanel({ reviews }: { reviews: TaskReviewViewModel[] }) {
  if (reviews.length === 0) {
    return <FAEmptyState title="无待复核项" description="当前没有待复核内容。" className="p-6" />;
  }

  return (
    <div className="max-h-[calc(100vh-260px)] space-y-3 overflow-y-auto pr-1">
      {reviews.map((review) => (
        <article key={review.review_id} className="rounded-[14px] border border-[var(--border)] bg-[var(--bg-card)] p-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="text-[13px] font-semibold text-[var(--fg-2)]">{review.source_module}</div>
              <div className="mt-2 text-[12px] leading-relaxed text-[var(--fg-3)]">{review.reason}</div>
            </div>
            <FAStatusPill tone={review.status === "pending" ? "warn" : "dim"}>{review.status}</FAStatusPill>
          </div>
          <div className="mt-3 font-mono text-[10px] text-[var(--fg-5)]">{compactId(review.review_id, 16, 4)}</div>
        </article>
      ))}
    </div>
  );
}
