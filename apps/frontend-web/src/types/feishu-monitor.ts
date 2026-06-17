export type FeishuMonitorFilterStatus = "high_value" | "candidate" | "archive_only" | "reject" | "unknown" | string;

export interface FeishuMonitorRelevance {
  score?: number | null;
  reasons: string[];
  asset_tags: string[];
  topic_tags: string[];
  event_type_hint?: string | null;
  need_detail_fetch: boolean;
  need_verification: boolean;
}

export interface FeishuMonitorAcceptedItem {
  source_key?: string | null;
  title?: string | null;
  url?: string | null;
  domain?: string | null;
  event_type?: string | null;
  duplicate_key?: string | null;
  verification_status?: string | null;
}

export interface FeishuMonitorTrigger {
  trigger_id?: string | null;
  run_id?: string | null;
  priority?: string | null;
  status?: string | null;
  event_type?: string | null;
  reason_codes: string[];
  suggested_actions: string[];
  data_quality?: Record<string, unknown>;
  artifact_path?: string | null;
}

export interface FeishuMonitorArticleBrief {
  brief_id?: string | null;
  run_id?: string | null;
  article_class?: string | null;
  display_bucket?: string | null;
  headline?: string | null;
  access_status?: string | null;
  final_url?: string | null;
  analysis_summary?: string | null;
  detail_artifacts?: {
    parsed_path?: string | null;
    raw_html_path?: string | null;
    image_asset_count?: number | null;
    vlm_insight_count?: number | null;
  };
  data_quality?: Record<string, unknown>;
  artifact_path?: string | null;
}

export interface FeishuMonitorTaskStep {
  name?: string | null;
  status?: string | null;
  blocked_reason?: string | null;
  error_type?: string | null;
}

export interface FeishuMonitorTask {
  run_id?: string | null;
  status?: string | null;
  current_stage?: string | null;
  progress?: number | null;
  error_summary?: string | null;
  steps: FeishuMonitorTaskStep[];
}

export interface FeishuMonitorMessage {
  message_id: string;
  chat_id?: string | null;
  sender_name?: string | null;
  message_type?: string | null;
  published_at?: string | null;
  content?: string | null;
  links: string[];
  primary_url?: string | null;
  source_marker?: string | null;
  looks_like_jin10: boolean;
  filter_status: FeishuMonitorFilterStatus;
  relevance: FeishuMonitorRelevance;
  accepted_item?: FeishuMonitorAcceptedItem | null;
  trigger?: FeishuMonitorTrigger | null;
  article_brief?: FeishuMonitorArticleBrief | null;
  task?: FeishuMonitorTask | null;
  parsed_artifact_path?: string | null;
}

export interface FeishuMonitorResponse {
  status: "available" | "empty" | string;
  date: string;
  message_count: number;
  accepted_count: number;
  triggered_count: number;
  brief_count: number;
  task_count: number;
  source_refs: Array<Record<string, unknown>>;
  messages: FeishuMonitorMessage[];
  data_quality: {
    parsed_artifact_count?: number;
    trigger_url_count?: number;
    brief_url_count?: number;
    task_url_count?: number;
    warning_count?: number;
    warnings?: string[];
  };
}
