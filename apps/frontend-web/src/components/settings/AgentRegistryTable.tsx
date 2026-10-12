import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { EvidenceRecordActions } from "@/components/shared/EvidenceRecordActions";
import type { AgentRegistryItem } from "@/types/agent-registry";
import { agentNameLabel, agentPriorityLabel, agentStatusLabel, promptKindLabel, promptStatusLabel } from "./settingsFormat";

function agentTypeLabel(value: string): string {
  const labels: Record<string, string> = {
    analysis: "分析智能体",
    synthesis: "综合智能体",
    collector: "采集智能体",
    rule: "规则智能体",
  };
  return labels[value] ?? (value ? "未解释类型" : "未提供类型");
}

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
        <div className="font-semibold text-[var(--fg-1)]">{agentNameLabel(agent.name)}</div>
        <details className="mt-0.5 text-[10px] text-[var(--fg-5)]" onClick={(event) => event.stopPropagation()}>
          <summary className="cursor-pointer">查看技术标识</summary>
          <div className="mt-2"><EvidenceRecordActions label="智能体技术标识" record={{ agent_id: agent.agent_id }} /></div>
        </details>
      </td>
      <td className="px-3 py-2.5">
        <FAStatusPill tone="dim" className="text-[12px]">
          {agentTypeLabel(agent.agent_type)}
        </FAStatusPill>
      </td>
      <td className="px-3 py-2.5">
        <FAStatusPill tone={agent.priority === "P0" ? "warn" : "dim"} className="text-[12px]">
          {agentPriorityLabel(agent.priority)}
        </FAStatusPill>
      </td>
      <td className="px-3 py-2.5">
        <FAStatusPill tone={agentStatusTone(agent.status, agent.priority)} className="text-[12px]">
          {agentStatusLabel(agent.status, agent.status_label)}
        </FAStatusPill>
      </td>
      <td className="px-3 py-2.5">
        {agent.prompt_versions_synced && agent.prompt_version ? (
          <div className="flex items-center gap-1.5">
            <FAStatusPill tone="info" className="text-[12px]">
              {agent.prompt_version.version}
            </FAStatusPill>
            <FAStatusPill tone={agent.prompt_version.enabled ? "neutral" : "down"} className="text-[12px]">
              {promptStatusLabel(agent.prompt_version.status)}
            </FAStatusPill>
          </div>
        ) : (
          <span className="text-[12px] text-[var(--fg-4)]">等待提示词版本同步</span>
        )}
      </td>
      <td className="px-3 py-2.5">
          <span className="text-[12px] text-[var(--fg-3)]">{promptKindLabel(agent.prompt?.kind)}</span>
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
            <th className="px-3 py-2 font-semibold">智能体</th>
            <th className="px-3 py-2 font-semibold">类型</th>
            <th className="px-3 py-2 font-semibold">优先级</th>
            <th className="px-3 py-2 font-semibold">状态</th>
            <th className="px-3 py-2 font-semibold">提示词版本</th>
            <th className="px-3 py-2 font-semibold">来源模块</th>
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
