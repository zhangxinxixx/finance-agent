import { fetchJson } from "@/adapters/apiClient";
import type { LLMAuditDetail, LLMAuditListResponse } from "@/types/llm-audit";

export interface LLMAuditFilters {
  limit?: number;
  offset?: number;
  status?: string;
  provider?: string;
  model?: string;
  caller?: string;
  runId?: string;
  reportId?: string;
  tradeDate?: string;
}

export async function fetchLLMAudits(filters: LLMAuditFilters = {}): Promise<LLMAuditListResponse> {
  const params = new URLSearchParams();
  if (filters.limit != null) params.set("limit", String(filters.limit));
  if (filters.offset != null) params.set("offset", String(filters.offset));
  if (filters.status) params.set("status", filters.status);
  if (filters.provider) params.set("provider", filters.provider);
  if (filters.model) params.set("model", filters.model);
  if (filters.caller) params.set("caller", filters.caller);
  if (filters.runId) params.set("run_id", filters.runId);
  if (filters.reportId) params.set("report_id", filters.reportId);
  if (filters.tradeDate) params.set("trade_date", filters.tradeDate);
  const query = params.toString();
  return fetchJson<LLMAuditListResponse>(`/api/llm/audits${query ? `?${query}` : ""}`);
}

export async function fetchLLMAuditDetail(auditId: string): Promise<LLMAuditDetail> {
  return fetchJson<LLMAuditDetail>(`/api/llm/audits/${encodeURIComponent(auditId)}`);
}
