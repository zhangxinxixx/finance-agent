import {
  KnowledgeBaseErrorState,
  KnowledgeBaseLoadingState,
} from "@/components/knowledge/KnowledgeBasePageStates";
import { KnowledgeDetailPane } from "@/components/knowledge/KnowledgeDetailPane";
import { KnowledgeFilterBar } from "@/components/knowledge/KnowledgeFilterBar";
import { KnowledgeListPane } from "@/components/knowledge/KnowledgeListPane";
import { KnowledgeOpsPane } from "@/components/knowledge/KnowledgeOpsPane";
import { KnowledgePlaybookSection } from "@/components/knowledge/KnowledgePlaybookSection";
import { KnowledgeTypeTabs } from "@/components/knowledge/KnowledgeTypeTabs";
import { FAPageIntro } from "@/components/shared/FAPageIntro";
import { FAPageScaffold } from "@/components/shared/FAPageScaffold";
import { useKnowledge } from "@/hooks/useKnowledge";
import { useKnowledgePageState, useKnowledgeSelectionSync } from "@/hooks/useKnowledgePageState";

export function KnowledgeBasePage() {
  const {
    search,
    setSearch,
    topic,
    status,
    typeTab,
    selectedId,
    setSelectedId,
    detailTab,
    setDetailTab,
    opsTab,
    setOpsTab,
    handleSelectItem,
    handleTopicFilter,
    handleStatusFilter,
    handleTypeTabChange,
  } = useKnowledgePageState();

  const knowledge = useKnowledge({ search, topic, status, typeTab, selectedId });

  useKnowledgeSelectionSync({
    dataSelectedId: knowledge.data?.selectedId,
    selectedId,
    setSelectedId,
  });

  if (knowledge.isLoading && !knowledge.data) {
    return <KnowledgeBaseLoadingState />;
  }

  if (knowledge.isError || !knowledge.data) {
    return <KnowledgeBaseErrorState message={knowledge.error?.message ?? "未知错误"} onRetry={knowledge.refetch} />;
  }

  const { items, selectedItem, stats } = knowledge.data;

  return (
    <FAPageScaffold
      intro={(
        <FAPageIntro
          eyebrow="研究知识资产"
          title="知识库"
          description="左侧管理条目列表，中间阅读与验证细节，右侧承载运营统计和规则动作，避免把筛选、详情和运维信息混在同一列。"
          meta={(
            <>
              <span className="text-[10px] text-[var(--fg-4)]">条目 {items.length}</span>
              <span className="text-[10px] text-[var(--fg-4)]">当前类型 {typeTab}</span>
              {selectedItem ? <span className="text-[10px] text-[var(--fg-4)]">已选 {selectedItem.title}</span> : null}
            </>
          )}
        />
      )}
      toolbar={(
        <div className="fa-page-stack">
          <KnowledgeFilterBar
            search={search}
            onSearchChange={setSearch}
            topic={topic}
            topics={knowledge.topics}
            onTopicChange={handleTopicFilter}
            status={status}
            statuses={knowledge.statuses}
            onStatusChange={handleStatusFilter}
          />

          <KnowledgeTypeTabs value={typeTab} onChange={handleTypeTabChange} />
        </div>
      )}
    >
      <div className="fa-page-grid fa-page-grid--triple flex-1">
        <KnowledgeListPane items={items} selectedId={selectedId} onSelect={handleSelectItem} />
        <KnowledgeDetailPane item={selectedItem} activeTab={detailTab} onTabChange={setDetailTab} />
        <KnowledgeOpsPane
          stats={stats}
          selectedItem={selectedItem}
          items={items}
          activeTab={opsTab}
          onTabChange={setOpsTab}
        />
      </div>

      {typeTab === "playbook" ? <KnowledgePlaybookSection /> : null}
    </FAPageScaffold>
  );
}

export default KnowledgeBasePage;
