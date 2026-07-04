export interface Jin10WebFlashBrief {
  brief_id: string;
  item_id: string;
  source_key: string;
  content_family: string;
  display_bucket: string;
  headline: string;
  summary: string;
  published_at: string;
  url: string;
  priority_bucket: string;
  importance_source: string;
  verification_status: string;
  access_status: string;
  tags: string[];
  source_refs: Array<Record<string, unknown>>;
  artifact_refs: Array<Record<string, unknown>>;
  created_at: string;
  data_quality: Record<string, unknown>;
}

export interface Jin10WebFlashBriefsResponse {
  status: string;
  date: string;
  run_id: string;
  retrieved_date?: string | null;
  artifact_path: string;
  as_of?: string | null;
  rule_version?: string | null;
  brief_count: number;
  briefs: Jin10WebFlashBrief[];
  data_quality: Record<string, unknown>;
  source_refs: Array<Record<string, unknown>>;
  artifact_refs: Array<Record<string, unknown>>;
  quality_flags: Record<string, unknown>;
}
