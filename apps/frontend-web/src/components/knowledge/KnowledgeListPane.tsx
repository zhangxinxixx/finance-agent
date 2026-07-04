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
    <aside className="knowledge-list-panel">
      <div className="knowledge-panel-heading">
        <div>
          <div className="knowledge-panel-kicker">条目列表</div>
          <div className="knowledge-panel-title">知识条目</div>
        </div>
        <span className="knowledge-panel-count">{items.length}</span>
      </div>
      <div className="knowledge-list-scroll">
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
      </div>
    </aside>
  );
}
