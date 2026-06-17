import { FAEmptyState } from "@/components/shared/FAEmptyState";
import { KnowledgeDetail } from "@/components/knowledge/KnowledgeDetail";
import type { KnowledgeDetailTab, KnowledgeItem } from "@/types/knowledge";

interface KnowledgeDetailPaneProps {
  item: KnowledgeItem | null;
  activeTab: KnowledgeDetailTab;
  onTabChange: (tab: KnowledgeDetailTab) => void;
}

export function KnowledgeDetailPane({ item, activeTab, onTabChange }: KnowledgeDetailPaneProps) {
  if (!item) {
    return <FAEmptyState title="未选中条目" description="请在左侧选择一条知识条目查看详情。" />;
  }

  return <KnowledgeDetail item={item} activeTab={activeTab} onTabChange={onTabChange} />;
}
