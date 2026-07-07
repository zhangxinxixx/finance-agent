import { FAEmptyState } from "@/components/shared/FAEmptyState";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { compactId } from "@/lib/format";
import type { AgentInspectionItem, AgentInspectionViewModel } from "@/types/agent-task";
import { taskStatusTone } from "./agentTaskMeta";
import { JsonBlock } from "./AgentTaskDisplayBlocks";
import { AgentInspectionFeedbackForm } from "./AgentInspectionFeedbackForm";

function extractClaimCount(agent: AgentInspectionItem): number {
  const payload = agent.output.payload;
  if (!payload || typeof payload !== "object" || !("claims" in payload)) {
    return 0;
  }
  const claims = (payload as { claims?: unknown }).claims;
  return Array.isArray(claims) ? claims.length : 0;
}

function extractFactReviewStatus(agent: AgentInspectionItem): string | null {
  const payload = agent.output.payload;
  if (!payload || typeof payload !== "object" || !("fact_review_status" in payload)) {
    return null;
  }
  const status = (payload as { fact_review_status?: unknown }).fact_review_status;
  return typeof status === "string" && status ? status : null;
}

function AgentInspectionCard({ agent }: { agent: AgentInspectionItem }) {
  const promptText = agent.prompt.available
    ? agent.prompt.messages.map((message) => `${message.role}:\n${message.content}`).join("\n\n---\n\n")
    : agent.prompt.note || "未记录 prompt。";
  const claimCount = extractClaimCount(agent);
  const factReviewStatus = extractFactReviewStatus(agent);
  const promptChecksum = agent.output.prompt_checksum ?? agent.prompt.checksum;
  const promptId = agent.output.prompt_id ?? agent.prompt.prompt_id;
  const promptVersion = agent.output.prompt_version ?? agent.prompt.version;
  const promptSourceFile = agent.output.prompt_source_file ?? agent.prompt.source_file;

  return (
    <article className="rounded-[14px] border border-[var(--border)] bg-[var(--bg-card)] p-4">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-[14px] font-semibold text-[var(--fg-1)]">{agent.display_name || agent.agent_name}</div>
          <div className="mt-1 font-mono text-[10px] text-[var(--fg-5)]">
            {agent.agent_name}
            {agent.registry_id ? ` · ${agent.registry_id}` : ""}
            {agent.role ? ` · ${agent.role}` : ""}
          </div>
          <div className="mt-1 font-mono text-[10px] text-[var(--fg-5)]">
            {agent.module} · {agent.snapshot_id}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <FAStatusPill tone={agent.prompt.available ? "info" : "dim"}>{agent.prompt.kind === "llm" ? "Prompt" : "规则型"}</FAStatusPill>
          <FAStatusPill tone={taskStatusTone(agent.status)}>{agent.status}</FAStatusPill>
        </div>
      </div>

      <div className="grid gap-3 xl:grid-cols-3">
        <div className="space-y-2">
          <div className="text-[11px] font-semibold text-[var(--fg-2)]">Prompt</div>
          <JsonBlock value={promptText} />
        </div>
        <div className="space-y-2">
          <div className="text-[11px] font-semibold text-[var(--fg-2)]">输入</div>
          <JsonBlock value={agent.input} />
        </div>
        <div className="space-y-2">
          <div className="text-[11px] font-semibold text-[var(--fg-2)]">输出</div>
          <JsonBlock value={agent.output} />
        </div>
      </div>

      {agent.llm.model ? (
        <div className="mt-3 flex flex-wrap gap-2 text-[10px] text-[var(--fg-5)]">
          <span className="rounded-full border border-[var(--border-faint)] px-2 py-1">{agent.llm.model}</span>
          {agent.llm.elapsed_seconds != null ? <span className="rounded-full border border-[var(--border-faint)] px-2 py-1">{agent.llm.elapsed_seconds.toFixed(1)}s</span> : null}
        </div>
      ) : null}

      <div className="mt-3 flex flex-wrap gap-2 text-[10px] text-[var(--fg-5)]">
        {agent.agent_output_id ? (
          <span className="rounded-full border border-[var(--border-faint)] px-2 py-1">output {compactId(agent.agent_output_id, 10, 4)}</span>
        ) : null}
        {agent.prompt_version_id ? (
          <span className="rounded-full border border-[var(--border-faint)] px-2 py-1">prompt {compactId(agent.prompt_version_id, 10, 4)}</span>
        ) : null}
        {promptId ? (
          <span className="rounded-full border border-[var(--border-faint)] px-2 py-1">prompt_id {promptId}</span>
        ) : null}
        {promptVersion ? (
          <span className="rounded-full border border-[var(--border-faint)] px-2 py-1">version {promptVersion}</span>
        ) : null}
        {promptChecksum ? (
          <span className="rounded-full border border-[var(--border-faint)] px-2 py-1">checksum {compactId(promptChecksum, 8, 4)}</span>
        ) : null}
        {promptSourceFile ? (
          <span className="rounded-full border border-[var(--border-faint)] px-2 py-1">source_file {promptSourceFile}</span>
        ) : null}
        <span className="rounded-full border border-[var(--border-faint)] px-2 py-1">claims {claimCount}</span>
        <span className="rounded-full border border-[var(--border-faint)] px-2 py-1">
          fact_review {factReviewStatus ?? "pending"}
        </span>
      </div>

      <AgentInspectionFeedbackForm agent={agent} />
    </article>
  );
}

export function AgentInspectionPanel({ inspection }: { inspection?: AgentInspectionViewModel | null }) {
  if (!inspection || inspection.agents.length === 0) {
    return (
      <FAEmptyState
        title="暂无 Agent 检查数据"
        description="当前运行未匹配到 agent_outputs。历史任务可能只记录步骤引用，未记录 Agent prompt/input/output。"
        className="p-6"
      />
    );
  }

  return (
    <div className="space-y-3">
      <div className="rounded-[14px] border border-[var(--border)] bg-[var(--bg-card)] p-4">
        <div className="text-[11px] font-semibold text-[var(--fg-2)]">Agent Prompt / 输入 / 输出</div>
        <div className="mt-2 flex flex-wrap gap-2 text-[10px] text-[var(--fg-5)]">
          <span>交易日 {inspection.trade_date || "-"}</span>
          <span>Run {compactId(inspection.run_id, 12, 4)}</span>
          <span>Snapshot {compactId(inspection.snapshot_id, 12, 4)}</span>
          <span>{inspection.agents.length} 个 Agent</span>
        </div>
      </div>
      {inspection.agents.map((agent) => (
        <AgentInspectionCard key={`${agent.agent_name}-${agent.snapshot_id}`} agent={agent} />
      ))}
    </div>
  );
}
