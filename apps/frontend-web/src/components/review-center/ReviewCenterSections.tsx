import { Link } from "react-router-dom";
import { FACard } from "@/components/shared/FACard";
import { FASourceTraceBadge } from "@/components/shared/FASourceTraceBadge";
import { FAStatusPill, type FAStatusTone } from "@/components/shared/FAStatusPill";
import { SourceTrace } from "@/components/shared/SourceTrace";
import { getStatusTone } from "@/components/shared/statusMeta";
import { formatDateTime } from "@/lib/date";
import { compactId } from "@/lib/format";
import type { TaskReviewViewModel } from "@/types/agent-task";
import type { ReviewActionKind } from "@/adapters/agentTasks";
import type { PromptEvolutionPreviewResponse } from "@/types/agent-registry";

function statusTone(status: string): FAStatusTone {
  return getStatusTone(status, "review");
}

function severityTone(severity: string): FAStatusTone {
  return getStatusTone(severity);
}

const REVIEW_ACTIONS: Array<{ action: ReviewActionKind; label: string }> = [
  { action: "use-fallback", label: "采用备用结果" },
  { action: "rerun", label: "重新运行" },
  { action: "approve", label: "通过" },
  { action: "reject", label: "驳回" },
];

function reviewActionLabel(value: string | null | undefined): string {
  const labels: Record<string, string> = {
    approve: "通过",
    reject: "驳回",
    rerun: "重新运行",
    use_fallback: "采用备用结果",
  };
  return value ? labels[value] ?? value : "待处理";
}

export function ReviewCard({
  review,
  onAction,
  actionReviewId,
}: {
  review: TaskReviewViewModel;
  onAction?: (review: TaskReviewViewModel, action: ReviewActionKind) => void;
  actionReviewId?: string | null;
}) {
  const isFactReviewIssue = Boolean(review.claim_id || review.agent_output_id);
  const isPending = review.status === "pending";
  const isActing = actionReviewId === review.review_id;

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
          {review.action_status ? <div className="mt-1">{review.action_status}</div> : null}
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

      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-3 py-2">
        <div className="min-w-0 text-[10px] leading-4 text-[var(--fg-4)]">
          <span className="font-semibold text-[var(--fg-5)]">处理结果：</span>
          {review.resolution_action ? `${reviewActionLabel(review.resolution_action)}${review.resolution_note ? ` · ${review.resolution_note}` : ""}` : "待处理"}
        </div>
        <div className="flex flex-wrap gap-1.5">
          {REVIEW_ACTIONS.map((item) => (
            <button
              key={item.action}
              type="button"
              disabled={!isPending || isActing || !onAction}
              onClick={() => onAction?.(review, item.action)}
              className="inline-flex h-7 items-center rounded-[var(--radius-sm)] border border-[var(--border)] bg-[var(--bg-card)] px-2 text-[10px] font-semibold text-[var(--fg-3)] transition hover:border-[var(--border-strong)] hover:text-[var(--fg-1)] disabled:cursor-not-allowed disabled:opacity-45"
            >
              {isActing ? "处理中" : item.label}
            </button>
          ))}
        </div>
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

function booleanTone(value?: boolean): FAStatusTone {
  return value ? "warn" : "dim";
}

function formatProposalValue(value: unknown, fallback = "暂无"): string {
  if (typeof value === "string" && value.trim()) return value;
  if (typeof value === "number") return String(value);
  if (typeof value === "boolean") return value ? "true" : "false";
  return fallback;
}

export function PromptEvolutionProposalCard({
  preview,
  selectedAgentId,
  agentOptions,
  isLoading,
  isError,
  errorMessage,
  onAgentChange,
  onRefresh,
}: {
  preview: PromptEvolutionPreviewResponse | null;
  selectedAgentId: string;
  agentOptions: Array<{ value: string; label: string }>;
  isLoading: boolean;
  isError: boolean;
  errorMessage?: string | null;
  onAgentChange: (agentId: string) => void;
  onRefresh: () => void;
}) {
  const proposal = preview?.proposal;
  const proposalDetail = proposal?.prompt_update_proposal;
  const failurePatterns = proposal?.failure_patterns ?? [];
  const inputRefs = preview?.input_refs;
  const testCaseCount = proposalDetail?.test_cases?.length ?? 0;

  return (
    <FACard
      title="PromptEvolution 提案预览"
      eyebrow="只读治理"
      description="从现有 AgentOutput、PromptFeedback 和 ReviewGate findings 生成可审核提案，不写入生产 Prompt。"
      accent="info"
      action={(
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={selectedAgentId}
            onChange={(event) => onAgentChange(event.target.value)}
            className="h-8 rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-card-inner)] px-2 text-[length:var(--type-label)] text-[var(--fg-2)]"
            aria-label="选择 PromptEvolution 目标 Agent"
          >
            {agentOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          <button type="button" onClick={onRefresh} className="fa-workspace-toolbar-button">
            刷新提案
          </button>
        </div>
      )}
      bodyClassName="space-y-3"
    >
      {isError ? (
        <div className="rounded-[var(--radius-md)] border border-[var(--warn-border)] bg-[var(--warn-soft)] px-3 py-2 text-[length:var(--type-body-sm)] text-[var(--warn)]">
          {errorMessage ?? "无法加载 PromptEvolution 提案预览"}
        </div>
      ) : null}

      <div className="flex flex-wrap items-center gap-2">
        <FAStatusPill tone={preview?.proposal_only ? "info" : "warn"}>{preview?.proposal_only ? "proposal_only" : "未确认只读"}</FAStatusPill>
        <FAStatusPill tone={preview && preview.writes.length === 0 ? "up" : "warn"}>writes {preview?.writes.length ?? "?"}</FAStatusPill>
        <FAStatusPill tone={booleanTone(proposal?.manual_review_required)}>人工复核</FAStatusPill>
        {isLoading ? <FAStatusPill tone="dim">加载中</FAStatusPill> : null}
      </div>

      <div className="grid gap-3 lg:grid-cols-[1.15fr_0.85fr]">
        <div className="min-w-0 rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
          <div className="fa-label text-[var(--fg-4)]">问题摘要</div>
          <p className="mt-2 text-[length:var(--type-body)] leading-6 text-[var(--fg-2)]">
            {formatProposalValue(proposal?.problem_summary, isLoading ? "正在生成预览..." : "暂无足够证据生成提案。")}
          </p>
          <div className="mt-3 grid gap-2 sm:grid-cols-3">
            <div>
              <div className="fa-compact-label text-[var(--fg-5)]">proposal_type</div>
              <div className="mt-1 text-[length:var(--type-label)] text-[var(--fg-2)]">
                {formatProposalValue(proposalDetail?.proposal_type)}
              </div>
            </div>
            <div>
              <div className="fa-compact-label text-[var(--fg-5)]">failure_patterns</div>
              <div className="fa-num mt-1 text-[length:var(--type-card-title)] text-[var(--fg-2)]">{failurePatterns.length}</div>
            </div>
            <div>
              <div className="fa-compact-label text-[var(--fg-5)]">test_cases</div>
              <div className="fa-num mt-1 text-[length:var(--type-card-title)] text-[var(--fg-2)]">{testCaseCount}</div>
            </div>
          </div>
        </div>

        <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
          <div className="fa-label text-[var(--fg-4)]">证据输入</div>
          <div className="mt-2 grid grid-cols-3 gap-2">
            <div>
              <div className="fa-num text-[length:var(--type-card-title)] text-[var(--fg-2)]">{preview?.recent_run_count ?? 0}</div>
              <div className="fa-compact-label text-[var(--fg-5)]">AgentOutput</div>
            </div>
            <div>
              <div className="fa-num text-[length:var(--type-card-title)] text-[var(--fg-2)]">{preview?.feedback_count ?? 0}</div>
              <div className="fa-compact-label text-[var(--fg-5)]">Feedback</div>
            </div>
            <div>
              <div className="fa-num text-[length:var(--type-card-title)] text-[var(--fg-2)]">{preview?.review_gate_finding_count ?? 0}</div>
              <div className="fa-compact-label text-[var(--fg-5)]">Review</div>
            </div>
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            <FAStatusPill tone={booleanTone(proposal?.requires_schema_change)}>schema</FAStatusPill>
            <FAStatusPill tone={booleanTone(proposal?.requires_data_source_change)}>data_source</FAStatusPill>
            <FAStatusPill tone={booleanTone(proposal?.requires_dag_change)}>dag</FAStatusPill>
          </div>
          <div className="mt-3 text-[length:var(--type-caption)] leading-5 text-[var(--fg-4)]">
            prompt: {preview?.current_prompt_source ?? "unknown"} · refs: {inputRefs?.agent_output_ids.length ?? 0}/
            {inputRefs?.feedback_ids.length ?? 0}/{inputRefs?.review_ids.length ?? 0}
          </div>
        </div>
      </div>

      {proposalDetail?.patch ? (
        <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-panel)] p-3">
          <div className="fa-label text-[var(--fg-4)]">建议补丁</div>
          <p className="mt-2 max-h-[120px] overflow-y-auto whitespace-pre-wrap text-[length:var(--type-body-sm)] leading-6 text-[var(--fg-2)]">
            {proposalDetail.patch}
          </p>
        </div>
      ) : null}
    </FACard>
  );
}
