import type { ArtifactRef } from "@/types/artifact";
import type { DataStatus, DataAvailability, SourceRef } from "@/types/common";

export interface SnapshotRef {
  snapshot_id: string | null;
  dataDate?: string | null;
  asOf?: string | null;
  run_id?: string | null;
  status?: DataStatus | null;
  availability?: DataAvailability | null;
  source_refs?: SourceRef[];
  artifact_refs?: ArtifactRef[];
  input_snapshot_ids?: string[];
}

export interface SnapshotEnvelope extends SnapshotRef {
  snapshot_type?: string | null;
  source_key?: string | null;
  data_category?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  metadata?: Record<string, unknown> | null;
}
