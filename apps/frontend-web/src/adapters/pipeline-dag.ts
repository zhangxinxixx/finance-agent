// ── Pipeline DAG Adapter ──────────────────────────────────────
// Primary: Uses Dagster graph topology for accurate DAG structure.
// Fallback: Builds DAG from task_runs + agent_outputs heuristics.

import { fetchSchedulerOverview } from "@/adapters/scheduler";
import {
  fetchAgentAnalysis,
  agentAnalysisToTaskRun,
  type SchedulerTaskRun,
  type AgentAnalysisItem,
} from "@/adapters/scheduler";
import {
  fetchDagsterGraphTopology,
  fetchDagsterRuns,
  fetchDagsterRunDetail,
  buildDagsterDagGraph,
  type DagsterGraphTopology,
  type DagsterRunSummary,
} from "@/adapters/dagster";
import {
  DAG_GROUPS,
  DAG_GROUP_ORDER,
  aggregateDagStatus,
  attachDagLineage,
  buildFixedTaskDataFlowEdges,
  groupForTaskLike,
  taskNodesForTaskLike,
} from "@/adapters/pipeline-dag-groups";
import type {
  DagNodeSpec,
  DagNodeType,
  DagNodeStatus,
  DagEdge,
  DagGraph,
  DagSourceRef,
  DagArtifactRef,
} from "@/types/pipeline-dag";

export type {
  DagNodeSpec,
  DagNodeType,
  DagNodeStatus,
  DagEdge,
  DagGraph,
  DagSourceRef,
  DagArtifactRef,
};

// ── Stage Mapping ──
const STAGE_ORDER: DagNodeType[] = ["collector", "parser", "features", "analysis", "output"];

const STAGE_COLORS: Record<DagNodeType, string> = {
  collector: "#3b82f6",
  parser:    "#f59e0b",
  features:  "#8b5cf6",
  analysis:  "#10b981",
  output:    "#06b6d4",
};

const STAGE_LABELS: Record<DagNodeType, string> = {
  collector: "采集",
  parser:    "解析",
  features:  "特征",
  analysis:  "分析",
  output:    "输出",
};

export { STAGE_ORDER, STAGE_COLORS, STAGE_LABELS };

// ── Type → Stage ──
export function taskTypeToDagStage(taskType: string): DagNodeType {
  const t = taskType.toLowerCase();
  if (t.includes("collect") || t.includes("fetch") || t.includes("data") ||
      ["technical", "positioning", "dxy", "treasury", "fed", "fred"].includes(t))
    return "collector";
  if (t.includes("parse") || t.includes("extract") || t.includes("ocr"))
    return "parser";
  if (t.includes("feature") || t.includes("compute") || t.includes("calculate"))
    return "features";
  if (t.includes("analy") || t.includes("agent") || t.includes("regime") || t.includes("impact"))
    return "analysis";
  if (t.includes("render") || t.includes("report") || t.includes("output") ||
      t.includes("generate") || t.includes("strategy") || t.includes("jin10"))
    return "output";
  return "analysis";
}

// ── Status Normalization ──
export function normalizeStatus(status: string): DagNodeStatus {
  const s = status.toLowerCase();
  if (s === "success") return "success";
  if (s === "failed" || s === "blocked" || s === "stale") return "failed";
  if (s === "running") return "running";
  if (s === "pending" || s === "queued") return "pending";
  if (s === "partial" || s === "partial_success") return "partial";
  return "pending";
}

// ── TaskRun → DagNode (fallback path) ──
export function taskRunToDagNode(run: SchedulerTaskRun): DagNodeSpec {
  const stage = taskTypeToDagStage(run.task_type);
  const status = normalizeStatus(run.status);

  const durationMs = run.started_at && run.ended_at
    ? new Date(run.ended_at).getTime() - new Date(run.started_at).getTime()
    : null;

  return {
    node_id: run.run_id,
    type: stage,
    label: run.task_name,
    sub_type: run.task_type,
    trade_date: run.trade_date,
    status,
    category: run.category,
    module: run.category || stage,
    input: {
      source: "task_run",
      summary: `Task: ${run.task_type}`,
      fields: { task_type: run.task_type, category: run.category },
      source_refs: [],
      artifact_refs: [],
    },
    output: {
      source: run.snapshot_id || run.run_id,
      summary: `Snapshot: ${run.snapshot_id || "N/A"}`,
      fields: { status: run.status, progress: run.progress },
      source_refs: [],
      artifact_refs: [],
    },
    execution: {
      started_at: run.started_at,
      ended_at: run.ended_at,
      duration_ms: durationMs,
      retries: 0,
    },
    upstream_ids: [],
    downstream_ids: [],
  };
}

// ── AgentOutput → DagNode (fallback path) ──
export function agentOutputToDagNode(a: AgentAnalysisItem): DagNodeSpec {
  const stage = taskTypeToDagStage(a.agent_name);
  const status = normalizeStatus(a.status);

  return {
    node_id: a.agent_output_id,
    type: stage,
    label: a.display_name || a.agent_name,
    sub_type: a.agent_name,
    trade_date: a.trade_date || null,
    status,
    category: a.module || "analysis",
    module: a.module || "analysis",
    input: {
      source: "agent_analysis",
      summary: `Agent: ${a.agent_name}`,
      fields: { registry_id: a.registry_id, module: a.module },
      source_refs: [],
      artifact_refs: [],
    },
    output: {
      source: a.snapshot_id || a.agent_output_id,
      summary: `Snapshot: ${a.snapshot_id || "N/A"}`,
      fields: { status: a.status },
      source_refs: [],
      artifact_refs: [],
    },
    execution: {
      started_at: null,
      ended_at: null,
      duration_ms: null,
      retries: 0,
    },
    upstream_ids: [],
    downstream_ids: [],
  };
}

// ── Build Edges (fallback: heuristic stage-based) ──
export function buildDagEdges(nodes: DagNodeSpec[]): DagEdge[] {
  const edges: DagEdge[] = [];

  const groups = new Map<string, DagNodeSpec[]>();
  for (const n of nodes) {
    const key = `${n.trade_date || "any"}::${n.type}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key)!.push(n);
  }

  const tradeDates = new Set(nodes.map(n => n.trade_date || "any"));

  for (const td of tradeDates) {
    for (let i = 0; i < STAGE_ORDER.length - 1; i++) {
      const fromStage = STAGE_ORDER[i];
      const toStage = STAGE_ORDER[i + 1];

      const fromKey = `${td}::${fromStage}`;
      const toKey = `${td}::${toStage}`;

      const fromNodes = groups.get(fromKey) || [];
      const toNodes = groups.get(toKey) || [];

      for (const from of fromNodes) {
        for (const to of toNodes) {
          const stageKey = `${fromStage}→${toStage}`;
          const edgeType = stageKey.includes("analysis→output") ? "signal_flow" as const
                         : stageKey.includes("→") ? "data_flow" as const
                         : "dependency" as const;

          edges.push({
            from: from.node_id,
            to: to.node_id,
            edge_type: edgeType,
            data_contract: {
              fields: Object.keys(from.output.fields),
              stage: stageKey,
            },
          });
          from.downstream_ids.push(to.node_id);
          to.upstream_ids.push(from.node_id);
        }
      }
    }
  }

  return edges;
}

// ── Build Full DAG Graph (fallback path) ──
export interface DagGraphInput {
  taskRuns: SchedulerTaskRun[];
  agentOutputs: AgentAnalysisItem[];
  tradeDateFilter?: string;
}

export function buildDagGraph(input: DagGraphInput): DagGraph {
  const { taskRuns, agentOutputs, tradeDateFilter } = input;

  let taskRunsFiltered = taskRuns;
  let agentsFiltered = agentOutputs;

  if (tradeDateFilter) {
    taskRunsFiltered = taskRuns.filter(r => r.trade_date === tradeDateFilter);
    agentsFiltered = agentOutputs.filter(a => a.trade_date === tradeDateFilter);
  }

  const taskNodes = taskRunsFiltered.map(taskRunToDagNode);
  const agentNodes = agentsFiltered.map(agentOutputToDagNode);
  const sourceNodes = [...taskNodes, ...agentNodes];

  const allNodes = DAG_GROUP_ORDER
    .flatMap((groupId) => {
      const meta = DAG_GROUPS[groupId];
      return meta.tasks.map((task) => {
        const matchedMembers: DagNodeSpec[] = sourceNodes.filter((node) => {
          const nodeGroupId = groupForTaskLike(node.sub_type, node.category);
          return nodeGroupId === groupId && taskNodesForTaskLike(groupId, node.sub_type, node.category).includes(task.id);
        });
        const startedAt = matchedMembers.map((node) => node.execution.started_at).filter(Boolean).sort()[0] ?? null;
        const endedAt = matchedMembers.map((node) => node.execution.ended_at).filter(Boolean).sort().reverse()[0] ?? null;
        const status = aggregateDagStatus(matchedMembers.map((node) => node.status));
        const memberTradeDate = matchedMembers.find((node: DagNodeSpec) => node.trade_date)?.trade_date ?? null;
        const memberSubTypes = matchedMembers.map((node: DagNodeSpec) => node.sub_type);
        const memberLabels = matchedMembers.map((node: DagNodeSpec) => node.label);

        return {
          node_id: task.id,
          type: meta.type,
          label: task.label,
          sub_type: meta.label,
          trade_date: tradeDateFilter || memberTradeDate,
          status,
          category: meta.id,
          module: meta.module,
          input: {
            source: "task_run_read_model",
            summary: task.description,
            fields: {
              group_id: meta.id,
              group_label: meta.label,
              task_id: task.id,
              task_count: matchedMembers.length,
              members: memberSubTypes,
            },
            source_refs: [],
            artifact_refs: [],
          },
          output: {
            source: "task_run_read_model",
            summary: matchedMembers.length > 0 ? matchedMembers.slice(0, 4).map((node) => node.label).join(" / ") : meta.summary,
            fields: {
              status,
              group_order: meta.order,
              task_count: matchedMembers.length,
              members: memberLabels,
            },
            source_refs: [],
            artifact_refs: [],
          },
          execution: {
            started_at: startedAt,
            ended_at: endedAt,
            duration_ms: null,
            retries: 0,
          },
          upstream_ids: [],
          downstream_ids: [],
        } satisfies DagNodeSpec;
      });
    });

  const edges: DagEdge[] = buildFixedTaskDataFlowEdges(allNodes);
  attachDagLineage(allNodes, edges);

  return {
    nodes: allNodes,
    edges,
    trade_date: tradeDateFilter || "all",
    generated_at: new Date().toISOString(),
  };
}

// ── Fetch & Build (Dagster primary, fallback to legacy) ──

let _cachedTopology: DagsterGraphTopology | null = null;

async function tryDagsterPath(): Promise<DagGraph | null> {
  try {
    // Fetch topology (cached)
    if (!_cachedTopology) {
      _cachedTopology = await fetchDagsterGraphTopology();
    }
    const topology = _cachedTopology;
    if (!topology || topology.ops.length === 0) return null;

    // Fetch latest run for status
    const runs = await fetchDagsterRuns("premarket_job", 1);
    const latestRun = runs[0] ?? null;
    const latestDetail = latestRun ? await fetchDagsterRunDetail(latestRun.runId) : null;

    return buildDagsterDagGraph(topology, runs, latestDetail);
  } catch {
    return null;
  }
}

export async function fetchDagGraph(days: number, tradeDateFilter?: string): Promise<DagGraph> {
  // Try Dagster first
  const dagsterGraph = await tryDagsterPath();
  if (dagsterGraph) return dagsterGraph;

  // Fallback to legacy API
  const overview = await fetchSchedulerOverview(days);
  const agentData = await fetchAgentAnalysis("latest");

  return buildDagGraph({
    taskRuns: overview.task_runs,
    agentOutputs: agentData,
    tradeDateFilter,
  });
}
