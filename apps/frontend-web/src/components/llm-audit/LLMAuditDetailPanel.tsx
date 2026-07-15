import { Link } from "react-router-dom";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import type { LLMAuditDetail } from "@/types/llm-audit";

function pretty(value: unknown): string {
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function Block({ title, value }: { title: string; value: unknown }) {
  return (
    <details open className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card)]">
      <summary className="cursor-pointer px-3 py-2 text-[11px] font-semibold text-[var(--fg-2)]">{title}</summary>
      <pre className="max-h-[420px] overflow-auto whitespace-pre-wrap break-words border-t border-[var(--border-faint)] px-3 py-3 font-mono text-[10px] leading-5 text-[var(--fg-3)]">{pretty(value)}</pre>
    </details>
  );
}

export function LLMAuditDetailPanel({ audit }: { audit: LLMAuditDetail | null }) {
  if (!audit) {
    return <div className="rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card)] p-6 text-[12px] text-[var(--fg-4)]">选择一条调用记录查看完整审计内容。</div>;
  }
  return (
    <div className="space-y-3">
      <div className="rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card)] p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <div className="text-[13px] font-semibold text-[var(--fg-1)]">LLM 调用审计</div>
            <div className="mt-1 font-mono text-[10px] text-[var(--fg-5)]">{audit.caller} · {audit.created_at ?? "-"}</div>
          </div>
          <FAStatusPill tone={audit.status === "success" ? "up" : "down"}>{audit.status}</FAStatusPill>
        </div>
        <div className="mt-3 flex flex-wrap gap-2 text-[10px] text-[var(--fg-4)]">
          <span className="rounded-full border border-[var(--border-faint)] px-2 py-1">provider {audit.provider_resolved ?? "-"}</span>
          <span className="rounded-full border border-[var(--border-faint)] px-2 py-1">model {audit.model_resolved ?? "-"}</span>
          <span className="rounded-full border border-[var(--border-faint)] px-2 py-1">reasoning {audit.reasoning_effort_resolved ?? "-"}</span>
          <span className="rounded-full border border-[var(--border-faint)] px-2 py-1">尝试 {audit.attempt_count}</span>
          {audit.run_id ? <span className="rounded-full border border-[var(--border-faint)] px-2 py-1">run {audit.run_id}</span> : null}
          {audit.report_id ? <Link className="rounded-full border border-[var(--border-faint)] px-2 py-1 text-[var(--accent)]" to={`/reports/${encodeURIComponent(audit.report_id)}`}>report {audit.report_id}</Link> : null}
        </div>
        <div className="mt-2 text-[10px] text-[var(--fg-5)]">敏感配置已脱敏；记录不可变。Prompt SHA256：{audit.request_sha256}</div>
      </div>
      <Block title="LLM 配置" value={audit.request_config} />
      <Block title="实际 Prompt / 请求消息（已脱敏）" value={audit.request_messages} />
      <Block title="关联输入与来源" value={{ context: audit.context, source_refs: audit.source_refs }} />
      <Block title="原始输出" value={audit.response_text ?? audit.error_message ?? "（无文本输出）"} />
      <Block title="重试与调用结果" value={{ attempts: audit.attempts, usage: audit.usage, latency_ms: audit.latency_ms, response_sha256: audit.response_sha256 }} />
    </div>
  );
}
