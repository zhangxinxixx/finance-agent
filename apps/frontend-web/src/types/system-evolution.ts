export interface SystemEvolutionArtifacts {
  findings?: string | null;
  improvement_proposals?: string | null;
  review?: string | null;
}

export interface SystemEvolutionFinding {
  finding_id?: string | null;
  code?: string | null;
  severity?: string | null;
  category?: string | null;
  title?: string | null;
  description?: string | null;
  affected_entities?: Record<string, unknown>;
  evidence?: Record<string, unknown>;
  source_refs?: unknown[];
  created_at?: string | null;
}

export interface SystemEvolutionProposal {
  proposal_id?: string | null;
  proposal_type?: string | null;
  title?: string | null;
  rationale?: string | null;
  proposed_changes?: string[];
  expected_impact?: string | null;
  risks?: string[];
  rollback_plan?: string | null;
  test_plan?: string[];
  status?: string | null;
  finding_codes?: string[];
  linked_issue?: string | null;
  linked_pr?: string | null;
  review_action_status?: string | null;
  review_actor?: string | null;
  review_note?: string | null;
  review_recorded_at?: string | null;
  test_result?: string | null;
  manual_confirmation?: string | null;
  rollback_reason?: string | null;
}

export interface SystemEvolutionReview {
  review_status?: string | null;
  blocked?: boolean;
  required_followups?: string[];
  [key: string]: unknown;
}

export interface SystemEvolutionItemList<T> {
  count: number;
  items: T[];
}

export interface SystemEvolutionReviewResponse {
  trade_date: string;
  artifacts: SystemEvolutionArtifacts;
  review: SystemEvolutionReview;
  findings: SystemEvolutionItemList<SystemEvolutionFinding>;
  proposals: SystemEvolutionItemList<SystemEvolutionProposal>;
  proposal_actions?: {
    trade_date: string;
    count: number;
    actions: unknown[];
  };
}
