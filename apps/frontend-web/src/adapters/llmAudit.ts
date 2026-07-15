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

function auditHeaders(token: string): HeadersInit | undefined {
  return token ? { "X-Finance-Audit-Token": token } : undefined;
}

export async function fetchLLMAudits(filters: LLMAuditFilters = {}, token = ""): Promise<LLMAuditListResponse> {
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
  return fetchJson<LLMAuditListResponse>(`/api/llm/audits${query ? `?${query}` : ""}`, { headers: auditHeaders(token) });
}

export async function fetchLLMAuditDetail(auditId: string, token = "", includeContent = false): Promise<LLMAuditDetail> {
  const suffix = includeContent ? "?include_content=true" : "";
  return fetchJson<LLMAuditDetail>(`/api/llm/audits/${encodeURIComponent(auditId)}${suffix}`, { headers: auditHeaders(token) });
}
