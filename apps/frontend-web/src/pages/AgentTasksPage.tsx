import { useMemo, useState } from "react";
import { AgentTasksKpiStrip, getRunReviewCount } from "@/components/agent-tasks/AgentTaskPanels";
import { AgentTasksFilterBar } from "@/components/agent-tasks/AgentTasksFilterBar";
import {
  AgentTasksConsoleCard,
  RunOverviewCard,
} from "@/components/agent-tasks/AgentTasksPageSections";
import { AgentTasksRail, type AgentTaskStatusFilter } from "@/components/agent-tasks/AgentTasksRail";
import {
  AgentTasksDetailWarning,
  AgentTasksEmptyState,
  AgentTasksErrorState,
  AgentTasksLoadingState,
} from "@/components/agent-tasks/AgentTasksPageStates";
import {
  buildAgentTasksPageModel,
  type TaskDateFilter,
} from "@/components/agent-tasks/agentTasksPageModel";
import type { AgentCategoryKey } from "@/components/agent-tasks/agentTaskMeta";
import { useAgentTasks } from "@/hooks/useAgentTasks";

export function AgentTasksPage() {
  const agentTasks = useAgentTasks();
  const [activeCategory, setActiveCategory] = useState<AgentCategoryKey | "all">("all");
  const [activeStatus, setActiveStatus] = useState<AgentTaskStatusFilter>("all");
  const [activeDate, setActiveDate] = useState<TaskDateFilter>("latest");
  const [query, setQuery] = useState("");
  const safeData = agentTasks.data;
  const runs = safeData?.runs ?? [];

  const pageModel = useMemo(
    () => buildAgentTasksPageModel(runs, activeCategory, activeStatus, activeDate, query),
    [activeCategory, activeDate, activeStatus, query, runs],
  );

  if (agentTasks.isLoading && !agentTasks.data) {
    return <AgentTasksLoadingState />;
  }

  if (agentTasks.isError || !agentTasks.data) {
    return <AgentTasksErrorState message={agentTasks.error?.message ?? "未知错误"} onRetry={agentTasks.refetch} />;
  }

  const readyData = agentTasks.data;

  if (!readyData.has_data) {
    return <AgentTasksEmptyState />;
  }

  return (
    <div className="finance-page-shell">
      <div className="flex min-h-full flex-col gap-4">
        <AgentTasksKpiStrip
          runs={readyData.runs}
          reviewsTotal={readyData.reviews.length}
          categoryCount={pageModel.categoryCount}
          filteredCount={pageModel.filteredRuns.length}
        />

        <AgentTasksFilterBar
          statusTabs={pageModel.statusTabs}
          activeStatus={activeStatus}
          onStatusChange={setActiveStatus}
          dateTabs={pageModel.dateTabs}
          activeDate={activeDate}
          onDateChange={setActiveDate}
          query={query}
          onQueryChange={setQuery}
          onRefresh={agentTasks.refetch}
        />

        <div className="grid min-h-0 gap-4 xl:grid-cols-[240px_minmax(0,1fr)]">
          <AgentTasksRail
            runs={readyData.runs}
            activeCategory={activeCategory}
            onCategoryChange={setActiveCategory}
          />

          <div className="min-h-0 space-y-4">
            <AgentTasksDetailWarning message={readyData.detail_error} />

            {pageModel.featuredRun ? (
              <RunOverviewCard
                run={pageModel.featuredRun}
                reviewCount={getRunReviewCount(readyData.reviews, pageModel.featuredRun.run_id)}
              />
            ) : null}

            <AgentTasksConsoleCard
              featuredRun={pageModel.featuredRun}
              reviews={readyData.reviews}
              activeDateLabel={pageModel.activeDateLabel}
              filteredRunsCount={pageModel.filteredRuns.length}
              remainingRunCount={pageModel.remainingRunCount}
              needsReviewCount={pageModel.needsReviewCount}
              query={query}
            />
          </div>
        </div>
      </div>
    </div>
  );
}

export default AgentTasksPage;
