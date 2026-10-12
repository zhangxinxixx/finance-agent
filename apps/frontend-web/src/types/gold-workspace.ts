import type { ResearchIdentity } from "@/types/research-identity";
import type { ResearchTradePlan } from "./research-trade-plan";

export type GoldFactStatus = "fresh" | "recent" | "stale" | "unverified" | "unavailable";
export type GoldImpact = "supportive" | "pressure" | "mixed" | "neutral" | "unconfirmed";
export interface GoldFact {
  key: string;
  label: string;
  value: number | null;
  unit: string;
  change: number | null;
  change_unit: string;
  change_window: string | null;
  observed_at: string | null;
  source: string | null;
  frequency: "intraday" | "daily" | "weekly" | "monthly";
  status: GoldFactStatus;
  impact: GoldImpact;
  interpretation: string;
  short_term_summary: string;
  macro_effect: { impact: GoldImpact; summary: string; change: number | null; unit: string; window: string | null; basis: string };
  source_refs: Array<Record<string, unknown>>;
}
export interface GoldResearchHorizon {
  status: "current" | "historical" | "unavailable";
  horizon: string;
  basis: "report_explicit" | "report_excerpt" | "unavailable";
  summary: string;
  sections: Array<{ title: string; content: string }>;
  as_of: string | null;
  note: string;
}
export type GoldTopicGroup = "changes" | "macro" | "funds" | "price" | "risk";
export interface GoldResearchTopic {
  key: string;
  label: string;
  group: GoldTopicGroup;
  status: "current" | "historical" | "unavailable";
  basis: "verified_report_topics" | "report_excerpt" | "unavailable";
  judgment: string;
  facts: string;
  transmission: string;
  response: string;
  alternatives: string;
  falsification: string;
  pending: string[];
  sections: Array<{ title: string; content: string }>;
  as_of: string | null;
  note: string;
}
export interface GoldWorkspace {
  schema_version: "gold_workspace.v1";
  generated_at: string;
  status: "available" | "partial" | "unavailable";
  price: GoldFact;
  factors: GoldFact[];
  research: {
    research_identity?: ResearchIdentity | null;
    status: "current" | "historical" | "unavailable";
    report_id: string | null;
    run_id: string | null;
    snapshot_id: string | null;
    trade_date: string | null;
    as_of: string | null;
    bias: string | null;
    summary: string;
    narrative: string;
    reason: string | null;
    latest_status: "available" | "unavailable";
    latest_reason: string | null;
    latest_run_id: string | null;
    authority: string;
    publish_allowed: boolean;
    trade_plan: ResearchTradePlan | null;
    key_levels: Array<Record<string, unknown>>;
    horizons: { short_term: GoldResearchHorizon; long_term: GoldResearchHorizon };
    topics: GoldResearchTopic[];
  };
  comparison: {
    status: "available" | "unavailable";
    reference_price: number | null;
    reference_time: string | null;
    price_change: number | null;
    price_change_pct: number | null;
    note: string;
  };
  warnings: string[];
  environment_watch: {
    status: "available" | "partial" | "unavailable";
    basis: string;
    conditions: Array<{ key: string; label: string; value: number; unit: string; supportive_condition: string; pressure_condition: string; observed_at: string | null }>;
    note: string;
  };
  cme_structure: {
    status: "reference" | "historical" | "unavailable";
    coordinate: "GC futures";
    trade_date: string | null;
    version_type: string | null;
    reference_price: number | null;
    basis_status: "unvalidated";
    levels: Array<{ price: number | null; lower: number | null; upper: number | null; role: string; label: string; meaning: string; expiry: string | null; invalidation: string[] }>;
    source_refs: Array<Record<string, unknown>>;
    note: string;
  };
}
export interface GoldAnalysisTask {
  id: string;
  status: string;
  error: string | null;
  steps: Array<{ name: string; status: string; error: string | null }>;
}
export interface GoldAnalysisPreflight {
  can_launch: boolean;
  blocking_reasons: string[];
  active_task_id: string | null;
  blocked_sources: string[];
}
export interface GoldAnalysisStart {
  phase: "running" | "blocked" | "uncertain";
  task_id: string | null;
  message: string;
}
