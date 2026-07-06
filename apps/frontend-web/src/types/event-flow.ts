import type {
  GoldMacroOverview,
  GoldMainline,
  GoldMainlinesViewModel,
  GoldNetBias,
  TransmissionChain,
  TransmissionPath,
} from "@/types/gold-mainlines";

export type EventImportance = "高" | "中" | "低";
export type EventStatus = "已公布" | "发展中" | "传闻中" | "已结束" | "即将公布";
export type EventImpact =
  | "利多黄金"
  | "利空黄金"
  | "混合"
  | "混合偏空"
  | "偏空黄金"
  | "高波动待定"
  | "弱修复承压"
  | "双向波动"
  | "偏鹰扰动"
  | "边际偏空"
  | "事件前谨慎";
export type EventType =
  | "货币政策"
  | "经济数据"
  | "地缘政治"
  | "贸易政策"
  | "市场事件"
  | "宏观数据"
  | "市场价格"
  | "通胀数据"
  | "就业数据"
  | "地缘/能源"
  | "政策变量"
  | "资金流"
  | "政策会议";
export type PricingStatus = "已定价" | "部分定价" | "未定价";

export interface EventFlowTimelineItem {
  id: string;
  time: string;
  date: string;
  title: string;
  desc: string;
  type: EventType;
  importance: EventImportance;
  status: EventStatus;
  impact: EventImpact;
  source?: string | null;
  assets?: string | null;
  period?: string | null;
  pricing?: PricingStatus | null;
  verification_status?: string | null;
  risk_level?: string | null;
  event_kind?: string | null;
  raw_event_type?: string | null;
  processing_trace_id?: string | null;
  source_refs?: import("@/types/common").SourceRef[];
  affected_assets?: string[];
  impact_path?: string | null;
  gold_impact?: string | null;
  silver_impact?: string | null;
  dollar_impact?: string | null;
  yield_impact?: string | null;
  oil_impact?: string | null;
  market_validation?: Record<string, unknown>;
  market_snapshot?: Record<string, unknown>;
  related_news_items?: EventFlowRelatedNewsItem[];
  mainlines?: GoldMainline[];
  primary_mainline?: GoldMainline | null;
  transmission_chains?: Array<TransmissionPath | TransmissionChain>;
  dominant_driver?: string | null;
  bullish_drivers?: string[];
  bearish_drivers?: string[];
  net_effect?: GoldNetBias | null;
  verification_needed?: string[];
  verification_chain?: Record<string, unknown> | null;
  changed_dominant_theme?: boolean;
}

export interface EventFlowRelatedNewsItem {
  news_item_id: string;
  source_ref?: string | null;
  source: string;
  source_label: string;
  source_type?: string | null;
  title: string;
  summary?: string | null;
  importance?: string | null;
  confidence?: number | null;
  url?: string | null;
  domain?: string | null;
  published_at?: string | null;
  raw_path?: string | null;
  parsed_path?: string | null;
  status?: string | null;
  evaluation_role?: string | null;
}

export interface EventFlowChainStep {
  num: string;
  title: string;
  kind: "blue" | "warn" | "teal" | "up" | "down" | "grey";
  items: string[];
  pricing: PricingStatus | null;
}

export interface EventFlowSentimentItem {
  label: string;
  value: string;
  unit: string;
  delta: string;
  deltaDir: "up" | "down";
  deltaLabel: string;
  points: number[];
  kind: "bar" | "line";
  accent: string;
}

export interface EventFlowRadarAxis {
  label: string;
  value: number;
  idx: number;
}

export interface EventFlowTableRow {
  id?: string;
  time: string;
  title: string;
  type: EventType;
  source: string;
  assets: string;
  impact: EventImpact;
  pricing: PricingStatus;
  period: string;
  stars: number;
  verification_status?: string | null;
  risk_level?: string | null;
  event_kind?: string | null;
  source_refs?: import("@/types/common").SourceRef[];
  related_news_items?: EventFlowRelatedNewsItem[];
}

export interface EventFlowReportItem {
  title: string;
  desc: string;
  color: string;
}

export interface EventImpactSummary {
  bias: string;
  confidence: number;
  summary: string;
  sentiment: Record<string, unknown>;
  riskRadar: Record<string, unknown>;
  events: Array<Record<string, unknown>>;
  llmModel: string | null;
  llmElapsedSeconds: number | null;
}

export interface EventFlowBriefCounts {
  confirmedEventCount: number;
  candidateEventCount: number;
  unconfirmedRiskCount: number;
  calendarEventCount: number;
  sourceRefCount: number;
}

export interface EventFlowBriefSummary {
  headline: string;
  summary: string;
  status: string | null;
  riskLevel: string | null;
  verificationStatus: string | null;
  pricingStatus: string | null;
  artifactPath: string | null;
  counts: EventFlowBriefCounts;
  newsHighlights: string[];
  watchlist: string[];
  riskPoints: string[];
}

export interface EventFlowDailyBrief {
  status: string;
  reportMode: string;
  structured: {
    coreEventCount: number;
    keyArticleCount: number;
    marketReactionCount: number;
    riskFlagCount: number;
    oneLineInputs: string[];
  };
  markdownPreview?: string;
  qualityFlags: string[];
  date: string;
  runId: string;
  artifactPath?: string | null;
  inputSnapshotPath?: string | null;
  jsonPath?: string | null;
  sourceRefs: Array<Record<string, unknown>>;
}

export interface EventFlowReportInputItem {
  input_id: string;
  input_kind: "summary" | "followup" | "article_brief" | string;
  group: string;
  title: string;
  summary: string;
  verification_status?: string | null;
  access_status?: string | null;
  artifact_path?: string | null;
  source_url?: string | null;
  source_refs?: import("@/types/common").SourceRef[];
  task_status?: string | null;
}

export interface Jin10ArticleBrief {
  brief_id: string;
  article_class: string;
  display_bucket: string;
  headline: string;
  source_url: string;
  final_url?: string | null;
  access_status: string;
  original_excerpt: string;
  key_points: string[];
  analysis_summary: string;
  asset_tags: string[];
  topic_tags: string[];
  suggested_actions: string[];
  source_refs?: Array<Record<string, unknown>>;
  detail_artifacts?: Record<string, unknown>;
  data_quality?: Record<string, unknown>;
  created_at?: string | null;
}

export interface Jin10ArticleBriefBundle {
  status: "available" | "empty";
  date: string;
  run_id: string;
  artifact_path: string;
  as_of: string | null;
  rule_version: string | null;
  brief_count: number;
  display_bucket_counts: Record<string, number>;
  article_class_counts: Record<string, number>;
  access_status_counts: Record<string, number>;
  briefs: Jin10ArticleBrief[];
  data_quality?: Record<string, unknown>;
}

export interface EventFlowProgressTrigger {
  trigger_id: string;
  trigger_type: string;
  event_type: string;
  priority: string;
  status: string;
  source_title: string;
  evidence_text: string;
  source_url: string;
  created_at?: string | null;
  published_at?: string | null;
  source_domain?: string | null;
  asset_tags: string[];
  topic_tags: string[];
  source_refs?: import("@/types/common").SourceRef[];
  data_quality?: Record<string, unknown>;
}

export interface EventFlowProgressTriggerBundle {
  status: "available" | "empty";
  date: string;
  run_id: string;
  artifact_path: string;
  as_of: string | null;
  rule_version: string | null;
  trigger_count: number;
  triggers: EventFlowProgressTrigger[];
  data_quality?: Record<string, unknown>;
}

export interface EventFlowActionRequest {
  action?: string;
  actor?: string;
  reason?: string;
  note?: string;
  request_id?: string;
}

export interface EventFlowBriefLinkRequest extends EventFlowActionRequest {
  target_event_id: string;
}

export interface EventFlowActionResponse {
  run_id: string | null;
  snapshot_id?: string | null;
  data_status: string;
  source_refs: import("@/types/common").SourceRef[];
  artifact_refs?: Array<Record<string, unknown>>;
  warnings?: Array<Record<string, unknown>>;
  status: string;
  action: string;
  entity_type: string;
  entity_id: string;
  review_id: string | null;
  audit_id: string | null;
}

export interface EventFlowViewModel {
  status: "available" | "partial" | "error" | "unavailable";
  source: string;
  updated_at: string;
  timeline: EventFlowTimelineItem[];
  chain: EventFlowChainStep[];
  sentiment: EventFlowSentimentItem[];
  radar: EventFlowRadarAxis[];
  table: EventFlowTableRow[];
  reports: EventFlowReportItem[];
  event_impact_summary?: EventImpactSummary | null;
  brief_summary?: EventFlowBriefSummary | null;
  daily_analysis_triggers?: EventFlowProgressTriggerBundle | null;
  article_briefs?: Jin10ArticleBriefBundle | null;
  report_input_items?: EventFlowReportInputItem[];
  gold_macro_overview?: GoldMacroOverview | null;
  gold_mainlines?: GoldMainlinesViewModel | null;
  has_data: boolean;
  source_refs?: import("@/types/common").SourceRef[];
}
