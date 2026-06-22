// ── useNodeDetail Hook ──────────────────────────────────────
// 点击 DAG 节点后拉取真实 task_steps / agent 数据，填充 Inspector

import { useEffect, useState } from "react";
import {
  fetchRunDetail,
  type RunDetail,
  type RunStep,
  type AgentAnalysisItem,
} from "@/adapters/scheduler";
import { fetchDagsterRunDetail, type DagsterRunDetailResult } from "@/adapters/dagster";
import type { DagNodeSpec, DagSourceRef, DagArtifactRef } from "@/types/pipeline-dag";

export interface NodeDetailResult {
  detail: DagNodeSpec | null;
  isLoading: boolean;
  error: string | null;
}

function extractSourceRefs(steps: RunStep[]): DagSourceRef[] {
  const refs: DagSourceRef[] = [];
  for (const s of steps) {
    if (s.source_refs && Array.isArray(s.source_refs)) {
      for (const ref of s.source_refs) {
        if (ref && typeof ref === "object") {
          refs.push({
            source_ref: (ref as any).source_name || (ref as any).source_id || "unknown",
            label: (ref as any).source_name || (ref as any).source_id || "unknown",
            endpoint: (ref as any).endpoint || null,
            artifact_path: (ref as any).file_path || null,
            status: (ref as any).status || "unknown",
          });
        }
      }
    }
  }
  return refs;
}

function extractArtifactRefs(steps: RunStep[]): DagArtifactRef[] {
  const refs: DagArtifactRef[] = [];
  const seen = new Set<string>();
  for (const s of steps) {
    const allRefs = [
      ...(s.output_refs && Array.isArray(s.output_refs) ? s.output_refs : []),
      ...(s.artifact_refs && Array.isArray(s.artifact_refs) ? s.artifact_refs : []),
    ];
    for (const ref of allRefs) {
      if (ref && typeof ref === "object") {
        const id = (ref as any).artifact_id || (ref as any).file_path || JSON.stringify(ref);
        if (!seen.has(id)) {
          seen.add(id);
          refs.push({
            artifact_id: (ref as any).artifact_id || (ref as any).file_path || "unknown",
            artifact_type: (ref as any).artifact_type || "unknown",
            file_path: (ref as any).file_path || null,
          });
        }
      }
    }
  }
  return refs;
}

function populateFromRunDetail(node: DagNodeSpec, detail: RunDetail): DagNodeSpec {
  const sourceRefs = extractSourceRefs(detail.steps || []);
  const artifactRefs = extractArtifactRefs(detail.steps || []);

  // Build input/output fields from source_refs and artifact_refs
  const inputFields: Record<string, unknown> = {};
  for (const ref of sourceRefs.slice(0, 8)) {
    inputFields[ref.label] = ref.endpoint || ref.artifact_path || ref.status;
  }

  const outputFields: Record<string, unknown> = {};
  for (const ref of artifactRefs.slice(0, 8)) {
    outputFields[ref.artifact_type] = ref.file_path || ref.artifact_id;
  }

  // Collect step-level input_json/output_json
  const stepInputJsons: Record<string, unknown>[] = [];
  const stepOutputJsons: Record<string, unknown>[] = [];
  const stepErrorJsons: Record<string, unknown>[] = [];
  for (const s of detail.steps || []) {
    if (s.input_json && typeof s.input_json === "object") stepInputJsons.push(s.input_json);
    if (s.output_json && typeof s.output_json === "object") stepOutputJsons.push(s.output_json);
    if (s.error_json && typeof s.error_json === "object") stepErrorJsons.push(s.error_json);
  }

  // Compute duration
  const durationMs = detail.started_at && detail.ended_at
    ? new Date(detail.ended_at).getTime() - new Date(detail.started_at).getTime()
    : null;

  // Total retries across steps
  const totalRetries = (detail.steps || []).reduce((sum, s) => sum + (s.retry_count || 0), 0);

  return {
    ...node,
    input: {
      source: "task_run",
      summary: detail.error_summary || `${detail.steps?.length || 0} steps`,
      fields: Object.keys(inputFields).length > 0 ? inputFields : { task_type: detail.task_type, status: detail.status },
      source_refs: sourceRefs,
      artifact_refs: artifactRefs,
      step_jsons: stepInputJsons,
    } as any,
    output: {
      source: detail.run_id,
      summary: detail.status,
      fields: Object.keys(outputFields).length > 0 ? outputFields : { status: detail.status, progress: detail.progress ?? "N/A" },
      source_refs: sourceRefs,
      artifact_refs: artifactRefs,
      step_jsons: stepOutputJsons,
    } as any,
    execution: {
      started_at: detail.started_at,
      ended_at: detail.ended_at,
      duration_ms: durationMs,
      retries: totalRetries,
      events: detail.events ?? [],
      step_errors: stepErrorJsons,
    } as any,
  };
}

function populateFromAgentOutput(node: DagNodeSpec, agent: AgentAnalysisItem): DagNodeSpec {
  return {
    ...node,
    input: {
      source: "agent_analysis",
      summary: `Agent: ${agent.agent_name}`,
      fields: {
        registry_id: agent.registry_id,
        module: agent.module,
        version: (agent as any).version || "N/A",
      },
      source_refs: [],
      artifact_refs: [],
    },
    output: {
      source: agent.snapshot_id || agent.agent_output_id,
      summary: agent.status,
      fields: {
        status: agent.status,
        bias: (agent as any).bias || "N/A",
        confidence: (agent as any).confidence || "N/A",
      },
      source_refs: [],
      artifact_refs: [],
    },
    execution: {
      started_at: null,
      ended_at: null,
      duration_ms: null,
      retries: 0,
      events: [],
    },
  };
}

export function useNodeDetail(
  nodeId: string | null,
  agentOutputs: AgentAnalysisItem[],
): NodeDetailResult {
  const [detail, setDetail] = useState<DagNodeSpec | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const baseNode = detail; // we start from null, build up

  useEffect(() => {
    if (!nodeId) {
      setDetail(null);
      setIsLoading(false);
      setError(null);
      return;
    }

    let cancelled = false;

    async function load() {
      if (!nodeId) return; // guard
      setIsLoading(true);
      setError(null);

      const id: string = nodeId; // narrowed for TS

      try {
        // Heuristic: agent_output_ids are in the list
        const agent = agentOutputs.find(a => a.agent_output_id === id);

        if (agent) {
          const node = populateFromAgentOutput(
            buildPlaceholderNode(id, agent),
            agent,
          );
          if (!cancelled) setDetail(node);
        } else {
          // Try Dagster first, then legacy API
          let runDetail: RunDetail | null = null;
          const dagsterDetail = await fetchDagsterRunDetail(id).catch(() => null);
          if (dagsterDetail) {
            runDetail = dagsterToRunDetail(dagsterDetail);
          } else {
            runDetail = await fetchRunDetail(id).catch(() => null);
          }

          if (runDetail) {
            const node = populateFromRunDetail(
              buildPlaceholderNode(id, runDetail),
              runDetail,
            );
            if (!cancelled) setDetail(node);
          } else {
            if (!cancelled) {
              setError(`节点 ${id.slice(0, 8)} 无详情数据`);
              setDetail(null);
            }
          }
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "加载节点详情失败");
          setDetail(null);
        }
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    }

    void load();
    return () => { cancelled = true; };
  }, [nodeId]);

  return { detail, isLoading, error };
}

// Convert Dagster run detail to the existing RunDetail shape
function dagsterToRunDetail(d: DagsterRunDetailResult): RunDetail {
  return {
    run_id: d.runId,
    name: d.jobName,
    task_type: d.tags?.pipeline || d.jobName,
    status: d.status,
    trade_date: d.tradeDate,
    progress: null,
    error: null,
    error_summary: d.stepEvents?.find(e => e.eventType.includes("FAILURE"))?.message ?? null,
    started_at: d.startedAt,
    ended_at: d.endedAt,
    events: d.stepEvents.map((e, i) => ({
      id: `${d.runId}-event-${i}`,
      run_id: d.runId,
      task_id: e.stepKey || null,
      event_type: e.eventType,
      payload: e.message ? { error_message: e.message, step_name: e.stepKey, source: "dagster" } : { step_name: e.stepKey, source: "dagster" },
      created_at: e.timestamp,
    })),
    steps: d.stepEvents.map((e, i) => ({
      step_id: `${d.runId}-${e.stepKey}-${i}`,
      name: e.stepKey,
      stage: e.stepKey,
      status: e.eventType.includes("SUCCESS") ? "success" : e.eventType.includes("FAILURE") ? "failed" : "running",
      step_order: i,
      error: e.eventType.includes("FAILURE") ? e.message : null,
      input_refs: null,
      output_refs: null,
      source_refs: null,
      artifact_refs: null,
      started_at: e.eventType.includes("START") ? e.timestamp : null,
      finished_at: e.eventType.includes("SUCCESS") || e.eventType.includes("FAILURE") ? e.timestamp : null,
      input_json: null,
      output_json: e.message ? { message: e.message } : null,
      error_json: e.eventType.includes("FAILURE") ? { message: e.message } : null,
      duration_ms: null,
      retry_count: 0,
    })),
  };
}

// Build a minimal placeholder node when we only have the ID
function buildPlaceholderNode(
  nodeId: string,
  source: RunDetail | AgentAnalysisItem,
): DagNodeSpec {
  if ("agent_name" in source) {
    return {
      node_id: nodeId,
      type: "analysis",
      label: source.display_name || source.agent_name,
      sub_type: source.agent_name,
      trade_date: source.trade_date || null,
      status: "pending",
      category: source.module || "analysis",
      module: source.module || "analysis",
      input: { source: "", summary: "", fields: {}, source_refs: [], artifact_refs: [] },
      output: { source: "", summary: "", fields: {}, source_refs: [], artifact_refs: [] },
      execution: { started_at: null, ended_at: null, duration_ms: null, retries: 0, events: [] },
      upstream_ids: [],
      downstream_ids: [],
    };
  }
  return {
    node_id: nodeId,
    type: "collector",
    label: source.name || source.task_type,
    sub_type: source.task_type,
    trade_date: source.trade_date || null,
    status: "pending",
    category: "data_collection",
    module: "data_collection",
    input: { source: "", summary: "", fields: {}, source_refs: [], artifact_refs: [] },
    output: { source: "", summary: "", fields: {}, source_refs: [], artifact_refs: [] },
    execution: { started_at: null, ended_at: null, duration_ms: null, retries: 0, events: [] },
    upstream_ids: [],
    downstream_ids: [],
  };
}
