import { FAStatusPill } from "@/components/shared/FAStatusPill";
import type { AgentRegistryItem } from "@/types/agent-registry";

function agentStatusTone(status: string, priority: string): "up" | "down" | "warn" | "info" | "dim" | "neutral" {
  if (status === "active_prompt") return priority === "P0" ? "warn" : "info";
  if (status === "planned") return "dim";
  if (status === "disabled") return "down";
  return "neutral";
}

function AgentRegistryRow({
  agent,
  isSelected,
  onSelect,
}: {
  agent: AgentRegistryItem;
  isSelected: boolean;
  onSelect: (agentId: string) => void;
}) {
  return (
    <tr
      className={`cursor-pointer transition-colors ${
        isSelected ? "bg-[var(--brand-soft)] border-l-2 border-[var(--brand)]" : "hover:bg-[var(--bg-hover)]"
      }`}
      onClick={() => onSelect(agent.agent_id)}
    >
      <td className="px-3 py-2.5">
        <div className="font-semibold text-[var(--fg-1)]">{agent.name}</div>
        <div className="mt-0.5 font-mono text-[11px] text-[var(--fg-4)]">{agent.agent_id}</div>
      </td>
      <td className="px-3 py-2.5">
        <FAStatusPill tone="dim" className="text-[12px]">
          {agent.agent_type}
        </FAStatusPill>
      </td>
      <td className="px-3 py-2.5">
        <FAStatusPill tone={agent.priority === "P0" ? "warn" : "dim"} className="text-[12px]">
          {agent.priority}
        </FAStatusPill>
      </td>
      <td className="px-3 py-2.5">
        <FAStatusPill tone={agentStatusTone(agent.status, agent.priority)} className="text-[12px]">
          {agent.status_label}
        </FAStatusPill>
      </td>
      <td className="px-3 py-2.5">
        {agent.prompt_versions_synced && agent.prompt_version ? (
          <div className="flex items-center gap-1.5">
            <FAStatusPill tone="info" className="text-[12px]">
              {agent.prompt_version.version}
            </FAStatusPill>
            <FAStatusPill tone={agent.prompt_version.enabled ? "neutral" : "down"} className="text-[12px]">
              {agent.prompt_version.status === "active" ? "激活" : agent.prompt_version.status}
            </FAStatusPill>
          </div>
        ) : (
          <span className="font-mono text-[12px] text-[var(--fg-4)]">等待迁移</span>
        )}
      </td>
      <td className="px-3 py-2.5">
        <span className="text-[12px] text-[var(--fg-3)]">{agent.prompt?.kind ?? "-"}</span>
      </td>
    </tr>
  );
}

interface AgentRegistryTableProps {
  agents: AgentRegistryItem[];
  selectedAgentId: string | null;
  onSelectAgent: (agentId: string) => void;
}

export function AgentRegistryTable({
  agents,
  selectedAgentId,
  onSelectAgent,
}: AgentRegistryTableProps) {
  return (
    <div className="overflow-x-auto rounded-[var(--radius-md)] border border-[var(--border)]">
      <table className="w-full text-left text-[14px]">
        <thead className="border-b border-[var(--border)] bg-[var(--bg-panel)]">
          <tr className="text-[var(--fg-3)]">
            <th className="px-3 py-2 font-semibold">Agent</th>
            <th className="px-3 py-2 font-semibold">类型</th>
            <th className="px-3 py-2 font-semibold">优先级</th>
            <th className="px-3 py-2 font-semibold">状态</th>
            <th className="px-3 py-2 font-semibold">Prompt 版本</th>
            <th className="px-3 py-2 font-semibold">来源</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-[var(--border-faint)]">
          {agents.map((agent) => (
            <AgentRegistryRow
              key={agent.agent_id}
              agent={agent}
              isSelected={selectedAgentId === agent.agent_id}
              onSelect={onSelectAgent}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}
