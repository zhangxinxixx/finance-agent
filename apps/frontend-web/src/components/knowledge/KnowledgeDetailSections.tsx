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
    <section className="knowledge-reader-hero">
      <div className="knowledge-reader-hero-top">
        <div className="min-w-0">
          <div className="knowledge-reader-kicker">
            <span className="fa-num">{item.version}</span>
            <span>{item.author}</span>
            <span>{item.typeLabel}</span>
            <span>{item.topic}</span>
          </div>
          <h2>{item.title}</h2>
        </div>
        <div className="flex shrink-0 flex-wrap justify-end gap-1.5">
          <FAStatusPill tone={statusToneFor(item.status)}>{item.status}</FAStatusPill>
          {item.agentReady ? <FAStatusPill tone="info">智能体可调用</FAStatusPill> : null}
        </div>
      </div>
      <p>{item.thesis}</p>
      <div className="knowledge-fact-strip">
        <Fact label="创建" value={item.createdAt} />
        <Fact label="最近验证" value={item.verifiedAt} />
        <Fact label="引用" value={item.citations} />
        <Fact label="下游" value={item.dashboards} />
        <Fact label="可信度" value={`${item.confidence}%`} tone={item.reviewQueued ? "warn" : "up"} />
      </div>
    </section>
  );
}

function Fact({
  label,
  value,
  tone,
}: {
  label: string;
  value: string | number;
  tone?: "up" | "warn";
}) {
  return (
    <span className={tone ? `knowledge-fact knowledge-fact--${tone}` : "knowledge-fact"}>
      <span>{label}</span>
      <strong>{value}</strong>
    </span>
  );
}
