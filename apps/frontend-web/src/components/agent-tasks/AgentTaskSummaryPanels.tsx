import { FAEmptyState } from "@/components/shared/FAEmptyState";
import { FARuntimeLog, type FARuntimeLogEntry, type FARuntimeLogLevel } from "@/components/shared/FARuntimeLog";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { FAWarningBanner } from "@/components/shared/FAWarningBanner";
import { formatDateTime, formatTradeDate } from "@/lib/date";
import { compactId, formatPercent } from "@/lib/format";
import type { TaskLogViewModel, TaskRunEventViewModel, TaskRunViewModel, TaskStepViewModel } from "@/types/agent-task";
import { taskStatusLabel, taskStatusTone, taskTopicSummary, taskTypeLabel } from "./agentTaskMeta";

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
  if (Number.isNaN(date.getTime())) return String(value);
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
  return stepName ?? event.task_id ?? source ?? "run";
}

function eventMessage(event: TaskRunEventViewModel): string {
  const details = [
    typeof event.payload.reason === "string" ? event.payload.reason : null,
    typeof event.payload.blocked_reason === "string" ? event.payload.blocked_reason : null,
    typeof event.payload.error_message === "string" ? event.payload.error_message : null,
    typeof event.payload.from_status === "string" && typeof event.payload.to_status === "string"
      ? `${event.payload.from_status} -> ${event.payload.to_status}`
      : null,
  ].filter((item): item is string => Boolean(item));
  return details.length > 0 ? `${event.event_type} · ${details.join(" · ")}` : event.event_type;
}

export function SummaryPanel({ selectedRun }: { selectedRun: TaskRunViewModel }) {
  return (
    <div className="space-y-3">
      <div className="rounded-[14px] border border-[var(--border)] bg-[var(--bg-card)] p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--fg-5)]">当前任务</div>
            <div className="mt-2 text-[24px] font-semibold tracking-[-0.02em] text-[var(--fg-1)]">{taskTypeLabel(selectedRun.task_type)}</div>
            <div className="mt-2 font-mono text-[11px] text-[var(--fg-4)]">{selectedRun.run_id}</div>
          </div>
          <div className="flex flex-wrap gap-2">
            <FAStatusPill tone={taskStatusTone(selectedRun.status)}>{taskStatusLabel(selectedRun.status)}</FAStatusPill>
            {selectedRun.current_stage ? <FAStatusPill tone="info">{selectedRun.current_stage}</FAStatusPill> : null}
          </div>
        </div>
        <p className="mt-4 max-w-2xl text-[13px] leading-relaxed text-[var(--fg-3)]">{taskTopicSummary(selectedRun)}</p>
      </div>

      <div className="grid gap-3 xl:grid-cols-4">
        <div className="rounded-[12px] border border-[var(--border)] bg-[var(--bg-card)] p-4">
          <div className="text-[10px] text-[var(--fg-5)]">运行 ID</div>
          <div className="mt-2 font-mono text-[12px] font-semibold text-[var(--fg-2)]">{compactId(selectedRun.run_id, 16, 4)}</div>
        </div>
        <div className="rounded-[12px] border border-[var(--border)] bg-[var(--bg-card)] p-4">
          <div className="text-[10px] text-[var(--fg-5)]">快照</div>
          <div className="mt-2 font-mono text-[12px] font-semibold text-[var(--fg-2)]">{compactId(selectedRun.snapshot_id, 16, 4)}</div>
        </div>
        <div className="rounded-[12px] border border-[var(--border)] bg-[var(--bg-card)] p-4">
          <div className="text-[10px] text-[var(--fg-5)]">结果</div>
          <div className="mt-2 font-mono text-[12px] font-semibold text-[var(--fg-2)]">{compactId(selectedRun.final_result_id, 16, 4)}</div>
        </div>
        <div className="rounded-[12px] border border-[var(--border)] bg-[var(--bg-card)] p-4">
          <div className="text-[10px] text-[var(--fg-5)]">交易日</div>
          <div className="mt-2 text-[12px] font-semibold text-[var(--fg-2)]">{formatTradeDate(selectedRun.dataDate)}</div>
        </div>
      </div>
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
                {step.stage || "未标注阶段"}{step.task_kind ? ` · ${step.task_kind}` : ""}
              </div>
            </div>
            <FAStatusPill tone={taskStatusTone(step.status)}>{taskStatusLabel(step.status)}</FAStatusPill>
          </div>
          <div className="mt-4 grid gap-2 sm:grid-cols-3">
            <div className="rounded-[10px] bg-[var(--bg-panel)] px-3 py-2 text-[11px] text-[var(--fg-4)]">开始：{formatDateTime(step.started_at)}</div>
            <div className="rounded-[10px] bg-[var(--bg-panel)] px-3 py-2 text-[11px] text-[var(--fg-4)]">结束：{formatDateTime(step.finished_at)}</div>
            <div className="rounded-[10px] bg-[var(--bg-panel)] px-3 py-2 text-[11px] text-[var(--fg-4)]">进度：{step.progress != null ? formatPercent(step.progress) : "-"}</div>
          </div>
          {step.failure_reason ? <div className="mt-3"><FAWarningBanner title={step.error_type || "错误"} description={step.failure_reason} tone="down" /></div> : null}
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
          time: index === 0 ? log.step_id || "run" : "",
          level: logLevelFromStatus(log.status),
          source: log.task_id,
          message: line,
        }))
      : [{ id: `${log.step_id ?? "run"}-empty`, time: log.step_id || "run", level: "debug", source: log.task_id, message: "暂无日志" }],
  );

  return (
    <div className="rounded-[14px] border border-[var(--border)] bg-[var(--bg-card)] p-4">
      <div className="mb-4 text-[11px] font-semibold text-[var(--fg-2)]">运行日志</div>
      <div className="max-h-[420px] overflow-y-auto">
        {entries.length > 0 ? <FARuntimeLog entries={entries} /> : <FAEmptyState title="暂无日志" description="当前运行没有额外日志输出。" className="p-4" />}
      </div>
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
          : <FAEmptyState title="暂无事件时间线" description="当前运行尚未返回 execution events。" className="p-4" />}
      </div>
    </div>
  );
}
