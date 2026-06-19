// ── PipelineDagPage (v2) ──────────────────────────────────────
// Dify 风格交互式 DAG：React Flow + SmartNode/SmartEdge + dagre 布局
// 展示完整数据加工管线：采集 → 解析 → 特征 → 分析 → 输出

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ReactFlow,
  ReactFlowProvider,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
  Panel,
  MarkerType,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import dagre from "dagre";
import {
  ArrowLeft, GitBranch, XCircle, RefreshCw,
  Clock, Activity, Play, Loader2, Database, Gauge, FileText, Brain, Target, Save,
  Maximize2, Minimize2,
} from "lucide-react";
import {
  fetchDagGraph,
  STAGE_ORDER,
  STAGE_COLORS,
  STAGE_LABELS,
  type DagNodeSpec,
  type DagEdge,
  type DagGraph,
} from "@/adapters/pipeline-dag";
import { ApiError, fetchJson } from "@/adapters/apiClient";
import {
  fetchAgentAnalysis,
  fetchRunDetail,
  fetchSchedulerOverview,
  formatStatus,
  type AgentAnalysisItem,
  type RunDetail,
  type SchedulerOverviewResponse,
  type SchedulerTaskRun,
} from "@/adapters/scheduler";
import { fetchDagsterRunDetail } from "@/adapters/dagster";
import { SmartNode } from "@/components/dag/SmartNode";
import { SmartEdge } from "@/components/dag/SmartEdge";
import { FARuntimeLog } from "@/components/shared/FARuntimeLog";
import { useNodeDetail } from "@/hooks/useNodeDetail";

// ═══════════════════════════════════════════════════════════════
//  Constants
// ═══════════════════════════════════════════════════════════════

const NODE_WIDTH = 204;
const NODE_HEIGHT = 132;
const OUTPUT_COLUMN_GAP = 34;
const SIDE_BRANCH_GAP_X = 86;
const SIDE_BRANCH_GAP_Y = 74;
const DAG_LAYOUT_STORAGE_KEY = "finance-agent:scheduler-dag-layout:v1";
const OUTPUT_COLUMN_ORDER = [
  "daily_report",
  "strategy_card",
  "dashboard",
  "market_monitor",
  "source_trace",
];

const STAGE_ICON_MAP: Record<string, typeof Database> = {
  collector: Database,
  parser:    Gauge,
  features:  Target,
  analysis:  Brain,
  output:    FileText,
};

type PremarketReadinessSummary = {
  decision_counts?: {
    ready?: number;
    degraded_allowed?: number;
    blocked?: number;
  };
};

type PremarketLaunchPreflight = {
  force: boolean;
  can_launch: boolean;
  blocking_reasons: string[];
  stale_legacy_task_ids: string[];
  active_legacy_task?: {
    task_id: string;
    status: string;
    updated_at?: string | null;
  } | null;
  active_dagster_run?: {
    run_id: string;
    status: string;
  } | null;
  dagster_check_error?: string | null;
  source_readiness_summary?: PremarketReadinessSummary | null;
};

type PremarketLaunchResponse = {
  task_id: string;
  name: string;
  status: string;
  source_readiness_summary?: PremarketReadinessSummary | null;
};

type PremarketLaunchErrorDetail = {
  message?: string;
  reason?: string;
  force?: boolean;
  blocking_reasons?: string[];
  active_legacy_task?: PremarketLaunchPreflight["active_legacy_task"];
  active_dagster_run?: PremarketLaunchPreflight["active_dagster_run"];
  dagster_check_error?: string | null;
  source_readiness_summary?: PremarketReadinessSummary | null;
};

type DagLayoutSnapshot = {
  nodes: Record<string, { x: number; y: number }>;
  updated_at: string;
};

function formatPreflightBlockingReasons(blockingReasons: string[]): string {
  return blockingReasons.map((reason) => {
    if (reason === "legacy_active_task") return "已有旧任务运行中";
    if (reason === "dagster_active_run") return "Dagster 有活动运行";
    return reason;
  }).join(" / ");
}

function summarizePreflight(preflight: PremarketLaunchPreflight | null, error: string | null): string | null {
  if (error) return `预检异常: ${error}`;
  if (!preflight) return null;

  const counts = preflight.source_readiness_summary?.decision_counts;
  const blocked = counts?.blocked ?? 0;
  const degraded = counts?.degraded_allowed ?? 0;
  const parts: string[] = [];

  parts.push(
    preflight.can_launch
      ? "可启动"
      : `预检阻塞: ${formatPreflightBlockingReasons(preflight.blocking_reasons)}`,
  );

  if (blocked > 0) parts.push(`源阻塞 ${blocked}`);
  if (degraded > 0) parts.push(`源降级 ${degraded}`);
  if (preflight.stale_legacy_task_ids.length > 0) parts.push(`忽略 stale ${preflight.stale_legacy_task_ids.length}`);
  if (preflight.dagster_check_error) parts.push("Dagster 检查异常");

  return parts.join(" · ");
}

function parsePremarketLaunchErrorDetail(error: unknown): PremarketLaunchErrorDetail | null {
  if (!(error instanceof ApiError) || !error.responseBody) return null;
  try {
    const parsed = JSON.parse(error.responseBody) as { detail?: PremarketLaunchErrorDetail | string };
    if (!parsed.detail || typeof parsed.detail === "string") return null;
    return parsed.detail;
  } catch {
    return null;
  }
}

function readStoredDagLayout(): DagLayoutSnapshot | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(DAG_LAYOUT_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as DagLayoutSnapshot;
    if (!parsed || typeof parsed !== "object" || !parsed.nodes || typeof parsed.nodes !== "object") return null;
    return parsed;
  } catch {
    return null;
  }
}

function applyStoredDagLayout(nodes: Node[], snapshot: DagLayoutSnapshot | null): Node[] {
  if (!snapshot) return nodes;
  return nodes.map((node) => {
    const savedPosition = snapshot.nodes[node.id];
    if (!savedPosition) return node;
    return {
      ...node,
      position: savedPosition,
    };
  });
}

function persistDagLayout(nodes: Node[]): boolean {
  if (typeof window === "undefined") return false;
  try {
    const snapshot: DagLayoutSnapshot = {
      nodes: Object.fromEntries(nodes.map((node) => [
        node.id,
        { x: node.position.x, y: node.position.y },
      ])),
      updated_at: new Date().toISOString(),
    };
    window.localStorage.setItem(DAG_LAYOUT_STORAGE_KEY, JSON.stringify(snapshot));
    return true;
  } catch {
    return false;
  }
}

// ═══════════════════════════════════════════════════════════════
//  Dagre Layout → React Flow positions
// ═══════════════════════════════════════════════════════════════

function dagreLayout(
  rfNodes: Node[],
  rfEdges: Edge[],
  direction: "LR" | "TB" = "LR",
): { nodes: Node[] } {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: direction, nodesep: 72, ranksep: 118, marginx: 36, marginy: 56 });

  for (const n of rfNodes) {
    const rank = typeof (n.data as any)?.dag_rank === "number" ? (n.data as any).dag_rank : undefined;
    g.setNode(n.id, { width: NODE_WIDTH, height: NODE_HEIGHT, rank });
  }
  for (const e of rfEdges) {
    g.setEdge(e.source, e.target);
  }
  dagre.layout(g);

  const nodes = rfNodes.map(n => {
      const pos = g.node(n.id);
      return {
        ...n,
        position: {
          x: pos.x - NODE_WIDTH / 2,
          y: pos.y - NODE_HEIGHT / 2,
        },
      };
    });

  const outputNodes = nodes
    .filter((node) => ((node.data as any)?.node_spec as DagNodeSpec | undefined)?.category === "final_presentation")
    .filter((node) => node.id !== "feishu_monitor")
    .sort((a, b) => OUTPUT_COLUMN_ORDER.indexOf(a.id) - OUTPUT_COLUMN_ORDER.indexOf(b.id));

  if (outputNodes.length > 0) {
    const outputX = Math.max(...nodes.map((node) => node.position.x));
    const centerY = outputNodes.reduce((sum, node) => sum + node.position.y + NODE_HEIGHT / 2, 0) / outputNodes.length;
    const totalHeight = outputNodes.length * NODE_HEIGHT + Math.max(0, outputNodes.length - 1) * OUTPUT_COLUMN_GAP;
    const startY = centerY - totalHeight / 2;
    const outputYById = new Map(
      outputNodes.map((node, index) => [
        node.id,
        startY + index * (NODE_HEIGHT + OUTPUT_COLUMN_GAP),
      ]),
    );

    const branchAnchorNode = nodes.find((node) => node.id === "jin10_flash_parse")
      ?? nodes.find((node) => node.id === "jin10_message_raw");
    const newsBranchNodeIds = new Set([
      "jin10_message_raw",
      "jin10_report_raw",
      "jin10_flash_parse",
      "jin10_report_parse",
      "event_flow_feature",
      "news_agent",
    ]);
    const newsBranchMaxY = Math.max(
      ...nodes
        .filter((node) => newsBranchNodeIds.has(node.id))
        .map((node) => node.position.y),
      branchAnchorNode?.position.y ?? 0,
    );
    const feishuMonitorY = branchAnchorNode
      ? newsBranchMaxY + NODE_HEIGHT + SIDE_BRANCH_GAP_Y
      : startY + totalHeight + SIDE_BRANCH_GAP_Y;

    return {
      nodes: nodes.map((node) => {
        if (outputYById.has(node.id)) {
          return {
            ...node,
            position: {
              x: outputX,
              y: outputYById.get(node.id)!,
            },
          };
        }
        if (node.id === "feishu_monitor") {
          return {
            ...node,
            position: {
              x: branchAnchorNode ? branchAnchorNode.position.x + SIDE_BRANCH_GAP_X : outputX - NODE_WIDTH - SIDE_BRANCH_GAP_X,
              y: feishuMonitorY,
            },
          };
        }
        return node;
      }),
    };
  }

  return { nodes };
}

function computeDagOrdering(nodes: DagNodeSpec[], edges: DagEdge[]) {
  const indegree = new Map<string, number>();
  const outgoing = new Map<string, string[]>();
  const depth = new Map<string, number>();

  for (const node of nodes) {
    indegree.set(node.node_id, 0);
    outgoing.set(node.node_id, []);
    depth.set(node.node_id, 0);
  }

  for (const edge of edges) {
    indegree.set(edge.to, (indegree.get(edge.to) ?? 0) + 1);
    outgoing.set(edge.from, [...(outgoing.get(edge.from) ?? []), edge.to]);
  }

  const queue = nodes
    .filter((node) => (indegree.get(node.node_id) ?? 0) === 0)
    .sort((a, b) => a.label.localeCompare(b.label, "zh-CN"));

  const orderedIds: string[] = [];
  while (queue.length > 0) {
    const current = queue.shift()!;
    orderedIds.push(current.node_id);
    const nextNodes = (outgoing.get(current.node_id) ?? []).sort((a, b) => a.localeCompare(b, "zh-CN"));
    for (const nextId of nextNodes) {
      depth.set(nextId, Math.max(depth.get(nextId) ?? 0, (depth.get(current.node_id) ?? 0) + 1));
      indegree.set(nextId, (indegree.get(nextId) ?? 1) - 1);
      if ((indegree.get(nextId) ?? 0) === 0) {
        const nextNode = nodes.find((node) => node.node_id === nextId);
        if (nextNode) queue.push(nextNode);
      }
    }
    queue.sort((a, b) => {
      const depthDiff = (depth.get(a.node_id) ?? 0) - (depth.get(b.node_id) ?? 0);
      if (depthDiff !== 0) return depthDiff;
      return a.label.localeCompare(b.label, "zh-CN");
    });
  }

  for (const node of nodes) {
    if (!orderedIds.includes(node.node_id)) {
      orderedIds.push(node.node_id);
    }
  }

  return {
    orderIndex: new Map(orderedIds.map((id, index) => [id, index + 1])),
    depth,
    orderedIds,
  };
}

// ═══════════════════════════════════════════════════════════════
//  Data → React Flow Nodes & Edges
// ═══════════════════════════════════════════════════════════════

function buildRFNodes(specs: DagNodeSpec[]): Node[] {
  return specs.map((spec, i) => ({
    id: spec.node_id,
    type: "smartNode",
    position: { x: 0, y: i * 100 }, // initial — dagre will reposition
    data: { node_spec: spec, highlighted: undefined },
  }));
}

function buildRFEdges(specEdges: DagEdge[]): Edge[] {
  return specEdges.map((e, i) => ({
    id: `${e.from}→${e.to}-${i}`,
    source: e.from,
    target: e.to,
    type: "smartEdge",
    data: { edge_type: e.edge_type, edge_status: e.data_contract.status, data_contract: e.data_contract },
    markerEnd: { type: MarkerType.ArrowClosed, width: 10, height: 7, color: "var(--fg-5)" },
  }));
}

type LineageState = "selected" | "upstream" | "downstream" | "dim";

function collectLineage(nodeId: string | null, edges: DagEdge[]) {
  const upstream = new Set<string>();
  const downstream = new Set<string>();
  const incoming = new Map<string, string[]>();
  const outgoing = new Map<string, string[]>();

  for (const edge of edges) {
    incoming.set(edge.to, [...(incoming.get(edge.to) ?? []), edge.from]);
    outgoing.set(edge.from, [...(outgoing.get(edge.from) ?? []), edge.to]);
  }

  if (!nodeId) return { upstream, downstream };

  const visitUpstream = (currentId: string) => {
    for (const nextId of incoming.get(currentId) ?? []) {
      if (upstream.has(nextId)) continue;
      upstream.add(nextId);
      visitUpstream(nextId);
    }
  };
  const visitDownstream = (currentId: string) => {
    for (const nextId of outgoing.get(currentId) ?? []) {
      if (downstream.has(nextId)) continue;
      downstream.add(nextId);
      visitDownstream(nextId);
    }
  };

  visitUpstream(nodeId);
  visitDownstream(nodeId);
  return { upstream, downstream };
}

function edgeLineageState(edge: Edge, activeNodeId: string | null, upstream: Set<string>, downstream: Set<string>): LineageState | undefined {
  if (!activeNodeId) return undefined;
  if (edge.source === activeNodeId && edge.target === activeNodeId) return "selected";
  if ((edge.source === activeNodeId && downstream.has(edge.target)) || (downstream.has(edge.source) && downstream.has(edge.target))) {
    return "downstream";
  }
  if ((upstream.has(edge.source) && edge.target === activeNodeId) || (upstream.has(edge.source) && upstream.has(edge.target))) {
    return "upstream";
  }
  return "dim";
}

function DagAtmosphereStyles() {
  return (
    <style>{`
      @keyframes dag-pan-grid {
        0% { transform: translate3d(0, 0, 0); }
        100% { transform: translate3d(-56px, -28px, 0); }
      }
      @keyframes dag-node-progress-sheen {
        0% { transform: translateX(-140%); opacity: 0; }
        18% { opacity: 0.9; }
        100% { transform: translateX(260%); opacity: 0; }
      }
      .dag-canvas-atmosphere::before {
        content: "";
        position: absolute;
        inset: -20%;
        background-image:
          linear-gradient(rgba(255,255,255,0.035) 1px, transparent 1px),
          linear-gradient(90deg, rgba(255,255,255,0.035) 1px, transparent 1px);
        background-size: 56px 56px;
        animation: dag-pan-grid 18s linear infinite;
        opacity: 0.28;
      }
      .dag-canvas-atmosphere::after {
        content: "";
        position: absolute;
        inset: 0;
        pointer-events: none;
        background:
          radial-gradient(circle at 12% 18%, rgba(59,130,246,0.20), transparent 24%),
          radial-gradient(circle at 48% 8%, rgba(245,158,11,0.16), transparent 18%),
          radial-gradient(circle at 84% 22%, rgba(16,185,129,0.17), transparent 22%),
          linear-gradient(180deg, rgba(4,10,18,0.18) 0%, rgba(4,10,18,0.04) 18%, transparent 100%);
      }
      .dag-node-progress-sheen {
        animation: dag-node-progress-sheen 1.6s linear infinite;
      }
    `}</style>
  );
}

// ═══════════════════════════════════════════════════════════════
//  Run Pipeline (polling)
// ═══════════════════════════════════════════════════════════════

interface RunLogEntry {
  time: string;
  type: string;
  content: string;
  status: "success" | "running" | "failed" | "pending";
  duration: string;
}

function pollTaskStatus(
  taskId: string,
  onUpdate: (status: string, entry: RunLogEntry) => void,
  maxPolls = 30,
  interval = 3000,
) {
  let polls = 0;
  async function poll() {
    if (polls >= maxPolls) return;
    polls++;
    try {
      // Try Dagster first, fallback to legacy
      let status = "unknown";
      let taskType = "premarket";
      let startedAt: string | null = null;
      let endedAt: string | null = null;

      const dagster = await fetchDagsterRunDetail(taskId).catch(() => null);
      if (dagster) {
        status = dagster.status;
        taskType = dagster.tags?.pipeline || dagster.jobName;
        startedAt = dagster.startedAt;
        endedAt = dagster.endedAt;
      } else {
        const data = await fetchJson<any>(`/api/runs/${taskId}`);
        status = data.status || "unknown";
        taskType = data.task_type || "premarket";
        startedAt = data.started_at;
        endedAt = data.ended_at;
      }

      const entry: RunLogEntry = {
        time: new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" }),
        type: "管线执行",
        content: taskType,
        status: status === "success" ? "success" : status === "failed" ? "failed" : "running",
        duration: startedAt && endedAt
          ? `${((new Date(endedAt).getTime() - new Date(startedAt).getTime()) / 1000).toFixed(1)}s`
          : "—",
      };
      onUpdate(status, entry);
      if (status === "success" || status === "failed" || status === "partial_success") return;
      setTimeout(poll, interval);
    } catch {
      if (polls < maxPolls) setTimeout(poll, interval);
    }
  }
  poll();
}

function schedulerEventLevel(eventType: string): "debug" | "info" | "warn" | "error" | "success" {
  const value = eventType.toUpperCase();
  if (value.includes("FAILED") || value.includes("ERROR")) return "error";
  if (value.includes("BLOCKED") || value.includes("FALLBACK") || value.includes("DEGRADED")) return "warn";
  if (value.includes("FINISHED") || value.includes("SUCCESS") || value.includes("WRITTEN")) return "success";
  if (value.includes("STARTED") || value.includes("STATUS_CHANGED") || value.includes("EVALUATED")) return "info";
  return "debug";
}

function schedulerEventSource(event: RunDetail["events"][number]): string {
  const payload = event.payload ?? {};
  const stepName = typeof payload.step_name === "string" ? payload.step_name : null;
  const source = typeof payload.source === "string" ? payload.source : null;
  return stepName ?? event.task_id ?? source ?? "run";
}

function schedulerEventMessage(event: RunDetail["events"][number]): string {
  const payload = event.payload ?? {};
  const details = [
    typeof payload.reason === "string" ? payload.reason : null,
    typeof payload.blocked_reason === "string" ? payload.blocked_reason : null,
    typeof payload.error_message === "string" ? payload.error_message : null,
    typeof payload.from_status === "string" && typeof payload.to_status === "string"
      ? `${payload.from_status} -> ${payload.to_status}`
      : null,
  ].filter((item): item is string => Boolean(item));
  return details.length > 0 ? `${event.event_type} · ${details.join(" · ")}` : event.event_type;
}

function schedulerEventTime(value: string | null | undefined): string {
  if (!value) return "--:--:--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleTimeString("zh-CN", {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function formatRunClock(value: string | null | undefined): string {
  if (!value) return "--:--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "--:--";
  return date.toLocaleTimeString("zh-CN", {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
  });
}

function stageFromTask(run: SchedulerTaskRun): string {
  return run.current_stage || run.category || run.task_type || "task";
}

function matchTaskToNodeId(task: SchedulerTaskRun | null, nodes: DagNodeSpec[]): string | null {
  if (!task) return null;
  const stage = stageFromTask(task).toLowerCase();
  const taskType = task.task_type.toLowerCase();
  const taskName = task.task_name.toLowerCase();
  const exactStage = nodes.find((node) => node.node_id === stage || node.type === stage);
  if (exactStage) return exactStage.node_id;
  const fuzzy = nodes.find((node) => {
    const haystack = `${node.node_id} ${node.label} ${node.type} ${node.sub_type} ${node.module} ${node.category}`.toLowerCase();
    return haystack.includes(taskType) || haystack.includes(taskName) || haystack.includes(stage);
  });
  return fuzzy?.node_id ?? null;
}

// ═══════════════════════════════════════════════════════════════
//  Top Global Bar
// ═══════════════════════════════════════════════════════════════

function TopBar({
  summary, running, runMessage, preflightHint, canRunPipeline, runButtonTitle, onRun, onRefresh,
  tradeDateFilter, setTradeDateFilter, tradeDates, onSaveLayout, onRestoreLayout, hasSavedLayout, layoutMessage,
}: {
  summary: { total: number; success: number; failed: number; running: number };
  running: boolean;
  runMessage: string | null;
  preflightHint: string | null;
  canRunPipeline: boolean;
  runButtonTitle?: string;
  onRun: () => void;
  onRefresh: () => void;
  tradeDateFilter: string;
  setTradeDateFilter: (v: string) => void;
  tradeDates: string[];
  onSaveLayout: () => void;
  onRestoreLayout: () => void;
  hasSavedLayout: boolean;
  layoutMessage: string | null;
}) {
  const ok = summary.failed === 0 && summary.running === 0;

  return (
    <div className="flex items-center gap-3 px-4 py-2 border-b border-[var(--border-faint)]"
      style={{ background: "var(--bg-card)", minHeight: 42 }}>
      <GitBranch size={16} className="text-[var(--brand-gold)] shrink-0" />
      <span className="text-[12px] font-bold text-[var(--fg-1)] tracking-wide shrink-0">
        调度中心
      </span>
      <span className="rounded-md border border-[var(--border)] bg-[var(--bg-card-inner)] px-2.5 py-1 text-[9px] font-semibold text-[var(--fg-4)] shrink-0">
        每日 DAG 运行视图
      </span>

      <div className="flex items-center gap-1 shrink-0">
        <div className={`w-2 h-2 rounded-full ${ok ? "bg-[var(--up)]" : "bg-[var(--down)]"}`} />
        <span className="text-[9px] text-[var(--fg-4)]">{ok ? "正常" : "异常"}</span>
      </div>

      <div className="w-px h-5 bg-[var(--border-faint)]" />

      <button
        onClick={onRun}
        disabled={running || !canRunPipeline}
        title={runButtonTitle}
        className="inline-flex items-center gap-1 rounded-md px-3 py-1.5 text-[10px] font-semibold text-black hover:opacity-90 disabled:opacity-50 transition-opacity shrink-0"
        style={{ background: "linear-gradient(135deg, #10b981, #059669)" }}
      >
        {running ? <Loader2 size={11} className="animate-spin" /> : <Play size={11} />}
        {running ? "运行中..." : canRunPipeline ? "执行运行" : "预检阻塞"}
      </button>

      <button onClick={onRefresh}
        className="inline-flex items-center gap-1 rounded-md border border-[var(--border)] px-2.5 py-1.5 text-[10px] text-[var(--fg-3)] hover:bg-[var(--bg-hover)] transition-colors shrink-0">
        <RefreshCw size={11} /> 刷新
      </button>

      <button
        onClick={onSaveLayout}
        className="inline-flex items-center gap-1 rounded-md border border-[var(--border)] px-2.5 py-1.5 text-[10px] text-[var(--fg-3)] hover:bg-[var(--bg-hover)] transition-colors shrink-0"
      >
        <Save size={11} /> 保存布局
      </button>

      <button
        onClick={onRestoreLayout}
        disabled={!hasSavedLayout}
        className="inline-flex items-center gap-1 rounded-md border border-[var(--border)] px-2.5 py-1.5 text-[10px] text-[var(--fg-3)] hover:bg-[var(--bg-hover)] disabled:opacity-50 transition-colors shrink-0"
      >
        <RefreshCw size={11} /> 恢复布局
      </button>

      {preflightHint && <span className="text-[9px] text-[var(--fg-5)] shrink-0">{preflightHint}</span>}
      {runMessage && <span className="text-[9px] text-[var(--fg-4)] shrink-0">{runMessage}</span>}
      {layoutMessage && <span className="text-[9px] text-[var(--fg-4)] shrink-0">{layoutMessage}</span>}

      <div className="flex-1" />

      <div className="flex items-center gap-3 text-[9px] shrink-0">
        {[{ l: "总计", v: summary.total, c: "var(--fg-2)" },
          { l: "成功", v: summary.success, c: "var(--up)" },
          { l: "失败", v: summary.failed, c: summary.failed > 0 ? "var(--down)" : "var(--fg-4)" },
          { l: "运行中", v: summary.running, c: summary.running > 0 ? "var(--warn)" : "var(--fg-4)" },
        ].map(({ l, v, c }) => (
          <div key={l} className="flex items-center gap-1">
            <span className="text-[var(--fg-5)]">{l}</span>
            <span className="font-semibold" style={{ color: c }}>{v}</span>
          </div>
        ))}
      </div>

      <div className="w-px h-5 bg-[var(--border-faint)]" />

      <select value={tradeDateFilter}
        onChange={e => setTradeDateFilter(e.target.value)}
        className="rounded-md border border-[var(--border)] bg-[var(--bg-card-inner)] px-2 py-1 text-[9px] text-[var(--fg-3)] outline-none">
        <option value="">选择日期</option>
        {tradeDates.map(d => <option key={d} value={d}>{d}</option>)}
      </select>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
//  Stage Legend Bar
// ═══════════════════════════════════════════════════════════════

function StageLegend({ counts }: { counts: Record<string, number> }) {
  return (
    <div className="flex items-center gap-4 px-4 py-1.5 text-[8px] border-b border-[var(--border-faint)]"
      style={{ background: "var(--bg-panel)" }}>
      <span className="text-[var(--fg-5)] font-semibold uppercase tracking-wider">数据流阶段</span>
      {STAGE_ORDER.map((stage, i) => {
        const Icon = STAGE_ICON_MAP[stage] || Activity;
        const color = STAGE_COLORS[stage];
        const count = counts[stage] || 0;
        return (
          <div key={stage} className="flex items-center gap-1">
            {i > 0 && <span className="text-[var(--fg-6)] mr-1">→</span>}
            <Icon size={10} style={{ color }} />
            <span className="text-[var(--fg-4)]">{STAGE_LABELS[stage]}</span>
            <span className="font-semibold text-[var(--fg-2)]">{count}</span>
          </div>
        );
      })}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
//  Inspector Panel (右侧属性栏)
// ═══════════════════════════════════════════════════════════════

// ═══════════════════════════════════════════════════════════════
//  JSON Viewer (compact key-value tree)
// ═══════════════════════════════════════════════════════════════

function JsonViewer({ data, maxDepth = 2 }: { data: unknown; maxDepth?: number }) {
  if (data == null) return <span className="text-[8px] text-[var(--fg-5)]">null</span>;
  if (typeof data === "string") return <span className="text-[8px] font-mono text-[var(--fg-3)] break-all">{data}</span>;
  if (typeof data === "number" || typeof data === "boolean") return <span className="text-[8px] font-mono text-[var(--brand-gold)]">{String(data)}</span>;

  if (Array.isArray(data)) {
    if (data.length === 0) return <span className="text-[8px] text-[var(--fg-5)]">[]</span>;
    return (
      <div className="pl-2 border-l border-[var(--border-faint)]">
        {data.slice(0, 10).map((item, i) => (
          <div key={i} className="py-px">
            <span className="text-[7px] text-[var(--fg-5)] mr-1">[{i}]</span>
            <JsonViewer data={item} maxDepth={maxDepth - 1} />
          </div>
        ))}
        {data.length > 10 && <div className="text-[7px] text-[var(--fg-5)]">...{data.length - 10} more</div>}
      </div>
    );
  }

  if (typeof data === "object") {
    const entries = Object.entries(data as Record<string, unknown>);
    if (entries.length === 0) return <span className="text-[8px] text-[var(--fg-5)]">{"{}"}</span>;
    return (
      <div className="pl-2 border-l border-[var(--border-faint)]">
        {entries.slice(0, 15).map(([k, v]) => (
          <div key={k} className="py-px">
            <span className="text-[7px] font-semibold text-[var(--fg-4)]">{k}:</span>{" "}
            {typeof v === "object" && v !== null && maxDepth > 0 ? (
              <JsonViewer data={v} maxDepth={maxDepth - 1} />
            ) : (
              <span className="text-[8px] font-mono text-[var(--fg-3)] break-all">
                {v == null ? "null" : typeof v === "string" ? v : JSON.stringify(v)}
              </span>
            )}
          </div>
        ))}
        {entries.length > 15 && <div className="text-[7px] text-[var(--fg-5)]">...{entries.length - 15} more</div>}
      </div>
    );
  }

  return <span className="text-[8px] font-mono text-[var(--fg-3)]">{String(data)}</span>;
}

// ═══════════════════════════════════════════════════════════════
//  Inspector Panel (5-tab)
// ═══════════════════════════════════════════════════════════════

type InspectorTab = "input" | "output" | "logs" | "lineage" | "execution";

const TAB_CONFIG: { key: InspectorTab; label: string; icon: typeof Database }[] = [
  { key: "input",     label: "输入",   icon: Database },
  { key: "output",    label: "输出",   icon: FileText },
  { key: "logs",      label: "日志",   icon: Activity },
  { key: "lineage",   label: "血缘",   icon: GitBranch },
  { key: "execution", label: "执行",   icon: Clock },
];

function InspectorPanel({
  node, isLoading, onClose, onFitNode,
}: {
  node: DagNodeSpec | null;
  isLoading: boolean;
  onClose: () => void;
  onFitNode: () => void;
}) {
  const [activeTab, setActiveTab] = useState<InspectorTab>("input");

  if (!node) return null;
  const color = STAGE_COLORS[node.type] || "#94a3b8";

  // Extract step-level JSON data (populated by useNodeDetail)
  const stepInputJsons = ((node as any).input?.step_jsons as Record<string, unknown>[]) || [];
  const stepOutputJsons = ((node as any).output?.step_jsons as Record<string, unknown>[]) || [];
  const stepErrors = ((node as any).execution?.step_errors as Record<string, unknown>[]) || [];

  return (
    <div className="shrink-0 border-l border-[var(--border)] bg-[var(--bg-card)] flex flex-col"
      style={{ width: 300 }}>
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-2.5 border-b border-[var(--border-faint)] shrink-0 bg-[var(--bg-card)]">
        <div className="w-2 h-2 rounded-full shrink-0" style={{ background: color }} />
        <h3 className="text-[11px] font-bold text-[var(--fg-2)] flex-1 truncate">{node.label}</h3>
        <button onClick={onFitNode} title="定位节点"
          className="rounded p-1 hover:bg-[var(--bg-hover)] text-[var(--fg-5)]">
          <Maximize2 size={12} />
        </button>
        <button onClick={onClose}
          className="rounded p-1 hover:bg-[var(--bg-hover)] text-[var(--fg-5)]">
          <ArrowLeft size={12} />
        </button>
      </div>

      {/* Status strip */}
      <div className="flex items-center gap-2 px-3 py-1.5 border-b border-[var(--border-faint)] text-[8px] shrink-0"
        style={{ background: "var(--bg-panel)" }}>
        <span className="font-semibold" style={{
          color: node.status === "success" ? "var(--up)" : node.status === "failed" ? "var(--down)" : "var(--fg-4)",
        }}>{node.status}</span>
        <span className="text-[var(--fg-5)]">·</span>
        <span className="text-[var(--fg-4)]">{STAGE_LABELS[node.type] || node.type}</span>
        {node.execution.duration_ms != null && (
          <>
            <span className="text-[var(--fg-5)]">·</span>
            <span className="font-mono text-[var(--fg-4)]">{(node.execution.duration_ms / 1000).toFixed(1)}s</span>
          </>
        )}
        {node.trade_date && (
          <>
            <span className="text-[var(--fg-5)]">·</span>
            <span className="font-mono text-[var(--fg-4)]">{node.trade_date}</span>
          </>
        )}
      </div>

      {/* Tabs */}
      <div className="flex border-b border-[var(--border-faint)] shrink-0">
        {TAB_CONFIG.map(tab => {
          const Icon = tab.icon;
          return (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className="flex-1 flex items-center justify-center gap-1 py-1.5 text-[9px] font-semibold transition-colors border-b-2"
              style={{
                borderColor: activeTab === tab.key ? "var(--brand-gold)" : "transparent",
                color: activeTab === tab.key ? "var(--fg-1)" : "var(--fg-5)",
                background: activeTab === tab.key ? "var(--bg-card-inner)" : "transparent",
              }}
            >
              <Icon size={10} />
              {tab.label}
            </button>
          );
        })}
      </div>

      {/* Tab Content */}
      <div className="flex-1 overflow-auto p-3 space-y-2">
        {isLoading && (
          <div className="flex justify-center py-6"><Loader2 size={14} className="animate-spin text-[var(--fg-5)]" /></div>
        )}

        {activeTab === "input" && <InputTab node={node} stepJsons={stepInputJsons} />}
        {activeTab === "output" && <OutputTab node={node} stepJsons={stepOutputJsons} />}
        {activeTab === "logs" && <LogsTab node={node} stepErrors={stepErrors} />}
        {activeTab === "lineage" && <LineageTab node={node} />}
        {activeTab === "execution" && <ExecutionTab node={node} />}
      </div>
    </div>
  );
}

function InputTab({ node, stepJsons }: { node: DagNodeSpec; stepJsons: Record<string, unknown>[] }) {
  return (
    <>
      <Section title="数据源" icon={<Database size={10} />}>
        <div className="text-[8px] font-mono text-[var(--fg-4)] mb-1">{node.input.source}</div>
        <div className="text-[8px] text-[var(--fg-5)]">{node.input.summary}</div>
      </Section>

      {Object.keys(node.input.fields).length > 0 && (
        <Section title="字段" icon={<Activity size={10} />}>
          <div className="space-y-0.5">
            {Object.entries(node.input.fields).slice(0, 10).map(([k, v]) => (
              <KV key={k} label={k} value={typeof v === "object" ? JSON.stringify(v) : String(v)} />
            ))}
          </div>
        </Section>
      )}

      {stepJsons.length > 0 && (
        <Section title="步骤输入详情" icon={<Database size={10} />}>
          {stepJsons.map((sj, i) => (
            <div key={i} className="mb-2 last:mb-0">
              {stepJsons.length > 1 && <div className="text-[7px] text-[var(--fg-5)] mb-1">Step {i + 1}</div>}
              <JsonViewer data={sj} />
            </div>
          ))}
        </Section>
      )}

      {node.input.source_refs.length > 0 && (
        <Section title="数据源引用" icon={<Database size={10} />}>
          {node.input.source_refs.slice(0, 6).map((ref, i) => (
            <div key={i} className="flex items-center gap-1 text-[7px] py-px">
              <span className="w-1.5 h-1.5 rounded-full bg-[var(--up)] shrink-0" />
              <span className="text-[var(--fg-3)] truncate">{ref.label}</span>
              {ref.endpoint && <span className="text-[var(--fg-5)] ml-auto font-mono truncate">{ref.endpoint}</span>}
            </div>
          ))}
        </Section>
      )}
    </>
  );
}

function OutputTab({ node, stepJsons }: { node: DagNodeSpec; stepJsons: Record<string, unknown>[] }) {
  return (
    <>
      <Section title="输出" icon={<FileText size={10} />}>
        <div className="text-[8px] font-mono text-[var(--fg-4)] mb-1">{node.output.source?.slice(0, 32)}</div>
        <div className="text-[8px] text-[var(--fg-5)]">{node.output.summary}</div>
      </Section>

      {Object.keys(node.output.fields).length > 0 && (
        <Section title="字段" icon={<Activity size={10} />}>
          <div className="space-y-0.5">
            {Object.entries(node.output.fields).slice(0, 10).map(([k, v]) => (
              <KV key={k} label={k} value={typeof v === "object" ? JSON.stringify(v) : String(v)} />
            ))}
          </div>
        </Section>
      )}

      {stepJsons.length > 0 && (
        <Section title="步骤输出详情" icon={<FileText size={10} />}>
          {stepJsons.map((sj, i) => (
            <div key={i} className="mb-2 last:mb-0">
              {stepJsons.length > 1 && <div className="text-[7px] text-[var(--fg-5)] mb-1">Step {i + 1}</div>}
              <JsonViewer data={sj} />
            </div>
          ))}
        </Section>
      )}

      {node.output.artifact_refs.length > 0 && (
        <Section title="产物引用" icon={<FileText size={10} />}>
          {node.output.artifact_refs.slice(0, 6).map((ref, i) => (
            <div key={i} className="flex items-center gap-1 text-[7px] py-px">
              <span className="w-1.5 h-1.5 rounded-full bg-[var(--brand-gold)] shrink-0" />
              <span className="text-[var(--fg-3)] truncate">{ref.artifact_type}</span>
              {ref.file_path && <span className="text-[var(--fg-5)] ml-auto font-mono truncate">{ref.file_path.split("/").pop()}</span>}
            </div>
          ))}
        </Section>
      )}
    </>
  );
}

function LogsTab({ node, stepErrors }: { node: DagNodeSpec; stepErrors: Record<string, unknown>[] }) {
  const hasError = node.status === "failed" || stepErrors.length > 0;

  return (
    <>
      {hasError ? (
        <Section title="错误" icon={<XCircle size={10} />}>
          {stepErrors.length > 0 ? stepErrors.map((err, i) => (
            <div key={i} className="mb-2 last:mb-0">
              {stepErrors.length > 1 && <div className="text-[7px] text-[var(--fg-5)] mb-1">Step {i + 1}</div>}
              <div className="rounded bg-[var(--color-down-subtle)] p-2 text-[8px]">
                <JsonViewer data={err} />
              </div>
            </div>
          )) : (
            <div className="text-[8px] text-[var(--down)]">任务执行失败</div>
          )}
        </Section>
      ) : (
        <div className="text-[9px] text-[var(--fg-5)] text-center py-8">
          {node.status === "success" ? "执行成功，无错误日志" : "暂无日志"}
        </div>
      )}

      <Section title="状态" icon={<Activity size={10} />}>
        <KV label="状态" value={node.status}
          color={node.status === "success" ? "var(--up)" : node.status === "failed" ? "var(--down)" : "var(--fg-4)"} />
        <KV label="类型" value={node.sub_type} />
        <KV label="阶段" value={node.category} />
      </Section>
    </>
  );
}

function LineageTab({ node }: { node: DagNodeSpec }) {
  return (
    <>
      <Section title="血缘" icon={<GitBranch size={10} />}>
        {node.upstream_ids.length > 0 && (
          <div className="mb-2">
            <span className="text-[7px] font-semibold text-[var(--fg-5)] uppercase">
              上游 ({node.upstream_ids.length})
            </span>
            <div className="mt-0.5 space-y-0.5">
              {node.upstream_ids.slice(0, 5).map(id => (
                <div key={id} className="flex items-center gap-1 text-[7px]">
                  <span className="w-1 h-1 rounded-full bg-[var(--brand-gold)]" />
                  <span className="font-mono text-[var(--fg-3)]">{id.replace(/^(step|src|grp)::/, "")}</span>
                </div>
              ))}
              {node.upstream_ids.length > 5 && <div className="text-[7px] text-[var(--fg-5)]">...{node.upstream_ids.length - 5} more</div>}
            </div>
          </div>
        )}
        {node.downstream_ids.length > 0 && (
          <div>
            <span className="text-[7px] font-semibold text-[var(--fg-5)] uppercase">
              下游 ({node.downstream_ids.length})
            </span>
            <div className="mt-0.5 space-y-0.5">
              {node.downstream_ids.slice(0, 5).map(id => (
                <div key={id} className="flex items-center gap-1 text-[7px]">
                  <span className="w-1 h-1 rounded-full bg-[var(--up)]" />
                  <span className="font-mono text-[var(--fg-3)]">{id.replace(/^(step|src|grp)::/, "")}</span>
                </div>
              ))}
              {node.downstream_ids.length > 5 && <div className="text-[7px] text-[var(--fg-5)]">...{node.downstream_ids.length - 5} more</div>}
            </div>
          </div>
        )}
        {node.upstream_ids.length === 0 && node.downstream_ids.length === 0 && (
          <div className="text-[8px] text-[var(--fg-5)]">暂无血缘信息</div>
        )}
      </Section>
    </>
  );
}

function ExecutionTab({ node }: { node: DagNodeSpec }) {
  const eventEntries = (node.execution.events ?? []).map((event) => {
    const payload = event.payload ?? {};
    const details = [
      typeof payload.reason === "string" ? payload.reason : null,
      typeof payload.blocked_reason === "string" ? payload.blocked_reason : null,
      typeof payload.error_message === "string" ? payload.error_message : null,
      typeof payload.from_status === "string" && typeof payload.to_status === "string"
        ? `${payload.from_status} -> ${payload.to_status}`
        : null,
    ].filter((item): item is string => Boolean(item));
    const eventType = event.event_type.toUpperCase();
    const level: "debug" | "info" | "warn" | "error" | "success" =
      eventType.includes("FAILED") || eventType.includes("ERROR")
        ? "error"
        : eventType.includes("BLOCKED") || eventType.includes("FALLBACK") || eventType.includes("DEGRADED")
        ? "warn"
        : eventType.includes("FINISHED") || eventType.includes("SUCCESS") || eventType.includes("WRITTEN")
        ? "success"
        : eventType.includes("STARTED") || eventType.includes("STATUS_CHANGED") || eventType.includes("EVALUATED")
        ? "info"
        : "debug";
    return {
      id: event.id,
      time: event.created_at
        ? new Date(event.created_at).toLocaleTimeString("zh-CN", {
            hour12: false,
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit",
          })
        : "--:--:--",
      level,
      source: typeof payload.step_name === "string" ? payload.step_name : event.task_id ?? "run",
      message: details.length > 0 ? `${event.event_type} · ${details.join(" · ")}` : event.event_type,
    };
  });

  return (
    <>
      <Section title="执行信息" icon={<Clock size={10} />}>
        <KV label="开始" value={node.execution.started_at || "—"} />
        <KV label="结束" value={node.execution.ended_at || "—"} />
        {node.execution.duration_ms != null && (
          <KV label="耗时" value={`${(node.execution.duration_ms / 1000).toFixed(1)}s`} />
        )}
        <KV label="重试" value={String(node.execution.retries)} />
      </Section>

      <Section title="元数据" icon={<Activity size={10} />}>
        <KV label="node_id" value={node.node_id} />
        <KV label="type" value={node.type} />
        <KV label="module" value={node.module} />
        <KV label="category" value={node.category} />
      </Section>

      <Section title="事件时间线" icon={<Activity size={10} />}>
        {eventEntries.length > 0 ? (
          <FARuntimeLog entries={eventEntries} emptyText="暂无事件时间线" className="max-h-[220px] overflow-y-auto" />
        ) : (
          <div className="text-[8px] text-[var(--fg-5)]">暂无事件时间线</div>
        )}
      </Section>
    </>
  );
}

function Section({ title, icon, children }: { title: string; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="rounded-md border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2.5 py-2">
      <div className="flex items-center gap-1.5 mb-1.5 text-[var(--fg-5)]">
        {icon}
        <span className="text-[8px] font-semibold uppercase tracking-wider">{title}</span>
      </div>
      {children}
    </div>
  );
}

function KV({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="flex items-baseline gap-2 text-[8px] py-px">
      <span className="text-[var(--fg-5)] shrink-0 min-w-[48px]">{label}</span>
      <span className="font-mono truncate" style={{ color: color || "var(--fg-3)" }}>{value}</span>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
//  Execution Log Table (底部)
// ═══════════════════════════════════════════════════════════════

function DailyRunsPanel({
  tradeDate,
  tasks,
  selectedRunId,
  onSelectRun,
}: {
  tradeDate: string;
  tasks: SchedulerTaskRun[];
  selectedRunId: string | null;
  onSelectRun: (runId: string) => void;
}) {
  return (
    <section className="min-h-0 rounded-tl-md border-r border-[var(--border)] bg-[var(--bg-card)]">
      <div className="flex items-center justify-between gap-3 border-b border-[var(--border-faint)] px-4 py-2">
        <div>
          <div className="text-[10px] font-semibold text-[var(--fg-2)]">任务列表</div>
          <div className="text-[8px] text-[var(--fg-5)]">{tradeDate} · {tasks.length} 条运行记录</div>
        </div>
        <div className="rounded-full border border-white/8 bg-black/10 px-2.5 py-1 text-[7px] font-semibold uppercase tracking-[0.16em] text-[var(--fg-4)]">
          Daily Runs
        </div>
      </div>

      <div className="max-h-[320px] overflow-auto">
        {tasks.length === 0 ? (
          <div className="px-4 py-10 text-[9px] text-[var(--fg-5)]">该日期暂无任务运行记录</div>
        ) : (
          <div className="divide-y divide-[var(--border-faint)]">
            {tasks.map((task) => {
              const active = task.run_id === selectedRunId;
              const status = task.status.toLowerCase();
              const accent =
                status === "success" ? "var(--up)" :
                status === "failed" ? "var(--down)" :
                status === "running" ? "var(--warn)" :
                "var(--fg-5)";
              return (
                <button
                  key={task.run_id}
                  onClick={() => onSelectRun(task.run_id)}
                  className="flex w-full items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-[var(--bg-card-inner)]"
                  style={{ background: active ? "var(--bg-card-inner)" : "transparent" }}
                >
                  <span className="mt-0.5 h-2 w-2 rounded-full shrink-0" style={{ background: accent }} />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="truncate text-[10px] font-semibold text-[var(--fg-2)]">{task.task_name}</span>
                      <span className="rounded px-1.5 py-px text-[7px] font-semibold" style={{ background: "var(--bg-panel)", color: accent }}>
                        {formatStatus(task.status)}
                      </span>
                    </div>
                    <div className="mt-1 flex items-center gap-2 text-[8px] text-[var(--fg-5)]">
                      <span>{stageFromTask(task)}</span>
                      <span>·</span>
                      <span>{formatRunClock(task.started_at)}</span>
                      <span>·</span>
                      <span>{task.step_count} steps</span>
                    </div>
                    {task.error_summary && (
                      <div className="mt-1 truncate text-[8px] text-[var(--down)]">{task.error_summary}</div>
                    )}
                  </div>
                </button>
              );
            })}
          </div>
        )}
      </div>
    </section>
  );
}

function RunLogPanel({
  tradeDate,
  selectedTask,
  detail,
  detailLoading,
  localRunLogs,
}: {
  tradeDate: string;
  selectedTask: SchedulerTaskRun | null;
  detail: RunDetail | null;
  detailLoading: boolean;
  localRunLogs: RunLogEntry[];
}) {
  const entries: React.ComponentProps<typeof FARuntimeLog>["entries"] = useMemo(() => {
    if (detail?.events?.length) {
      return detail.events.map((event) => ({
        id: event.id,
        time: schedulerEventTime(event.created_at),
        level: schedulerEventLevel(event.event_type),
        source: schedulerEventSource(event),
        message: schedulerEventMessage(event),
      }));
    }
    return localRunLogs.map((log, index) => ({
      id: `${log.time}-${index}`,
      time: log.time,
      level:
        log.status === "success" ? "success" :
        log.status === "failed" ? "error" :
        log.status === "running" ? "info" :
        "debug",
      source: log.type,
      message: `${log.content}${log.duration !== "—" ? ` · ${log.duration}` : ""}`,
    }));
  }, [detail, localRunLogs]);

  return (
    <section className="min-h-0 rounded-tr-md bg-[var(--bg-card)]">
      <div className="flex items-center justify-between gap-3 border-b border-[var(--border-faint)] px-4 py-2">
        <div>
          <div className="text-[10px] font-semibold text-[var(--fg-2)]">日志信息</div>
          <div className="text-[8px] text-[var(--fg-5)]">
            {selectedTask ? `${selectedTask.task_name} · ${tradeDate}` : `${tradeDate} · 最近运行记录`}
          </div>
        </div>
        {selectedTask && (
          <div className="text-right text-[8px] text-[var(--fg-5)]">
            <div>{formatStatus(selectedTask.status)}</div>
            <div>{selectedTask.run_id.slice(0, 10)}</div>
          </div>
        )}
      </div>

      <div className="space-y-3 p-4">
        {detailLoading ? (
          <div className="flex items-center justify-center py-8 text-[9px] text-[var(--fg-5)]">
            <Loader2 size={14} className="mr-2 animate-spin" /> 加载任务日志...
          </div>
        ) : (
          <>
            {detail && (
              <div className="grid grid-cols-4 gap-2 text-[8px]">
                {[
                  { label: "状态", value: formatStatus(detail.status) },
                  { label: "步骤", value: String(detail.steps.length) },
                  { label: "开始", value: formatRunClock(detail.started_at) },
                  { label: "结束", value: formatRunClock(detail.ended_at) },
                ].map((item) => (
                  <div key={item.label} className="rounded border border-[var(--border-faint)] bg-[var(--bg-panel)] px-2 py-1.5">
                    <div className="text-[7px] uppercase text-[var(--fg-6)]">{item.label}</div>
                    <div className="mt-0.5 font-mono text-[var(--fg-2)]">{item.value}</div>
                  </div>
                ))}
              </div>
            )}
            <FARuntimeLog
              entries={entries}
              emptyText={selectedTask ? "当前任务暂无事件日志" : "暂无运行日志"}
              className="max-h-[260px] overflow-y-auto"
            />
          </>
        )}
      </div>
    </section>
  );
}

// ═══════════════════════════════════════════════════════════════
//  MiniMap Node Colors
// ═══════════════════════════════════════════════════════════════

function nodeColor(node: Node): string {
  const spec = (node.data as any)?.node_spec as DagNodeSpec | undefined;
  if (!spec) return "#94a3b8";
  if (spec.status === "success") return "var(--up)";
  if (spec.status === "failed") return "var(--down)";
  if (spec.status === "running") return "var(--warn)";
  return STAGE_COLORS[spec.type] || "#94a3b8";
}

// ═══════════════════════════════════════════════════════════════
//  React Flow DAG Canvas
// ═══════════════════════════════════════════════════════════════

function FlowCanvas({
  rfNodes, rfEdges, onNodesChange, onEdgesChange, onNodeClick, onNodeMouseEnter, onNodeMouseLeave, onPaneClick,
}: {
  rfNodes: Node[];
  rfEdges: Edge[];
  onNodesChange: any;
  onEdgesChange: any;
  onNodeClick: (_: any, node: Node) => void;
  onNodeMouseEnter: (_: any, node: Node) => void;
  onNodeMouseLeave: () => void;
  onPaneClick: () => void;
}) {
  const flowRef = useRef<any>(null);

  return (
    <ReactFlow
      ref={flowRef}
      nodes={rfNodes}
      edges={rfEdges}
      onNodesChange={onNodesChange}
      onEdgesChange={onEdgesChange}
      onNodeClick={onNodeClick}
      onNodeMouseEnter={onNodeMouseEnter}
      onNodeMouseLeave={onNodeMouseLeave}
      onPaneClick={onPaneClick}
      nodeTypes={{ smartNode: SmartNode }}
      edgeTypes={{ smartEdge: SmartEdge }}
      fitView
      fitViewOptions={{ padding: 0.12 }}
      minZoom={0.18}
      maxZoom={2.4}
      defaultEdgeOptions={{
        type: "smartEdge",
        markerEnd: { type: MarkerType.ArrowClosed, width: 10, height: 7, color: "var(--fg-5)" },
      }}
      proOptions={{ hideAttribution: true }}
      style={{ background: "transparent" }}
    >
      <svg width="0" height="0" className="absolute">
        <defs>
          <filter id="dag-edge-glow" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="3" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>
      </svg>
      <Background color="var(--border-faint)" gap={20} size={1} />
      <Controls
        className="!rounded-md !border !border-[var(--border)] !bg-[var(--bg-card)] !shadow-sm"
        style={{ display: "flex", flexDirection: "column", gap: 2 }}
      />
      <MiniMap
        nodeColor={nodeColor}
        maskColor="var(--bg-panel)"
        style={{ background: "var(--bg-card)", border: "1px solid var(--border)", borderRadius: 6 }}
        className="!rounded-md !shadow-sm"
        pannable
        zoomable
      />
    </ReactFlow>
  );
}

// ═══════════════════════════════════════════════════════════════
//  MAIN PAGE
// ═══════════════════════════════════════════════════════════════

export function PipelineDagPage() {
  const [dagData, setDagData] = useState<DagGraph | null>(null);
  const [schedulerOverview, setSchedulerOverview] = useState<SchedulerOverviewResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null);
  const [days] = useState(30);
  const [tradeDateFilter, setTradeDateFilter] = useState("");
  const [running, setRunning] = useState(false);
  const [runMessage, setRunMessage] = useState<string | null>(null);
  const [preflight, setPreflight] = useState<PremarketLaunchPreflight | null>(null);
  const [preflightError, setPreflightError] = useState<string | null>(null);
  const [agentOutputs, setAgentOutputs] = useState<AgentAnalysisItem[]>([]);
  const [runLogs, setRunLogs] = useState<RunLogEntry[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [selectedRunDetail, setSelectedRunDetail] = useState<RunDetail | null>(null);
  const [runDetailLoading, setRunDetailLoading] = useState(false);
  const [hasSavedLayout, setHasSavedLayout] = useState(false);
  const [layoutMessage, setLayoutMessage] = useState<string | null>(null);

  useEffect(() => { fetchAgentAnalysis("latest").then(setAgentOutputs).catch(() => {}); }, []);

  const load = useCallback(async () => {
    setLoading(true); setError(null); setSelectedNodeId(null);
    try {
      const [graph, preflightData, overview] = await Promise.all([
        fetchDagGraph(days),
        fetchJson<PremarketLaunchPreflight>("/api/tasks/premarket/preflight").catch((preflightFetchError) => {
          setPreflightError(
            preflightFetchError instanceof Error ? preflightFetchError.message : "预检失败",
          );
          return null;
        }),
        fetchSchedulerOverview(days),
      ]);
      setDagData(graph);
      setPreflight(preflightData);
      setSchedulerOverview(overview);
      if (preflightData) setPreflightError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载 DAG 失败");
    } finally { setLoading(false); }
  }, [days]);

  useEffect(() => { load(); }, [load]);

  const { detail: filledNode, isLoading: detailLoading } = useNodeDetail(selectedNodeId, agentOutputs);
  const dagOrdering = useMemo(
    () => computeDagOrdering(dagData?.nodes ?? [], dagData?.edges ?? []),
    [dagData],
  );

  useEffect(() => {
    if (!selectedRunId) {
      setSelectedRunDetail(null);
      return;
    }
    setRunDetailLoading(true);
    fetchRunDetail(selectedRunId)
      .then(setSelectedRunDetail)
      .catch(() => setSelectedRunDetail(null))
      .finally(() => setRunDetailLoading(false));
  }, [selectedRunId]);

  // Build React Flow nodes & edges from DAG data
  const { rfNodesRaw, rfEdgesRaw } = useMemo(() => {
    if (!dagData || dagData.nodes.length === 0) return { rfNodesRaw: [], rfEdgesRaw: [] };
    return {
      rfNodesRaw: buildRFNodes(dagData.nodes).map((node) => ({
        ...node,
        data: {
          ...(node.data as any),
          sequence_index: dagOrdering.orderIndex.get(node.id) ?? null,
          dag_rank: dagOrdering.depth.get(node.id) ?? 0,
        },
      })),
      rfEdgesRaw: buildRFEdges(dagData.edges),
    };
  }, [dagData, dagOrdering]);

  // Apply dagre layout
  const { nodes: layoutedNodes } = useMemo(() => {
    if (rfNodesRaw.length === 0) return { nodes: [] as Node[] };
    return dagreLayout(rfNodesRaw, rfEdgesRaw, "LR");
  }, [rfNodesRaw, rfEdgesRaw]);

  // React Flow state (applied after layout)
  const [rfNodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [rfEdges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const layoutAppliedRef = useRef(false);

  useEffect(() => {
    setHasSavedLayout(Boolean(readStoredDagLayout()));
  }, [dagData]);

  useEffect(() => {
    if (layoutedNodes.length > 0 && !layoutAppliedRef.current) {
      const storedLayout = readStoredDagLayout();
      setNodes(applyStoredDagLayout(layoutedNodes, storedLayout));
      setEdges(rfEdgesRaw);
      setHasSavedLayout(Boolean(storedLayout));
      layoutAppliedRef.current = true;
      // Fit view after layout
      setTimeout(() => {
        (window as any).__reactFlowInstance?.fitView?.({ padding: 0.3, duration: 300 });
      }, 100);
    }
  }, [layoutedNodes, rfEdgesRaw, setNodes, setEdges]);

  // Reset layout flag when data changes
  useEffect(() => {
    layoutAppliedRef.current = false;
  }, [dagData]);

  useEffect(() => {
    if (!layoutMessage) return;
    const timer = window.setTimeout(() => setLayoutMessage(null), 2200);
    return () => window.clearTimeout(timer);
  }, [layoutMessage]);

  const activeLineageNodeId = hoveredNodeId || selectedNodeId;

  useEffect(() => {
    if (!dagData) return;
    const { upstream, downstream } = collectLineage(activeLineageNodeId, dagData.edges);

    setNodes((nodes) => nodes.map((node) => {
      let highlighted: LineageState | undefined;
      if (activeLineageNodeId) {
        highlighted = node.id === activeLineageNodeId
          ? "selected"
          : upstream.has(node.id)
          ? "upstream"
          : downstream.has(node.id)
          ? "downstream"
          : "dim";
      }
      return {
        ...node,
        data: {
          ...(node.data as any),
          highlighted,
        },
      };
    }));

    setEdges((edges) => edges.map((edge) => {
      const lineageState = edgeLineageState(edge, activeLineageNodeId, upstream, downstream);
      return {
        ...edge,
        data: {
          ...(edge.data as any),
          lineage_state: lineageState,
        },
        selected: lineageState === "upstream" || lineageState === "downstream",
      };
    }));
  }, [activeLineageNodeId, dagData, setNodes, setEdges]);

  const handleNodeClick = useCallback((_: any, node: Node) => {
    setSelectedNodeId(node.id);
  }, []);

  const handleNodeMouseEnter = useCallback((_: any, node: Node) => {
    setHoveredNodeId(node.id);
  }, []);

  const handleNodeMouseLeave = useCallback(() => {
    setHoveredNodeId(null);
  }, []);

  const handlePaneClick = useCallback(() => {
    setSelectedNodeId(null);
  }, []);

  const handleSaveLayout = useCallback(() => {
    const ok = persistDagLayout(rfNodes);
    setHasSavedLayout(ok);
    setLayoutMessage(ok ? "已保存布局" : "保存失败");
  }, [rfNodes]);

  const handleRestoreLayout = useCallback(() => {
    const storedLayout = readStoredDagLayout();
    if (!storedLayout) {
      setHasSavedLayout(false);
      setLayoutMessage("暂无已保存布局");
      return;
    }
    setNodes((nodes) => applyStoredDagLayout(nodes, storedLayout));
    setHasSavedLayout(true);
    setLayoutMessage("已恢复布局");
    setTimeout(() => {
      (window as any).__reactFlowInstance?.fitView?.({ padding: 0.22, duration: 260 });
    }, 80);
  }, [setNodes]);

  // Fit to selected node
  const fitSelectedNode = useCallback(() => {
    const el = document.querySelector(`[data-id="${selectedNodeId}"]`);
    if (el) el.scrollIntoView({ behavior: "smooth", block: "center", inline: "center" });
  }, [selectedNodeId]);

  const runPipeline = useCallback(async () => {
    setRunning(true); setRunMessage("启动中...");
    const startLog: RunLogEntry = {
      time: new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" }),
      type: "管线", content: "premarket 启动", status: "running", duration: "—",
    };
    setRunLogs(prev => [startLog, ...prev]);

    try {
      const latestPreflight = await fetchJson<PremarketLaunchPreflight>("/api/tasks/premarket/preflight");
      setPreflight(latestPreflight);
      setPreflightError(null);

      if (!latestPreflight.can_launch) {
        const blockedMessage = `预检阻塞: ${formatPreflightBlockingReasons(latestPreflight.blocking_reasons)}`;
        setRunning(false);
        setRunMessage(blockedMessage);
        setRunLogs(prev => [{
          time: new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" }),
          type: "预检",
          content: blockedMessage,
          status: "failed",
          duration: "—",
        }, ...prev]);
        setTimeout(() => setRunMessage(null), 4000);
        return;
      }

      const data = await fetchJson<PremarketLaunchResponse>("/api/tasks/premarket", { method: "POST" });
      const runId = data.task_id;
      if (data.source_readiness_summary) {
        setPreflight({
          ...latestPreflight,
          source_readiness_summary: data.source_readiness_summary,
        });
      }

      if (!runId) throw new Error("无法启动管线");
      setRunMessage(`运行中: ${runId.slice(0, 8)}`);

      pollTaskStatus(runId, (status, entry) => {
        setRunMessage(status === "success" ? "完成" : status === "failed" ? "失败" : `运行中: ${status}`);
        setRunLogs(prev => [entry, ...prev]);
        if (status === "success" || status === "failed") {
          setRunning(false); load();
          setTimeout(() => setRunMessage(null), 3000);
        }
      });
    } catch (e) {
      setRunning(false);
      const launchErrorDetail = parsePremarketLaunchErrorDetail(e);
      if (launchErrorDetail?.source_readiness_summary) {
        setPreflight((current) => ({
          force: false,
          can_launch: false,
          blocking_reasons: launchErrorDetail.blocking_reasons ?? current?.blocking_reasons ?? [],
          stale_legacy_task_ids: current?.stale_legacy_task_ids ?? [],
          active_legacy_task: launchErrorDetail.active_legacy_task ?? current?.active_legacy_task ?? null,
          active_dagster_run: launchErrorDetail.active_dagster_run ?? current?.active_dagster_run ?? null,
          dagster_check_error: launchErrorDetail.dagster_check_error ?? current?.dagster_check_error ?? null,
          source_readiness_summary: launchErrorDetail.source_readiness_summary,
        }));
      }
      setRunMessage(`启动失败: ${launchErrorDetail?.message ?? (e instanceof Error ? e.message : "未知")}`);
      setTimeout(() => setRunMessage(null), 4000);
    }
  }, [load]);

  const preflightHint = useMemo(
    () => summarizePreflight(preflight, preflightError),
    [preflight, preflightError],
  );

  const canRunPipeline = useMemo(
    () => running || preflight == null || preflight.can_launch,
    [preflight, running],
  );

  const runButtonTitle = useMemo(() => {
    if (running) return "运行中";
    if (!preflight || preflight.can_launch) return "执行 premarket 运行";
    return `预检阻塞: ${formatPreflightBlockingReasons(preflight.blocking_reasons)}`;
  }, [preflight, running]);

  const tradeDates = useMemo(() => {
    const dates = new Set<string>();
    for (const n of dagData?.nodes ?? []) { if (n.trade_date) dates.add(n.trade_date); }
    for (const run of schedulerOverview?.task_runs ?? []) { if (run.trade_date) dates.add(run.trade_date); }
    if (dates.size === 0) return [];
    return [...dates].sort().reverse();
  }, [dagData, schedulerOverview]);

  useEffect(() => {
    if (!tradeDateFilter && tradeDates.length > 0) {
      setTradeDateFilter(tradeDates[0]);
    }
  }, [tradeDateFilter, tradeDates]);

  const dailyRuns = useMemo(() => {
    const selectedDate = tradeDateFilter || tradeDates[0] || "";
    if (!selectedDate || !schedulerOverview) return [];
    return [...schedulerOverview.task_runs]
      .filter((run) => run.trade_date === selectedDate)
      .sort((a, b) => {
        const ta = a.started_at ?? "";
        const tb = b.started_at ?? "";
        return tb.localeCompare(ta);
      });
  }, [schedulerOverview, tradeDateFilter, tradeDates]);

  useEffect(() => {
    if (dailyRuns.length === 0) {
      setSelectedRunId(null);
      return;
    }
    if (!selectedRunId || !dailyRuns.some((run) => run.run_id === selectedRunId)) {
      setSelectedRunId(dailyRuns[0].run_id);
    }
  }, [dailyRuns, selectedRunId]);

  const selectedTask = useMemo(
    () => dailyRuns.find((run) => run.run_id === selectedRunId) ?? null,
    [dailyRuns, selectedRunId],
  );

  const stageCounts = useMemo(() => {
    const c: Record<string, number> = {};
    if (!dagData) return c;
    for (const n of dagData.nodes) c[n.type] = (c[n.type] || 0) + 1;
    return c;
  }, [dagData]);

  const summary = useMemo(() => {
    if (!dagData) return { total: 0, success: 0, failed: 0, running: 0 };
    const nodes = dagData.nodes;
    return {
      total: nodes.length,
      success: nodes.filter(n => n.status === "success").length,
      failed: nodes.filter(n => n.status === "failed").length,
      running: nodes.filter(n => n.status === "running").length,
    };
  }, [dagData]);

  const activeTradeDate = tradeDateFilter || tradeDates[0] || "";

  const inspectorNode = filledNode || dagData?.nodes.find(n => n.node_id === selectedNodeId) || null;

  const dailyRunLogs = useMemo(() => {
    if (selectedRunDetail?.events?.length) return [];
    return runLogs;
  }, [selectedRunDetail, runLogs]);

  return (
    <ReactFlowProvider>
      <div className="finance-page-shell flex flex-col h-full">
        <DagAtmosphereStyles />
        <TopBar
          summary={summary}
          running={running}
          runMessage={runMessage}
          preflightHint={preflightHint}
          canRunPipeline={canRunPipeline}
          runButtonTitle={runButtonTitle}
          onRun={runPipeline}
          onRefresh={load}
          tradeDateFilter={tradeDateFilter}
          setTradeDateFilter={setTradeDateFilter}
          tradeDates={tradeDates}
          onSaveLayout={handleSaveLayout}
          onRestoreLayout={handleRestoreLayout}
          hasSavedLayout={hasSavedLayout}
          layoutMessage={layoutMessage}
        />

        <div className="flex-1 min-h-0">
          <div className="flex h-full min-h-0">
            <div className="dag-canvas-atmosphere flex-1 min-w-0 relative overflow-hidden" style={{ background: "linear-gradient(180deg, #06101a 0%, #09131e 38%, #0b1622 100%)" }}>
              {loading && (
                <div className="absolute inset-0 flex items-center justify-center z-20 bg-[var(--bg-panel)]/80">
                  <div className="flex flex-col items-center gap-2">
                    <Loader2 size={24} className="animate-spin text-[var(--brand-gold)]" />
                    <span className="text-[10px] text-[var(--fg-4)]">加载 DAG 运行图...</span>
                  </div>
                </div>
              )}
              {error && (
                <div className="absolute inset-0 flex flex-col items-center justify-center z-20 bg-[var(--bg-panel)]/80">
                  <XCircle size={28} className="text-[var(--down)] mb-2" />
                  <span className="text-sm text-[var(--fg-3)]">{error}</span>
                  <button onClick={load} className="mt-3 rounded-md border border-[var(--border)] px-4 py-1.5 text-[10px] text-[var(--fg-3)] hover:bg-[var(--bg-hover)]">重试</button>
                </div>
              )}
              {!loading && !error && (
                <>
                  <FlowCanvas
                    rfNodes={rfNodes}
                    rfEdges={rfEdges}
                    onNodesChange={onNodesChange}
                    onEdgesChange={onEdgesChange}
                    onNodeClick={handleNodeClick}
                    onNodeMouseEnter={handleNodeMouseEnter}
                    onNodeMouseLeave={handleNodeMouseLeave}
                    onPaneClick={handlePaneClick}
                  />
                  <Panel position="top-right" className="!m-3 !rounded-[18px] !border !border-white/10 !bg-[rgba(6,12,20,0.68)] !px-3 !py-2 !shadow-[0_20px_50px_-34px_rgba(0,0,0,0.85)] !backdrop-blur-md">
                    <div className="flex items-center gap-2 text-[7px] uppercase tracking-[0.16em] text-[var(--fg-5)]">
                      {STAGE_ORDER.map((stage) => (
                        <div key={stage} className="flex items-center gap-1 rounded-full border border-white/8 bg-white/5 px-2 py-1">
                          <span className="h-1.5 w-1.5 rounded-full" style={{ background: STAGE_COLORS[stage] }} />
                          <span>{STAGE_LABELS[stage]}</span>
                          <span className="font-mono text-[var(--fg-3)]">{stageCounts[stage] ?? 0}</span>
                        </div>
                      ))}
                    </div>
                  </Panel>
                  <Panel position="bottom-right" className="!m-3 !rounded-[18px] !border !border-white/10 !bg-[rgba(6,12,20,0.66)] !px-3 !py-2 !shadow-[0_20px_50px_-34px_rgba(0,0,0,0.85)] !backdrop-blur-md">
                    <div className="text-[7px] uppercase tracking-[0.18em] text-[var(--fg-6)]">Daily runs</div>
                    <div className="mt-1 flex items-center gap-3 text-[10px] text-[var(--fg-3)]">
                      <span className="font-mono">{activeTradeDate || "latest"}</span>
                      <span>{dailyRuns.length} runs</span>
                      {selectedTask && <span className="max-w-[180px] truncate text-[var(--fg-5)]">{selectedTask.task_name}</span>}
                    </div>
                  </Panel>
                </>
              )}
            </div>

            <InspectorPanel
              node={inspectorNode}
              isLoading={detailLoading}
              onClose={() => setSelectedNodeId(null)}
              onFitNode={fitSelectedNode}
            />
          </div>
        </div>
      </div>
    </ReactFlowProvider>
  );
}

export default PipelineDagPage;
