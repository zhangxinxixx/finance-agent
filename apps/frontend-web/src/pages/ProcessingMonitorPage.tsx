import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { Link, useOutletContext, useSearchParams } from "react-router-dom";
import { ArrowRight, CircleX, Network, RefreshCw, Search, ShieldCheck, Workflow } from "lucide-react";

import {
  fetchProcessingOverview,
  fetchProcessingTrace,
  fetchProcessingTraceByChain,
  fetchProcessingTraceByEvent,
  fetchProcessingTraceByInput,
  fetchProcessingTraceByMainline,
  fetchProcessingTraceBySourceRef,
} from "@/adapters/processingMonitor";
import type { AppShellOutletContext } from "@/components/AppShell";
import { TraceDetailPanels } from "@/components/processing-monitor/TraceDetailPanels";
import { ErrorState } from "@/components/shared/ErrorState";
import { FACard } from "@/components/shared/FACard";
import { FAEmptyState } from "@/components/shared/FAEmptyState";
import { FAPageScaffold } from "@/components/shared/FAPageScaffold";
import { FAStatusPill, type FAStatusTone } from "@/components/shared/FAStatusPill";
import { HeaderBreadcrumb } from "@/components/shared/HeaderBreadcrumb";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";
import { EvidenceRecordActions } from "@/components/shared/EvidenceRecordActions";
import type {
  ProcessingOverviewResponse,
  ProcessingExecutionSummary,
  ProcessingQualityGate,
  ProcessingTraceMode,
  ProcessingTracePathNode,
  ProcessingTraceResponse,
} from "@/types/processing-monitor";
import {
  evidenceLabel,
  operationFieldLabel,
  operationMainlineLabel,
  operationReadableLabel,
  operationReasonLabel,
  operationStageLabel,
  operationStatusLabel,
} from "@/components/operations/operationsLabels";

const TRACE_MODE_OPTIONS: Array<{ value: ProcessingTraceMode; label: string; placeholder: string }> = [
  { value: "processing_trace_id", label: "加工链路标识", placeholder: "输入链路标识" },
  { value: "event_id", label: "事件标识", placeholder: "输入事件标识" },
  { value: "source_ref", label: "来源引用", placeholder: "输入来源引用" },
  { value: "input_id", label: "输入标识", placeholder: "输入数据标识" },
  { value: "mainline", label: "主线", placeholder: "输入主线名称或标识" },
  { value: "transmission_chain", label: "传导链", placeholder: "输入传导链标识" },
];

function statusTone(value: string | null | undefined): FAStatusTone {
  const normalized = (value ?? "").toLowerCase();
  if (["covered", "bound", "matched", "pass", "available", "ok", "complete", "ready", "success", "succeeded"].includes(normalized)) return "up";
  if (["partial", "degraded", "stale", "needs_review", "pending"].includes(normalized)) return "warn";
  if (["missing", "blocked", "not_found", "failed", "error", "unavailable"].includes(normalized)) return "down";
  return "neutral";
}

function statusLabel(value: string | null | undefined): string {
  const labels: Record<string, string> = {
    covered: "已覆盖",
    degraded: "降级",
    missing: "缺失",
    stale: "过期",
    pass: "通过",
    needs_review: "待复核",
    blocked: "阻塞",
    bound: "已绑定",
    matched: "已匹配",
    not_found: "未匹配",
    partial: "部分可用",
    unavailable: "不可用",
    ready: "就绪",
    success: "成功",
    succeeded: "成功",
    failed: "失败",
    observe: "观察等待",
    accepted: "已采用",
  };
  return labels[value ?? ""] ?? operationStatusLabel(value);
}

function fieldLabel(value: string): string {
  const labels: Record<string, string> = {
    news_input_count: "新闻输入",
    report_input_count: "报告输入",
    followup_count: "追问输入",
    article_brief_count: "文章摘要",
    source_ref_count: "来源引用",
    artifact_ref_count: "产物引用",
    without_source_ref_count: "缺少来源引用",
    source_freshness: "源新鲜度",
    feature_freshness: "特征新鲜度",
    analysis_freshness: "分析新鲜度",
    frontend_freshness: "前端绑定",
  };
  return labels[value] ?? operationFieldLabel(value);
}

function idLabel(value: string | null | undefined): string {
  return evidenceLabel(value, "未提供");
}

function dagFocusPath(nodeId: string | null | undefined): string {
  return `/scheduler?focus=${encodeURIComponent(nodeId || "gold_macro_overview")}`;
}

function preferredDagFocusPath(nodes: ProcessingTracePathNode[]): string {
  const preferredNodeIds = [
    "gold_macro_overview",
    "driver_decomposition",
    "transmission_chain_detection",
    "mainline_attribution",
    "event_flow_feature",
  ];
  const nodeIds = new Set(nodes.map((node) => node.node_id));
  return dagFocusPath(preferredNodeIds.find((nodeId) => nodeIds.has(nodeId)) ?? nodes[0]?.node_id);
}

function traceNodeRefSummary(node: ProcessingTracePathNode): string {
  const parts = [];
  if (node.source_ref_count > 0) parts.push(`来源 ${node.source_ref_count}`);
  if (node.artifact_ref_count > 0) parts.push(`产物 ${node.artifact_ref_count}`);
  return parts.length ? parts.join(" · ") : "无引用";
}

function traceNodeLabel(node: ProcessingTracePathNode): string {
  if (node.label && /[\u3400-\u9fff]/.test(node.label)) return node.label;
  return operationMainlineLabel(node.node_id);
}

function readableFreshnessValue(value: unknown): string {
  if (typeof value !== "string" || !value.trim()) return "状态尚未说明";
  if (/^\d{4}-\d{2}-\d{2}(?:[T ]|$)/.test(value)) return value;
  if (/[\u3400-\u9fff]/.test(value)) return value;
  return operationReadableLabel(value, "状态尚未说明");
}

function TracePathStrip({ nodes }: { nodes: ProcessingTracePathNode[] }) {
  if (!nodes.length) {
    return <FAEmptyState title="暂无路径节点" description="后端暂未返回加工链路路径。" />;
  }

  return (
    <div className="overflow-x-auto">
      <div className="flex min-w-max items-stretch gap-2">
        {nodes.map((node, index) => (
          <div key={`${node.node_id}-${index}`} className="flex items-center gap-2">
            <Link
              to={dagFocusPath(node.node_id)}
              className="w-[164px] rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-3 py-2 no-underline transition hover:border-[var(--info-border)] hover:bg-[var(--bg-hover)]"
            >
              <div className="truncate text-[11px] font-semibold text-[var(--fg-2)]">{traceNodeLabel(node)}</div>
              <div className="mt-1 flex items-center justify-between gap-2 text-[9px] uppercase text-[var(--fg-5)]">
                <span className="truncate">{operationStageLabel(node.stage)}</span>
                <span className="fa-num">#{index + 1}</span>
              </div>
              <div className="mt-2 flex items-center justify-between gap-2">
                <FAStatusPill tone={statusTone(node.status)} dot={false} className="px-1.5 py-0 text-[9px]">
                  {statusLabel(node.status)}
                </FAStatusPill>
                <span className="truncate text-[9px] text-[var(--fg-5)]">{traceNodeRefSummary(node)}</span>
              </div>
            </Link>
            {index < nodes.length - 1 ? <ArrowRight size={14} className="shrink-0 text-[var(--fg-5)]" /> : null}
          </div>
        ))}
      </div>
    </div>
  );
}

function SummaryMetric({ label, value, tone = "neutral" }: { label: string; value: string | number; tone?: FAStatusTone }) {
  return (
    <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
      <div className="text-[10px] font-semibold text-[var(--fg-5)]">{label}</div>
      <div className={`mt-1 fa-num text-[18px] font-semibold ${tone === "down" ? "text-[var(--down)]" : tone === "warn" ? "text-[var(--warn)]" : "text-[var(--fg-1)]"}`}>
        {value}
      </div>
    </div>
  );
}

function OverviewSummary({ overview }: { overview: ProcessingOverviewResponse }) {
  const coverage = overview.input_coverage;
  const coveredMainlines = overview.mainline_coverage.filter((item) => item.status === "covered").length;
  const missingMainlines = overview.mainline_coverage.filter((item) => item.status === "missing").length;
  const boundViews = overview.view_bindings.filter((item) => item.status === "bound").length;

  return (
    <div className="grid gap-3 md:grid-cols-4">
      <SummaryMetric label="主线覆盖" value={`${coveredMainlines}/${overview.mainline_coverage.length}`} tone={missingMainlines ? "warn" : "up"} />
      <SummaryMetric label="输入事件" value={coverage.news_input_count} />
    <SummaryMetric label="来源引用" value={coverage.source_ref_count} tone={coverage.without_source_ref_count ? "warn" : "up"} />
      <SummaryMetric label="视图绑定" value={`${boundViews}/${overview.view_bindings.length}`} tone={boundViews === overview.view_bindings.length ? "up" : "warn"} />
    </div>
  );
}

function artifactPaths(refs: ProcessingExecutionSummary["final_output"]["report_artifact_refs"]): string[] {
  return refs
    .map((ref) => ref.file_path || ref.path)
    .filter((path): path is string => typeof path === "string" && path.length > 0);
}

function outputModeLabel(mode: ProcessingExecutionSummary["final_output"]["mode"]): string {
  if (mode === "accepted") return "已采用";
  if (mode === "observe") return "观察等待";
  return "不可用";
}

function ArtifactPathList({ paths }: { paths: string[] }) {
  if (paths.length === 0) return <span>未登记</span>;
  return (
    <div className="rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-panel)] px-2 py-1">
      <div>{paths.length} 项最终输出已登记；页面不展示文件路径。</div>
    </div>
  );
}

function ExecutionSummaryPanel({ summary }: { summary: ProcessingExecutionSummary }) {
  const inputCount = Object.keys(summary.used_data.input_snapshot_ids).length;
  const reportPaths = artifactPaths(summary.final_output.report_artifact_refs);
  const strategyCardPaths = artifactPaths(summary.final_output.strategy_card_artifact_refs);

  return (
    <FACard
      title="本次执行摘要"
      eyebrow="执行摘要"
      accent={summary.status === "failed" || summary.status === "blocked" ? "down" : summary.status === "partial" ? "warn" : "up"}
      action={<FAStatusPill tone={statusTone(summary.status)}>{statusLabel(summary.status)}</FAStatusPill>}
    >
      <div className="grid gap-3 lg:grid-cols-[0.85fr_1.15fr]">
        <div className="grid gap-2">
          <div className="grid grid-cols-3 gap-2">
            <SummaryMetric label="输入快照" value={inputCount} />
            <SummaryMetric label="来源引用" value={summary.used_data.source_refs.length} />
            <SummaryMetric label="分析产物" value={summary.used_data.agent_artifact_refs.length} />
          </div>
          <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-3 py-2 text-[length:var(--type-caption)] leading-4">
            <div className="font-semibold text-[var(--fg-5)]">失败步骤</div>
            <div className={`mt-1 break-words ${summary.failed_steps.length ? "text-[var(--danger)]" : "text-[var(--fg-3)]"}`}>
              {summary.failed_steps.length ? `${summary.failed_steps.length} 个步骤失败` : "无失败步骤"}
            </div>
            {summary.failed_steps.length ? <div className="mt-2"><EvidenceRecordActions record={summary.failed_steps} label="失败步骤依据" /></div> : null}
          </div>
        </div>

        <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <span className="text-[length:var(--type-caption)] font-semibold text-[var(--fg-5)]">最终输出</span>
              <FAStatusPill tone={summary.final_output.mode === "accepted" ? "up" : summary.final_output.mode === "observe" ? "warn" : "down"} dot={false}>
                {outputModeLabel(summary.final_output.mode)}
              </FAStatusPill>
            </div>
            <span className="text-[length:var(--type-caption)] text-[var(--fg-5)]">
              {statusLabel(summary.final_output.review_status)} · {summary.final_output.publish_allowed === null ? "发布状态未知" : summary.final_output.publish_allowed ? "允许发布" : "禁止发布"}
            </span>
          </div>
          <div className="mt-3 grid gap-2 text-[length:var(--type-caption)] leading-4 md:grid-cols-2">
            <div>
                <div className="font-semibold text-[var(--fg-5)]">报告产物</div>
                <div className="mt-1 text-[var(--fg-3)]"><ArtifactPathList paths={reportPaths} /></div>
            </div>
            <div>
                <div className="font-semibold text-[var(--fg-5)]">策略卡片产物</div>
                <div className="mt-1 text-[var(--fg-3)]"><ArtifactPathList paths={strategyCardPaths} /></div>
            </div>
          </div>
        </div>
      </div>
    </FACard>
  );
}

function acceptedOutputSummary(outputs: Record<string, unknown>): string {
  const count = Object.values(outputs).reduce<number>((total, value) => total + (Array.isArray(value) ? value.length : value == null ? 0 : 1), 0);
  return count ? `${count} 项最终输出已登记` : "—";
}

function QualityGatePanel({ qualityGate }: { qualityGate: ProcessingQualityGate }) {
  const review = qualityGate.fallback_review;
  const fallbackOutput = review.fallback_outputs[0];
  const task = review.task_results[0];

  return (
    <FACard
      title="质量门控"
      eyebrow="质量门控流程"
      accent={qualityGate.status === "blocked" ? "down" : qualityGate.status === "needs_review" ? "warn" : "up"}
      action={<FAStatusPill tone={statusTone(qualityGate.status)}>{statusLabel(qualityGate.status)}</FAStatusPill>}
    >
      <div className="grid gap-3 xl:grid-cols-[0.9fr_1.1fr]">
        <div className="grid gap-2">
          <div className="flex items-center justify-between gap-3 rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-3 py-2">
            <div className="flex min-w-0 items-center gap-2">
              <ShieldCheck size={14} className="shrink-0 text-[var(--warn)]" />
              <span className="truncate text-[11px] font-semibold text-[var(--fg-2)]">{operationReasonLabel(qualityGate.quality_gate_action)}</span>
            </div>
            <FAStatusPill tone={review.fallback_used ? "warn" : "up"} dot={false}>
              {review.fallback_used ? "回退结果" : "主结果"}
            </FAStatusPill>
          </div>
          <div className="grid grid-cols-2 gap-2 text-[10px] text-[var(--fg-4)]">
            <div className="rounded-[var(--radius-sm)] bg-[var(--bg-card-inner)] px-3 py-2">
              <div className="font-semibold text-[var(--fg-5)]">发布</div>
              <div className="mt-1 text-[var(--fg-2)]">{qualityGate.publish_allowed ? "允许" : "受限"}</div>
            </div>
            <div className="rounded-[var(--radius-sm)] bg-[var(--bg-card-inner)] px-3 py-2">
              <div className="font-semibold text-[var(--fg-5)]">复核</div>
              <div className="mt-1 text-[var(--fg-2)]">{review.manual_review_required ? "需要" : "无需"}</div>
            </div>
          </div>
          <div className="rounded-[var(--radius-sm)] bg-[var(--bg-card-inner)] px-3 py-2 text-[10px] leading-4 text-[var(--fg-4)]">
            <div className="font-semibold text-[var(--fg-5)]">原因</div>
            <div className="mt-1 break-words">{review.reasons.length ? review.reasons.map(operationReasonLabel).join(" / ") : qualityGate.fallback_reasons.map(operationReasonLabel).join(" / ") || "—"}</div>
            {(review.reasons.length || qualityGate.fallback_reasons.length) ? <div className="mt-2"><EvidenceRecordActions record={{ reasons: review.reasons, fallback_reasons: qualityGate.fallback_reasons }} label="质量门控原因依据" /></div> : null}
          </div>
        </div>

        <div className="grid gap-2">
          <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
            <div className="grid gap-2 text-[10px] leading-4 text-[var(--fg-4)] md:grid-cols-2">
              <div>
                <div className="font-semibold text-[var(--fg-5)]">主结果</div>
                <div className="mt-1 break-all text-[var(--fg-2)]">{review.primary_outputs.length ? `${review.primary_outputs.length} 项主结果已登记` : "—"}</div>
                {review.primary_outputs.length ? <div className="mt-2"><EvidenceRecordActions record={review.primary_outputs} label="主结果依据" /></div> : null}
              </div>
              <div>
                <div className="font-semibold text-[var(--fg-5)]">最终采用</div>
                <div className="mt-1 break-all text-[var(--fg-2)]">{review.accepted_output ? "最终结果已登记" : acceptedOutputSummary(review.accepted_outputs)}</div>
                {(review.accepted_output || Object.keys(review.accepted_outputs).length) ? <div className="mt-2"><EvidenceRecordActions record={review.accepted_output ?? review.accepted_outputs} label="最终结果依据" /></div> : null}
              </div>
            </div>
          </div>
          {task ? (
            <div className="flex flex-wrap items-center justify-between gap-2 rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-3 py-2 text-[10px]">
              <span className="font-semibold text-[var(--fg-2)]">{operationReasonLabel(task.task_type)}</span>
              <span className="text-[var(--fg-5)]">{task.fallback_output_agent || task.fallback_of || task.reason ? "回退依据已登记" : "未提供回退说明"}</span>
              <EvidenceRecordActions record={task} label="回退任务依据" />
              <FAStatusPill tone={statusTone(task.status)} dot={false}>{statusLabel(task.status)}</FAStatusPill>
            </div>
          ) : null}
          {fallbackOutput ? (
            <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-[11px] font-semibold text-[var(--fg-2)]">回退结果已登记</span>
                <span className="fa-num text-[10px] text-[var(--fg-5)]">{fallbackOutput.confidence ?? "—"}</span>
              </div>
              <div className="mt-2 line-clamp-2 text-[10px] leading-4 text-[var(--fg-4)]">{fallbackOutput.summary ? "已返回摘要" : "未返回摘要"}</div>
              <div className="mt-2"><EvidenceRecordActions record={fallbackOutput} label="回退结果依据" /></div>
            </div>
          ) : null}
        </div>
      </div>
    </FACard>
  );
}

function CoverageMatrix({ overview }: { overview: ProcessingOverviewResponse }) {
  return (
    <FACard title="九主线覆盖矩阵" eyebrow="主线覆盖" accent="brand" bodyClassName="!p-0">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[760px] table-fixed text-left text-[11px]">
          <colgroup>
            <col className="w-[240px]" />
            <col className="w-[100px]" />
            <col className="w-[90px]" />
            <col className="w-[110px]" />
            <col />
          </colgroup>
          <thead className="border-b border-[var(--border-faint)] bg-[var(--bg-card-inner)] text-[var(--fg-5)]">
            <tr>
              <th className="px-3 py-2 font-semibold">主线</th>
              <th className="px-3 py-2 font-semibold">状态</th>
              <th className="px-3 py-2 font-semibold">事件</th>
              <th className="px-3 py-2 font-semibold">证据</th>
              <th className="px-3 py-2 font-semibold">缺口</th>
            </tr>
          </thead>
          <tbody>
            {overview.mainline_coverage.map((row) => (
              <tr key={row.mainline_id} className="border-b border-[var(--border-faint)] last:border-0">
                <td className="px-3 py-2 font-semibold text-[var(--fg-2)]">{operationMainlineLabel(row.mainline_id)}</td>
                <td className="px-3 py-2">
                  <FAStatusPill tone={statusTone(row.status)} dot={false}>{statusLabel(row.status)}</FAStatusPill>
                </td>
                <td className="px-3 py-2 fa-num text-[var(--fg-2)]">{row.event_count}</td>
                <td className="px-3 py-2 fa-num text-[var(--fg-2)]">{row.source_ref_count}</td>
                <td className="px-3 py-2 text-[var(--fg-4)]">
                  <div className="line-clamp-1 break-words">{row.missing_data.length ? `${row.missing_data.length} 项缺口已登记` : "—"}</div>
                  {row.missing_data.length ? <EvidenceRecordActions record={row.missing_data} label="主线缺口依据" /> : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </FACard>
  );
}

function ChainCoverage({ overview }: { overview: ProcessingOverviewResponse }) {
  return (
    <FACard title="传导链覆盖" eyebrow="影响路径" accent="info">
      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
        {overview.transmission_chain_coverage.map((row) => (
          <div key={row.chain_id} className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0 text-[11px] font-semibold text-[var(--fg-2)]">{operationMainlineLabel(row.chain_id)}</div>
              <FAStatusPill tone={statusTone(row.status)} dot={false}>{statusLabel(row.status)}</FAStatusPill>
            </div>
            <div className="mt-2 line-clamp-2 min-h-[34px] text-[10px] leading-4 text-[var(--fg-5)]">
              {row.verification_needed.length ? `${row.verification_needed.length} 项验证要求已登记` : "无额外验证缺口"}
              {row.verification_needed.length ? <div className="mt-2"><EvidenceRecordActions record={row.verification_needed} label="验证要求依据" /></div> : null}
            </div>
          </div>
        ))}
      </div>
    </FACard>
  );
}

function HealthAndBindings({ overview, trace }: { overview: ProcessingOverviewResponse; trace: ProcessingTraceResponse | null }) {
  const freshness = Object.entries(overview.source_freshness);
  const bindings = trace?.view_bindings ?? overview.view_bindings;
  const sourceHealth = overview.source_health;

  return (
    <div className="grid gap-3 xl:grid-cols-[0.95fr_1.05fr]">
      <FACard title="混合驱动健康度" eyebrow="驱动完整性" accent="warn">
        <div className="flex items-center justify-between gap-3">
          <FAStatusPill tone={statusTone(overview.mixed_health.status)}>{statusLabel(overview.mixed_health.status)}</FAStatusPill>
          <div className="fa-num text-[18px] font-semibold text-[var(--fg-1)]">{overview.mixed_health.mixed_events_total}</div>
        </div>
        <div className="mt-3 grid grid-cols-2 gap-2 text-[10px] text-[var(--fg-4)]">
          <div>缺多头驱动：{overview.mixed_health.mixed_without_bullish_drivers}</div>
          <div>缺空头驱动：{overview.mixed_health.mixed_without_bearish_drivers}</div>
          <div>缺主导驱动：{overview.mixed_health.mixed_without_dominant_driver}</div>
          <div>缺验证要求：{overview.mixed_health.mixed_without_verification_needed}</div>
        </div>
        <div className="mt-4 grid gap-2">
          <div className="rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-3 py-2">
            <div className="flex items-center justify-between gap-3">
              <span className="text-[10px] font-semibold text-[var(--fg-5)]">来源健康度</span>
              <FAStatusPill tone={statusTone(sourceHealth.overall_status)} dot={false}>
                {statusLabel(sourceHealth.overall_status)}
              </FAStatusPill>
            </div>
            <div className="mt-2 grid gap-1 text-[10px] leading-4 text-[var(--fg-4)]">
              <div>P0 缺口：{sourceHealth.p0_missing.length ? `${sourceHealth.p0_missing.length} 项关键来源缺口已登记` : "无"}</div>
              {sourceHealth.p0_missing.length ? <div><EvidenceRecordActions record={sourceHealth.p0_missing} label="关键来源缺口依据" /></div> : null}
              <div>可构建总览：{sourceHealth.can_build_gold_macro_overview ? "是" : "否"}</div>
              {sourceHealth.blocking_reasons.length > 0 ? (
                <div className="space-y-2 text-[var(--danger)]"><div>存在 {sourceHealth.blocking_reasons.length} 项阻断原因。</div><EvidenceRecordActions record={sourceHealth.blocking_reasons} label="阻断原因依据" /></div>
              ) : null}
            </div>
          </div>
          {freshness.map(([key, value]) => (
            <div key={key} className="flex items-center justify-between gap-3 rounded-[var(--radius-sm)] bg-[var(--bg-card-inner)] px-3 py-2 text-[10px]">
              <span className="font-semibold text-[var(--fg-5)]">{fieldLabel(key)}</span>
              <span className="truncate text-[var(--fg-3)]">{readableFreshnessValue(value)}</span>
            </div>
          ))}
        </div>
      </FACard>

      <FACard title="视图绑定" eyebrow={trace ? "链路范围" : "总览范围"} accent="up">
        <div className="grid gap-2 sm:grid-cols-2">
          {bindings.map((binding) => (
            <div key={binding.view} className="flex items-center justify-between gap-2 rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-3 py-2">
              <span className="text-[11px] font-semibold text-[var(--fg-2)]">{operationMainlineLabel(binding.view)}</span>
              <FAStatusPill tone={statusTone(binding.status)} dot={false}>{statusLabel(binding.status)}</FAStatusPill>
            </div>
          ))}
        </div>
      </FACard>
    </div>
  );
}

function RefsPanel({ overview, trace }: { overview: ProcessingOverviewResponse; trace: ProcessingTraceResponse | null }) {
  const sourceRefs = trace?.source_refs ?? overview.source_refs;
  const artifactRefs = trace?.artifact_refs ?? overview.artifact_refs;

  return (
    <div className="grid gap-3 xl:grid-cols-2">
      <FACard title="来源摘要" eyebrow={`${sourceRefs.length} 条`} accent="info">
        {sourceRefs.length ? (
          <div className="grid gap-2">
            {sourceRefs.slice(0, 8).map((ref, index) => (
              <div key={`${ref.source_ref}-${index}`} className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-3 py-2">
                <div className="text-[11px] font-semibold text-[var(--fg-2)]">来源引用已登记</div>
                <div className="mt-1 text-[10px] text-[var(--fg-5)]">{ref.provider ? "来源方已登记" : (ref.endpoint ? "接口来源已登记" : operationStatusLabel(ref.status))}</div>
                {ref.generated_at || ref.asOf ? <div className="mt-1 text-[10px] text-[var(--fg-5)]">截至 {ref.generated_at || ref.asOf}</div> : null}
              </div>
            ))}
          </div>
        ) : (
          <FAEmptyState title="暂无来源引用" description="当前范围未绑定可追溯源引用。" />
        )}
      </FACard>

      <FACard title="输出登记" eyebrow={`${artifactRefs.length} 项`} accent="emphasis">
        {artifactRefs.length
          ? <p className="fa-muted-text">最终输出已登记；文件名、文件路径与原始产物内容不在页面层提供。</p>
          : <FAEmptyState title="暂无输出登记" description="当前范围未返回最终输出摘要。" />}
      </FACard>
    </div>
  );
}

function TraceDetail({ trace }: { trace: ProcessingTraceResponse | null }) {
  if (!trace) {
    return (
      <FACard title="链路查询结果" eyebrow="链路查询" accent="none">
        <FAEmptyState title="尚未查询链路" description="选择查询模式并输入标识后，可查看事件、主线、传导链和追溯路径绑定。" />
      </FACard>
    );
  }

  return (
    <FACard
      title="链路查询结果"
      eyebrow="链路查询"
      accent={trace.status === "matched" ? "up" : "warn"}
      action={<FAStatusPill tone={statusTone(trace.status)}>{statusLabel(trace.status)}</FAStatusPill>}
    >
      {trace.matched_event ? (
        <div className="grid gap-3">
          <div className="grid gap-3 md:grid-cols-4">
            <SummaryMetric label="事件标识" value={idLabel(trace.matched_event.event_id)} />
            <SummaryMetric label="输入标识" value={idLabel(trace.matched_event.input_id)} />
            <SummaryMetric label="加工链路标识" value={idLabel(trace.matched_event.processing_trace_id)} />
            <SummaryMetric label="主要主线" value={operationMainlineLabel(trace.matched_event.primary_mainline)} />
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
              <div className="text-[10px] font-semibold text-[var(--fg-5)]">主线集合</div>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {trace.mainlines.map((item) => <FAStatusPill key={item} tone="info" dot={false}>{operationMainlineLabel(item)}</FAStatusPill>)}
              </div>
            </div>
            <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
              <div className="text-[10px] font-semibold text-[var(--fg-5)]">传导链集合</div>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {trace.transmission_chains.map((item) => <FAStatusPill key={item} tone="neutral" dot={false}>{operationMainlineLabel(item)}</FAStatusPill>)}
              </div>
            </div>
          </div>
          <TracePathStrip nodes={trace.trace_path} />
          <div className="flex justify-end">
            <Link to={preferredDagFocusPath(trace.trace_path)} className="text-[11px] font-semibold text-[var(--info)] hover:text-[var(--fg-1)]">
              在 DAG 中定位此链路
            </Link>
          </div>
        </div>
      ) : (
        <FAEmptyState title="未匹配事件" description="当前标识没有命中 event_links；可切换查询模式或检查后端产物中的 trace 字段。" />
      )}
    </FACard>
  );
}

function queryTrace(mode: ProcessingTraceMode, value: string): Promise<ProcessingTraceResponse> {
  if (mode === "event_id") return fetchProcessingTraceByEvent(value);
  if (mode === "source_ref") return fetchProcessingTraceBySourceRef(value);
  if (mode === "input_id") return fetchProcessingTraceByInput(value);
  if (mode === "mainline") return fetchProcessingTraceByMainline(value);
  if (mode === "transmission_chain") return fetchProcessingTraceByChain(value);
  return fetchProcessingTrace(value);
}

function isTraceMode(value: string | null): value is ProcessingTraceMode {
  return TRACE_MODE_OPTIONS.some((item) => item.value === value);
}

function traceQueryFromSearchParams(params: URLSearchParams): { mode: ProcessingTraceMode; value: string } | null {
  const q = params.get("q")?.trim();
  const mode = params.get("mode");
  if (q && isTraceMode(mode)) return { mode, value: q };

  const aliases: Array<[string, ProcessingTraceMode]> = [
    ["trace_id", "processing_trace_id"],
    ["processing_trace_id", "processing_trace_id"],
    ["event_id", "event_id"],
    ["source_ref", "source_ref"],
    ["input_id", "input_id"],
    ["mainline", "mainline"],
    ["transmission_chain", "transmission_chain"],
  ];
  for (const [key, nextMode] of aliases) {
    const value = params.get(key)?.trim();
    if (value) return { mode: nextMode, value };
  }
  return null;
}

export function ProcessingMonitorPage() {
  const shell = useOutletContext<AppShellOutletContext | null>() ?? { setHeaderContent: () => undefined };
  const [searchParams] = useSearchParams();
  const [overview, setOverview] = useState<ProcessingOverviewResponse | null>(null);
  const [trace, setTrace] = useState<ProcessingTraceResponse | null>(null);
  const [mode, setMode] = useState<ProcessingTraceMode>("processing_trace_id");
  const [queryValue, setQueryValue] = useState("");
  const [loadingOverview, setLoadingOverview] = useState(true);
  const [loadingTrace, setLoadingTrace] = useState(false);
  const [overviewError, setOverviewError] = useState<string | null>(null);
  const [traceError, setTraceError] = useState<string | null>(null);

  const selectedMode = useMemo(() => TRACE_MODE_OPTIONS.find((item) => item.value === mode) ?? TRACE_MODE_OPTIONS[0], [mode]);

  const loadOverview = useCallback(async () => {
    setLoadingOverview(true);
    setOverviewError(null);
    try {
      setOverview(await fetchProcessingOverview());
    } catch (error) {
      setOverviewError(error instanceof Error ? error.message : "加载加工监控概览失败");
    } finally {
      setLoadingOverview(false);
    }
  }, []);

  useEffect(() => {
    shell.setHeaderContent(<HeaderBreadcrumb rootLabel="调度中心" title="加工监控" meta="加工链路" />);
    return () => shell.setHeaderContent(null);
  }, [shell]);

  useEffect(() => {
    void loadOverview();
  }, [loadOverview]);

  useEffect(() => {
    const initialQuery = traceQueryFromSearchParams(searchParams);
    if (!initialQuery) return;

    let cancelled = false;
    setMode(initialQuery.mode);
    setQueryValue(initialQuery.value);
    setLoadingTrace(true);
    setTraceError(null);
    setTrace(null);
    const query = queryTrace(initialQuery.mode, initialQuery.value);
    query
      .then((result) => {
        if (cancelled) return;
        setTrace(result as ProcessingTraceResponse);
      })
      .catch((error) => {
        if (!cancelled) setTraceError(error instanceof Error ? error.message : "Trace 查询失败");
      })
      .finally(() => {
        if (!cancelled) setLoadingTrace(false);
      });

    return () => {
      cancelled = true;
    };
  }, [searchParams]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = queryValue.trim();
    if (!value) return;

    setLoadingTrace(true);
    setTraceError(null);
    setTrace(null);
    try {
      setTrace(await queryTrace(mode, value));
    } catch (error) {
      setTraceError(error instanceof Error ? error.message : "Trace 查询失败");
    } finally {
      setLoadingTrace(false);
    }
  }

  function handleModeChange(nextMode: ProcessingTraceMode) {
    setMode(nextMode);
    setQueryValue("");
    setTrace(null);
    setTraceError(null);
  }

  function clearTraceQuery() {
    setQueryValue("");
    setTrace(null);
    setTraceError(null);
  }

  if (loadingOverview && !overview) {
    return (
      <FAPageScaffold>
        <LoadingSkeleton variant="page" />
      </FAPageScaffold>
    );
  }

  if (overviewError || !overview) {
    return (
      <FAPageScaffold>
      <ErrorState title="加工监控不可用" message="加工监控概览暂时无法读取，请稍后重试。" onRetry={loadOverview} />
      </FAPageScaffold>
    );
  }

  return (
    <FAPageScaffold
      intro={
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-card-inner)] text-[var(--info)]">
              <Workflow size={16} />
            </div>
            <div className="min-w-0">
              <div className="whitespace-nowrap text-[18px] font-semibold leading-tight text-[var(--fg-1)]">加工监控</div>
              <div className="mt-1 hidden text-[11px] text-[var(--fg-5)] sm:block">黄金分析输入、主线、传导链与前端绑定追溯</div>
            </div>
          </div>
        </div>
      }
      status={
        <div className="flex flex-wrap items-center justify-end gap-2">
          <FAStatusPill tone={statusTone(overview.status)}>{statusLabel(overview.status)}</FAStatusPill>
          <span className="fa-num hidden text-[11px] text-[var(--fg-4)] sm:inline">{overview.date ?? "—"} · {overview.run_id ? "运行记录已登记" : "运行标识未提供"}</span>
          {overview.run_id ? <EvidenceRecordActions record={overview.run_id} label="运行记录依据" /> : null}
        </div>
      }
      actions={
        <button
          type="button"
          aria-label="刷新加工监控"
          onClick={loadOverview}
          className="inline-flex h-8 items-center gap-1.5 rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-card-inner)] px-3 text-[11px] font-semibold text-[var(--fg-3)] transition hover:border-[var(--brand-border)] hover:text-[var(--fg-1)]"
        >
          <RefreshCw size={13} />
          <span className="hidden sm:inline">刷新</span>
        </button>
      }
      toolbar={
        <form onSubmit={handleSubmit} className="flex flex-col gap-2 rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card)] p-3 md:flex-row md:items-center">
          <div className="flex items-center gap-2 text-[11px] font-semibold text-[var(--fg-4)]">
            <Network size={14} className="text-[var(--info)]" />
            <span className="whitespace-nowrap">链路查询</span>
          </div>
          <select
            value={mode}
            onChange={(event) => handleModeChange(event.target.value as ProcessingTraceMode)}
            className="h-8 rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-card-inner)] px-2 text-[11px] font-semibold text-[var(--fg-2)] outline-none focus:border-[var(--brand-border)]"
          >
            {TRACE_MODE_OPTIONS.map((item) => (
              <option key={item.value} value={item.value}>{item.label}</option>
            ))}
          </select>
          <input
            value={queryValue}
            onChange={(event) => setQueryValue(event.target.value)}
            placeholder={selectedMode.placeholder}
            className="h-8 min-w-0 flex-1 rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-card-inner)] px-3 text-[11px] text-[var(--fg-2)] outline-none placeholder:text-[var(--fg-5)] focus:border-[var(--brand-border)]"
          />
          {queryValue || trace ? (
            <button
              type="button"
              aria-label="清空链路查询"
              title="清空链路查询"
              onClick={clearTraceQuery}
              className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-card-inner)] text-[var(--fg-4)] transition hover:border-[var(--brand-border)] hover:text-[var(--fg-1)]"
            >
              <CircleX size={14} />
            </button>
          ) : null}
          <button
            type="submit"
            disabled={!queryValue.trim() || loadingTrace}
            className="inline-flex h-8 items-center justify-center gap-1.5 rounded-[var(--radius-md)] border border-[var(--brand-border)] bg-[var(--brand-soft)] px-3 text-[11px] font-semibold text-[var(--brand)] transition hover:bg-[var(--bg-hover)] disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Search size={13} />
            {loadingTrace ? "查询中" : "查询"}
          </button>
        </form>
      }
    >
      <div className="grid gap-3">
        {overview.warnings.length ? (
          <div className="break-all rounded-[var(--radius-lg)] border border-[var(--warn-border)] bg-[var(--warn-soft)] px-4 py-3 text-[11px] leading-5 text-[var(--warn)]">
            存在 {overview.warnings.length} 项运行提醒。
            <div className="mt-2"><EvidenceRecordActions record={overview.warnings} label="运行提醒依据" /></div>
          </div>
        ) : null}

        <OverviewSummary overview={overview} />
        <ExecutionSummaryPanel summary={overview.execution_summary} />

        <FACard
          title="加工链路"
          eyebrow="加工链路"
          accent="info"
          action={
            <div className="flex flex-wrap items-center justify-end gap-2">
              {overview.generated_from ? (
                <Link to="/gold-mainlines" className="text-[11px] font-semibold text-[var(--info)] hover:text-[var(--fg-1)]">查看黄金主线</Link>
              ) : null}
              <Link to={preferredDagFocusPath(overview.trace_path)} className="text-[11px] font-semibold text-[var(--info)] hover:text-[var(--fg-1)]">在 DAG 中定位</Link>
            </div>
          }
        >
          <TracePathStrip nodes={overview.trace_path} />
        </FACard>

        {traceError ? <ErrorState title="链路查询失败" message="链路查询暂时无法读取，请核对查询条件后重试。" className="!p-4" /> : null}
        <TraceDetail trace={trace} />
        {trace ? <TraceDetailPanels trace={trace} /> : null}

        <QualityGatePanel qualityGate={overview.quality_gate} />
        <CoverageMatrix overview={overview} />
        <ChainCoverage overview={overview} />
        <HealthAndBindings overview={overview} trace={trace} />
        <RefsPanel overview={overview} trace={trace} />
      </div>
    </FAPageScaffold>
  );
}
