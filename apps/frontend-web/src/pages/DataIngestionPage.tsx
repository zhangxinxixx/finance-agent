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
  filterSourcesByStage,
  getGlobalDataFreshness,
} from "@/components/data-ingestion/dataIngestionPageModel";
import {
  BlockingIssuesPanel,
  IngestionActionsPanel,
  SourceDetailPanel,
} from "@/components/data-ingestion/DataIngestionSidePanels";
import { PipelineRunsLog } from "@/components/data-ingestion/PipelineRunsLog";
import { PipelineStageProgress } from "@/components/data-ingestion/PipelineStageProgress";
import { SourcePipelineMatrix } from "@/components/data-ingestion/SourcePipelineMatrix";
import { SourceStageDetailDrawer } from "@/components/data-ingestion/SourceStageDetailDrawer";
import { FAPageScaffold } from "@/components/shared/FAPageScaffold";
import { FAWorkspaceHeader } from "@/components/shared/FAWorkspaceHeader";
import { Database, RefreshCw } from "lucide-react";

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
  const { globalDataDate } = getGlobalDataFreshness(sources, systemStatus);
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
    <FAPageScaffold
      className="data-ingestion-page-shell"
      toolbar={(
        <FAWorkspaceHeader
          className="data-ingestion-workspace-header"
          icon={Database}
          title="数据接入"
          actions={(
            <button type="button" onClick={ingestion.refetch} className="fa-workspace-toolbar-button">
              <RefreshCw size={12} />
              刷新
            </button>
          )}
          primaryLabel="数据源"
          primaryItems={[
            { label: "可用", value: `${vmSummary?.available_count ?? 0}/${sources.length}` },
            { label: "待处理", value: degradedCount },
            ...(globalDataDate ? [{ label: "数据日期", value: globalDataDate }] : []),
          ]}
          secondaryLabel="运行"
          secondaryItems={[
            ...(systemStatus?.latest_run_created_at ? [{ label: "最近", value: systemStatus.latest_run_created_at.slice(0, 16).replace("T", " ") }] : []),
          ]}
        />
      )}
      bodyClassName="fa-page-stack"
    >
      <CriticalAlertBanner sources={sources} />

      <PipelineStageProgress
        sources={sources}
        onStageFilter={setStageFilter}
        activeFilter={stageFilter}
      />

      <div className="fa-split-grid fa-split-grid--right data-ingestion-main-grid">
        <div className="data-ingestion-left-stack">
          <SourcePipelineMatrix
            sources={filteredSources}
            selectedId={selectedSourceId}
            onSelect={handleSourceSelect}
            onStageClick={(sourceId, stageKey) => {
              setStageDrawerSource(sourceId);
              setStageDrawerKey(stageKey);
            }}
          />
          <PipelineRunsLog sources={sources} />
        </div>

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
