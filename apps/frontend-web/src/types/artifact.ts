import type { DataStatus, DataAvailability, ReportFormat, SourceRef } from "@/types/common";

export type ArtifactKind =
  | "source"
  | "analysis"
  | "visual"
  | "evidence"
  | "markdown"
  | "html"
  | "json"
  | "raw"
  | "report"
  | "unknown";

export interface ArtifactRef {
  artifact_id?: string | null;
  artifact_type?: ArtifactKind | string | null;
  family?: string | null;
  title?: string | null;
  format?: ReportFormat | string | null;
  content_type?: string | null;
  file_path?: string | null;
  path?: string | null;
  is_primary?: boolean | null;
  run_id?: string | null;
  snapshot_id?: string | null;
  dataDate?: string | null;
  asOf?: string | null;
  status?: DataStatus | null;
  availability?: DataAvailability | null;
  source_refs?: SourceRef[];
}
