import { Link } from "react-router-dom";
import { FACard } from "@/components/shared/FACard";
import { FASourceTraceBadge } from "@/components/shared/FASourceTraceBadge";
import { FAStatusPill, type FAStatusTone } from "@/components/shared/FAStatusPill";
import { SourceTrace } from "@/components/shared/SourceTrace";
import { getStatusTone } from "@/components/shared/statusMeta";
import { formatDateTime } from "@/lib/date";
import { compactId } from "@/lib/format";
import type { TaskReviewViewModel } from "@/types/agent-task";

function statusTone(status: string): FAStatusTone {
  return getStatusTone(status, "review");
}

function severityTone(severity: string): FAStatusTone {
  return getStatusTone(severity);
}

export function ReviewCard({ review }: { review: TaskReviewViewModel }) {
  const isFactReviewIssue = Boolean(review.claim_id || review.agent_output_id);

  return (
    <article className="rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card)] p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-[10px] text-[var(--fg-5)]">{review.review_id}</span>
            {isFactReviewIssue ? <FAStatusPill tone="info">事实审查</FAStatusPill> : null}
            <FAStatusPill tone={statusTone(review.status)}>{review.status}</FAStatusPill>
            <FAStatusPill tone={severityTone(review.severity)}>{review.severity}</FAStatusPill>
          </div>
          <h2 className="mt-2 text-[13px] font-semibold text-[var(--fg-2)]">{review.source_module}</h2>
          <p className="mt-2 max-w-3xl text-[12px] leading-6 text-[var(--fg-3)]">{review.reason}</p>
        </div>
        <div className="text-right text-[10px] text-[var(--fg-5)]">
          <div>{review.created_at ? formatDateTime(review.created_at) : "创建时间不可用"}</div>
          <div className="mt-1 font-mono">{review.run_id ?? "run 不可用"}</div>
        </div>
      </div>

      <div className="mt-3 grid gap-2 md:grid-cols-3">
        <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
          <div className="text-[9px] uppercase tracking-[0.1em] text-[var(--fg-5)]">来源步骤</div>
          <div className="mt-1 font-mono text-[10px] text-[var(--fg-3)]">{review.source_step_id ?? "—"}</div>
        </div>
        <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
          <div className="text-[9px] uppercase tracking-[0.1em] text-[var(--fg-5)]">关联 Claim</div>
          <div className="mt-1 font-mono text-[10px] text-[var(--fg-3)]">{review.claim_id ?? "—"}</div>
        </div>
        <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
          <div className="text-[9px] uppercase tracking-[0.1em] text-[var(--fg-5)]">建议动作</div>
          <div className="mt-1 text-[10px] text-[var(--fg-3)]">{review.suggested_action ?? "只读复核，暂无建议动作"}</div>
        </div>
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        <FASourceTraceBadge source={compactId(review.run_id, 12, 4)} status="run_id" tone="info" />
        {review.agent_output_id ? (
          <FASourceTraceBadge source={compactId(review.agent_output_id, 12, 4)} status="agent_output" tone="dim" />
        ) : null}
        {review.impact_modules.map((module) => (
          <FASourceTraceBadge key={`${review.review_id}-${module}`} source={module} status="impact" tone="warn" />
        ))}
      </div>

      {review.impact_report_ids.length > 0 ? (
        <div className="mt-3">
          <div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.1em] text-[var(--fg-5)]">影响报告</div>
          <div className="flex flex-wrap gap-2">
            {review.impact_report_ids.map((reportId) => (
              <Link
                key={`${review.review_id}-${reportId}`}
                to={`/reports/${encodeURIComponent(reportId)}`}
                className="rounded-full border border-[var(--border-faint)] bg-[var(--bg-panel)] px-2.5 py-1 font-mono text-[10px] text-[var(--brand-hover)] hover:border-[var(--border-strong)] hover:text-[var(--brand)]"
              >
                {reportId}
              </Link>
            ))}
          </div>
        </div>
      ) : null}

      {review.source_refs.length > 0 ? (
        <div className="mt-3">
          <div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.1em] text-[var(--fg-5)]">事实审查溯源</div>
          <div className="max-h-[260px] overflow-y-auto pr-1">
            <SourceTrace sourceRefs={review.source_refs} compact emptyText="当前复核项没有 source refs。" />
          </div>
        </div>
      ) : null}

      {review.evidence_refs.length > 0 ? (
        <div className="mt-3">
          <div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.1em] text-[var(--fg-5)]">证据产物</div>
          <div className="max-h-[180px] overflow-y-auto pr-1">
            <div className="flex flex-wrap gap-2">
              {review.evidence_refs.map((artifact) => (
                <span
                  key={`${artifact.artifact_id}-${artifact.file_path}`}
                  className="rounded-full border border-[var(--border-faint)] bg-[var(--bg-panel)] px-2 py-1 font-mono text-[9px] text-[var(--fg-4)]"
                >
                  {artifact.artifact_type}:{artifact.file_path}
                </span>
              ))}
            </div>
          </div>
        </div>
      ) : null}
    </article>
  );
}

export function ReviewCenterSummaryCard({
  source,
  total,
  filteredCount,
}: {
  source: string;
  total: number;
  filteredCount: number;
}) {
  return (
    <FACard
      title="人工复核中心"
      eyebrow="事实审查承接"
      accent="warn"
      action={<FAStatusPill tone={source === "api" ? "up" : "warn"}>{source}</FAStatusPill>}
      bodyClassName="space-y-3"
    >
      <div className="grid gap-3 sm:grid-cols-3">
        <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
          <div className="text-[9px] uppercase tracking-[0.1em] text-[var(--fg-5)]">总数</div>
          <div className="fa-num mt-1 text-[20px] text-[var(--fg-2)]">{total}</div>
        </div>
        <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
          <div className="text-[9px] uppercase tracking-[0.1em] text-[var(--fg-5)]">筛选后</div>
          <div className="fa-num mt-1 text-[20px] text-[var(--fg-2)]">{filteredCount}</div>
        </div>
        <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
          <div className="text-[9px] uppercase tracking-[0.1em] text-[var(--fg-5)]">操作</div>
          <div className="mt-1 text-[11px] text-[var(--fg-3)]">继续保持只读，并承接事实审查问题项的追溯字段</div>
        </div>
      </div>
    </FACard>
  );
}
