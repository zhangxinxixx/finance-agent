import { fetchJson } from "@/adapters/apiClient";
import type { SystemEvolutionReviewResponse } from "@/types/system-evolution";

const SYSTEM_EVOLUTION_LATEST_PATH = "/api/governance/system-evolution/latest";
const SYSTEM_EVOLUTION_PROPOSAL_ACTION_PATH = "/api/governance/system-evolution/proposal/action";

export type SystemEvolutionProposalAction =
  | "approve"
  | "reject"
  | "link_issue"
  | "link_pr"
  | "mark_implemented"
  | "mark_rolled_back";

export interface SystemEvolutionProposalActionResponse {
  status: string;
  trade_date: string;
  action: {
    proposal_id: string;
    action: SystemEvolutionProposalAction;
    actor: string;
    note?: string | null;
    issue_url?: string | null;
    pr_url?: string | null;
    test_result?: string | null;
    manual_confirmation?: string | null;
    rollback_reason?: string | null;
    recorded_at: string;
  };
}

export async function fetchSystemEvolutionReview(date?: string | null): Promise<SystemEvolutionReviewResponse> {
  const search = new URLSearchParams();
  if (date) search.set("date", date);
  const suffix = search.toString() ? `?${search.toString()}` : "";
  return fetchJson<SystemEvolutionReviewResponse>(`${SYSTEM_EVOLUTION_LATEST_PATH}${suffix}`);
}

export async function submitSystemEvolutionProposalAction(params: {
  date: string;
  proposalId: string;
  action: SystemEvolutionProposalAction;
  actor?: string | null;
  note?: string | null;
  issueUrl?: string | null;
  prUrl?: string | null;
  testResult?: string | null;
  manualConfirmation?: string | null;
  rollbackReason?: string | null;
}): Promise<SystemEvolutionProposalActionResponse> {
  return fetchJson<SystemEvolutionProposalActionResponse>(SYSTEM_EVOLUTION_PROPOSAL_ACTION_PATH, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      date: params.date,
      proposal_id: params.proposalId,
      action: params.action,
      actor: params.actor ?? "review_center",
      note: params.note ?? undefined,
      issue_url: params.issueUrl ?? undefined,
      pr_url: params.prUrl ?? undefined,
      test_result: params.testResult ?? undefined,
      manual_confirmation: params.manualConfirmation ?? undefined,
      rollback_reason: params.rollbackReason ?? undefined,
    }),
  });
}
