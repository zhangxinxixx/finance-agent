export interface AgentPromptRegistry {
  kind: "llm" | "rule" | "hybrid" | "planned" | string;
  source: string;
  template: string | Record<string, unknown>;
}

/** DB-synced prompt version metadata (P2-11). */
export type PromptVersionStatus = "active" | "draft" | "candidate" | "deprecated" | "rolled_back";

export interface AgentPromptVersion {
  id: string;
  version: string;
  prompt_kind: string;
  status: PromptVersionStatus;
  enabled: boolean;
  model_routing?: Record<string, unknown> | null;
  change_note?: string | null;
  updated_at?: string | null;
}

export interface AgentRegistryItem {
  agent_id: string;
  name: string;
  agent_type: string;
  priority: string;
  status: string;
  status_label: string;
  description: string;
  input_sections: string[];
  output_targets: string[];
  source_module: string;
  prompt: AgentPromptRegistry;
  /** P2-11: populated when DB prompt_versions table is seeded */
  prompt_version?: AgentPromptVersion;
  prompt_versions_synced: boolean;
}

export interface AgentRegistryResponse {
  source: string;
  updated_at: string;
  agents: AgentRegistryItem[];
}

// ── P2-11 Prompt Versions ──

export interface PromptVersionItem {
  id: string;
  agent_id: string;
  version: string;
  prompt_kind: string;
  prompt_source?: string | null;
  prompt_template: Record<string, unknown>;
  prompt_sha256: string;
  status: PromptVersionStatus;
  enabled: boolean;
  model_routing?: Record<string, unknown> | null;
  change_note?: string | null;
  created_by?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface PromptVersionsResponse {
  source: string;
  count: number;
  versions: PromptVersionItem[];
  agent_id?: string;
  name?: string;
  note?: string;
}

export interface PromptVersionCreateRequest {
  prompt_kind?: string;
  prompt_source?: string | null;
  prompt_template: Record<string, unknown>;
  status?: PromptVersionStatus;
  enabled?: boolean;
  model_routing?: Record<string, unknown> | null;
  change_note?: string | null;
  created_by?: string | null;
  request_id?: string | null;
}

export interface PromptVersionActivateRequest {
  version: string;
  reason?: string | null;
}

// ── P2-11 Prompt Feedback ──

export interface PromptFeedbackItem {
  feedback_id: string;
  agent_output_id?: string | null;
  agent_id: string;
  prompt_version_id?: string | null;
  run_id?: string | null;
  rating?: number | null;
  category: string;
  comment?: string | null;
  suggested_changes?: Record<string, unknown> | null;
  review_item_id?: string | null;
  status: string;
  submitted_by?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface PromptFeedbackListResponse {
  source: string;
  count: number;
  feedback: PromptFeedbackItem[];
  agent_id?: string;
}

export interface PromptFeedbackCreateRequest {
  agent_id: string;
  agent_output_id?: string;
  prompt_version_id?: string;
  run_id?: string;
  rating?: number;
  category?: string;
  comment?: string;
  suggested_changes?: Record<string, unknown>;
  submitted_by?: string;
  request_id?: string;
}

// ── Gold v3 Prompt Evolution Preview ──

export interface PromptEvolutionFailurePattern {
  pattern_id?: string | null;
  description?: string | null;
  frequency?: number | null;
  examples?: unknown[];
  likely_root_cause?: string | null;
}

export interface PromptEvolutionProposalDetail {
  proposal_id?: string | null;
  proposal_type?: string | null;
  before_summary?: string | null;
  after_summary?: string | null;
  patch?: string | null;
  rationale?: string | null;
  risk?: string | null;
  rollback_plan?: string | null;
  test_cases?: unknown[];
}

export interface PromptEvolutionProposal {
  agent_name?: string | null;
  problem_summary?: string | null;
  failure_patterns?: PromptEvolutionFailurePattern[];
  prompt_update_proposal?: PromptEvolutionProposalDetail;
  requires_schema_change?: boolean;
  requires_data_source_change?: boolean;
  requires_dag_change?: boolean;
  manual_review_required?: boolean;
}

export interface PromptEvolutionInputRefs {
  agent_output_ids: string[];
  feedback_ids: string[];
  review_ids: string[];
}

export interface PromptEvolutionPreviewResponse {
  source: string;
  agent_id: string;
  proposal_only: boolean;
  current_prompt_source: string;
  recent_run_count: number;
  feedback_count: number;
  review_gate_finding_count: number;
  input_refs: PromptEvolutionInputRefs;
  proposal: PromptEvolutionProposal;
  writes: unknown[];
}
