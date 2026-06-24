import { Bot } from "lucide-react";
import { FACard } from "@/components/shared/FACard";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import type { AgentRegistryItem } from "@/types/agent-registry";

export function AgentPromptEmptyState() {
  return (
    <FACard title="Prompt 详情" eyebrow="Agent Prompt" accent="brand" bodyClassName="space-y-2">
      <div className="py-8 text-center text-[13px] text-[var(--fg-4)]">
        <Bot size={24} className="mx-auto mb-2 opacity-30" />
        点击左侧 Agent 行<br />查看 Prompt 模板详情
      </div>
    </FACard>
  );
}

interface AgentPromptSummaryProps {
  agent: AgentRegistryItem;
  promptText: string;
}

export function AgentPromptSummary({ agent, promptText }: AgentPromptSummaryProps) {
  const version = agent.prompt_version;

  return (
    <>
      <div className="flex items-center justify-between gap-2">
        <span className="text-[12px] font-semibold text-[var(--fg-2)]">{agent.agent_id}</span>
        <FAStatusPill tone="dim" className="text-[12px]">{agent.prompt?.kind ?? "unknown"}</FAStatusPill>
      </div>

      {version ? (
        <div className="flex items-center gap-2 rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-panel)] px-2.5 py-2">
          <span className="text-[12px] text-[var(--fg-4)]">当前版本</span>
          <FAStatusPill tone="info" className="text-[12px]">{version.version}</FAStatusPill>
          <FAStatusPill tone={version.enabled ? "neutral" : "down"} className="text-[12px]">
            {version.status === "active" ? "激活" : version.status}
          </FAStatusPill>
          {version.change_note ? (
            <span className="ml-auto truncate text-[12px] text-[var(--fg-3)]" title={version.change_note}>
              {version.change_note}
            </span>
          ) : null}
        </div>
      ) : (
        <div className="rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-panel)] px-2.5 py-2 text-[12px] text-[var(--fg-4)]">
          尚未同步 prompt_versions 表
        </div>
      )}

      <div className="flex items-center gap-2 text-[12px] text-[var(--fg-3)]">
        <span className="shrink-0">来源</span>
        <span className="truncate font-mono text-[var(--fg-2)]" title={agent.prompt?.source ?? agent.source_module}>
          {agent.prompt?.source ?? agent.source_module}
        </span>
      </div>

      <div className="rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-panel)]">
        <div className="border-b border-[var(--border-faint)] px-2.5 py-1.5 text-[12px] font-semibold text-[var(--fg-2)]">
          Prompt 模板
        </div>
        <pre className="max-h-[500px] overflow-auto whitespace-pre-wrap p-2.5 text-[12px] leading-6 text-[var(--fg-1)]">
          {promptText || "未配置 Prompt 模板"}
        </pre>
      </div>

      <div className="text-[12px] text-[var(--fg-3)]">
        {agent.description}
      </div>
    </>
  );
}
