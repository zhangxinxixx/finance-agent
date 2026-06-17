// ── Data Lineage DAG Adapter ──────────────────────────────────
// 数据源 → 加工步骤 → 产出 的血缘图构建

import { fetchDataIngestionData } from "@/adapters/dataIngestion";
import type { DataSourceStatusViewModel } from "@/types/data-ingestion";
import type { DagNodeSpec, DagEdge, DagGraph } from "@/types/pipeline-dag";

// ── Source → Step Mapping ──

const SOURCE_TO_STEP: Record<string, string> = {
  fred: "macro_collect",
  fed: "macro_collect",
  treasury: "macro_collect",
  dxy: "macro_collect",
  openbb_macro: "macro_collect",
  cme_daily_bulletin: "cme_download",
  cme_options: "cme_ingest",
  technical_yahoo: "macro_collect",
  positioning_cot: "macro_collect",
  jin10_mcp_market: "macro_collect",
  jin10_news: "news_collect",
  jin10_flash: "news_collect",
  jin10_mcp_flash: "news_collect",
  jin10_mcp_calendar: "news_collect",
  jin10_xnews_public: "news_collect",
  jin10_datacenter_reports: "news_collect",
  jin10_svip_reports: "news_collect",
  jin10_feishu: "news_collect",
  fed_rss: "news_collect",
  bls_calendar: "news_collect",
  bea_calendar: "news_collect",
  eia_energy: "news_collect",
  gdelt_news: "news_collect",
  google_news_rss: "news_collect",
  reuters_public_news: "news_collect",
};

// ── Source Group Definitions ──
// 聚合多个数据源为一个源组节点，减少视觉冗余

interface SourceGroupDef {
  group_id: string;
  label: string;
  domain: string;
  source_keys: string[];
  icon: string;
}

const SOURCE_GROUPS: SourceGroupDef[] = [
  {
    group_id: "macro_data",
    label: "宏观数据",
    domain: "macro",
    source_keys: ["fred", "fed", "treasury", "dxy", "openbb_macro"],
    icon: "📊",
  },
  {
    group_id: "macro_market",
    label: "行情/持仓",
    domain: "technical",
    source_keys: ["technical_yahoo", "positioning_cot", "jin10_mcp_market"],
    icon: "📈",
  },
  {
    group_id: "cme_data",
    label: "CME 期权",
    domain: "cme",
    source_keys: ["cme_daily_bulletin", "cme_options"],
    icon: "📋",
  },
  {
    group_id: "news_jin10",
    label: "金十资讯",
    domain: "news",
    source_keys: [
      "jin10_news", "jin10_flash", "jin10_mcp_flash", "jin10_mcp_calendar",
      "jin10_xnews_public", "jin10_datacenter_reports", "jin10_svip_reports", "jin10_feishu",
    ],
    icon: "⚡",
  },
  {
    group_id: "news_official",
    label: "官方/机构",
    domain: "news",
    source_keys: ["fed_rss", "bls_calendar", "bea_calendar", "eia_energy"],
    icon: "🏛️",
  },
  {
    group_id: "news_media",
    label: "媒体/聚合",
    domain: "news",
    source_keys: ["gdelt_news", "google_news_rss", "reuters_public_news"],
    icon: "🌐",
  },
];

// ── Step → Step Dependency Graph ──

const STEP_GRAPH: Record<string, string[]> = {
  macro_collect: ["macro_feature"],
  macro_feature: ["report_render"],
  cme_download: ["cme_parse"],
  cme_parse: ["cme_ingest"],
  cme_ingest: ["option_wall"],
  news_collect: ["news_feature"],
  news_feature: ["news_brief"],
  report_render: ["strategy_card"],
  option_wall: ["strategy_card"],
  news_brief: ["strategy_card"],
};

// ── Step Metadata ──

export interface StepMeta {
  label: string;
  domain: string;
  color: string;
}

const STEP_META: Record<string, StepMeta> = {
  macro_collect:   { label: "宏观采集",   domain: "macro",      color: "#3b82f6" },
  macro_feature:   { label: "宏观特征",   domain: "macro",      color: "#8b5cf6" },
  report_render:   { label: "宏观报告",   domain: "macro",      color: "#06b6d4" },
  cme_download:    { label: "CME下载",    domain: "cme",        color: "#f59e0b" },
  cme_parse:       { label: "CME解析",    domain: "cme",        color: "#f59e0b" },
  cme_ingest:      { label: "CME入库",    domain: "cme",        color: "#f59e0b" },
  option_wall:     { label: "期权分析",   domain: "cme",        color: "#10b981" },
  news_collect:    { label: "新闻采集",   domain: "news",       color: "#ef4444" },
  news_feature:    { label: "新闻特征",   domain: "news",       color: "#8b5cf6" },
  news_brief:      { label: "每日简报",   domain: "news",       color: "#06b6d4" },
  strategy_card:   { label: "策略卡",     domain: "output",     color: "#10b981" },
};

export { STEP_META };

// ── Step Node ID ──

function stepNodeId(step: string): string {
  return `step::${step}`;
}

function sourceNodeId(sourceKey: string): string {
  return `src::${sourceKey}`;
}

// ── Domain Colors ──

const DOMAIN_COLORS: Record<string, string> = {
  macro: "#3b82f6",
  cme: "#f59e0b",
  technical: "#8b5cf6",
  positioning: "#10b981",
  news: "#ef4444",
  report: "#06b6d4",
};

export { DOMAIN_COLORS };

// ── Status Mapping ──

function sourceStatusToDag(status: string): "success" | "partial" | "failed" | "pending" {
  switch (status) {
    case "ok": return "success";
    case "partial":
    case "warn": return "partial";
    case "error": return "failed";
    default: return "pending";
  }
}

// ── Provider Role Label ──

export function providerRoleLabel(role: string): string {
  switch (role) {
    case "official_primary": return "主源";
    case "fallback": return "备用";
    case "supplemental": return "补充";
    case "derived": return "衍生";
    case "aggregator": return "聚合";
    case "wire_public_candidate": return "候选";
    default: return role;
  }
}

// ── Build DAG Graph ──

export interface LineageDagGraph extends DagGraph {
  sourceNodes: DagNodeSpec[];
  stepNodes: DagNodeSpec[];
  outputNodes: DagNodeSpec[];
}

export async function fetchLineageDagGraph(domainFilter?: string): Promise<LineageDagGraph> {
  const response = await fetchDataIngestionData();
  const sources = response.view_model.sources;

  return buildLineageDagGraph(sources, domainFilter);
}

function buildLineageDagGraph(
  sources: DataSourceStatusViewModel[],
  domainFilter?: string,
): LineageDagGraph {
  const nodes: DagNodeSpec[] = [];
  const edges: DagEdge[] = [];
  const sourceNodes: DagNodeSpec[] = [];
  const stepNodes: DagNodeSpec[] = [];
  const outputNodes: DagNodeSpec[] = [];

  // Index sources by id for quick lookup
  const sourceMap = new Map<string, DataSourceStatusViewModel>();
  for (const src of sources) sourceMap.set(src.id, src);

  // Determine which source groups are active based on domain filter
  const activeGroups = domainFilter
    ? SOURCE_GROUPS.filter(g => g.domain === domainFilter || g.source_keys.some(k => sourceMap.get(k)?.group === domainFilter))
    : SOURCE_GROUPS;

  // Collect active steps based on active groups
  const activeSteps = new Set<string>();
  for (const grp of activeGroups) {
    for (const key of grp.source_keys) {
      const step = SOURCE_TO_STEP[key];
      if (step) {
        activeSteps.add(step);
        const addDownstream = (s: string) => {
          for (const ds of STEP_GRAPH[s] || []) {
            activeSteps.add(ds);
            addDownstream(ds);
          }
        };
        addDownstream(step);
      }
    }
  }
  activeSteps.add("strategy_card");

  // Create grouped source nodes (去重：每组一个节点)
  for (const grp of activeGroups) {
    const groupSources = grp.source_keys
      .map(k => sourceMap.get(k))
      .filter((s): s is DataSourceStatusViewModel => !!s);

    if (groupSources.length === 0) continue;

    // Aggregate status: worst wins
    const statuses = groupSources.map(s => sourceStatusToDag(s.raw_status));
    const aggStatus = statuses.includes("failed") ? "failed"
      : statuses.includes("partial") ? "partial"
      : statuses.every(s => s === "success") ? "success"
      : "pending";

    const onlineCount = groupSources.filter(s => s.raw_status === "ok").length;
    const domainColor = DOMAIN_COLORS[grp.domain] || "#94a3b8";

    const nodeId = `grp::${grp.group_id}`;
    const node: DagNodeSpec = {
      node_id: nodeId,
      type: "collector",
      label: `${grp.label} (${groupSources.length})`,
      sub_type: grp.domain,
      trade_date: null,
      status: aggStatus,
      category: grp.domain,
      module: "group",
      input: {
        source: groupSources.map(s => s.endpoint || s.id).join(", "),
        summary: `${groupSources.length} 个源 · ${onlineCount} 在线`,
        fields: {
          source_keys: grp.source_keys,
          sources: groupSources.map(s => ({
            id: s.id,
            label: s.label,
            status: s.raw_status,
            role: s.role,
          })),
        },
        source_refs: [],
        artifact_refs: [],
      },
      output: {
        source: grp.group_id,
        summary: `${onlineCount}/${groupSources.length} 在线`,
        fields: {
          total: groupSources.length,
          online: onlineCount,
          failed: groupSources.filter(s => s.raw_status === "error").length,
        },
        source_refs: [],
        artifact_refs: [],
      },
      execution: { started_at: null, ended_at: null, duration_ms: null, retries: 0 },
      upstream_ids: [],
      downstream_ids: [],
    };

    sourceNodes.push(node);
    nodes.push(node);
  }

  // Create step nodes (加工层)
  for (const step of activeSteps) {
    const meta = STEP_META[step];
    if (!meta) continue;

    const nodeId = stepNodeId(step);
    const isOutput = step === "strategy_card";

    const node: DagNodeSpec = {
      node_id: nodeId,
      type: isOutput ? "output" : step.includes("collect") ? "collector"
        : step.includes("parse") || step.includes("download") ? "parser"
        : step.includes("feature") ? "features"
        : step.includes("render") || step.includes("brief") || step.includes("wall") ? "output"
        : "analysis",
      label: meta.label,
      sub_type: meta.domain,
      trade_date: null,
      status: "pending",
      category: meta.domain,
      module: meta.domain,
      input: { source: "pipeline", summary: "", fields: {}, source_refs: [], artifact_refs: [] },
      output: { source: "pipeline", summary: "", fields: {}, source_refs: [], artifact_refs: [] },
      execution: { started_at: null, ended_at: null, duration_ms: null, retries: 0 },
      upstream_ids: [],
      downstream_ids: [],
    };

    if (isOutput) outputNodes.push(node);
    else stepNodes.push(node);
    nodes.push(node);
  }

  // Build edges: source group → step (deduplicated: one edge per group)
  const groupEdgeSeen = new Set<string>();
  for (const grp of activeGroups) {
    // Find the target step for this group (first source's step)
    const targetSteps = new Set<string>();
    for (const key of grp.source_keys) {
      const step = SOURCE_TO_STEP[key];
      if (step && activeSteps.has(step)) targetSteps.add(step);
    }

    for (const step of targetSteps) {
      const edgeKey = `grp::${grp.group_id}→${step}`;
      if (groupEdgeSeen.has(edgeKey)) continue;
      groupEdgeSeen.add(edgeKey);

      const fromId = `grp::${grp.group_id}`;
      const toId = stepNodeId(step);

      edges.push({
        from: fromId,
        to: toId,
        edge_type: "data_flow",
        data_contract: { fields: [], stage: `${grp.group_id}→${step}` },
      });

      const fromNode = nodes.find(n => n.node_id === fromId);
      const toNode = nodes.find(n => n.node_id === toId);
      if (fromNode) fromNode.downstream_ids.push(toId);
      if (toNode) toNode.upstream_ids.push(fromId);
    }
  }

  // Build edges: step → step
  for (const [from, tos] of Object.entries(STEP_GRAPH)) {
    if (!activeSteps.has(from)) continue;
    for (const to of tos) {
      if (!activeSteps.has(to)) continue;

      const fromId = stepNodeId(from);
      const toId = stepNodeId(to);

      edges.push({
        from: fromId,
        to: toId,
        edge_type: "data_flow",
        data_contract: { fields: [], stage: `${from}→${to}` },
      });

      const fromNode = nodes.find(n => n.node_id === fromId);
      const toNode = nodes.find(n => n.node_id === toId);
      if (fromNode) fromNode.downstream_ids.push(toId);
      if (toNode) toNode.upstream_ids.push(fromId);
    }
  }

  return {
    nodes,
    edges,
    trade_date: "all",
    generated_at: new Date().toISOString(),
    sourceNodes,
    stepNodes,
    outputNodes,
  };
}
