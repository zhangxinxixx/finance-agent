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
  Clock, Activity, Play, Loader2, ChevronDown,
  ChevronUp, Database, Gauge, FileText, Brain, Target,
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
import { fetchJson } from "@/adapters/apiClient";
import { fetchAgentAnalysis, type AgentAnalysisItem } from "@/adapters/scheduler";
import { launchDagsterRun, fetchDagsterRunDetail } from "@/adapters/dagster";
import { SmartNode } from "@/components/dag/SmartNode";
import { SmartEdge } from "@/components/dag/SmartEdge";
import { useNodeDetail } from "@/hooks/useNodeDetail";
import { LineagePanel } from "@/pages/DataLineageDagPage";

// ═══════════════════════════════════════════════════════════════
//  Constants
// ═══════════════════════════════════════════════════════════════

const NODE_WIDTH = 200;
const NODE_HEIGHT = 90;

const STAGE_ICON_MAP: Record<string, typeof Database> = {
  collector: Database,
  parser:    Gauge,
  features:  Target,
  analysis:  Brain,
  output:    FileText,
};

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
  g.setGraph({ rankdir: direction, nodesep: 60, ranksep: 140 });

  for (const n of rfNodes) {
    g.setNode(n.id, { width: NODE_WIDTH, height: NODE_HEIGHT + 20 });
  }
  for (const e of rfEdges) {
    g.setEdge(e.source, e.target);
  }
  dagre.layout(g);

  return {
    nodes: rfNodes.map(n => {
      const pos = g.node(n.id);
      return {
        ...n,
        position: {
          x: pos.x - NODE_WIDTH / 2,
          y: pos.y - (NODE_HEIGHT + 20) / 2,
        },
      };
    }),
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
    data: { edge_type: e.edge_type, data_contract: e.data_contract },
    markerEnd: { type: MarkerType.ArrowClosed, width: 10, height: 7, color: "var(--fg-5)" },
  }));
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

// ═══════════════════════════════════════════════════════════════
//  Top Global Bar
// ═══════════════════════════════════════════════════════════════

function TopBar({
  summary, running, runMessage, onRun, onRefresh,
  tradeDateFilter, setTradeDateFilter, tradeDates, days,
  viewMode, setViewMode,
}: {
  summary: { total: number; success: number; failed: number; running: number };
  running: boolean;
  runMessage: string | null;
  onRun: () => void;
  onRefresh: () => void;
  tradeDateFilter: string;
  setTradeDateFilter: (v: string) => void;
  tradeDates: string[];
  days: number;
  viewMode: "pipeline" | "lineage";
  setViewMode: (v: "pipeline" | "lineage") => void;
}) {
  const ok = summary.failed === 0 && summary.running === 0;

  return (
    <div className="flex items-center gap-3 px-4 py-2 border-b border-[var(--border-faint)]"
      style={{ background: "var(--bg-card)", minHeight: 42 }}>
      <GitBranch size={16} className="text-[var(--brand-gold)] shrink-0" />
      <span className="text-[12px] font-bold text-[var(--fg-1)] tracking-wide shrink-0">
        Pipeline Flow Studio
      </span>

      {/* View mode tabs */}
      <div className="flex items-center gap-0.5 rounded-md border border-[var(--border)] p-0.5 shrink-0">
        {[
          { key: "pipeline" as const, label: "管线流" },
          { key: "lineage" as const, label: "数据血缘" },
        ].map(tab => (
          <button
            key={tab.key}
            onClick={() => setViewMode(tab.key)}
            className="rounded px-2.5 py-1 text-[9px] font-semibold transition-colors"
            style={{
              background: viewMode === tab.key ? "var(--bg-card-inner)" : "transparent",
              color: viewMode === tab.key ? "var(--fg-2)" : "var(--fg-5)",
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="flex items-center gap-1 shrink-0">
        <div className={`w-2 h-2 rounded-full ${ok ? "bg-[var(--up)]" : "bg-[var(--down)]"}`} />
        <span className="text-[9px] text-[var(--fg-4)]">{ok ? "正常" : "异常"}</span>
      </div>

      <div className="w-px h-5 bg-[var(--border-faint)]" />

      <button
        onClick={onRun}
        disabled={running}
        className="inline-flex items-center gap-1 rounded-md px-3 py-1.5 text-[10px] font-semibold text-black hover:opacity-90 disabled:opacity-50 transition-opacity shrink-0"
        style={{ background: "linear-gradient(135deg, #10b981, #059669)" }}
      >
        {running ? <Loader2 size={11} className="animate-spin" /> : <Play size={11} />}
        {running ? "运行中..." : "执行运行"}
      </button>

      <button onClick={onRefresh}
        className="inline-flex items-center gap-1 rounded-md border border-[var(--border)] px-2.5 py-1.5 text-[10px] text-[var(--fg-3)] hover:bg-[var(--bg-hover)] transition-colors shrink-0">
        <RefreshCw size={11} /> 刷新
      </button>

      {runMessage && <span className="text-[9px] text-[var(--fg-4)] shrink-0">{runMessage}</span>}

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
        <option value="">全部日期</option>
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
      style={{ width: 360 }}>
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

function ExecutionLog({ logs, collapsed, onToggle }: {
  logs: RunLogEntry[];
  collapsed: boolean;
  onToggle: () => void;
}) {
  return (
    <div className="border-t border-[var(--border)]" style={{ background: "var(--bg-panel)" }}>
      <button onClick={onToggle}
        className="flex items-center gap-2 w-full px-4 py-1.5 text-[9px] text-[var(--fg-4)] hover:bg-[var(--bg-hover)] transition-colors">
        {collapsed ? <ChevronUp size={10} /> : <ChevronDown size={10} />}
        <Clock size={10} />
        <span className="font-semibold">运行日志</span>
        <span className="text-[var(--fg-5)]">({logs.length})</span>
      </button>

      {!collapsed && (
        <div className="max-h-[160px] overflow-auto">
          <table className="w-full text-left" style={{ borderCollapse: "collapse" }}>
            <thead className="sticky top-0 z-10" style={{ background: "var(--bg-card)" }}>
              <tr className="border-b border-[var(--border)]">
                <th className="px-4 py-1.5 text-[7px] font-semibold text-[var(--fg-5)] uppercase tracking-wider w-[80px]">时间</th>
                <th className="px-3 py-1.5 text-[7px] font-semibold text-[var(--fg-5)] uppercase tracking-wider w-[80px]">类型</th>
                <th className="px-3 py-1.5 text-[7px] font-semibold text-[var(--fg-5)] uppercase tracking-wider">内容</th>
                <th className="px-3 py-1.5 text-[7px] font-semibold text-[var(--fg-5)] uppercase tracking-wider w-[60px]">状态</th>
                <th className="px-3 py-1.5 text-[7px] font-semibold text-[var(--fg-5)] uppercase tracking-wider w-[60px]">耗时</th>
              </tr>
            </thead>
            <tbody>
              {logs.length === 0 ? (
                <tr><td colSpan={5} className="px-4 py-4 text-center text-[9px] text-[var(--fg-5)]">暂无运行记录</td></tr>
              ) : (
                logs.map((log, i) => (
                  <tr key={i} className="border-b border-[var(--border-faint)] hover:bg-[var(--bg-card-inner)] transition-colors">
                    <td className="px-4 py-1.5 text-[8px] font-mono text-[var(--fg-4)]">{log.time}</td>
                    <td className="px-3 py-1.5 text-[8px] text-[var(--fg-3)]">{log.type}</td>
                    <td className="px-3 py-1.5 text-[8px] text-[var(--fg-2)] truncate max-w-[200px]">{log.content}</td>
                    <td className="px-3 py-1.5">
                      <span className="rounded px-1.5 py-px text-[7px] font-semibold"
                        style={{
                          background: log.status === "success" ? "var(--color-up-subtle)" : log.status === "failed" ? "var(--color-down-subtle)" : "var(--bg-card-inner)",
                          color: log.status === "success" ? "var(--up)" : log.status === "failed" ? "var(--down)" : log.status === "running" ? "var(--warn)" : "var(--fg-4)",
                        }}>
                        {log.status === "success" ? "成功" : log.status === "failed" ? "失败" : log.status === "running" ? "运行中" : "等待"}
                      </span>
                    </td>
                    <td className="px-3 py-1.5 text-[8px] font-mono text-[var(--fg-4)]">{log.duration}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
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
  rfNodes, rfEdges, onNodesChange, onEdgesChange, onNodeClick,
}: {
  rfNodes: Node[];
  rfEdges: Edge[];
  onNodesChange: any;
  onEdgesChange: any;
  onNodeClick: (_: any, node: Node) => void;
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
      nodeTypes={{ smartNode: SmartNode }}
      edgeTypes={{ smartEdge: SmartEdge }}
      fitView
      fitViewOptions={{ padding: 0.3 }}
      minZoom={0.1}
      maxZoom={2}
      defaultEdgeOptions={{
        type: "smartEdge",
        markerEnd: { type: MarkerType.ArrowClosed, width: 10, height: 7, color: "var(--fg-5)" },
      }}
      proOptions={{ hideAttribution: true }}
      style={{ background: "var(--bg-panel)" }}
    >
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
  const [viewMode, setViewMode] = useState<"pipeline" | "lineage">("pipeline");
  const [dagData, setDagData] = useState<DagGraph | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [days] = useState(30);
  const [tradeDateFilter, setTradeDateFilter] = useState("");
  const [running, setRunning] = useState(false);
  const [runMessage, setRunMessage] = useState<string | null>(null);
  const [agentOutputs, setAgentOutputs] = useState<AgentAnalysisItem[]>([]);
  const [runLogs, setRunLogs] = useState<RunLogEntry[]>([]);
  const [logCollapsed, setLogCollapsed] = useState(false);
  const flowRef = useRef<any>(null);

  useEffect(() => { fetchAgentAnalysis("latest").then(setAgentOutputs).catch(() => {}); }, []);

  const load = useCallback(async () => {
    setLoading(true); setError(null); setSelectedNodeId(null);
    try {
      const graph = await fetchDagGraph(days, tradeDateFilter || undefined);
      setDagData(graph);
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载 DAG 失败");
    } finally { setLoading(false); }
  }, [days, tradeDateFilter]);

  useEffect(() => { load(); }, [load]);

  const { detail: filledNode, isLoading: detailLoading } = useNodeDetail(selectedNodeId, agentOutputs);

  // Build React Flow nodes & edges from DAG data
  const { rfNodesRaw, rfEdgesRaw } = useMemo(() => {
    if (!dagData || dagData.nodes.length === 0) return { rfNodesRaw: [], rfEdgesRaw: [] };
    return {
      rfNodesRaw: buildRFNodes(dagData.nodes),
      rfEdgesRaw: buildRFEdges(dagData.edges),
    };
  }, [dagData]);

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
    if (layoutedNodes.length > 0 && !layoutAppliedRef.current) {
      setNodes(layoutedNodes);
      setEdges(rfEdgesRaw);
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

  const handleNodeClick = useCallback((_: any, node: Node) => {
    setSelectedNodeId(node.id);
  }, []);

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
    setLogCollapsed(false);

    try {
      // Try Dagster launch first
      let runId: string | null = null;
      const dagsterResult = await launchDagsterRun("premarket_job").catch(() => null);
      if (dagsterResult) {
        runId = dagsterResult.runId;
      } else {
        // Fallback to legacy API
        const data = await fetchJson<{ task_id: string }>("/api/tasks/premarket?force=true", { method: "POST" });
        runId = data.task_id;
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
      setRunMessage(`启动失败: ${e instanceof Error ? e.message : "未知"}`);
      setTimeout(() => setRunMessage(null), 4000);
    }
  }, [load]);

  const tradeDates = useMemo(() => {
    if (!dagData) return [];
    const dates = new Set<string>();
    for (const n of dagData.nodes) { if (n.trade_date) dates.add(n.trade_date); }
    return [...dates].sort().reverse();
  }, [dagData]);

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

  const inspectorNode = filledNode || dagData?.nodes.find(n => n.node_id === selectedNodeId) || null;

  return (
    <ReactFlowProvider>
      <div className="finance-page-shell flex flex-col h-full">
        <TopBar
          summary={summary}
          running={running}
          runMessage={runMessage}
          onRun={runPipeline}
          onRefresh={load}
          tradeDateFilter={tradeDateFilter}
          setTradeDateFilter={setTradeDateFilter}
          tradeDates={tradeDates}
          days={days}
          viewMode={viewMode}
          setViewMode={setViewMode}
        />

        {viewMode === "pipeline" && <StageLegend counts={stageCounts} />}

        {viewMode === "lineage" ? (
          <div className="flex-1 min-h-0">
            <LineagePanel />
          </div>
        ) : (
          <>
            <div className="flex-1 flex min-h-0">
              {/* React Flow Canvas */}
              <div className="flex-1 min-w-0 relative" style={{ background: "var(--bg-panel)" }}>
                {loading && (
                  <div className="absolute inset-0 flex items-center justify-center z-20 bg-[var(--bg-panel)]/80">
                    <div className="flex flex-col items-center gap-2">
                      <Loader2 size={24} className="animate-spin text-[var(--brand-gold)]" />
                      <span className="text-[10px] text-[var(--fg-4)]">加载管线数据...</span>
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
                  <FlowCanvas
                    rfNodes={rfNodes}
                    rfEdges={rfEdges}
                    onNodesChange={onNodesChange}
                    onEdgesChange={onEdgesChange}
                    onNodeClick={handleNodeClick}
                  />
                )}
              </div>

              {/* Inspector */}
              <InspectorPanel
                node={inspectorNode}
                isLoading={detailLoading}
                onClose={() => setSelectedNodeId(null)}
                onFitNode={fitSelectedNode}
              />
            </div>

            <ExecutionLog logs={runLogs} collapsed={logCollapsed} onToggle={() => setLogCollapsed(!logCollapsed)} />
          </>
        )}
      </div>
    </ReactFlowProvider>
  );
}

export default PipelineDagPage;
