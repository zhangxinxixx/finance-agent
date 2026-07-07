import { fetchJson } from "@/adapters/apiClient";
import type {
  PromptEvolutionReleaseAction,
  PromptEvolutionReleaseActionResponse,
  PromptEvolutionReviewResponse,
} from "@/types/prompt-evolution";

const PROMPT_EVOLUTION_LATEST_PATH = "/api/governance/prompt-evolution/latest";
const PROMPT_EVOLUTION_RELEASE_ACTION_PATH = "/api/governance/prompt-evolution/release/action";

export async function fetchPromptEvolutionReview(date?: string | null): Promise<PromptEvolutionReviewResponse> {
  const search = new URLSearchParams();
  if (date) search.set("date", date);
  const suffix = search.toString() ? `?${search.toString()}` : "";
  return fetchJson<PromptEvolutionReviewResponse>(`${PROMPT_EVOLUTION_LATEST_PATH}${suffix}`);
}

export async function submitPromptEvolutionReleaseAction(params: {
  tradeDate: string;
  agentName: string;
  action: PromptEvolutionReleaseAction;
  activePromptVersionId?: string | null;
  candidatePromptVersionId?: string | null;
  validationArtifact?: string | null;
  reviewApprovedBy?: string | null;
  testResult?: string | null;
  rollbackReason?: string | null;
}): Promise<PromptEvolutionReleaseActionResponse> {
  return fetchJson<PromptEvolutionReleaseActionResponse>(PROMPT_EVOLUTION_RELEASE_ACTION_PATH, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      trade_date: params.tradeDate,
      agent_name: params.agentName,
      action: params.action,
      active_prompt_version_id: params.activePromptVersionId ?? undefined,
      candidate_prompt_version_id: params.candidatePromptVersionId ?? undefined,
      validation_artifact: params.validationArtifact ?? undefined,
      review_approved_by: params.reviewApprovedBy ?? "review_center",
      test_result: params.testResult ?? undefined,
      rollback_reason: params.rollbackReason ?? undefined,
    }),
  });
}
