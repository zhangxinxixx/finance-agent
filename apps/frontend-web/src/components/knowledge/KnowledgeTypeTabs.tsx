import { FATabBar, type FATabOption } from "@/components/shared/FATabBar";
import type { KnowledgeTypeTab } from "@/types/knowledge";

export const KNOWLEDGE_TYPE_TABS: FATabOption<KnowledgeTypeTab>[] = [
  { value: "all", label: "全部" },
  { value: "method", label: "方法论" },
  { value: "playbook", label: "剧本模板" },
  { value: "note", label: "研究笔记" },
  { value: "review", label: "复盘" },
  { value: "agent", label: "智能体规则" },
  { value: "dict", label: "数据字典" },
];

export function buildKnowledgeTypeTabs(
  counts?: Partial<Record<KnowledgeTypeTab, number>>,
): FATabOption<KnowledgeTypeTab>[] {
  return KNOWLEDGE_TYPE_TABS.map((tab) => {
    const count = counts?.[tab.value];
    const disabled = tab.value !== "all" && typeof count === "number" && count === 0;
    return {
      ...tab,
      count,
      disabled,
    };
  });
}

interface KnowledgeTypeTabsProps {
  value: KnowledgeTypeTab;
  onChange: (value: KnowledgeTypeTab) => void;
}

export function KnowledgeTypeTabs({ value, onChange }: KnowledgeTypeTabsProps) {
  return <FATabBar tabs={buildKnowledgeTypeTabs()} value={value} onChange={onChange} ariaLabel="知识类型筛选" />;
}
