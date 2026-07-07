import { fetchJson } from "@/adapters/apiClient";

const ORCHESTRATION_MANUAL_REVIEW_PATH = "/api/orchestration/manual-review";
const ORCHESTRATION_MANUAL_REVIEW_ACTION_PATH = "/api/orchestration/manual-review/action";

export type OrchestrationManualReviewAction = "acknowledged" | "resolved" | "dismissed";

export interface OrchestrationManualReviewItem {
  workflow_id: string;
  trigger?: string | null;
  status?: string | null;
  kind?: string | null;
  dedupe_key: string;
  reason?: string | null;
  facts: Record<string, unknown>;
  action_status: string;
  action_note?: string | null;
  action_actor?: string | null;
  action_recorded_at?: string | null;
}

export interface OrchestrationManualReviewResponse {
  trade_date: string;
  count: number;
  items: OrchestrationManualReviewItem[];
}

export interface OrchestrationManualReviewActionResponse {
  status: string;
  trade_date: string;
  action: {
    dedupe_key: string;
    action: OrchestrationManualReviewAction;
    actor: string;
    note?: string | null;
    recorded_at: string;
  };
}

export async function fetchOrchestrationManualReview(date?: string | null): Promise<OrchestrationManualReviewResponse> {
  const search = new URLSearchParams();
  if (date) search.set("date", date);
  const suffix = search.toString() ? `?${search.toString()}` : "";
  return fetchJson<OrchestrationManualReviewResponse>(`${ORCHESTRATION_MANUAL_REVIEW_PATH}${suffix}`);
}

export async function submitOrchestrationManualReviewAction(params: {
  date: string;
  dedupeKey: string;
  action: OrchestrationManualReviewAction;
  actor?: string | null;
  note?: string | null;
}): Promise<OrchestrationManualReviewActionResponse> {
  return fetchJson<OrchestrationManualReviewActionResponse>(ORCHESTRATION_MANUAL_REVIEW_ACTION_PATH, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      date: params.date,
      dedupe_key: params.dedupeKey,
      action: params.action,
      actor: params.actor ?? "review_center",
      note: params.note ?? undefined,
    }),
  });
}
