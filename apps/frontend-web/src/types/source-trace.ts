import type { ArtifactRef } from "@/types/artifact";
import type { DataStatus, DataAvailability, SourceRef } from "@/types/common";
import type { SnapshotRef } from "@/types/snapshot";

export type SourceTraceTargetType = "snapshot" | "report" | "strategy" | "run" | "artifact" | "source" | "unknown";

export interface SourceTraceEnvelope {
  target_type: SourceTraceTargetType;
  target_id?: string | null;
  status: DataStatus;
  availability?: DataAvailability | null;
  run_id?: string | null;
  snapshot_id?: string | null;
  dataDate?: string | null;
  asOf?: string | null;
  source_refs: SourceRef[];
  artifact_refs: ArtifactRef[];
  input_snapshots?: SnapshotRef[];
  related_artifacts?: ArtifactRef[];
  error_reason?: string | null;
}

export interface SourceTracePayload extends SourceTraceEnvelope {
  snapshot?: SnapshotRef | null;
}
