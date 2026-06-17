import { FACard } from "@/components/shared/FACard";
import { FAEmptyState } from "@/components/shared/FAEmptyState";
import { KnowledgeListItem } from "@/components/knowledge/KnowledgeListItem";
import type { KnowledgeItem } from "@/types/knowledge";

interface KnowledgeListPaneProps {
  items: KnowledgeItem[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}

export function KnowledgeListPane({ items, selectedId, onSelect }: KnowledgeListPaneProps) {
  return (
    <FACard
      title="知识条目"
      eyebrow="条目列表"
      accent="info"
      className="flex min-h-0 flex-col"
      bodyClassName="min-h-0 flex-1 space-y-2 overflow-y-auto"
    >
      {items.length > 0 ? (
        items.map((item) => (
          <KnowledgeListItem
            key={item.id}
            item={item}
            isActive={item.id === selectedId}
            onSelect={onSelect}
          />
        ))
      ) : (
        <FAEmptyState title="没有匹配到条目" description="试试放宽主题或状态筛选。" />
      )}
    </FACard>
  );
}
