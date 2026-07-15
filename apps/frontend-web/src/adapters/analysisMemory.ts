import { fetchJson } from "@/adapters/apiClient";
import type {
  AnalysisMemorySnapshot,
  AnalysisStateLineage,
  AnalysisStateView,
  AnalysisTransitionView,
  CandidateStatePage,
  CanonicalStateResponse,
  ContextBlockMetadata,
  ContextBundleMetadata,
  ContextBundleMetadataPage,
} from "@/types/analysis-memory";

type RawRecord = Record<string, unknown>;

function record(value: unknown): RawRecord {
  return value && typeof value === "object" && !Array.isArray(value) ? value as RawRecord : {};
}

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function optionalText(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function numberValue(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function records(value: unknown): RawRecord[] {
  return Array.isArray(value) ? value.filter((item): item is RawRecord => Boolean(item) && typeof item === "object" && !Array.isArray(item)) : [];
}

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function transition(value: unknown): AnalysisTransitionView | null {
  const item = record(value);
  if (!text(item.transition_id)) return null;
  return {
    transition_id: text(item.transition_id),
    from_state_id: optionalText(item.from_state_id),
    to_state_id: text(item.to_state_id),
    run_id: text(item.run_id),
    summary: text(item.summary),
    changes: records(item.changes),
    evidence_refs: records(item.evidence_refs),
    content_hash: text(item.content_hash),
    created_at: optionalText(item.created_at),
  };
}

function lineage(value: unknown): AnalysisStateLineage {
  const item = record(value);
  const snapshots = record(item.input_snapshot_ids);
  return {
    run_id: text(item.run_id),
    analysis_snapshot_db_id: optionalText(item.analysis_snapshot_db_id),
    final_analysis_result_id: optionalText(item.final_analysis_result_id),
    accepted_output_snapshot_id: optionalText(item.accepted_output_snapshot_id),
    input_snapshot_ids: Object.fromEntries(Object.entries(snapshots).filter((entry): entry is [string, string] => typeof entry[1] === "string")),
    source_refs: records(item.source_refs),
    artifact_ids: strings(item.artifact_ids),
  };
}

function state(value: unknown): AnalysisStateView {
  const item = record(value);
  const rawKind = text(item.state_kind);
  const stateKind = rawKind === "accepted_canonical" || rawKind === "candidate" || rawKind === "blocked" ? rawKind : "blocked";
  return {
    state_id: text(item.state_id),
    state_kind: stateKind,
    asset: text(item.asset),
    as_of: text(item.as_of),
    previous_state_id: optionalText(item.previous_state_id),
    quality_gate_action: text(item.quality_gate_action),
    publish_allowed: item.publish_allowed === true,
    accepted_output_source: text(item.accepted_output_source),
    accepted_output_agent_name: optionalText(item.accepted_output_agent_name),
    content_hash: text(item.content_hash),
    payload: record(item.payload),
    lineage: lineage(item.lineage),
    transition: transition(item.transition),
    created_at: optionalText(item.created_at),
  };
}

function pagination(value: unknown) {
  const item = record(value);
  return {
    page: numberValue(item.page),
    page_size: numberValue(item.page_size),
    total_items: numberValue(item.total_items),
    total_pages: numberValue(item.total_pages),
  };
}

function canonical(value: unknown): CanonicalStateResponse {
  const item = record(value);
  const canonicalState = state(item.state);
  if (canonicalState.state_kind !== "accepted_canonical" || !canonicalState.publish_allowed) {
    throw new Error("analysis-memory canonical contract rejected non-accepted state");
  }
  return {
    asset: text(item.asset),
    head_version: numberValue(item.head_version),
    state: canonicalState,
    canonical_chain: records(item.canonical_chain).map(state),
  };
}

function candidates(value: unknown): CandidateStatePage {
  const item = record(value);
  return { asset: text(item.asset), data: records(item.data).map(state), pagination: pagination(item.pagination) };
}

function block(value: unknown): ContextBlockMetadata {
  const item = record(value);
  return {
    name: text(item.name),
    utf8_bytes: numberValue(item.utf8_bytes),
    estimated_tokens: numberValue(item.estimated_tokens),
    trim_reasons: strings(item.trim_reasons),
    retained_evidence_ids: strings(item.retained_evidence_ids),
  };
}

function bundle(value: unknown): ContextBundleMetadata {
  const item = record(value);
  return {
    bundle_id: text(item.bundle_id),
    content_hash: text(item.content_hash),
    asset: text(item.asset),
    run_id: text(item.run_id),
    canonical_state_id: text(item.canonical_state_id),
    cutoff_at: text(item.cutoff_at),
    assembled_at: text(item.assembled_at),
    budget_tokens: numberValue(item.budget_tokens),
    estimated_tokens: numberValue(item.estimated_tokens),
    total_utf8_bytes: numberValue(item.total_utf8_bytes),
    within_budget: item.within_budget === true,
    blocks: records(item.blocks).map(block),
    source_refs: records(item.source_refs),
    artifact_path: text(item.artifact_path),
  };
}

function bundles(value: unknown): ContextBundleMetadataPage {
  const item = record(value);
  return { asset: text(item.asset), data: records(item.data).map(bundle), pagination: pagination(item.pagination) };
}

export async function fetchAnalysisMemory(asset = "XAUUSD"): Promise<AnalysisMemorySnapshot> {
  const encoded = encodeURIComponent(asset);
  const [canonicalResult, candidateResult, bundleResult] = await Promise.allSettled([
    fetchJson<unknown>(`/api/analysis-memory/assets/${encoded}/canonical?maxDepth=20`),
    fetchJson<unknown>(`/api/analysis-memory/assets/${encoded}/candidates?page=1&pageSize=20`),
    fetchJson<unknown>(`/api/analysis-memory/assets/${encoded}/context-bundles?page=1&pageSize=20`),
  ]);
  const warnings: string[] = [];
  let canonicalValue: CanonicalStateResponse | null = null;
  if (canonicalResult.status === "fulfilled") {
    try {
      canonicalValue = canonical(canonicalResult.value);
    } catch (cause) {
      warnings.push(cause instanceof Error ? cause.message : "canonical contract invalid");
    }
  } else {
    warnings.push("accepted canonical 尚不可用");
  }
  const candidateValue = candidateResult.status === "fulfilled"
    ? candidates(candidateResult.value)
    : { asset, data: [], pagination: { page: 1, page_size: 20, total_items: 0, total_pages: 0 } };
  const bundleValue = bundleResult.status === "fulfilled"
    ? bundles(bundleResult.value)
    : { asset, data: [], pagination: { page: 1, page_size: 20, total_items: 0, total_pages: 0 } };
  if (candidateResult.status === "rejected") warnings.push("candidate list 加载失败");
  if (bundleResult.status === "rejected") warnings.push("ContextBundle metadata 加载失败");
  if (!canonicalValue && candidateResult.status === "rejected" && bundleResult.status === "rejected") {
    throw new Error("Analysis Memory read APIs unavailable");
  }
  return { canonical: canonicalValue, candidates: candidateValue, bundles: bundleValue, warnings };
}

export async function acceptAnalysisMemoryCandidate(params: {
  candidateId: string;
  token: string;
  actor: string;
  reason: string;
  requestId: string;
  canonicalStateId: string;
  headVersion: number;
}): Promise<void> {
  await fetchJson(`/api/analysis-memory/candidates/${encodeURIComponent(params.candidateId)}/reviews`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Finance-Analysis-Memory-Token": params.token },
    body: JSON.stringify({
      action: "accept",
      actor: params.actor,
      reason: params.reason,
      request_id: params.requestId,
      expected_canonical_state_id: params.canonicalStateId,
      expected_head_version: params.headVersion,
    }),
  });
}
