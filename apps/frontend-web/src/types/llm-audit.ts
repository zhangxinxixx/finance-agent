export interface LLMAuditSummary {
  audit_id: string;
  call_id: string;
  status: string;
  caller: string;
  provider_requested?: string | null;
  provider_resolved?: string | null;
  model_requested?: string | null;
  model_resolved?: string | null;
  reasoning_effort_requested?: string | null;
  reasoning_effort_resolved?: string | null;
  request_config: Record<string, unknown>;
  request_sha256: string;
  response_sha256?: string | null;
  prompt_message_count: number;
  prompt_char_count: number;
  response_char_count: number;
  usage: Record<string, unknown>;
  latency_ms?: number | null;
  attempt_count: number;
  error_type?: string | null;
  error_message?: string | null;
  run_id?: string | null;
  snapshot_id?: string | null;
  report_id?: string | null;
  trade_date?: string | null;
  created_at?: string | null;
}

export interface LLMAuditDetail extends LLMAuditSummary {
  request_messages: Array<Record<string, unknown>>;
  response_text?: string | null;
  attempts: Array<Record<string, unknown>>;
  context: Record<string, unknown>;
  source_refs: Array<Record<string, unknown>>;
  secrets_redacted: boolean;
  sanitization_performed: boolean;
  content_included: boolean;
  immutable: boolean;
}

export interface LLMAuditListResponse {
  count: number;
  limit: number;
  offset: number;
  audits: LLMAuditSummary[];
}
