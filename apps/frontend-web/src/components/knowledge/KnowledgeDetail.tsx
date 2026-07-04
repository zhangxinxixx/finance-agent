import type { KnowledgeDetailTab, KnowledgeItem } from "@/types/knowledge";
import {
  DETAIL_TABS,
  KnowledgeDetailHero,
  KnowledgeDetailTabPanels,
} from "@/components/knowledge/KnowledgeDetailSections";

interface KnowledgeDetailProps {
  item: KnowledgeItem;
  activeTab: KnowledgeDetailTab;
  onTabChange: (tab: KnowledgeDetailTab) => void;
}

export function KnowledgeDetail({ item, activeTab, onTabChange }: KnowledgeDetailProps) {
  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      <KnowledgeDetailHero item={item} />

      <div className="flex flex-wrap gap-1.5 rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-panel)] p-1.5">
        {DETAIL_TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            onClick={() => onTabChange(tab.id)}
            className={`rounded-[var(--radius-md)] px-2.5 py-1.5 text-[11px] font-semibold transition-colors ${
              activeTab === tab.id
                ? "bg-[var(--bg-active)] text-[var(--brand-hover)]"
                : "text-[var(--fg-4)] hover:bg-[var(--bg-hover)] hover:text-[var(--fg-2)]"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="min-h-0 flex-1">
        <KnowledgeDetailTabPanels item={item} activeTab={activeTab} />
      </div>
    </div>
  );
}
