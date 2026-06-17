import type { ArtifactRef } from "@/types/artifact";
import type { DataAvailability, DataSourceKind, DataStatus, SourceRef } from "@/types/common";
import type { SnapshotRef } from "@/types/snapshot";
import type { SourceTraceEnvelope } from "@/types/source-trace";

export interface PageError {
  message: string;
  code?: string;
  status?: number | string | null;
}

export interface PageEnvelope<T> {
  status: DataStatus;
  availability: DataAvailability;
  source: DataSourceKind;
  data: T | null;
  dataDate?: string | null;
  asOf?: string | null;
  run_id?: string | null;
  snapshot_id?: string | null;
  source_refs: SourceRef[];
  artifact_refs: ArtifactRef[];
  snapshots?: SnapshotRef[];
  sourceTrace?: SourceTraceEnvelope | null;
  updated_at?: string | null;
  warnings?: string[];
  error?: PageError | null;
}

export interface ModuleEnvelope<T> extends Omit<PageEnvelope<T>, "sourceTrace" | "snapshots"> {
  id: string;
  label: string;
}
