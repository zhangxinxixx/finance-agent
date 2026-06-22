export type FeishuMonitorFilterStatus = "high_value" | "candidate" | string;

export interface FeishuMonitorTrigger {
  run_id?: string | null;
  priority?: string | null;
  status?: string | null;
  event_type?: string | null;
}

export interface FeishuMonitorArticleBrief {
  brief_id?: string | null;
  run_id?: string | null;
  headline?: string | null;
  article_class?: string | null;
  display_bucket?: string | null;
  access_status?: string | null;
  source_url?: string | null;
  final_url?: string | null;
  original_excerpt?: string | null;
  key_points?: string[];
  analysis_summary?: string | null;
  asset_tags?: string[];
  topic_tags?: string[];
  suggested_actions?: string[];
  source_refs?: Array<Record<string, unknown>>;
  detail_artifacts?: Record<string, unknown> | null;
  created_at?: string | null;
}

export interface FeishuMonitorTask {
  run_id?: string | null;
  status?: string | null;
  current_stage?: string | null;
  blocked?: boolean;
  blocked_reason?: string | null;
}

export interface FeishuMonitorMessage {
  message_id: string;
  chat_id?: string | null;
  sender_name?: string | null;
  message_type?: string | null;
  published_at?: string | null;
  title?: string | null;
  summary?: string | null;
  links: string[];
  primary_url?: string | null;
  source_marker?: string | null;
  filter_status: FeishuMonitorFilterStatus;
  content_kind?: "flash" | "article" | string;
  report_tags?: string[];
  trigger?: FeishuMonitorTrigger | null;
  article_brief?: FeishuMonitorArticleBrief | null;
  task?: FeishuMonitorTask | null;
  blocked?: boolean;
  actionable?: boolean;
}

export interface FeishuMonitorResponse {
  status: "available" | "empty" | string;
  date: string;
  as_of?: string | null;
  latest_published_at?: string | null;
  message_count: number;
  accepted_count: number;
  high_value_count?: number;
  triggered_count: number;
  brief_count: number;
  task_count: number;
  status_counts?: Record<string, number>;
  access_status_counts?: Record<string, number>;
  task_status_counts?: Record<string, number>;
  blocked_count?: number;
  actionable_count?: number;
  source_refs: Array<Record<string, unknown>>;
  messages: FeishuMonitorMessage[];
  data_quality: {
    parsed_artifact_count?: number;
    trigger_url_count?: number;
    brief_url_count?: number;
    task_url_count?: number;
    warning_count?: number;
  };
}
