// ── DataLineageDagPage ────────────────────────────────────────
// 数据源加工 DAG 可视化：React Flow + dagre 布局
// 展示 数据源 → 采集/解析/特征 → 产出 的完整血缘

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
  MarkerType,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import dagre from "dagre";
import {
  GitBranch, XCircle, RefreshCw,
  Activity, Loader2,
  Database, Gauge, FileText, Brain, Target,
  Maximize2, ArrowLeft, Filter,
} from "lucide-react";
import {
  fetchLineageDagGraph,
  STEP_META,
  DOMAIN_COLORS,
  providerRoleLabel,
  type LineageDagGraph,
  type StepMeta,
} from "@/adapters/data-lineage";
import type { DagNodeSpec, DagEdge } from "@/types/pipeline-dag";
import { SmartNode } from "@/components/dag/SmartNode";
import { SmartEdge } from "@/components/dag/SmartEdge";
import { SourceNode } from "@/components/dag/SourceNode";

// ═══════════════════════════════════════════════════════════════
//  Constants
// ═══════════════════════════════════════════════════════════════

const NODE_WIDTH = 200;
const NODE_HEIGHT = 90;

const DOMAINS = [
  { key: "", label: "全部", color: "#94a3b8" },
  { key: "macro", label: "宏观", color: DOMAIN_COLORS.macro },
  { key: "cme", label: "CME", color: DOMAIN_COLORS.cme },
  { key: "technical", label: "技术", color: DOMAIN_COLORS.technical },
  { key: "positioning", label: "持仓", color: DOMAIN_COLORS.positioning },
  { key: "news", label: "新闻", color: DOMAIN_COLORS.news },
];

// ═══════════════════════════════════════════════════════════════
//  Dagre Layout
// ═══════════════════════════════════════════════════════════════

// Step → layer rank (0=采集源, 1=采集, 2=解析/特征, 3=分析/产出, 4=最终产出)
const STEP_RANK: Record<string, number> = {
  macro_collect: 1,
  cme_download: 1,
  news_collect: 1,
  macro_feature: 2,
  cme_parse: 2,
  news_feature: 2,
  cme_ingest: 3,
  report_render: 3,
  option_wall: 3,
  news_brief: 3,
  strategy_card: 4,
};

function dagreLayout(
  rfNodes: Node[],
  rfEdges: Edge[],
  direction: "LR" | "TB" = "LR",
): { nodes: Node[] } {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: direction, nodesep: 40, ranksep: 140, marginx: 20, marginy: 20 });

  for (const n of rfNodes) {
    const spec = (n.data as any)?.node_spec;
    const rank = spec?.node_id?.startsWith("grp::") ? 0
      : spec?.node_id?.startsWith("src::") ? 0
      : STEP_RANK[spec?.node_id?.replace("step::", "")] ?? 2;
    g.setNode(n.id, { width: NODE_WIDTH, height: NODE_HEIGHT + 20, rank });
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

function buildRFNodes(graph: LineageDagGraph): Node[] {
  return graph.nodes.map((spec, i) => ({
    id: spec.node_id,
    type: (spec.node_id.startsWith("src::") || spec.node_id.startsWith("grp::")) ? "sourceNode" : "smartNode",
    position: { x: 0, y: i * 100 },
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
//  Top Bar
// ═══════════════════════════════════════════════════════════════

function TopBar({
  summary, loading, onRefresh, domainFilter, setDomainFilter,
}: {
  summary: { sources: number; steps: number; outputs: number; ok: number; failed: number };
  loading: boolean;
  onRefresh: () => void;
  domainFilter: string;
  setDomainFilter: (v: string) => void;
}) {
  return (
    <div className="flex items-center gap-3 px-4 py-2 border-b border-[var(--border-faint)]"
      style={{ background: "var(--bg-card)", minHeight: 42 }}>
      <GitBranch size={16} className="text-[var(--brand-gold)] shrink-0" />
      <span className="text-[12px] font-bold text-[var(--fg-1)] tracking-wide shrink-0">
        Data Lineage DAG
      </span>

      <div className="w-px h-5 bg-[var(--border-faint)]" />

      <button onClick={onRefresh}
        className="inline-flex items-center gap-1 rounded-md border border-[var(--border)] px-2.5 py-1.5 text-[10px] text-[var(--fg-3)] hover:bg-[var(--bg-hover)] transition-colors shrink-0">
        {loading ? <Loader2 size={11} className="animate-spin" /> : <RefreshCw size={11} />}
        刷新
      </button>

      <div className="flex-1" />

      {/* Domain filter chips */}
      <div className="flex items-center gap-1 shrink-0">
        <Filter size={10} className="text-[var(--fg-5)] mr-0.5" />
        {DOMAINS.map(d => (
          <button
            key={d.key}
            onClick={() => setDomainFilter(d.key)}
            className="rounded-md px-2 py-1 text-[9px] font-semibold transition-colors"
            style={{
              background: domainFilter === d.key ? `${d.color}20` : "transparent",
              color: domainFilter === d.key ? d.color : "var(--fg-4)",
              border: domainFilter === d.key ? `1px solid ${d.color}40` : "1px solid transparent",
            }}
          >
            {d.label}
          </button>
        ))}
      </div>

      <div className="w-px h-5 bg-[var(--border-faint)]" />

      {/* Summary stats */}
      <div className="flex items-center gap-3 text-[9px] shrink-0">
        {[
          { l: "数据源", v: summary.sources, c: "var(--fg-2)" },
          { l: "在线", v: summary.ok, c: "var(--up)" },
          { l: "异常", v: summary.failed, c: summary.failed > 0 ? "var(--down)" : "var(--fg-4)" },
          { l: "步骤", v: summary.steps, c: "var(--fg-3)" },
        ].map(({ l, v, c }) => (
          <div key={l} className="flex items-center gap-1">
            <span className="text-[var(--fg-5)]">{l}</span>
            <span className="font-semibold" style={{ color: c }}>{v}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
//  Step Legend
// ═══════════════════════════════════════════════════════════════

function StepLegend({ activeSteps }: { activeSteps: Set<string> }) {
  const layers = [
    { label: "采集层", steps: ["macro_collect", "cme_download", "news_collect"] },
    { label: "解析层", steps: ["macro_feature", "cme_parse", "news_feature"] },
    { label: "产出层", steps: ["report_render", "cme_ingest", "option_wall", "news_brief"] },
    { label: "汇总", steps: ["strategy_card"] },
  ];

  return (
    <div className="flex items-center gap-4 px-4 py-1.5 text-[8px] border-b border-[var(--border-faint)] overflow-x-auto"
      style={{ background: "var(--bg-panel)" }}>
      {layers.map((layer, li) => {
        const activeInLayer = layer.steps.filter(s => activeSteps.has(s));
        if (activeInLayer.length === 0) return null;
        return (
          <div key={layer.label} className="flex items-center gap-1.5 shrink-0">
            {li > 0 && <span className="text-[var(--fg-6)]">│</span>}
            <span className="text-[var(--fg-5)] font-semibold uppercase tracking-wider mr-0.5">{layer.label}</span>
            {activeInLayer.map(step => {
              const meta = STEP_META[step];
              if (!meta) return null;
              return (
                <div key={step} className="flex items-center gap-0.5">
                  <div className="w-1.5 h-1.5 rounded-full" style={{ background: meta.color }} />
                  <span className="text-[var(--fg-4)]">{meta.label}</span>
                </div>
              );
            })}
          </div>
        );
      })}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
//  Inspector Panel
// ═══════════════════════════════════════════════════════════════

function InspectorPanel({
  node, onClose,
}: {
  node: DagNodeSpec | null;
  onClose: () => void;
}) {
  if (!node) return null;

  const isSource = node.node_id.startsWith("src::");
  const domainColor = DOMAIN_COLORS[node.sub_type] || STEP_META[node.sub_type]?.color || "#94a3b8";

  return (
    <div className="shrink-0 border-l border-[var(--border)] bg-[var(--bg-card)] overflow-auto flex flex-col"
      style={{ width: 300 }}>
      <div className="flex items-center gap-2 px-3 py-2.5 border-b border-[var(--border-faint)] sticky top-0 bg-[var(--bg-card)] z-10">
        <div className="w-2 h-2 rounded-full shrink-0" style={{ background: domainColor }} />
        <h3 className="text-[11px] font-bold text-[var(--fg-2)] flex-1 truncate">{node.label}</h3>
        <button onClick={onClose}
          className="rounded p-1 hover:bg-[var(--bg-hover)] text-[var(--fg-5)]">
          <ArrowLeft size={12} />
        </button>
      </div>

      <div className="p-3 space-y-2 flex-1 overflow-auto">
        <Section title="基础信息" icon={<Activity size={10} />}>
          <KV label="状态" value={node.status}
            color={node.status === "success" ? "var(--up)" : node.status === "failed" ? "var(--down)" : node.status === "partial" ? "#f59e0b" : "var(--fg-4)"} />
          <KV label="域" value={node.sub_type} />
          {isSource && (
            <>
              <KV label="类型" value={node.module} />
              <KV label="角色" value={providerRoleLabel((node.input.fields?.provider_role as string) || "")} />
            </>
          )}
          {!isSource && STEP_META[node.sub_type] && (
            <KV label="步骤" value={STEP_META[node.sub_type]!.label} />
          )}
        </Section>

        <Section title="Input" icon={<Database size={10} />}>
          <div className="text-[8px] font-mono text-[var(--fg-4)] mb-1">{node.input.source}</div>
          <div className="text-[8px] text-[var(--fg-5)]">{node.input.summary}</div>
          {Object.keys(node.input.fields).length > 0 && (
            <div className="mt-1 space-y-0.5">
              {Object.entries(node.input.fields).slice(0, 8).map(([k, v]) => (
                <KV key={k} label={k} value={typeof v === "object" ? JSON.stringify(v) : String(v)} />
              ))}
            </div>
          )}
        </Section>

        <Section title="Output" icon={<FileText size={10} />}>
          <div className="text-[8px] text-[var(--fg-5)]">{node.output.summary}</div>
          {Object.keys(node.output.fields).length > 0 && (
            <div className="mt-1 space-y-0.5">
              {Object.entries(node.output.fields).slice(0, 6).map(([k, v]) => (
                <KV key={k} label={k} value={typeof v === "object" ? JSON.stringify(v) : String(v)} />
              ))}
            </div>
          )}
        </Section>

        {(node.upstream_ids.length > 0 || node.downstream_ids.length > 0) && (
          <Section title="血缘" icon={<GitBranch size={10} />}>
            {node.upstream_ids.length > 0 && (
              <div className="mb-1">
                <span className="text-[7px] font-semibold text-[var(--fg-5)] uppercase">
                  上游 ({node.upstream_ids.length})
                </span>
                <div className="text-[7px] font-mono text-[var(--fg-4)] mt-0.5">
                  {node.upstream_ids.slice(0, 5).map(id => id.replace(/^(src|step)::/, "")).join(", ")}
                  {node.upstream_ids.length > 5 && " ..."}
                </div>
              </div>
            )}
            {node.downstream_ids.length > 0 && (
              <div>
                <span className="text-[7px] font-semibold text-[var(--fg-5)] uppercase">
                  下游 ({node.downstream_ids.length})
                </span>
                <div className="text-[7px] font-mono text-[var(--fg-4)] mt-0.5">
                  {node.downstream_ids.slice(0, 5).map(id => id.replace(/^(src|step)::/, "")).join(", ")}
                  {node.downstream_ids.length > 5 && " ..."}
                </div>
              </div>
            )}
          </Section>
        )}
      </div>
    </div>
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
//  MiniMap Node Colors
// ═══════════════════════════════════════════════════════════════

function nodeColor(node: Node): string {
  const spec = (node.data as any)?.node_spec as DagNodeSpec | undefined;
  if (!spec) return "#94a3b8";
  if (spec.status === "success") return "var(--up)";
  if (spec.status === "failed") return "var(--down)";
  if (spec.status === "partial") return "#f59e0b";
  return DOMAIN_COLORS[spec.sub_type] || STEP_META[spec.sub_type]?.color || "#94a3b8";
}

// Layer labels for legend
const LAYER_LABELS = [
  { key: "source", label: "采集层", color: "#64748b" },
  { key: "collect", label: "采集/下载", color: "#3b82f6" },
  { key: "parse", label: "解析/特征", color: "#8b5cf6" },
  { key: "analysis", label: "分析/产出", color: "#06b6d4" },
  { key: "output", label: "最终产出", color: "#10b981" },
];

// ═══════════════════════════════════════════════════════════════
//  React Flow Canvas
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
  return (
    <ReactFlow
      nodes={rfNodes}
      edges={rfEdges}
      onNodesChange={onNodesChange}
      onEdgesChange={onEdgesChange}
      onNodeClick={onNodeClick}
      nodeTypes={{ smartNode: SmartNode, sourceNode: SourceNode }}
      edgeTypes={{ smartEdge: SmartEdge }}
      fitView
      fitViewOptions={{ padding: 0.2 }}
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

export function LineagePanel() {
  const [dagData, setDagData] = useState<LineageDagGraph | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [domainFilter, setDomainFilter] = useState("");

  const load = useCallback(async () => {
    setLoading(true); setError(null); setSelectedNodeId(null);
    try {
      const graph = await fetchLineageDagGraph(domainFilter || undefined);
      setDagData(graph);
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载数据血缘失败");
    } finally { setLoading(false); }
  }, [domainFilter]);

  useEffect(() => { load(); }, [load]);

  // Build React Flow nodes & edges
  const { rfNodesRaw, rfEdgesRaw } = useMemo(() => {
    if (!dagData || dagData.nodes.length === 0) return { rfNodesRaw: [], rfEdgesRaw: [] };
    return {
      rfNodesRaw: buildRFNodes(dagData),
      rfEdgesRaw: buildRFEdges(dagData.edges),
    };
  }, [dagData]);

  // Apply dagre layout
  const { nodes: layoutedNodes } = useMemo(() => {
    if (rfNodesRaw.length === 0) return { nodes: [] as Node[] };
    return dagreLayout(rfNodesRaw, rfEdgesRaw, "LR");
  }, [rfNodesRaw, rfEdgesRaw]);

  // React Flow state
  const [rfNodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [rfEdges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const layoutAppliedRef = useRef(false);

  useEffect(() => {
    if (layoutedNodes.length > 0 && !layoutAppliedRef.current) {
      setNodes(layoutedNodes);
      setEdges(rfEdgesRaw);
      layoutAppliedRef.current = true;
      setTimeout(() => {
        (window as any).__reactFlowInstance?.fitView?.({ padding: 0.2, duration: 300 });
      }, 100);
    }
  }, [layoutedNodes, rfEdgesRaw, setNodes, setEdges]);

  useEffect(() => {
    layoutAppliedRef.current = false;
  }, [dagData]);

  const handleNodeClick = useCallback((_: any, node: Node) => {
    setSelectedNodeId(node.id);
  }, []);

  const inspectorNode = dagData?.nodes.find(n => n.node_id === selectedNodeId) || null;

  const activeSteps = useMemo(() => {
    if (!dagData) return new Set<string>();
    return new Set(
      dagData.stepNodes.map(n => n.sub_type)
        .concat(dagData.outputNodes.map(n => n.sub_type))
    );
  }, [dagData]);

  const summary = useMemo(() => {
    if (!dagData) return { sources: 0, steps: 0, outputs: 0, ok: 0, failed: 0 };
    return {
      sources: dagData.sourceNodes.length,
      steps: dagData.stepNodes.length,
      outputs: dagData.outputNodes.length,
      ok: dagData.sourceNodes.filter(n => n.status === "success").length,
      failed: dagData.sourceNodes.filter(n => n.status === "failed").length,
    };
  }, [dagData]);

  return (
    <ReactFlowProvider>
      <div className="finance-page-shell flex flex-col h-full">
        <TopBar
          summary={summary}
          loading={loading}
          onRefresh={load}
          domainFilter={domainFilter}
          setDomainFilter={setDomainFilter}
        />

        <StepLegend activeSteps={activeSteps} />

        <div className="flex-1 flex min-h-0">
          {/* Canvas */}
          <div className="flex-1 min-w-0 relative" style={{ background: "var(--bg-panel)" }}>
            {loading && (
              <div className="absolute inset-0 flex items-center justify-center z-20 bg-[var(--bg-panel)]/80">
                <div className="flex flex-col items-center gap-2">
                  <Loader2 size={24} className="animate-spin text-[var(--brand-gold)]" />
                  <span className="text-[10px] text-[var(--fg-4)]">加载数据血缘...</span>
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
            onClose={() => setSelectedNodeId(null)}
          />
        </div>
      </div>
    </ReactFlowProvider>
  );
}

export default LineagePanel;
