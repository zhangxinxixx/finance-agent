export interface PromptEvolutionArtifacts {
  prompt_evaluation_cases?: string | null;
  prompt_ab_validation_result?: string | null;
  prompt_release_records?: string | null;
}

export interface PromptEvolutionCase {
  case_id?: string | null;
  case_type?: string | null;
  expected_assertions?: string[];
  failure_reason?: string | null;
  created_from?: string | null;
  source_refs?: unknown[];
}

export interface PromptEvolutionValidation {
  agent_name?: string | null;
  validation_status?: string | null;
  improvement_count?: number;
  regression_count?: number;
  proposal_only?: boolean;
  activated_prompt?: boolean;
  risk_notes?: string[];
  case_results?: Array<Record<string, unknown>>;
  active_prompt_result?: Record<string, unknown>;
  candidate_prompt_result?: Record<string, unknown>;
}

export interface PromptEvolutionReleaseRecord {
  agent_name?: string | null;
  action?: string | null;
  active_prompt_version_id?: string | null;
  candidate_prompt_version_id?: string | null;
  validation_artifact?: string | null;
  review_approved_by?: string | null;
  test_result?: string | null;
  rollback_reason?: string | null;
  rolled_back_from?: string | null;
  rolled_back_to?: string | null;
  affected_agents?: string[];
  recorded_at?: string | null;
  activated_prompt?: boolean;
}

export type PromptEvolutionReleaseAction = "release_approved" | "rolled_back";

export interface PromptEvolutionReleaseActionResponse {
  source: string;
  status: string;
  trade_date: string;
  activated_prompt: boolean;
  writes: string[];
  record: PromptEvolutionReleaseRecord;
}

export interface PromptEvolutionReleaseReadiness {
  status: string;
  can_request_release_approval: boolean;
  can_activate_after_review: boolean;
  can_record_rollback: boolean;
  blocking_reasons: string[];
  latest_release_action?: string | null;
  latest_rollback_reason?: string | null;
}

export interface PromptEvolutionItemList<T> {
  count: number;
  items: T[];
}

export interface PromptEvolutionReviewResponse {
  trade_date: string;
  artifacts: PromptEvolutionArtifacts;
  cases: PromptEvolutionItemList<PromptEvolutionCase>;
  validation: PromptEvolutionValidation;
  release_records: PromptEvolutionItemList<PromptEvolutionReleaseRecord>;
  release_readiness: PromptEvolutionReleaseReadiness;
}
