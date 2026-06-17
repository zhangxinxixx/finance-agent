// ── Pipeline DAG Types ────────────────────────────────────────
// Standardized Node Spec for React Flow DAG visualization

export type DagNodeType = "collector" | "parser" | "features" | "analysis" | "output";
export type DagNodeStatus = "pending" | "running" | "success" | "failed" | "partial";

export interface DagNodeSpec {
  node_id: string;
  type: DagNodeType;
  label: string;
  sub_type: string;          // e.g., "technical", "dxy", "jin10_report"
  trade_date: string | null;
  status: DagNodeStatus;
  category: string;
  module: string;

  input: DagNodeIO;
  output: DagNodeIO;

  execution: {
    started_at: string | null;
    ended_at: string | null;
    duration_ms: number | null;
    retries: number;
  };

  // 血缘
  upstream_ids: string[];
  downstream_ids: string[];
}

export interface DagNodeIO {
  source: string;
  summary: string;           // 简短描述
  fields: Record<string, unknown>;
  source_refs: DagSourceRef[];
  artifact_refs: DagArtifactRef[];
}

export interface DagSourceRef {
  source_ref: string;
  label: string;
  endpoint: string | null;
  artifact_path: string | null;
  status: string;
}

export interface DagArtifactRef {
  artifact_id: string;
  artifact_type: string;
  file_path: string | null;
}

export interface DagEdge {
  from: string;
  to: string;
  edge_type: "data_flow" | "signal_flow" | "dependency" | "override";
  data_contract: {
    fields: string[];
    stage: string;
  };
}

export interface DagGraph {
  nodes: DagNodeSpec[];
  edges: DagEdge[];
  trade_date: string;
  generated_at: string;
}
