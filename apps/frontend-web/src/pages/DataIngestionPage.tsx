import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { triggerIngestionRetry } from "@/adapters/dataIngestion";
import { useDataIngestion } from "@/hooks/useDataIngestion";
import type { DataSourceActionResponse } from "@/types/data-ingestion";
import type { DataSourceStatusViewModel, PipelineStageKey } from "@/types/data-ingestion";

import { CriticalAlertBanner } from "@/components/data-ingestion/CriticalAlertBanner";
import {
  DataIngestionActionFeedback,
  DataIngestionEmptyState,
  DataIngestionErrorState,
  DataIngestionLoadingState,
} from "@/components/data-ingestion/DataIngestionPageStates";
import {
  computePipelineStats,
  filterSourcesByStage,
  getGlobalDataFreshness,
} from "@/components/data-ingestion/dataIngestionPageModel";
import {
  BlockingIssuesPanel,
  IngestionActionsPanel,
  SourceDetailPanel,
} from "@/components/data-ingestion/DataIngestionSidePanels";
import { IngestionSummaryBar } from "@/components/data-ingestion/IngestionSummaryBar";
import { PipelineRunsLog } from "@/components/data-ingestion/PipelineRunsLog";
import { PipelineStageProgress } from "@/components/data-ingestion/PipelineStageProgress";
import { SourcePipelineMatrix } from "@/components/data-ingestion/SourcePipelineMatrix";
import { SourceStageDetailDrawer } from "@/components/data-ingestion/SourceStageDetailDrawer";
import { FAPageScaffold } from "@/components/shared/FAPageScaffold";

export function DataIngestionPage() {
  const ingestion = useDataIngestion();
  const navigate = useNavigate();
  const { sourceId: routeSourceId } = useParams<{ sourceId?: string }>();
  const [actionResult, setActionResult] = useState<DataSourceActionResponse | null>(null);
  const [actionError, setActionError] = useState<Error | null>(null);
  const [selectedSourceId, setSelectedSourceId] = useState<string | null>(routeSourceId ?? null);
  const [stageDrawerSource, setStageDrawerSource] = useState<string | null>(null);
  const [stageDrawerKey, setStageDrawerKey] = useState<PipelineStageKey | null>(null);
  const [stageFilter, setStageFilter] = useState<PipelineStageKey | null>(null);

  useEffect(() => {
    setSelectedSourceId(routeSourceId ?? null);
  }, [routeSourceId]);

  if (ingestion.isLoading && !ingestion.data) {
    return <DataIngestionLoadingState />;
  }

  if (ingestion.isError || !ingestion.data) {
    return (
      <DataIngestionErrorState
        message={ingestion.error?.message ?? "未知 Data Ingestion 错误"}
        onRetry={ingestion.refetch}
      />
    );
  }

  if (!ingestion.data.has_data || ingestion.data.view_model.sources.length === 0) {
    return <DataIngestionEmptyState />;
  }

  const { view_model: viewModel } = ingestion.data;
  const vmSummary = viewModel.summary;
  const systemStatus = viewModel.system_status;
  const sources = viewModel.sources;
  const selectedSource = selectedSourceId ? sources.find((s) => s.id === selectedSourceId) ?? null : null;
  const pipelineStats = computePipelineStats(sources);
  const { globalDataDate, globalStaleness } = getGlobalDataFreshness(sources, systemStatus);
  const degradedCount = sources.filter((source) => source.status !== "available").length;

  // Find source for drawer
  const drawerSource = stageDrawerSource ? sources.find((s) => s.id === stageDrawerSource) ?? null : null;

  async function handleSourceRetry(source: DataSourceStatusViewModel, reason: string) {
    try {
      const result = await triggerIngestionRetry(source.id, {
        actor: "frontend",
        reason,
      });
      setActionError(null);
      setActionResult(result);
    } catch (cause) {
      setActionResult(null);
      setActionError(cause instanceof Error ? cause : new Error("重试登记失败"));
    }
  }

  function handleSourceSelect(sourceId: string) {
    setSelectedSourceId(sourceId);
    navigate(`/data-sources/${encodeURIComponent(sourceId)}`);
  }

  const filteredSources = filterSourcesByStage(sources, stageFilter);

  return (
    <FAPageScaffold>
      <IngestionSummaryBar
        summary={vmSummary}
        pipelineStats={pipelineStats}
        degradedCount={degradedCount}
        dataDate={globalDataDate}
        stalenessDays={globalStaleness}
        lastRun={systemStatus?.latest_run_created_at?.slice(0, 16).replace("T", " ") ?? null}
        onRefresh={ingestion.refetch}
      />

      <CriticalAlertBanner sources={sources} />

      <PipelineStageProgress
        sources={sources}
        onStageFilter={setStageFilter}
        activeFilter={stageFilter}
      />

      <div className="fa-split-grid fa-split-grid--right data-ingestion-main-grid">
        <SourcePipelineMatrix
          sources={filteredSources}
          selectedId={selectedSourceId}
          onSelect={handleSourceSelect}
          onStageClick={(sourceId, stageKey) => {
            setStageDrawerSource(sourceId);
            setStageDrawerKey(stageKey);
          }}
        />

        <div className="fa-scroll-column data-ingestion-side-rail">
          <SourceDetailPanel
            source={selectedSource}
            onRetry={(source) => {
              void handleSourceRetry(source, `从数据源详情请求重试 ${source.label}`);
            }}
          />
          <DataIngestionActionFeedback actionResult={actionResult} actionError={actionError} />
          <IngestionActionsPanel
            sources={sources}
            onActionComplete={(result) => {
              setActionError(null);
              setActionResult(result);
            }}
            onActionError={(error) => {
              setActionResult(null);
              setActionError(error);
            }}
          />
          <BlockingIssuesPanel
            sources={sources}
            systemStatus={systemStatus}
          />
          <PipelineRunsLog sources={sources} />
        </div>
      </div>

      <SourceStageDetailDrawer
        source={drawerSource}
        stageKey={stageDrawerKey}
        onClose={() => {
          setStageDrawerSource(null);
          setStageDrawerKey(null);
        }}
        onRetry={(sourceId) => {
          const source = sources.find((item) => item.id === sourceId);
          if (source) {
            void handleSourceRetry(source, "从阶段详情重试");
          }
        }}
      />
    </FAPageScaffold>
  );
}
