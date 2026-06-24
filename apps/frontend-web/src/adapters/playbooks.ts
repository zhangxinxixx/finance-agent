import { fetchJson } from "@/adapters/apiClient";
import type { PlaybookRegistryViewModel, PlaybookTemplateDetail, PlaybookTemplateSourceRef, PlaybookTemplateVersion } from "@/types/playbook";

interface PlaybookListApiResponse {
  items?: Array<Record<string, unknown>>;
  total?: number;
}

interface PlaybookDetailApiResponse extends Record<string, unknown> {
  versions?: Array<Record<string, unknown>>;
}

function asString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function asStringOrNull(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function toSourceRef(item: Record<string, unknown>): PlaybookTemplateSourceRef {
  return {
    source_ref: asString(item.source_ref),
    label: asStringOrNull(item.label),
    endpoint: asStringOrNull(item.endpoint),
    artifact_path: asStringOrNull(item.artifact_path),
    snapshot_id: asStringOrNull(item.snapshot_id),
    run_id: asStringOrNull(item.run_id),
  };
}

function toVersion(item: Record<string, unknown>): PlaybookTemplateVersion {
  return {
    playbook_id: asString(item.playbook_id),
    version: asString(item.version),
    status: asString(item.status),
    title: asString(item.title),
    summary: asString(item.summary),
    conditions: Array.isArray(item.conditions) ? item.conditions.filter((value): value is string => typeof value === "string") : [],
    actions: Array.isArray(item.actions) ? item.actions.filter((value): value is string => typeof value === "string") : [],
    invalidations: Array.isArray(item.invalidations)
      ? item.invalidations.filter((value): value is string => typeof value === "string")
      : [],
    source_refs: Array.isArray(item.source_refs)
      ? item.source_refs.map((sourceRef) => toSourceRef(sourceRef as Record<string, unknown>))
      : [],
    last_validated: asStringOrNull(item.last_validated),
    actor: asStringOrNull(item.actor),
    reason: asStringOrNull(item.reason),
    request_id: asStringOrNull(item.request_id),
    audit_id: asStringOrNull(item.audit_id),
    created_at: asStringOrNull(item.created_at),
    updated_at: asStringOrNull(item.updated_at),
  };
}

function toDetail(item: Record<string, unknown>): PlaybookTemplateDetail {
  return {
    ...toVersion(item),
    versions: Array.isArray(item.versions)
      ? item.versions.map((version) => toVersion(version as Record<string, unknown>))
      : [],
  };
}

export async function fetchPlaybookRegistryView(selectedId?: string | null): Promise<PlaybookRegistryViewModel> {
  const raw = await fetchJson<PlaybookListApiResponse>("/api/playbooks");
  const items = (raw.items ?? []).map((item) => toVersion(item));
  if (items.length === 0) {
    return {
      status: "unavailable",
      source: "api",
      items,
      selectedId: null,
      selectedItem: null,
      total: 0,
      source_refs: [],
      has_data: false,
    };
  }

  const effectiveId = selectedId && items.some((item) => item.playbook_id === selectedId)
    ? selectedId
    : items[0]?.playbook_id ?? null;

  let selectedItem: PlaybookTemplateDetail | null = null;
  let status: PlaybookRegistryViewModel["status"] = "available";
  if (effectiveId) {
    try {
      const detail = await fetchJson<PlaybookDetailApiResponse>(`/api/playbooks/${effectiveId}`);
      selectedItem = toDetail(detail);
    } catch {
      selectedItem = {
        ...items.find((item) => item.playbook_id === effectiveId) ?? items[0],
        versions: items.filter((item) => item.playbook_id === effectiveId),
      };
      status = "partial";
    }
  }

  return {
    status,
    source: "api",
    items,
    selectedId: effectiveId,
    selectedItem,
    total: raw.total ?? items.length,
    source_refs: selectedItem?.source_refs ?? items[0]?.source_refs ?? [],
    has_data: true,
  };
}
