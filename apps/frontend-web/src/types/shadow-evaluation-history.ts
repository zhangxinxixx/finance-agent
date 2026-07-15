export interface ShadowEvaluationHistoryItem {
  trade_date: string;
  evaluation_id: string;
  strategy_status: string;
  publish_allowed: boolean;
  outcome_count: number;
  approved_count: number;
  blocked_count: number;
  unscorable_count: number;
  accuracy: number | null;
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
