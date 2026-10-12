import { FAEmptyState } from "@/components/shared/FAEmptyState";
import { FARuntimeLog, type FARuntimeLogEntry, type FARuntimeLogLevel } from "@/components/shared/FARuntimeLog";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { FAWarningBanner } from "@/components/shared/FAWarningBanner";
import { EvidenceRecordActions } from "@/components/shared/EvidenceRecordActions";
import { formatDateTime, formatTradeDate } from "@/lib/date";
import { formatPercent } from "@/lib/format";
import type { TaskLogViewModel, TaskRunEventViewModel, TaskRunViewModel, TaskStepViewModel } from "@/types/agent-task";
import { taskStatusLabel, taskStatusTone, taskTopicSummary, taskTypeLabel } from "./agentTaskMeta";
import { operationEventLabel, operationStageLabel, operationStatusLabel } from "@/components/operations/operationsLabels";

function logLevelFromStatus(status: TaskLogViewModel["status"]): FARuntimeLogLevel {
  if (status === "available") return "success";
  if (status === "error") return "error";
  if (status === "partial") return "warn";
  return "debug";
}

function eventLevelFromType(eventType: string): FARuntimeLogLevel {
  const value = eventType.toUpperCase();
  if (value.includes("FAILED") || value.includes("ERROR")) return "error";
  if (value.includes("BLOCKED") || value.includes("FALLBACK") || value.includes("DEGRADED")) return "warn";
  if (value.includes("FINISHED") || value.includes("SUCCESS") || value.includes("WRITTEN")) return "success";
  if (value.includes("STARTED") || value.includes("STATUS_CHANGED") || value.includes("EVALUATED")) return "info";
  return "debug";
}

function formatEventTime(value: string | null | undefined): string {
  if (!value) return "--:--:--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "时间格式待确认";
  return date.toLocaleTimeString("zh-CN", {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function eventSource(event: TaskRunEventViewModel): string {
  const stepName = typeof event.payload.step_name === "string" ? event.payload.step_name : null;
  const source = typeof event.payload.source === "string" ? event.payload.source : null;
  if (stepName) return "相关步骤";
  if (event.task_id) return "任务记录";
  if (source) return "来源记录";
  return "运行记录";
}

function readableEventDetail(value: unknown, fallback: string): string | null {
  if (typeof value !== "string" || !value.trim()) return null;
  const text = value.trim();
  const looksMachineLike = /(?:\/api\/|https?:\/\/|fixture[-_]|(?:debug|success|error|failed|started_at|ended_at|run_id|step_id))/i.test(text);
  return /[㐀-鿿]/.test(text) && !looksMachineLike ? text : fallback;
}

function eventMessage(event: TaskRunEventViewModel): string {
  const details = [
    readableEventDetail(event.payload.reason, "原因已登记"),
    readableEventDetail(event.payload.blocked_reason, "阻塞说明已登记"),
    readableEventDetail(event.payload.error_message, "错误说明已登记"),
    typeof event.payload.from_status === "string" && typeof event.payload.to_status === "string"
      ? `${operationStatusLabel(event.payload.from_status)} → ${operationStatusLabel(event.payload.to_status)}`
      : null,
  ].filter((item): item is string => Boolean(item));
  const eventLabel = operationEventLabel(event.event_type);
  return details.length > 0 ? `${eventLabel} · ${details.join(" · ")}` : eventLabel;
}

export function SummaryPanel({ selectedRun }: { selectedRun: TaskRunViewModel }) {
  return (
    <div className="space-y-3">
      <div className="rounded-[14px] border border-[var(--border)] bg-[var(--bg-card)] p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--fg-5)]">当前任务</div>
            <div className="mt-2 text-[24px] font-semibold tracking-[-0.02em] text-[var(--fg-1)]">{taskTypeLabel(selectedRun.task_type)}</div>
            <div className="mt-2 text-[11px] text-[var(--fg-4)]">{selectedRun.run_id ? "运行记录已登记" : "运行标识未提供"}</div>
          </div>
          <div className="flex flex-wrap gap-2">
            <FAStatusPill tone={taskStatusTone(selectedRun.status)}>{taskStatusLabel(selectedRun.status)}</FAStatusPill>
            {selectedRun.current_stage ? <FAStatusPill tone="info">{operationStageLabel(selectedRun.current_stage)}</FAStatusPill> : null}
          </div>
        </div>
        <p className="mt-4 max-w-2xl text-[13px] leading-relaxed text-[var(--fg-3)]">{taskTopicSummary(selectedRun)}</p>
      </div>

      <div className="grid gap-3 xl:grid-cols-4">
        <div className="rounded-[12px] border border-[var(--border)] bg-[var(--bg-card)] p-4">
          <div className="text-[10px] text-[var(--fg-5)]">运行标识</div>
          <div className="mt-2 text-[12px] font-semibold text-[var(--fg-2)]">{selectedRun.run_id ? "已登记" : "未提供"}</div>
        </div>
        <div className="rounded-[12px] border border-[var(--border)] bg-[var(--bg-card)] p-4">
          <div className="text-[10px] text-[var(--fg-5)]">快照</div>
          <div className="mt-2 text-[12px] font-semibold text-[var(--fg-2)]">{selectedRun.snapshot_id ? "已登记" : "未提供"}</div>
        </div>
        <div className="rounded-[12px] border border-[var(--border)] bg-[var(--bg-card)] p-4">
          <div className="text-[10px] text-[var(--fg-5)]">结果</div>
          <div className="mt-2 text-[12px] font-semibold text-[var(--fg-2)]">{selectedRun.final_result_id ? "已登记" : "未提供"}</div>
        </div>
        <div className="rounded-[12px] border border-[var(--border)] bg-[var(--bg-card)] p-4">
          <div className="text-[10px] text-[var(--fg-5)]">交易日</div>
          <div className="mt-2 text-[12px] font-semibold text-[var(--fg-2)]">{formatTradeDate(selectedRun.dataDate)}</div>
        </div>
      </div>
      <EvidenceRecordActions
        record={{ run_id: selectedRun.run_id, snapshot_id: selectedRun.snapshot_id, final_result_id: selectedRun.final_result_id }}
        label="任务证据记录"
      />
    </div>
  );
}

export function StepSummaryCards({ steps }: { steps: TaskStepViewModel[] }) {
  if (steps.length === 0) {
    return <FAEmptyState title="暂无分析内容" description="当前任务没有返回步骤结果。" className="p-6" />;
  }

  return (
    <div className="space-y-3">
      {steps.map((step) => (
        <article key={step.id} className="rounded-[14px] border border-[var(--border)] bg-[var(--bg-card)] p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <div className="text-[15px] font-semibold text-[var(--fg-1)]">{step.label}</div>
              <div className="mt-1 text-[11px] text-[var(--fg-4)]">
                {operationStageLabel(step.stage)}{step.task_kind ? ` · ${operationStageLabel(step.task_kind)}` : ""}
              </div>
            </div>
            <FAStatusPill tone={taskStatusTone(step.status)}>{taskStatusLabel(step.status)}</FAStatusPill>
          </div>
          <div className="mt-4 grid gap-2 sm:grid-cols-3">
            <div className="rounded-[10px] bg-[var(--bg-panel)] px-3 py-2 text-[11px] text-[var(--fg-4)]">开始：{formatDateTime(step.started_at)}</div>
            <div className="rounded-[10px] bg-[var(--bg-panel)] px-3 py-2 text-[11px] text-[var(--fg-4)]">结束：{formatDateTime(step.finished_at)}</div>
            <div className="rounded-[10px] bg-[var(--bg-panel)] px-3 py-2 text-[11px] text-[var(--fg-4)]">进度：{step.progress != null ? formatPercent(step.progress) : "-"}</div>
          </div>
          {step.failure_reason ? <div className="mt-3"><FAWarningBanner title={operationStatusLabel(step.error_type || "error")} description={step.failure_reason} tone="down" /></div> : null}
        </article>
      ))}
    </div>
  );
}

export function LogPanel({ logs }: { logs: TaskLogViewModel[] }) {
  const entries: FARuntimeLogEntry[] = logs.flatMap((log) =>
    log.lines.length > 0
      ? log.lines.map((line, index) => ({
          id: `${log.step_id ?? "run"}-${index}-${line}`,
          time: index === 0 ? formatDateTime(log.started_at) : "",
          level: logLevelFromStatus(log.status),
          source: "运行日志",
          message: line,
        }))
      : [{ id: `${log.step_id ?? "run"}-empty`, time: formatDateTime(log.started_at), level: "debug", source: "运行日志", message: "暂无日志" }],
  );

  return (
    <div className="rounded-[14px] border border-[var(--border)] bg-[var(--bg-card)] p-4">
      <div className="mb-4 text-[11px] font-semibold text-[var(--fg-2)]">运行日志</div>
      <div className="max-h-[420px] overflow-y-auto">
        {entries.length > 0 ? <FARuntimeLog entries={entries} /> : <FAEmptyState title="暂无日志" description="当前运行没有额外日志输出。" className="p-4" />}
      </div>
      {logs.length > 0 ? <div className="mt-3"><EvidenceRecordActions record={logs.map((log) => log.source_record ?? log)} label="原始运行日志" /></div> : null}
    </div>
  );
}

export function EventTimelinePanel({ events }: { events: TaskRunEventViewModel[] }) {
  const entries: FARuntimeLogEntry[] = events.map((event) => ({
    id: event.id,
    time: formatEventTime(event.created_at),
    level: eventLevelFromType(event.event_type),
    source: eventSource(event),
    message: eventMessage(event),
  }));

  return (
    <div className="rounded-[14px] border border-[var(--border)] bg-[var(--bg-card)] p-4">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div className="text-[11px] font-semibold text-[var(--fg-2)]">事件时间线</div>
        <div className="text-[10px] text-[var(--fg-5)]">{events.length > 0 ? `${events.length} 条事件` : "暂无事件"}</div>
      </div>
      <div className="max-h-[420px] overflow-y-auto">
        {entries.length > 0
          ? <FARuntimeLog entries={entries} emptyText="暂无事件时间线" />
          : <FAEmptyState title="暂无事件时间线" description="当前运行尚未返回执行事件。" className="p-4" />}
      </div>
      {events.length > 0 ? <div className="mt-3"><EvidenceRecordActions record={events.map((event) => event.source_record ?? event)} label="原始事件记录" /></div> : null}
    </div>
  );
}
