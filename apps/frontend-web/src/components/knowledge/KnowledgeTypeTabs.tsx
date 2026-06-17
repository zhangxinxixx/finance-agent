import { FATabBar, type FATabOption } from "@/components/shared/FATabBar";
import type { KnowledgeTypeTab } from "@/types/knowledge";

const TYPE_TABS: FATabOption<KnowledgeTypeTab>[] = [
  { value: "all", label: "全部" },
  { value: "method", label: "方法论" },
  { value: "playbook", label: "剧本模板" },
  { value: "note", label: "研究笔记" },
  { value: "review", label: "复盘" },
  { value: "agent", label: "智能体规则" },
  { value: "dict", label: "数据字典" },
];

interface KnowledgeTypeTabsProps {
  value: KnowledgeTypeTab;
  onChange: (value: KnowledgeTypeTab) => void;
}

export function KnowledgeTypeTabs({ value, onChange }: KnowledgeTypeTabsProps) {
  return <FATabBar tabs={TYPE_TABS} value={value} onChange={onChange} ariaLabel="知识类型筛选" />;
}
