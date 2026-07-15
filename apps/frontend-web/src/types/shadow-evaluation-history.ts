import type { ShadowEvaluationHorizon } from "@/types/shadow-evaluation";

export type ShadowEvaluationLifecycleStatus =
  | "never_triggered"
  | "invalidated_before_entry"
  | "triggered"
  | "triggered_then_invalidated"
  | "target_reached"
  | "same_bar_ambiguous"
  | "insufficient_market_path"
  | "insufficient_strategy_contract"
  | "blocked";

export interface ShadowEvaluationOutcomeSummary {
  horizon: ShadowEvaluationHorizon;
  status: "scored" | "blocked" | "unscorable";
  classification: "correct" | "incorrect" | "neutral" | "hold" | "invalidated" | "blocked" | "unscorable";
  verification_status: "verified" | "legacy_unverified";
  lifecycle_status: ShadowEvaluationLifecycleStatus | null;
  setup_id: string | null;
  fill_price: number | null;
  fill_time: string | null;
  target_price: number | null;
  target_time: string | null;
  exit_price: number | null;
  exit_time: string | null;
  return_abs: number | null;
  return_pct: number | null;
  mfe: number | null;
  mae: number | null;
  reason_codes: string[];
}

export interface ShadowEvaluationHistoryItem {
  trade_date: string;
  evaluation_id: string;
  strategy_status: string;
  as_of: string | null;
  publish_allowed: boolean;
  outcome_count: number;
  approved_count: number;
  blocked_count: number;
  unscorable_count: number;
  legacy_unverified_count: number;
  accuracy: number | null;
  outcomes: ShadowEvaluationOutcomeSummary[];
  artifact_refs: string[];
}
export interface ShadowEvaluationHistoryResponse {
  schema_version: "shadow_evaluation_history.v1";
  account_id: string;
  asset: string;
  items: ShadowEvaluationHistoryItem[];
  total: number;
  truncated: boolean;
}
