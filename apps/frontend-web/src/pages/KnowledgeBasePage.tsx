import { BookOpen, RefreshCw } from "lucide-react";
import {
  KnowledgeBaseErrorState,
  KnowledgeBaseLoadingState,
} from "@/components/knowledge/KnowledgeBasePageStates";
import { KnowledgeDetailPane } from "@/components/knowledge/KnowledgeDetailPane";
import { KnowledgeFilterBar } from "@/components/knowledge/KnowledgeFilterBar";
import { KnowledgeListPane } from "@/components/knowledge/KnowledgeListPane";
import { KnowledgeOpsPane } from "@/components/knowledge/KnowledgeOpsPane";
import { KnowledgePlaybookSection } from "@/components/knowledge/KnowledgePlaybookSection";
import { buildKnowledgeTypeTabs } from "@/components/knowledge/KnowledgeTypeTabs";
import { FAPageScaffold } from "@/components/shared/FAPageScaffold";
import { FAWorkspaceHeader } from "@/components/shared/FAWorkspaceHeader";
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
  const typeTabs = buildKnowledgeTypeTabs(knowledge.data.typeCounts);

  return (
    <FAPageScaffold
      className="knowledge-page-shell"
      toolbar={(
        <div className="fa-page-stack">
          <FAWorkspaceHeader
            className="knowledge-workspace-header"
            icon={BookOpen}
            title="知识库"
            tabs={typeTabs}
            value={typeTab}
            onChange={handleTypeTabChange}
            ariaLabel="知识类型筛选"
            actions={(
              <button type="button" onClick={knowledge.refetch} className="fa-workspace-toolbar-button">
                <RefreshCw size={12} />
                刷新
              </button>
            )}
            primaryLabel="知识资产"
            primaryItems={[
              { label: "条目", value: items.length },
              { label: "主题", value: topic },
              { label: "状态", value: status },
            ]}
            secondaryLabel="当前"
            secondaryItems={[
              ...(selectedItem ? [{ label: "已选", value: selectedItem.title, title: selectedItem.title }] : []),
            ]}
          />

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
        </div>
      )}
    >
      <div className="fa-page-grid knowledge-page-grid flex-1">
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
