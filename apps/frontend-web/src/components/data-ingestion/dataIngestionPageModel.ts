import type {
  DataIngestionSystemStatusViewModel,
  DataSourceStatusViewModel,
  PipelineStageKey,
} from "@/types/data-ingestion";

export function computePipelineStats(sources: DataSourceStatusViewModel[]) {
  const total = sources.length;
  let rawReady = 0;
  let parseReady = 0;
  let snapshotReady = 0;
  let consumerReady = 0;

  for (const source of sources) {
    const stages = source.pipeline_health.stages;
    if (stages.rawLanding.status === "OK") rawReady++;
    if (stages.parse.status === "OK") parseReady++;
    if (stages.snapshot.status === "READY" || stages.snapshot.status === "OK") snapshotReady++;
    if (stages.consumerReady.status === "READY" || stages.consumerReady.status === "OK") consumerReady++;
  }

  return { total, rawReady, parseReady, snapshotReady, consumerReady };
}

export function getGlobalDataFreshness(
  sources: DataSourceStatusViewModel[],
  systemStatus: DataIngestionSystemStatusViewModel | null,
) {
  const allDates = sources
    .map((source) => source.pipeline_health.latestDataDate)
    .filter((date): date is string => Boolean(date))
    .sort()
    .reverse();
  const globalDataDate = systemStatus?.data_date ?? allDates[0] ?? null;
  const globalStaleness = globalDataDate
    ? Math.floor((new Date().getTime() - new Date(globalDataDate).getTime()) / 86400000)
    : null;
  return { globalDataDate, globalStaleness };
}

export function filterSourcesByStage(
  sources: DataSourceStatusViewModel[],
  stageFilter: PipelineStageKey | null,
) {
  if (!stageFilter) return sources;
  return sources.filter((source) => {
    const stage = source.pipeline_health.stages[stageFilter];
    return stage.status !== "OK" && stage.status !== "READY";
  });
}
