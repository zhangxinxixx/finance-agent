import type { SourceRef } from "@/types/common";

export interface PlaybookTemplateSourceRef extends SourceRef {
  source_ref: string;
  label?: string | null;
}

export interface PlaybookTemplateVersion {
  playbook_id: string;
  version: string;
  status: string;
  title: string;
  summary: string;
  conditions: string[];
  actions: string[];
  invalidations: string[];
  source_refs: PlaybookTemplateSourceRef[];
  last_validated: string | null;
  actor: string | null;
  reason: string | null;
  request_id: string | null;
  audit_id: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface PlaybookTemplateDetail extends PlaybookTemplateVersion {
  versions: PlaybookTemplateVersion[];
}

export interface PlaybookRegistryViewModel {
  status: "available" | "partial" | "unavailable" | "error";
  source: "api" | "mock" | "unavailable";
  items: PlaybookTemplateVersion[];
  selectedId: string | null;
  selectedItem: PlaybookTemplateDetail | null;
  total: number;
  source_refs: SourceRef[];
  has_data: boolean;
}
