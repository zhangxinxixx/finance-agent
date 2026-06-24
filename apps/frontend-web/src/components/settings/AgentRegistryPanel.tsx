import { FACard } from "@/components/shared/FACard";
import { FASectionHeader } from "@/components/shared/FASectionHeader";
import { FAWarningBanner } from "@/components/shared/FAWarningBanner";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";
import type { AgentRegistryItem } from "@/types/agent-registry";
import { AgentRegistryTable } from "./AgentRegistryTable";

interface AgentRegistryPanelProps {
  agents: AgentRegistryItem[];
  selectedAgentId: string | null;
  isLoading: boolean;
  isError: boolean;
  errorMessage?: string;
  onSelectAgent: (agentId: string) => void;
}

export function AgentRegistryPanel({
  agents,
  selectedAgentId,
  isLoading,
  isError,
  errorMessage,
  onSelectAgent,
}: AgentRegistryPanelProps) {
  return (
    <FACard title="Agent 配置" eyebrow="Agent Registry" accent="brand" bodyClassName="space-y-3">
      <FASectionHeader
        title="Agent 注册表"
        description="这里仅管理可配置的 Agent 对象；每日运行的 Prompt、输入、输出统一进入 Agent Tasks。"
      />
      <FAWarningBanner
        title="运行输出已从 Settings 移除"
        description="Settings 不再展示 bias、summary、findings 等每日结果，避免把配置治理页变成历史输出墙。"
        tone="info"
      />
      {isError ? (
        <FAWarningBanner
          title="Agent 注册表加载失败"
          description={errorMessage ?? "无法读取 /api/agents/registry"}
          tone="down"
        />
      ) : null}
      {isLoading ? (
        <div className="space-y-2">
          <LoadingSkeleton variant="card" rows={3} />
          <LoadingSkeleton variant="card" rows={3} />
        </div>
      ) : null}
      <AgentRegistryTable agents={agents} selectedAgentId={selectedAgentId} onSelectAgent={onSelectAgent} />
    </FACard>
  );
}
