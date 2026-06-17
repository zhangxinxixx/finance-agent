import { fetchJson } from "@/adapters/apiClient";
import type {
  AgentRegistryResponse,
  PromptFeedbackCreateRequest,
  PromptFeedbackItem,
  PromptFeedbackListResponse,
  PromptVersionActivateRequest,
  PromptVersionCreateRequest,
  PromptVersionItem,
  PromptVersionsResponse,
} from "@/types/agent-registry";

const AGENT_REGISTRY_PATH = "/api/agents/registry";
const AGENT_PROMPTS_PATH = "/api/agents/prompts";
const AGENT_FEEDBACK_PATH = "/api/agents/feedback";

export async function fetchAgentRegistry(): Promise<AgentRegistryResponse> {
  return fetchJson<AgentRegistryResponse>(AGENT_REGISTRY_PATH);
}

function jsonHeaders(): HeadersInit {
  return { "Content-Type": "application/json" };
}

export async function fetchAgentPromptVersions(agentId: string): Promise<PromptVersionsResponse> {
  return fetchJson<PromptVersionsResponse>(`${AGENT_PROMPTS_PATH}/${encodeURIComponent(agentId)}`);
}

export async function createAgentPromptVersion(agentId: string, payload: PromptVersionCreateRequest): Promise<PromptVersionItem> {
  return fetchJson<PromptVersionItem>(`${AGENT_PROMPTS_PATH}/${encodeURIComponent(agentId)}`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify(payload),
  });
}

export async function activateAgentPromptVersion(agentId: string, payload: PromptVersionActivateRequest): Promise<PromptVersionItem> {
  return fetchJson<PromptVersionItem>(`${AGENT_PROMPTS_PATH}/${encodeURIComponent(agentId)}/activate`, {
    method: "PATCH",
    headers: jsonHeaders(),
    body: JSON.stringify(payload),
  });
}

export async function createAgentPromptFeedback(payload: PromptFeedbackCreateRequest): Promise<PromptFeedbackItem> {
  return fetchJson<PromptFeedbackItem>(AGENT_FEEDBACK_PATH, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify(payload),
  });
}

export async function fetchAgentPromptFeedback(params: {
  agentId?: string | null;
  status?: string | null;
  limit?: number;
} = {}): Promise<PromptFeedbackListResponse> {
  const search = new URLSearchParams();
  if (params.agentId) search.set("agent_id", params.agentId);
  if (params.status) search.set("status", params.status);
  if (params.limit) search.set("limit", String(params.limit));
  const suffix = search.toString();
  return fetchJson<PromptFeedbackListResponse>(suffix ? `${AGENT_FEEDBACK_PATH}?${suffix}` : AGENT_FEEDBACK_PATH);
}
