// ── Dagster GraphQL Adapter ──────────────────────────────────────
// Queries Dagster's GraphQL API for pipeline runs, graph topology, and step events.
// Transforms responses into the same shapes the existing UI expects.

const DAGSTER_GRAPHQL_URL =
  import.meta.env.VITE_DAGSTER_GRAPHQL_URL?.trim() || "/dagster/graphql";

// ── Low-level GraphQL client ──

interface GraphQLResponse<T> {
  data: T | null;
  errors?: Array<{ message: string; locations?: Array<{ line: number; column: number }> }>;
}

async function dagsterQuery<T>(query: string, variables?: Record<string, unknown>): Promise<T> {
  const res = await fetch(DAGSTER_GRAPHQL_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ query, variables }),
  });

  if (!res.ok) {
    throw new Error(`Dagster GraphQL ${res.status}: ${res.statusText}`);
  }

  const json = (await res.json()) as GraphQLResponse<T>;
  if (json.errors?.length) {
    throw new Error(`Dagster GraphQL error: ${json.errors.map((e) => e.message).join("; ")}`);
  }
  if (!json.data) {
    throw new Error("Dagster GraphQL returned null data");
  }
  return json.data;
}

// ── Dagster raw types (from GraphQL) ──

interface DagsterRun {
  runId: string;
  jobName: string;
  status: string;           // SUCCESS, FAILURE, STARTING, CANCELING, etc.
  creationTime: number;
  startTime: number | null;
  endTime: number | null;
  tags: Array<{ key: string; value: string }>;
  mode: string;
  repositoryOrigin: { repositoryName: string; repositoryLocationName: string } | null;
}

interface DagsterRunStepEvent {
  stepKey: string;
  eventType: string;        // STEP_START, STEP_SUCCESS, STEP_FAILURE, etc.
  timestamp: number;
  level: string;
  message: string | null;
}

interface DagsterRunDetail extends DagsterRun {
  stepEvents: DagsterRunStepEvent[];
  runConfigYaml: string | null;
}

interface DagsterPipelineSnapshot {
  name: string;
  description: string | null;
  solids: Array<{
    name: string;
    definition: { name: string; description: string | null; metadata: Array<{ key: string; value: string }> };
    inputs: Array<{ name: string; dependsOn: { solid: { name: string } } | null }>;
    outputs: Array<{ name: string; dependedBy: Array<{ solid: { name: string } }> }>;
  }>;
}

interface DagsterSchedule {
  name: string;
  cronSchedule: string;
  executionTimezone: string;
  jobName: string;
  scheduleState: { status: string; id: string; runs: Array<{ runId: string; status: string; creationTime: number }> } | null;
}

// ── GraphQL Queries ──

const RUNS_QUERY = `
  query RunsQuery($jobName: String!, $limit: Int!) {
    runsOrError(
      filter: { pipelineName: $jobName }
      limit: $limit
    ) {
      ... on Runs {
        results {
          runId
          jobName
          status
          creationTime
          startTime
          endTime
          tags { key value }
          mode
          repositoryOrigin { repositoryName repositoryLocationName }
        }
      }
    }
  }
`;

const RUN_DETAIL_QUERY = `
  query RunDetailQuery($runId: ID!) {
    runOrError(runId: $runId) {
      ... on Run {
        runId
        jobName
        status
        creationTime
        startTime
        endTime
        tags { key value }
        mode
        runConfigYaml
        repositoryOrigin { repositoryName repositoryLocationName }
        stepEvents {
          ... on StepEvent {
            stepKey
            eventType
            timestamp
            level
            message
          }
          ... on ExecutionStepFailureEvent {
            stepKey
            eventType
            timestamp
            level
            message
            error { message stack }
          }
          ... on ExecutionStepSuccessEvent {
            stepKey
            eventType
            timestamp
            level
            message
          }
        }
      }
      ... on RunNotFoundError {
        message
      }
    }
  }
`;

const PIPELINE_SNAPSHOT_QUERY = `
  query PipelineSnapshotQuery($jobName: String!) {
    pipelineOrError(params: { pipelineName: $jobName, repositoryName: "__repository__", repositoryLocationName: "dagster_finance.definitions" }) {
      ... on Pipeline {
        name
        description
        solids {
          name
          definition { name description metadata { key value } }
          inputs { name dependsOn { solid { name } } }
          outputs { name dependedBy { solid { name } } }
        }
      }
      ... on PipelineNotFoundError {
        message
      }
    }
  }
`;

const SCHEDULES_QUERY = `
  query SchedulesQuery {
    schedulesOrError {
      ... on Schedules {
        results {
          name
          cronSchedule
          executionTimezone
          jobName
          scheduleState {
            status
            id
            runs(limit: 1) {
              runId
              status
              creationTime
            }
          }
        }
      }
    }
  }
`;

const LAUNCH_RUN_MUTATION = `
  mutation LaunchRun($jobName: String!) {
    launchPipelineExecution(
      executionParams: {
        selector: {
          pipelineName: $jobName
          repositoryName: "__repository__"
          repositoryLocationName: "dagster_finance.definitions"
        }
        mode: "default"
      }
    ) {
      ... on LaunchRunSuccess {
        run { runId status }
      }
      ... on PythonError {
        message
      }
    }
  }
`;

// ── Status mapping (Dagster → UI) ──

const DAGSTER_STATUS_MAP: Record<string, string> = {
  SUCCESS: "success",
  FAILURE: "failed",
  STARTING: "running",
  STARTED: "running",
  CANCELING: "running",
  CANCELED: "cancelled",
  QUEUED: "queued",
  NOT_STARTED: "pending",
};

export function mapDagsterStatus(dagsterStatus: string): string {
  return DAGSTER_STATUS_MAP[dagsterStatus.toUpperCase()] || dagsterStatus.toLowerCase();
}

// ── Tag helpers ──

function getTag(run: DagsterRun, key: string): string | null {
  return run.tags.find((t) => t.key === key)?.value ?? null;
}

function getTradeDate(run: DagsterRun): string | null {
  return getTag(run, "trade_date") ?? null;
}

function getPipelineTag(run: DagsterRun): string | null {
  return getTag(run, "pipeline") ?? null;
}

// ── Exported adapter functions ──

export interface DagsterRunSummary {
  runId: string;
  jobName: string;
  status: string;
  tradeDate: string | null;
  pipeline: string | null;
  startedAt: string | null;
  endedAt: string | null;
  createdAt: string;
  tags: Record<string, string>;
}

export async function fetchDagsterRuns(jobName = "premarket_job", limit = 50): Promise<DagsterRunSummary[]> {
  const data = await dagsterQuery<{ runsOrError: { results: DagsterRun[] } | { message: string } }>(
    RUNS_QUERY,
    { jobName, limit },
  );

  const runsOrError = data.runsOrError;
  if (!("results" in runsOrError)) return [];

  return runsOrError.results.map((run) => ({
    runId: run.runId,
    jobName: run.jobName,
    status: mapDagsterStatus(run.status),
    tradeDate: getTradeDate(run),
    pipeline: getPipelineTag(run),
    startedAt: run.startTime ? new Date(run.startTime * 1000).toISOString() : null,
    endedAt: run.endTime ? new Date(run.endTime * 1000).toISOString() : null,
    createdAt: new Date(run.creationTime * 1000).toISOString(),
    tags: Object.fromEntries(run.tags.map((t) => [t.key, t.value])),
  }));
}

export interface DagsterStepEvent {
  stepKey: string;
  eventType: string;
  timestamp: string;
  level: string;
  message: string | null;
}

export interface DagsterRunDetailResult {
  runId: string;
  jobName: string;
  status: string;
  tradeDate: string | null;
  startedAt: string | null;
  endedAt: string | null;
  stepEvents: DagsterStepEvent[];
  runConfigYaml: string | null;
  tags: Record<string, string>;
}

export async function fetchDagsterRunDetail(runId: string): Promise<DagsterRunDetailResult | null> {
  const data = await dagsterQuery<{ runOrError: DagsterRunDetail | { message: string } }>(
    RUN_DETAIL_QUERY,
    { runId },
  );

  const runOrError = data.runOrError;
  if ("message" in runOrError) return null;

  const run = runOrError;
  return {
    runId: run.runId,
    jobName: run.jobName,
    status: mapDagsterStatus(run.status),
    tradeDate: getTradeDate(run),
    startedAt: run.startTime ? new Date(run.startTime * 1000).toISOString() : null,
    endedAt: run.endTime ? new Date(run.endTime * 1000).toISOString() : null,
    stepEvents: (run.stepEvents || []).map((e) => ({
      stepKey: e.stepKey,
      eventType: e.eventType,
      timestamp: new Date(e.timestamp * 1000).toISOString(),
      level: e.level,
      message: e.message,
    })),
    runConfigYaml: run.runConfigYaml,
    tags: Object.fromEntries(run.tags.map((t) => [t.key, t.value])),
  };
}

export async function launchDagsterRun(jobName = "premarket_job"): Promise<{ runId: string; status: string } | null> {
  const data = await dagsterQuery<{
    launchPipelineExecution: { run: { runId: string; status: string } } | { message: string };
  }>(LAUNCH_RUN_MUTATION, { jobName });

  const result = data.launchPipelineExecution;
  if ("run" in result) {
    return { runId: result.run.runId, status: result.run.status };
  }
  throw new Error("message" in result ? result.message : "Launch failed");
}

// ── Graph Topology ──

export interface DagsterOpNode {
  name: string;
  description: string | null;
  inputs: Array<{ name: string; upstreamOp: string | null }>;
  outputs: Array<{ name: string; downstreamOps: string[] }>;
}

export interface DagsterGraphTopology {
  jobName: string;
  description: string | null;
  ops: DagsterOpNode[];
}

export async function fetchDagsterGraphTopology(jobName = "premarket_job"): Promise<DagsterGraphTopology | null> {
  const data = await dagsterQuery<{
    pipelineOrError: DagsterPipelineSnapshot | { message: string };
  }>(PIPELINE_SNAPSHOT_QUERY, { jobName });

  const pipeline = data.pipelineOrError;
  if ("message" in pipeline) return null;

  return {
    jobName: pipeline.name,
    description: pipeline.description,
    ops: pipeline.solids.map((solid) => ({
      name: solid.name,
      description: solid.definition.description,
      inputs: solid.inputs.map((inp) => ({
        name: inp.name,
        upstreamOp: inp.dependsOn?.solid?.name ?? null,
      })),
      outputs: solid.outputs.map((out) => ({
        name: out.name,
        downstreamOps: out.dependedBy.map((d) => d.solid.name),
      })),
    })),
  };
}

// ── Schedules ──

export interface DagsterScheduleInfo {
  name: string;
  cronSchedule: string;
  executionTimezone: string;
  jobName: string;
  status: string;
  lastRunId: string | null;
  lastRunStatus: string | null;
  lastRunAt: string | null;
}

export async function fetchDagsterSchedules(): Promise<DagsterScheduleInfo[]> {
  const data = await dagsterQuery<{ schedulesOrError: { results: DagsterSchedule[] } }>(
    SCHEDULES_QUERY,
  );

  return data.schedulesOrError.results.map((s) => {
    const lastRun = s.scheduleState?.runs?.[0];
    return {
      name: s.name,
      cronSchedule: s.cronSchedule,
      executionTimezone: s.executionTimezone,
      jobName: s.jobName,
      status: s.scheduleState?.status ?? "UNKNOWN",
      lastRunId: lastRun?.runId ?? null,
      lastRunStatus: lastRun?.status ?? null,
      lastRunAt: lastRun?.creationTime ? new Date(lastRun.creationTime * 1000).toISOString() : null,
    };
  });
}

// ── Build DagGraph from Dagster topology + runs ──

import type { DagGraph, DagNodeSpec, DagEdge, DagNodeType } from "@/types/pipeline-dag";
import {
  DAG_GROUPS,
  DAG_GROUP_ORDER,
  aggregateDagStatus,
  attachDagLineage,
  buildFixedTaskDataFlowEdges,
  taskNodesForOpName,
} from "@/adapters/pipeline-dag-groups";

const OP_TO_STAGE: Record<string, DagNodeType> = {
  macro_init_op: "collector",
  macro_collect_op: "collector",
  macro_feature_op: "features",
  report_render_op: "output",
  cme_init_op: "collector",
  cme_download_op: "collector",
  cme_parse_op: "parser",
  cme_ingest_op: "parser",
  option_wall_op: "features",
  news_init_op: "collector",
  news_collect_op: "collector",
  news_feature_op: "features",
  news_brief_op: "output",
  macro_liquidity_agent_op: "analysis",
  cme_options_agent_op: "analysis",
  risk_agent_op: "analysis",
  technical_agent_op: "analysis",
  positioning_agent_op: "analysis",
  news_agent_op: "analysis",
  market_odds_agent_op: "analysis",
  coordinator_op: "analysis",
  strategy_card_op: "output",
  merge_analysis_snapshot_op: "features",
};

const OP_LABELS: Record<string, string> = {
  macro_init_op: "宏观初始化",
  macro_collect_op: "宏观数据采集",
  macro_feature_op: "宏观特征工程",
  report_render_op: "宏观报告渲染",
  cme_init_op: "CME初始化",
  cme_download_op: "CME下载",
  cme_parse_op: "CME解析",
  cme_ingest_op: "CME入库",
  option_wall_op: "期权墙分析",
  news_init_op: "新闻初始化",
  news_collect_op: "新闻采集",
  news_feature_op: "新闻特征",
  news_brief_op: "新闻简报",
  macro_liquidity_agent_op: "宏观流动性",
  cme_options_agent_op: "CME期权",
  risk_agent_op: "风险评估",
  technical_agent_op: "技术分析",
  positioning_agent_op: "持仓分析",
  news_agent_op: "新闻分析",
  market_odds_agent_op: "市场概率",
  coordinator_op: "协调器",
  strategy_card_op: "策略卡片",
  merge_analysis_snapshot_op: "快照合并",
};

function findStepStatus(stepEvents: DagsterStepEvent[], opName: string): string {
  // Look for step events matching this op name
  // Dagster step keys use format: graph_name.op_name for nested graphs
  const relevant = stepEvents.filter((e) => e.stepKey.includes(opName));
  if (relevant.length === 0) return "pending";

  const hasFailure = relevant.some((e) => e.eventType.includes("FAILURE"));
  const hasSuccess = relevant.some((e) => e.eventType.includes("SUCCESS"));
  const hasStart = relevant.some((e) => e.eventType.includes("START"));

  if (hasFailure) return "failed";
  if (hasSuccess) return "success";
  if (hasStart) return "running";
  return "pending";
}

export function buildDagsterDagGraph(
  topology: DagsterGraphTopology,
  runs: DagsterRunSummary[],
  latestRunDetail: DagsterRunDetailResult | null,
): DagGraph {
  const stepEvents = latestRunDetail?.stepEvents ?? [];
  const tradeDate = latestRunDetail?.tradeDate ?? runs[0]?.tradeDate ?? null;

  const nodes: DagNodeSpec[] = DAG_GROUP_ORDER
    .flatMap((groupId) => {
      const meta = DAG_GROUPS[groupId];
      return meta.tasks.map((task) => {
        const matchedOps = topology.ops.filter((op) => taskNodesForOpName(groupId, op.name).includes(task.id));
        const statuses = matchedOps.map((op) => (
          latestRunDetail ? findStepStatus(stepEvents, op.name) as DagNodeSpec["status"] : "pending"
        ));
        const status = aggregateDagStatus(statuses);
        const memberLabels = matchedOps.map((op) => OP_LABELS[op.name] || op.name);

        return {
          node_id: task.id,
          type: meta.type,
          label: task.label,
          sub_type: meta.label,
          trade_date: tradeDate,
          status,
          category: meta.id,
          module: meta.module,
          input: {
            source: "dagster_task",
            summary: task.description,
            fields: {
              group_id: meta.id,
              group_label: meta.label,
              task_id: task.id,
              matched_ops: matchedOps.map((op) => op.name),
              op_count: matchedOps.length,
            },
            source_refs: [],
            artifact_refs: [],
          },
          output: {
            source: "dagster_task",
            summary: memberLabels.length > 0 ? memberLabels.join(" / ") : meta.summary,
            fields: {
              status,
              group_order: meta.order,
              matched_ops: memberLabels,
              op_count: matchedOps.length,
            },
            source_refs: [],
            artifact_refs: [],
          },
          execution: {
            started_at: matchedOps.length > 0 ? latestRunDetail?.startedAt ?? null : null,
            ended_at: matchedOps.length > 0 ? latestRunDetail?.endedAt ?? null : null,
            duration_ms: null,
            retries: 0,
          },
          upstream_ids: [],
          downstream_ids: [],
        } satisfies DagNodeSpec;
      });
    });

  const edges: DagEdge[] = buildFixedTaskDataFlowEdges(nodes);
  attachDagLineage(nodes, edges);

  return {
    nodes,
    edges,
    trade_date: tradeDate || "all",
    generated_at: new Date().toISOString(),
  };
}
