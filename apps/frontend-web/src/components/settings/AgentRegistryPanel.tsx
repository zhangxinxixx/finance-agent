import { FACard } from "@/components/shared/FACard";
import { FASectionHeader } from "@/components/shared/FASectionHeader";
import { FAWarningBanner } from "@/components/shared/FAWarningBanner";
import { LoadingSkeleton } from "@/components/shared/LoadingSkeleton";
import type { AgentRegistryItem } from "@/types/agent-registry";
import { AgentRegistryTable } from "./AgentRegistryTable";
import { readingErrorMessage } from "@/components/reading/readingFormat";

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
    <FACard title="智能体配置" eyebrow="智能体注册表" accent="brand" bodyClassName="space-y-3">
      <FASectionHeader
        title="智能体注册表"
        description="这里仅管理可配置的智能体对象；每日运行的提示词、输入、输出统一进入运行任务。"
      />
      <FAWarningBanner
        title="运行输出已从设置页移除"
        description="设置页不再展示方向、摘要、关键发现等每日结果，避免把配置治理页变成历史输出墙。"
        tone="info"
      />
      {isError ? (
        <FAWarningBanner
          title="智能体注册表加载失败"
          description={readingErrorMessage(errorMessage, "无法读取智能体注册信息。")}
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
