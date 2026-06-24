import { FACard } from "@/components/shared/FACard";
import { FAMetricCard } from "@/components/shared/FAMetricCard";
import { FASectionHeader } from "@/components/shared/FASectionHeader";
import { FASourceTraceBadge } from "@/components/shared/FASourceTraceBadge";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import type { KnowledgeDetailTab, KnowledgeItem, KnowledgeItemStatus } from "@/types/knowledge";

export { KnowledgeDetailTabPanels } from "./KnowledgeDetailTabs";

export const DETAIL_TABS: Array<{ id: KnowledgeDetailTab; label: string }> = [
  { id: "overview", label: "概览" },
  { id: "rules", label: "规则" },
  { id: "io", label: "输入 / 输出" },
  { id: "dependencies", label: "下游依赖" },
  { id: "validation", label: "验证记录" },
  { id: "citations", label: "引用记录" },
];

function statusToneFor(status: KnowledgeItemStatus): "up" | "warn" | "info" {
  if (status === "长期有效") return "up";
  if (status === "待复核") return "warn";
  return "info";
}

export function KnowledgeDetailHero({ item }: { item: KnowledgeItem }) {
  return (
    <FACard
      accent="brand"
      bodyClassName="space-y-4"
      action={
        <div className="flex flex-wrap items-center gap-1.5">
          <FAStatusPill tone={statusToneFor(item.status)}>{item.status}</FAStatusPill>
          {item.agentReady ? <FAStatusPill tone="info">智能体可调用</FAStatusPill> : null}
        </div>
      }
    >
      <FASectionHeader
        title={item.title}
        description={item.thesis}
        eyebrow={
          <span className="flex items-center gap-2">
            <span className="font-mono text-[10px] text-[var(--fg-5)]">{item.version}</span>
            <span className="text-[var(--fg-6)]">/</span>
            <span className="text-[10px] text-[var(--fg-4)]">{item.author}</span>
          </span>
        }
      />
      <div className="flex flex-wrap items-center gap-2">
        <FASourceTraceBadge source={item.typeLabel} status="type" tone="info" />
        <FASourceTraceBadge source={item.topic} status="topic" tone="dim" />
        <FASourceTraceBadge source={`引用 ${item.citations}`} status="citations" tone="neutral" />
        <FASourceTraceBadge
          source={`可信度 ${item.confidence}%`}
          status="confidence"
          tone={item.confidence >= 90 ? "up" : item.confidence >= 75 ? "info" : "warn"}
        />
      </div>
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        <FAMetricCard label="版本" value={item.version} hint={`创建 ${item.createdAt}`} />
        <FAMetricCard label="最近验证" value={item.verifiedAt} hint={`作者 ${item.author}`} />
        <FAMetricCard
          label="引用强度"
          value={item.citations}
          hint={`下游模块 ${item.dashboards}`}
          trend={item.citations > 80 ? "up" : "flat"}
        />
        <FAMetricCard
          label="可信度"
          value={`${item.confidence}%`}
          hint={item.reviewQueued ? "进入复核队列" : "未触发复核告警"}
          trend={item.confidence >= 85 ? "up" : item.confidence < 70 ? "down" : "flat"}
        />
      </div>
    </FACard>
  );
}
