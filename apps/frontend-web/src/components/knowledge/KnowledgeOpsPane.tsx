import { KnowledgeOpsPanel } from "@/components/knowledge/KnowledgeOpsPanel";
import type { KnowledgeItem, KnowledgeOpsTab, KnowledgeViewModel } from "@/types/knowledge";

interface KnowledgeOpsPaneProps {
  stats: KnowledgeViewModel["stats"];
  selectedItem: KnowledgeItem | null;
  items: KnowledgeItem[];
  activeTab: KnowledgeOpsTab;
  onTabChange: (tab: KnowledgeOpsTab) => void;
}

export function KnowledgeOpsPane({
  stats,
  selectedItem,
  items,
  activeTab,
  onTabChange,
}: KnowledgeOpsPaneProps) {
  return (
    <div className="hidden min-h-0 xl:flex xl:flex-col">
      <KnowledgeOpsPanel
        stats={stats}
        selectedItem={selectedItem}
        allItems={items}
        activeTab={activeTab}
        onTabChange={onTabChange}
      />
    </div>
  );
}
