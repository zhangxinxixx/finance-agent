export type KnowledgeItemType = "method" | "playbook" | "note" | "review" | "agent" | "dict";

export type KnowledgeItemStatus = "长期有效" | "待复核" | "阶段有效";

export interface KnowledgeMonitorMetric {
  label: string;
  value: string;
  change: string;
  tone: "positive" | "negative" | "neutral";
}

export interface KnowledgeEvidence {
  title: string;
  body: string;
  meta: string;
}

export interface KnowledgeDownstream {
  name: string;
  state: string;
  note: string;
}

export interface KnowledgeTimelineEntry {
  time: string;
  title: string;
  copy: string;
}

export interface KnowledgeCitation {
  title: string;
  meta: string;
}

export interface KnowledgeItem {
  id: string;
  title: string;
  type: KnowledgeItemType;
  typeLabel: string;
  topic: string;
  status: KnowledgeItemStatus;
  summary: string;
  thesis: string;
  updated: string;
  createdAt: string;
  verifiedAt: string;
  version: string;
  author: string;
  confidence: number;
  citations: number;
  references: number;
  dashboards: number;
  agentReady: boolean;
  playbookReady: boolean;
  pinned: boolean;
  reviewQueued: boolean;
  tags: string[];
  scenes: string[];
  rules: string[];
  inputs: string[];
  monitorMetrics: KnowledgeMonitorMetric[];
  evidence: KnowledgeEvidence[];
  downstream: KnowledgeDownstream[];
  timeline: KnowledgeTimelineEntry[];
  citationFlow: {
    upstream: KnowledgeCitation[];
    downstream: KnowledgeCitation[];
  };
}

export type KnowledgeDetailTab = "overview" | "rules" | "io" | "dependencies" | "validation" | "citations";

export type KnowledgeOpsTab = "pinned" | "agent" | "distill" | "recent" | "recommend";

export type KnowledgeTypeTab = "all" | KnowledgeItemType;

export interface KnowledgeViewModel {
  status?: import("@/types/common").DataStatus;
  source?: "api" | "mock" | "unavailable";
  updated_at?: string | null;
  items: KnowledgeItem[];
  selectedId: string | null;
  selectedItem: KnowledgeItem | null;
  stats: {
    total: number;
    agentReady: number;
    playbookCount: number;
    playbookCandidateCount: number;
    playbookPublishedCount: number;
    reviewQueueCount: number;
    pinnedCount: number;
    totalCitations: number;
  };
  source_refs?: import("@/types/common").SourceRef[];
  has_data?: boolean;
}
