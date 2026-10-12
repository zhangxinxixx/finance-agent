import { Link } from "react-router-dom";
import { FACard } from "@/components/shared/FACard";
import { FASourceTraceBadge } from "@/components/shared/FASourceTraceBadge";
import { EvidenceRecordActions } from "@/components/shared/EvidenceRecordActions";
import { FAStatusPill, type FAStatusTone } from "@/components/shared/FAStatusPill";
import { getStatusTone } from "@/components/shared/statusMeta";
import { formatDateTime } from "@/lib/date";
import type { TaskReviewViewModel } from "@/types/agent-task";
import type { ReviewActionKind } from "@/adapters/agentTasks";
import type { OrchestrationManualReviewAction, OrchestrationManualReviewItem } from "@/adapters/orchestration";
import type { SystemEvolutionProposalAction } from "@/adapters/systemEvolution";
import type { PromptEvolutionPreviewResponse } from "@/types/agent-registry";
import type {
  PromptEvolutionReleaseAction,
  PromptEvolutionReleaseRecord,
  PromptEvolutionReviewResponse,
} from "@/types/prompt-evolution";
import type { SystemEvolutionProposal, SystemEvolutionReviewResponse } from "@/types/system-evolution";
import { evidenceLabel, operationFieldLabel, operationMainlineLabel, operationReadableLabel, operationReasonLabel, operationReviewLabel, operationStatusLabel } from "@/components/operations/operationsLabels";

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

const ORCHESTRATION_REVIEW_ACTIONS: Array<{ action: OrchestrationManualReviewAction; label: string }> = [
  { action: "acknowledged", label: "确认关注" },
  { action: "resolved", label: "标记解决" },
  { action: "dismissed", label: "忽略" },
];

const SYSTEM_EVOLUTION_ACTIONS: Array<{ action: SystemEvolutionProposalAction; label: string }> = [
  { action: "approve", label: "批准" },
  { action: "reject", label: "拒绝" },
  { action: "link_issue", label: "关联 Issue" },
  { action: "link_pr", label: "关联 PR" },
  { action: "mark_implemented", label: "标记已实施" },
  { action: "mark_rolled_back", label: "标记回滚" },
];

const PROMPT_EVOLUTION_RELEASE_ACTIONS: Array<{ action: PromptEvolutionReleaseAction; label: string }> = [
  { action: "release_approved", label: "记录发布批准" },
  { action: "rolled_back", label: "记录回滚" },
];

function reviewActionLabel(value: string | null | undefined): string {
  const labels: Record<string, string> = {
    approve: "通过",
    reject: "驳回",
    rerun: "重新运行",
    use_fallback: "采用备用结果",
  };
  return value ? labels[value] ?? operationReviewLabel(value) : "待处理";
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
            <span className="text-[10px] text-[var(--fg-5)]">复核记录已登记</span>
            {isFactReviewIssue ? <FAStatusPill tone="info">事实审查</FAStatusPill> : null}
            <FAStatusPill tone={statusTone(review.status)}>{operationStatusLabel(review.status)}</FAStatusPill>
            <FAStatusPill tone={severityTone(review.severity)}>{operationReviewLabel(review.severity)}</FAStatusPill>
          </div>
          <h2 className="mt-2 text-[13px] font-semibold text-[var(--fg-2)]">{operationMainlineLabel(review.source_module)}</h2>
          <p className="mt-2 max-w-3xl text-[12px] leading-6 text-[var(--fg-3)]">{review.reason}</p>
        </div>
        <div className="text-right text-[10px] text-[var(--fg-5)]">
          <div>{review.created_at ? formatDateTime(review.created_at) : "创建时间不可用"}</div>
          <div className="mt-1 font-mono">{review.run_id ? evidenceLabel(review.run_id) : "运行标识未提供"}</div>
          {review.action_status ? <div className="mt-1">{operationStatusLabel(review.action_status)}</div> : null}
        </div>
      </div>

      <div className="mt-3 grid gap-2 md:grid-cols-3">
        <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
          <div className="text-[9px] uppercase tracking-[0.1em] text-[var(--fg-5)]">来源步骤</div>
          <div className="mt-1 text-[10px] text-[var(--fg-3)]">{review.source_step_id ? "步骤记录已登记" : "未提供"}</div>
        </div>
        <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
          <div className="text-[9px] tracking-[0.1em] text-[var(--fg-5)]">关联主张</div>
          <div className="mt-1 font-mono text-[10px] text-[var(--fg-3)]">{review.claim_id ? evidenceLabel(review.claim_id) : "—"}</div>
        </div>
        <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
          <div className="text-[9px] uppercase tracking-[0.1em] text-[var(--fg-5)]">建议动作</div>
          <div className="mt-1 text-[10px] text-[var(--fg-3)]">{review.suggested_action ? reviewActionLabel(review.suggested_action) : "只读复核，暂无建议动作"}</div>
        </div>
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        <FASourceTraceBadge source="运行记录已登记" status="运行标识" tone="info" />
        {review.agent_output_id ? (
          <FASourceTraceBadge source="分析产物已登记" status="分析产物" tone="dim" />
        ) : null}
        {review.impact_modules.map((module) => (
          <FASourceTraceBadge key={`${review.review_id}-${module}`} source={operationMainlineLabel(module)} status="影响模块" tone="warn" />
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
                报告记录 · {evidenceLabel(reportId)}
              </Link>
            ))}
          </div>
        </div>
      ) : null}

      {review.source_refs.length > 0 ? (
        <div className="mt-3">
          <div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.1em] text-[var(--fg-5)]">事实审查溯源</div>
          <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
            <div className="text-[10px] text-[var(--fg-4)]">{review.source_refs.length} 条来源记录已登记，详情可复制核对。</div>
            <div className="mt-2"><EvidenceRecordActions record={review.source_refs} label="来源引用依据" /></div>
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
                  {operationFieldLabel(artifact.artifact_type || "artifact_type")}：已登记，可展开回查
                </span>
              ))}
            </div>
          </div>
        </div>
      ) : null}

      <div className="mt-3 border-t border-[var(--border-faint)] pt-3">
        <EvidenceRecordActions record={review} label="复核依据记录" />
      </div>
    </article>
  );
}

function factSummary(facts: Record<string, unknown>): string {
  const blockedOutputs = facts.blocked_outputs;
  if (Array.isArray(blockedOutputs) && blockedOutputs.length > 0) {
    return `${blockedOutputs.length} 项输出受阻，详情可复制依据记录`;
  }
  const entries = Object.entries(facts).filter(([, value]) => value !== null && value !== undefined);
  return entries.length ? `${entries.length} 项事实已登记，详情可复制依据记录` : "暂无事实依据";
}

export function OrchestrationManualReviewCard({
  item,
  onAction,
  actionDedupeKey,
}: {
  item: OrchestrationManualReviewItem;
  onAction?: (item: OrchestrationManualReviewItem, action: OrchestrationManualReviewAction) => void;
  actionDedupeKey?: string | null;
}) {
  const isOpen = item.action_status === "open";
  const isActing = actionDedupeKey === item.dedupe_key;

  return (
    <article className="rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card)] p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[10px] text-[var(--fg-5)]">编排记录已登记</span>
            <FAStatusPill tone="info">自动编排</FAStatusPill>
            <FAStatusPill tone={statusTone(item.status ?? "unknown")}>{operationStatusLabel(item.status)}</FAStatusPill>
            <FAStatusPill tone={isOpen ? "warn" : "up"}>{operationStatusLabel(item.action_status)}</FAStatusPill>
          </div>
          <h2 className="mt-2 text-[13px] font-semibold text-[var(--fg-2)]">{item.kind || item.trigger ? operationReasonLabel(item.kind ?? item.trigger) : "自动编排事件待确认"}</h2>
          <p className="mt-2 max-w-3xl text-[12px] leading-6 text-[var(--fg-3)]">{item.reason ?? "—"}</p>
        </div>
        <div className="text-right text-[10px] text-[var(--fg-5)]">
          <div>工作流标识已登记</div>
          {item.action_recorded_at ? <div className="mt-1">{formatDateTime(item.action_recorded_at)}</div> : null}
          {item.action_actor ? <div className="mt-1">操作人已登记</div> : null}
        </div>
      </div>

      <div className="mt-3 grid gap-2 md:grid-cols-3">
        <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
          <div className="text-[9px] tracking-[0.1em] text-[var(--fg-5)]">触发条件</div>
          <div className="mt-1 text-[10px] text-[var(--fg-3)]">{item.trigger ? operationReasonLabel(item.trigger) : "触发条件未提供"}</div>
        </div>
        <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
          <div className="text-[9px] tracking-[0.1em] text-[var(--fg-5)]">工作流标识</div>
          <div className="mt-1 text-[10px] text-[var(--fg-3)]">工作流记录已登记</div>
        </div>
        <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
          <div className="text-[9px] tracking-[0.1em] text-[var(--fg-5)]">事实依据</div>
          <div className="mt-1 line-clamp-2 text-[10px] text-[var(--fg-3)]">{factSummary(item.facts)}</div>
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-3 py-2">
        <div className="min-w-0 text-[10px] leading-4 text-[var(--fg-4)]">
          <span className="font-semibold text-[var(--fg-5)]">处理结果：</span>
          {item.action_status === "open" ? "待处理" : `${operationStatusLabel(item.action_status)}${item.action_note ? ` · ${item.action_note}` : ""}`}
        </div>
        <div className="flex flex-wrap gap-1.5">
          {ORCHESTRATION_REVIEW_ACTIONS.map((action) => (
            <button
              key={action.action}
              type="button"
              disabled={!isOpen || isActing || !onAction}
              onClick={() => onAction?.(item, action.action)}
              className="inline-flex h-7 items-center rounded-[var(--radius-sm)] border border-[var(--border)] bg-[var(--bg-card)] px-2 text-[10px] font-semibold text-[var(--fg-3)] transition hover:border-[var(--border-strong)] hover:text-[var(--fg-1)] disabled:cursor-not-allowed disabled:opacity-45"
            >
              {isActing ? "处理中" : action.label}
            </button>
          ))}
        </div>
      </div>
      <div className="mt-3 border-t border-[var(--border-faint)] pt-3">
        <EvidenceRecordActions record={item} label="编排事实依据" />
      </div>
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
      action={<FAStatusPill tone={source === "api" ? "up" : "warn"}>{source === "api" ? "接口结果" : "来源待确认"}</FAStatusPill>}
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
  if (typeof value === "boolean") return value ? "是" : "否";
  return fallback;
}

function readableNarrative(value: unknown, fallback = "说明已登记"): string {
  if (typeof value !== "string" || !value.trim()) return fallback;
  // Error responses can contain Chinese framing words while still exposing a
  // machine endpoint. Keep that detail in the evidence copy action only.
  if (/(?:\/api\/|https?:\/\/|\/(?:home|tmp|var|mnt)\/|(?:schema|snapshot|run|result|receipt|endpoint)[_-]?id)\S*/i.test(value)) {
    return fallback;
  }
  return /[\u3400-\u9fff]/.test(value) ? value : fallback;
}

function firstItems<T>(items: T[] | undefined, count = 3): T[] {
  return Array.isArray(items) ? items.slice(0, count) : [];
}

function proposalTitle(proposal: SystemEvolutionProposal): string {
  return readableNarrative(proposal.title, "系统演进提案已登记");
}

function releaseRecordTitle(record: PromptEvolutionReleaseRecord): string {
  if (record.action === "release_approved") return "发布批准记录";
  if (record.action === "rolled_back") return "回滚记录";
  return "发布记录已登记";
}

export function PromptEvolutionValidationCard({
  review,
  isLoading,
  isError,
  errorMessage,
  actionKind,
  actionError,
  onReleaseAction,
  onRefresh,
}: {
  review: PromptEvolutionReviewResponse | null;
  isLoading: boolean;
  isError: boolean;
  errorMessage?: string | null;
  actionKind?: PromptEvolutionReleaseAction | null;
  actionError?: Error | null;
  onReleaseAction?: (
    action: PromptEvolutionReleaseAction,
    params?: {
      rollbackReason?: string | null;
      testResult?: string | null;
    },
  ) => void;
  onRefresh: () => void;
}) {
  const validation = review?.validation;
  const validationStatus = validation?.validation_status ?? "unknown";
  const releaseRecords = review?.release_records.items ?? [];
  const releaseReadiness = review?.release_readiness;
  const cases = review?.cases.items ?? [];
  const activatedPrompt = Boolean(validation?.activated_prompt);
  const releaseActionDisabled = !onReleaseAction || isLoading || isError || !review?.trade_date;

  return (
    <FACard
      title="提示内容 A/B 验证"
      eyebrow="只读提示治理"
      description="展示提示评估样本、A/B 验证和发布/回滚记录；页面只读，不激活生产提示内容。"
      accent={validationStatus === "pass" ? "info" : "warn"}
      action={(
        <button type="button" onClick={onRefresh} className="fa-workspace-toolbar-button">
          刷新提示词验证
        </button>
      )}
      bodyClassName="space-y-3"
    >
      {isError ? (
        <div className="rounded-[var(--radius-md)] border border-[var(--warn-border)] bg-[var(--warn-soft)] px-3 py-2 text-[length:var(--type-body-sm)] text-[var(--warn)]">
          {readableNarrative(errorMessage, "提示内容验证暂时无法读取")}
          {errorMessage ? <div className="mt-2"><EvidenceRecordActions record={{ error: errorMessage }} label="验证错误依据" /></div> : null}
        </div>
      ) : null}
      {actionError ? (
        <div className="rounded-[var(--radius-md)] border border-[var(--warn-border)] bg-[var(--warn-soft)] px-3 py-2 text-[length:var(--type-body-sm)] text-[var(--warn)]">
          操作暂未完成，请稍后复核。
          <div className="mt-2"><EvidenceRecordActions record={actionError} label="操作错误依据" /></div>
        </div>
      ) : null}

      <div className="flex flex-wrap items-center gap-2">
        <FAStatusPill tone={statusTone(validationStatus)}>{operationStatusLabel(validationStatus)}</FAStatusPill>
        <FAStatusPill tone={validation?.proposal_only ? "info" : "warn"}>{validation?.proposal_only ? "仅提案，不写入" : "只读状态待确认"}</FAStatusPill>
        <FAStatusPill tone={activatedPrompt ? "warn" : "up"}>{activatedPrompt ? "已激活（需关注）" : "未激活"}</FAStatusPill>
        <FAStatusPill tone={(validation?.regression_count ?? 0) > 0 ? "warn" : "dim"}>回归问题 {validation?.regression_count ?? 0}</FAStatusPill>
        <FAStatusPill tone={(validation?.improvement_count ?? 0) > 0 ? "info" : "dim"}>改进项 {validation?.improvement_count ?? 0}</FAStatusPill>
        <FAStatusPill tone={releaseReadiness?.status === "approved" ? "up" : releaseReadiness?.status === "blocked" ? "warn" : "info"}>
          发布状态 {operationStatusLabel(releaseReadiness?.status)}
        </FAStatusPill>
        {isLoading ? <FAStatusPill tone="dim">加载中</FAStatusPill> : null}
      </div>

      {releaseReadiness?.blocking_reasons?.length ? (
        <div className="rounded-[var(--radius-md)] border border-[var(--warn-border)] bg-[var(--warn-soft)] px-3 py-2 text-[length:var(--type-body-sm)] text-[var(--warn)]">
          发布仍有 {releaseReadiness.blocking_reasons.length} 项阻断原因，详情可复制依据记录。
          <div className="mt-2"><EvidenceRecordActions record={releaseReadiness.blocking_reasons} label="发布阻断依据" /></div>
        </div>
      ) : null}

      <div className="grid gap-3 lg:grid-cols-[0.85fr_1.15fr]">
        <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
          <div className="fa-label text-[var(--fg-4)]">评估样本</div>
          <div className="mt-2 grid grid-cols-2 gap-2">
            <div>
              <div className="fa-num text-[length:var(--type-card-title)] text-[var(--fg-2)]">{review?.cases.count ?? 0}</div>
              <div className="fa-compact-label text-[var(--fg-5)]">评估样本</div>
            </div>
            <div>
              <div className="fa-num text-[length:var(--type-card-title)] text-[var(--fg-2)]">{review?.trade_date || "—"}</div>
              <div className="fa-compact-label text-[var(--fg-5)]">交易日</div>
            </div>
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            {firstItems(cases, 5).map((item) => (
              <FASourceTraceBadge key={item.case_id ?? item.case_type ?? "case"} source={operationReadableLabel(item.case_type, "评估样本已登记")} status={operationReadableLabel(item.created_from, "来源已登记")} tone="info" />
            ))}
          </div>
          <div className="mt-3 space-y-1 text-[length:var(--type-caption)] leading-5 text-[var(--fg-4)]">
            <div>评估样本：{review?.artifacts.prompt_evaluation_cases ? "已登记" : "未提供"}</div>
            <div>验证结果：{review?.artifacts.prompt_ab_validation_result ? "已登记" : "未提供"}</div>
            <div>发布记录：{review?.artifacts.prompt_release_records ? "已登记" : "未提供"}</div>
          </div>
          {review?.artifacts ? <div className="mt-2"><EvidenceRecordActions record={review.artifacts} label="验证产物依据" /></div> : null}
        </div>

        <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
          <div className="fa-label text-[var(--fg-4)]">发布记录</div>
          <div className="mt-2 flex flex-wrap gap-2">
            {PROMPT_EVOLUTION_RELEASE_ACTIONS.map((item) => {
              const isActing = actionKind === item.action;
              const readinessAllowsAction = item.action === "release_approved"
                ? Boolean(releaseReadiness?.can_request_release_approval)
                : Boolean(releaseReadiness?.can_record_rollback);
              return (
                <button
                  key={item.action}
                  type="button"
                  disabled={releaseActionDisabled || isActing || !readinessAllowsAction}
                  onClick={() => {
                    if (item.action === "rolled_back") {
                      const rollbackReason = window.prompt("Rollback reason", releaseRecords[0]?.rollback_reason ?? "");
                      if (!rollbackReason) return;
                      onReleaseAction?.(item.action, { rollbackReason });
                      return;
                    }
                    onReleaseAction?.(item.action, { testResult: validationStatus });
                  }}
                  className="inline-flex h-7 items-center rounded-[var(--radius-sm)] border border-[var(--border)] bg-[var(--bg-card)] px-2 text-[length:var(--type-label)] font-semibold text-[var(--fg-3)] transition hover:border-[var(--border-strong)] hover:text-[var(--fg-1)] disabled:cursor-not-allowed disabled:opacity-45"
                >
                  {isActing ? "处理中" : item.label}
                </button>
              );
            })}
          </div>
          <div className="mt-2 space-y-2">
            {firstItems(releaseRecords, 3).map((record) => (
              <div key={`${record.recorded_at ?? releaseRecordTitle(record)}-${record.action ?? "record"}`} className="rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-panel)] p-2">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-[length:var(--type-label)] font-semibold text-[var(--fg-2)]">{releaseRecordTitle(record)}</span>
                  <FAStatusPill tone={record.action === "rolled_back" ? "warn" : "info"}>{record.agent_name ? "代理已登记" : "代理未提供"}</FAStatusPill>
                  <FAStatusPill tone={record.activated_prompt ? "warn" : "up"}>{record.activated_prompt ? "已激活（需关注）" : "仅登记记录"}</FAStatusPill>
                </div>
                <p className="mt-1 text-[length:var(--type-body-sm)] leading-5 text-[var(--fg-4)]">
                  {readableNarrative(record.rollback_reason || record.test_result || record.validation_artifact, "发布说明已登记")}
                </p>
                {record.rolled_back_from || record.rolled_back_to || record.affected_agents?.length ? (
                  <div className="mt-1 flex flex-wrap gap-2 text-[length:var(--type-caption)] text-[var(--fg-muted)]">
                    {record.rolled_back_from ? <span>回滚前：{evidenceLabel(record.rolled_back_from)}</span> : null}
                    {record.rolled_back_to ? <span>回滚后：{evidenceLabel(record.rolled_back_to)}</span> : null}
                    {record.affected_agents?.length ? <span>受影响代理：{record.affected_agents.length} 个</span> : null}
                  </div>
                ) : null}
                <div className="mt-2"><EvidenceRecordActions record={record} label="发布记录依据" /></div>
              </div>
            ))}
            {releaseRecords.length === 0 ? (
              <div className="rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-panel)] p-2 text-[length:var(--type-body-sm)] text-[var(--fg-4)]">
                {isLoading ? "正在加载提示内容发布记录…" : "当前没有提示内容发布或回滚记录。"}
              </div>
            ) : null}
          </div>
        </div>
      </div>
    </FACard>
  );
}

export function SystemEvolutionProposalCard({
  review,
  isLoading,
  isError,
  errorMessage,
  actionProposalId,
  onProposalAction,
  onRefresh,
}: {
  review: SystemEvolutionReviewResponse | null;
  isLoading: boolean;
  isError: boolean;
  errorMessage?: string | null;
  actionProposalId?: string | null;
  onProposalAction?: (
    proposal: SystemEvolutionProposal,
    action: SystemEvolutionProposalAction,
    params?: {
      issueUrl?: string | null;
      prUrl?: string | null;
      testResult?: string | null;
      manualConfirmation?: string | null;
      rollbackReason?: string | null;
      note?: string | null;
    },
  ) => void;
  onRefresh: () => void;
}) {
  const reviewStatus = review?.review.review_status ?? "unknown";
  const blocked = Boolean(review?.review.blocked);
  const proposals = review?.proposals.items ?? [];
  const findings = review?.findings.items ?? [];
  const requiredFollowups = review?.review.required_followups ?? [];

  return (
    <FACard
      title="系统演进提案"
      eyebrow="只读系统治理"
      description="承接系统演进发现与改进提案，用于人工复核系统演进风险，不直接修改代码、提示内容或数据。"
      accent={blocked ? "warn" : "info"}
      action={(
        <button type="button" onClick={onRefresh} className="fa-workspace-toolbar-button">
          刷新系统演进
        </button>
      )}
      bodyClassName="space-y-3"
    >
      {isError ? (
        <div className="rounded-[var(--radius-md)] border border-[var(--warn-border)] bg-[var(--warn-soft)] px-3 py-2 text-[length:var(--type-body-sm)] text-[var(--warn)]">
          {readableNarrative(errorMessage, "系统演进复核暂时无法读取")}
          {errorMessage ? <div className="mt-2"><EvidenceRecordActions record={{ error: errorMessage }} label="系统复核错误依据" /></div> : null}
        </div>
      ) : null}

      <div className="flex flex-wrap items-center gap-2">
        <FAStatusPill tone={statusTone(reviewStatus)}>{operationStatusLabel(reviewStatus)}</FAStatusPill>
        <FAStatusPill tone={blocked ? "warn" : "up"}>{blocked ? "存在阻断" : "未发现阻断"}</FAStatusPill>
        <FAStatusPill tone={proposals.length > 0 ? "info" : "dim"}>改进提案 {review?.proposals.count ?? 0}</FAStatusPill>
        <FAStatusPill tone={findings.length > 0 ? "warn" : "dim"}>发现项 {review?.findings.count ?? 0}</FAStatusPill>
        {isLoading ? <FAStatusPill tone="dim">加载中</FAStatusPill> : null}
      </div>

      <div className="grid gap-3 lg:grid-cols-[1.15fr_0.85fr]">
        <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
          <div className="fa-label text-[var(--fg-4)]">待复核提案</div>
          <div className="mt-2 space-y-2">
            {firstItems(proposals, 3).map((proposal) => (
              <div key={proposal.proposal_id ?? proposalTitle(proposal)} className="rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-panel)] p-2">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-[length:var(--type-label)] font-semibold text-[var(--fg-2)]">{proposalTitle(proposal)}</span>
                  <FAStatusPill tone={statusTone(proposal.status ?? "pending_review")}>{operationStatusLabel(proposal.status ?? "pending_review")}</FAStatusPill>
                  {proposal.review_actor ? <FAStatusPill tone="dim">复核人已登记</FAStatusPill> : null}
                </div>
                <p className="mt-1 text-[length:var(--type-body-sm)] leading-5 text-[var(--fg-4)]">
                  {readableNarrative(proposal.rationale, "提案理由已登记")}
                </p>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {firstItems(proposal.finding_codes, 4).map((code) => (
                    <FASourceTraceBadge key={`${proposal.proposal_id}-${code}`} source={operationReasonLabel(code)} status="发现项" tone="warn" />
                  ))}
                </div>
                <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
                    <div className="min-w-0 text-[length:var(--type-caption)] leading-5 text-[var(--fg-5)]">
                      {proposal.linked_issue ? "Issue 已登记" : "未关联 Issue"} · {proposal.linked_pr ? "PR 已登记" : "未关联 PR"}
                      {proposal.test_result ? " · 测试结果已登记" : ""}
                      {proposal.rollback_reason ? " · 回滚说明已登记" : ""}
                    </div>
                  <div className="flex flex-wrap gap-1.5">
                    {SYSTEM_EVOLUTION_ACTIONS.map((item) => {
                      const isActing = actionProposalId === proposal.proposal_id;
                      return (
                        <button
                          key={item.action}
                          type="button"
                          disabled={isActing || !onProposalAction}
                          onClick={() => {
                            if (item.action === "link_issue") {
                              const issueUrl = window.prompt("Issue URL", proposal.linked_issue ?? "");
                              if (!issueUrl) return;
                              onProposalAction?.(proposal, item.action, { issueUrl });
                              return;
                            }
                            if (item.action === "link_pr") {
                              const prUrl = window.prompt("PR URL", proposal.linked_pr ?? "");
                              if (!prUrl) return;
                              onProposalAction?.(proposal, item.action, { prUrl });
                              return;
                            }
                            if (item.action === "mark_implemented") {
                              const testResult = window.prompt("Test result", proposal.test_result ?? "");
                              if (testResult) {
                                onProposalAction?.(proposal, item.action, { testResult });
                                return;
                              }
                              if (window.confirm("Confirm implemented without a test result?")) {
                                onProposalAction?.(proposal, item.action, { manualConfirmation: "review_center_manual_confirmation" });
                              }
                              return;
                            }
                            if (item.action === "mark_rolled_back") {
                              const rollbackReason = window.prompt("Rollback reason", proposal.rollback_reason ?? "");
                              if (!rollbackReason) return;
                              onProposalAction?.(proposal, item.action, { rollbackReason });
                              return;
                            }
                            onProposalAction?.(proposal, item.action);
                          }}
                          className="inline-flex h-7 items-center rounded-[var(--radius-sm)] border border-[var(--border)] bg-[var(--bg-card)] px-2 text-[10px] font-semibold text-[var(--fg-3)] transition hover:border-[var(--border-strong)] hover:text-[var(--fg-1)] disabled:cursor-not-allowed disabled:opacity-45"
                        >
                          {isActing ? "处理中" : item.label}
                        </button>
                      );
                    })}
                  </div>
                  <div className="mt-2"><EvidenceRecordActions record={proposal} label="系统演进提案依据" /></div>
                </div>
              </div>
            ))}
            {proposals.length === 0 ? (
              <div className="rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-panel)] p-2 text-[length:var(--type-body-sm)] text-[var(--fg-4)]">
                {isLoading ? "正在加载系统演进提案…" : "当前没有待复核系统演进提案。"}
              </div>
            ) : null}
          </div>
        </div>

        <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
          <div className="fa-label text-[var(--fg-4)]">阻断与产物</div>
          <div className="mt-2 grid grid-cols-2 gap-2">
            <div>
              <div className="fa-num text-[length:var(--type-card-title)] text-[var(--fg-2)]">{requiredFollowups.length}</div>
              <div className="fa-compact-label text-[var(--fg-5)]">待跟进项</div>
            </div>
            <div>
              <div className="fa-num text-[length:var(--type-card-title)] text-[var(--fg-2)]">{review?.trade_date || "—"}</div>
              <div className="fa-compact-label text-[var(--fg-5)]">交易日</div>
            </div>
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            {firstItems(requiredFollowups, 5).map((item) => (
              <FASourceTraceBadge key={item} source={operationReasonLabel(item)} status="待跟进" tone="warn" />
            ))}
          </div>
          <div className="mt-3 space-y-1 text-[length:var(--type-caption)] leading-5 text-[var(--fg-4)]">
            <div>发现项：{review?.artifacts.findings ? "已登记" : "未提供"}</div>
            <div>改进提案：{review?.artifacts.improvement_proposals ? "已登记" : "未提供"}</div>
            <div>复核记录：{review?.artifacts.review ? "已登记" : "未提供"}</div>
          </div>
          {review?.artifacts ? <div className="mt-2"><EvidenceRecordActions record={review.artifacts} label="系统演进产物依据" /></div> : null}
        </div>
      </div>
    </FACard>
  );
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
      title="提示内容改进提案预览"
      eyebrow="只读治理"
      description="从现有分析输出、人工反馈和质量门控发现生成可审核提案，不写入生产提示内容。"
      accent="info"
      action={(
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={selectedAgentId}
            onChange={(event) => onAgentChange(event.target.value)}
            className="h-8 rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-card-inner)] px-2 text-[length:var(--type-label)] text-[var(--fg-2)]"
            aria-label="选择提示内容改进目标代理"
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
          {readableNarrative(errorMessage, "提示内容改进提案暂时无法读取")}
          {errorMessage ? <div className="mt-2"><EvidenceRecordActions record={{ error: errorMessage }} label="提案错误依据" /></div> : null}
        </div>
      ) : null}

      <div className="flex flex-wrap items-center gap-2">
        <FAStatusPill tone={preview?.proposal_only ? "info" : "warn"}>{preview?.proposal_only ? "仅提案，不写入" : "只读状态待确认"}</FAStatusPill>
        <FAStatusPill tone={preview && preview.writes.length === 0 ? "up" : "warn"}>写入动作 {preview?.writes.length ?? "待确认"}</FAStatusPill>
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
              <div className="fa-compact-label text-[var(--fg-5)]">提案类型</div>
              <div className="mt-1 text-[length:var(--type-label)] text-[var(--fg-2)]">
                {operationReasonLabel(proposalDetail?.proposal_type)}
              </div>
            </div>
            <div>
              <div className="fa-compact-label text-[var(--fg-5)]">失败模式</div>
              <div className="fa-num mt-1 text-[length:var(--type-card-title)] text-[var(--fg-2)]">{failurePatterns.length}</div>
            </div>
            <div>
              <div className="fa-compact-label text-[var(--fg-5)]">测试用例</div>
              <div className="fa-num mt-1 text-[length:var(--type-card-title)] text-[var(--fg-2)]">{testCaseCount}</div>
            </div>
          </div>
        </div>

        <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
          <div className="fa-label text-[var(--fg-4)]">证据输入</div>
          <div className="mt-2 grid grid-cols-3 gap-2">
            <div>
              <div className="fa-num text-[length:var(--type-card-title)] text-[var(--fg-2)]">{preview?.recent_run_count ?? 0}</div>
              <div className="fa-compact-label text-[var(--fg-5)]">分析输出</div>
            </div>
            <div>
              <div className="fa-num text-[length:var(--type-card-title)] text-[var(--fg-2)]">{preview?.feedback_count ?? 0}</div>
              <div className="fa-compact-label text-[var(--fg-5)]">反馈</div>
            </div>
            <div>
              <div className="fa-num text-[length:var(--type-card-title)] text-[var(--fg-2)]">{preview?.review_gate_finding_count ?? 0}</div>
              <div className="fa-compact-label text-[var(--fg-5)]">复核发现</div>
            </div>
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            <FAStatusPill tone={booleanTone(proposal?.requires_schema_change)}>需要改数据结构</FAStatusPill>
            <FAStatusPill tone={booleanTone(proposal?.requires_data_source_change)}>需要改数据源</FAStatusPill>
            <FAStatusPill tone={booleanTone(proposal?.requires_dag_change)}>需要改流程图</FAStatusPill>
          </div>
          <div className="mt-3 text-[length:var(--type-caption)] leading-5 text-[var(--fg-4)]">
            提示来源：{preview?.current_prompt_source ? "已登记" : "未提供"} · 证据数量：{inputRefs?.agent_output_ids.length ?? 0}/
            {inputRefs?.feedback_ids.length ?? 0}/{inputRefs?.review_ids.length ?? 0}
          </div>
        </div>
      </div>

      {proposalDetail?.patch ? (
        <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-panel)] p-3">
          <div className="fa-label text-[var(--fg-4)]">建议补丁</div>
          <p className="mt-2 text-[length:var(--type-body-sm)] leading-6 text-[var(--fg-2)]">建议补丁已登记，可复制完整记录供技术复核。</p>
          <div className="mt-2"><EvidenceRecordActions record={proposalDetail.patch} label="建议补丁依据" /></div>
        </div>
      ) : null}
    </FACard>
  );
}
