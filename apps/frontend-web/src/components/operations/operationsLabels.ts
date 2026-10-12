/**
 * Labels used by the operational workbench.
 *
 * These are presentation translations only. The raw value remains available in
 * the evidence/detail views; the summary layer should never make an unknown
 * backend enum look healthy by falling back to a green-looking word.
 */

const STATUS_LABELS: Record<string, string> = {
  ok: "正常",
  live: "实时可读",
  configured: "已配置",
  scheduled: "已安排",
  idle: "空闲",
  stopped: "已停止",
  available: "可用",
  success: "成功",
  succeeded: "成功",
  complete: "已完成",
  completed: "已完成",
  ready: "已就绪",
  pass: "通过",
  passed: "通过",
  covered: "已覆盖",
  bound: "已绑定",
  matched: "已匹配",
  partial: "部分可用",
  partial_success: "部分成功",
  warn: "需关注",
  warning: "需关注",
  degraded: "降级可用",
  stale: "数据过期",
  pending: "等待处理",
  queued: "排队中",
  running: "运行中",
  retrying: "重试中",
  waiting: "等待中",
  needs_review: "待人工复核",
  observe: "观察等待",
  accepted: "已采用",
  blocked: "已阻塞",
  missing: "缺失",
  no_data: "暂无数据",
  no_snapshot: "无快照",
  not_found: "未匹配",
  unavailable: "不可用",
  failed: "失败",
  error: "错误",
  cancelled: "已取消",
  skipped: "已跳过",
  unknown: "待确认",
  rdy: "已就绪",
  err: "失败",
  blk: "已阻塞",
  wait: "等待中",
  source_missing: "来源缺失",
  event_stream: "事件流",
  observe_only: "仅观察，不形成结论",
};

const FIELD_LABELS: Record<string, string> = {
  task_type: "任务类型",
  trade_date: "交易日",
  current_stage: "当前阶段",
  progress: "运行进度",
  run_id: "运行标识",
  snapshot_id: "快照标识",
  result_id: "结果标识",
  final_result_id: "最终结果标识",
  steps: "步骤数",
  started_at: "开始时间",
  ended_at: "结束时间",
  token_in: "输入量",
  token_out: "输出量",
  cost_usd: "成本（USD）",
  source_ref: "来源引用",
  source_refs: "来源引用",
  artifact_ref: "产物引用",
  artifact_refs: "产物引用",
  source_health: "来源健康度",
  input_snapshot: "输入快照",
  input_snapshot_ids: "输入快照",
  agent_artifact: "分析产物",
  latest_raw_time: "最近原始数据",
  latest_parsed_time: "最近解析数据",
  row_count: "数据行数",
  next_run_time: "下次运行",
  last_run_id: "最近运行标识",
  fallback_for: "可替代来源",
  fallback_sources: "备用来源",
  configured: "配置状态",
  raw_ingested: "原始数据已接入",
  parsed: "已解析",
  analysis_ready: "分析已就绪",
  event_id: "事件标识",
  input_id: "输入标识",
  trace_id: "链路标识",
  processing_trace_id: "加工链路标识",
  primary_mainline: "主要主线",
  report: "报告",
  strategy_card: "策略卡片",
  publish_allowed: "发布权限",
  review_status: "复核状态",
};

const STAGE_LABELS: Record<string, string> = {
  connection: "连接",
  collect: "采集",
  rawLanding: "原始数据落地",
  parse: "解析",
  validate: "校验",
  snapshot: "快照",
  consumerReady: "消费就绪",
  collector: "采集",
  parser: "解析",
  features: "特征加工",
  analysis: "分析",
  renderer: "结果输出",
  raw: "原始数据",
  parsed: "解析数据",
  output: "分析输出",
  wait: "等待上游",
  idle: "空闲",
  out: "结果输出",
  fred: "FRED 宏观数据",
  treasury: "美国国债利率",
  dxy: "美元指数",
  cme: "CME 结构",
  cme_pdf: "CME 公告文件",
  collectors: "采集器",
  parsers: "解析器",
  agents: "分析代理",
  coordinator: "协调分析",
  reviewgate: "质量复核",
  dashboard: "看板",
  ops: "运维监控",
  event_stream: "事件流",
  cme_agent: "CME 期权分析",
  risk_agent: "风险分析",
  technical_agent: "技术结构分析",
  positioning_agent: "持仓分析",
  news_agent: "新闻事件分析",
  review_gate: "质量复核",
  source_health_check: "数据健康门控",
  gold_mainline_agent: "黄金主线分析",
};

const SOURCE_TYPE_LABELS: Record<string, string> = {
  api: "接口",
  pdf: "PDF 文件",
  scrape: "网页抓取",
  scraper: "网页抓取",
  structured: "结构化数据",
  webhook: "消息推送",
  rss: "订阅源",
  calendar: "事件日历",
  mcp: "数据通道",
  macro: "宏观数据",
  cme: "CME 结构",
  market: "市场行情",
  treasury: "国债利率",
  dxy: "美元指数",
};

const SOURCE_GROUP_LABELS: Record<string, string> = {
  macro: "宏观",
  cme: "CME 结构",
  market: "市场行情",
  liquidity: "流动性",
  positioning: "持仓与资金",
  news: "事件与新闻",
  events: "事件与新闻",
  reference: "参考资料",
};

const SOURCE_ROLE_LABELS: Record<string, string> = {
  primary: "主来源",
  fallback: "备用来源",
  derived: "派生来源",
  supplemental: "补充来源",
  primary_source: "主来源",
};

const STAGE_STATUS_LABELS: Record<string, string> = {
  ok: "正常",
  ready: "已就绪",
  warn: "需关注",
  partial: "部分可用",
  error: "失败",
  blocked: "已阻塞",
  waiting: "等待上游",
  no_data: "暂无数据",
  no_snapshot: "未生成快照",
  skipped: "已跳过",
};

const ENTITY_LABELS: Record<string, string> = {
  news: "新闻",
  report_input: "报告输入",
  event: "事件",
  analysis_signal: "分析信号",
  unknown: "待确认对象",
};

const REASON_LABELS: Record<string, string> = {
  standard_default: "常规任务默认路由",
  strong_default: "高复杂度任务默认路由",
  high_complexity: "复杂度较高",
  high_risk: "风险较高",
  explicit_request: "用户明确要求",
  failed_previous_attempt: "前次尝试失败",
  insufficient_comparable_evidence: "可比样本不足",
  missing_context: "上下文不足",
  analysis_error: "分析结果需要复核",
  prompt_quality: "提示内容质量",
  not_configured: "尚未配置",
  data_only: "目前只有数据接入",
  waiting: "等待任务接入",
  source_missing: "来源缺失",
  event_stream: "事件流输入",
  observe_only: "仅观察，不形成结论",
  not_enough_evidence: "证据不足",
  low_confidence: "置信度偏低",
  proposal_only: "仅提案，不写入",
  api_unavailable: "接口暂不可用",
};

const REVIEW_LABELS: Record<string, string> = {
  pending: "待处理",
  approved: "已通过",
  rejected: "已驳回",
  rerun: "重新运行",
  prompt_quality: "提示内容质量",
  analysis_error: "分析结果错误",
  missing_context: "上下文缺失",
  low: "低",
  medium: "中",
  high: "高",
  critical: "关键",
};

const ROUTER_LABELS: Record<string, string> = {
  auto: "自动路由",
  standard: "常规档",
  strong: "高强度档",
  disabled: "已停用",
  empty: "暂无记录",
  insufficient_comparable_evidence: "可比样本不足",
  candidate_available: "有候选方案，待独立验证",
  unknown: "待确认",
  low_confidence: "置信度偏低",
  not_enough_evidence: "证据不足",
};

const EVENT_LABELS: Record<string, string> = {
  run_started: "运行开始",
  run_finished: "运行完成",
  task_started: "任务开始",
  task_finished: "任务完成",
  step_started: "步骤开始",
  step_finished: "步骤完成",
  status_changed: "状态变化",
  evaluated: "已评估",
  written: "已写入",
  failed: "执行失败",
  error: "执行错误",
  blocked: "执行阻塞",
  degraded: "降级处理",
  fallback: "使用备用路径",
  retry: "重试",
  retried: "已重试",
};

const MAINLINE_LABELS: Record<string, string> = {
  gold_macro_overview: "黄金宏观总览",
  rates_dollar: "利率与美元",
  oil_geopolitics: "石油与地缘",
  geopolitical_war: "地缘冲突",
  cme_options: "CME 期权结构",
  event_flow: "事件流",
  technical_levels: "技术关键位",
  positioning: "持仓与资金",
  liquidity: "流动性",
  driver_decomposition: "驱动拆解",
  transmission_chain_detection: "传导链识别",
  mainline_attribution: "主线归因",
  event_flow_feature: "事件流特征",
  source_health: "数据健康门控",
  source_health_check: "数据健康门控",
  prompt_evolution: "提示内容治理",
  system_evolution: "系统演进治理",
};

function normalized(value: unknown): string {
  return typeof value === "string" ? value.trim().toLowerCase() : "";
}

export function operationStatusLabel(value: unknown): string {
  const key = normalized(value);
  if (!key) return "状态尚未说明";
  return STATUS_LABELS[key] ?? "状态尚未说明";
}

export function operationStatusToneKey(value: unknown): "positive" | "warning" | "negative" | "neutral" {
  const key = normalized(value);
  if (["ok", "available", "success", "succeeded", "complete", "completed", "ready", "pass", "passed", "covered", "bound", "matched", "accepted"].includes(key)) return "positive";
  if (["partial", "partial_success", "warn", "warning", "degraded", "stale", "pending", "queued", "running", "retrying", "waiting", "needs_review", "observe"].includes(key)) return "warning";
  if (["blocked", "missing", "no_data", "no_snapshot", "not_found", "unavailable", "failed", "error", "cancelled"].includes(key)) return "negative";
  return "neutral";
}

export function operationFieldLabel(value: unknown): string {
  const key = normalized(value);
  return FIELD_LABELS[key] ?? "字段尚未说明";
}

export function operationStageLabel(value: unknown): string {
  const key = typeof value === "string" ? value.trim().toLowerCase() : "";
  return key ? STAGE_LABELS[key] ?? "阶段尚未说明" : "阶段尚未说明";
}

export function operationSourceTypeLabel(value: unknown): string {
  const key = normalized(value);
  return key ? SOURCE_TYPE_LABELS[key] ?? "来源类型尚未说明" : "来源类型尚未说明";
}

export function operationSourceGroupLabel(value: unknown): string {
  const key = normalized(value);
  return key ? SOURCE_GROUP_LABELS[key] ?? "来源分组尚未说明" : "来源分组尚未说明";
}

export function operationSourceRoleLabel(value: unknown): string {
  const key = normalized(value);
  return key ? SOURCE_ROLE_LABELS[key] ?? "来源角色尚未说明" : "来源角色尚未说明";
}

export function operationStageStatusLabel(value: unknown): string {
  const key = normalized(value);
  return key ? STAGE_STATUS_LABELS[key] ?? "阶段状态尚未说明" : "阶段状态尚未说明";
}

export function operationEntityLabel(value: unknown): string {
  const key = normalized(value);
  return key ? ENTITY_LABELS[key] ?? "对象类型尚未说明" : "对象类型尚未说明";
}

export function operationReasonLabel(value: unknown): string {
  const key = normalized(value);
  return key ? REASON_LABELS[key] ?? "原因尚未说明" : "原因尚未说明";
}

export function operationReviewLabel(value: unknown): string {
  const key = normalized(value);
  return key ? REVIEW_LABELS[key] ?? "复核项尚未说明" : "复核项尚未说明";
}

export function operationRouterLabel(value: unknown): string {
  const key = normalized(value);
  return key ? ROUTER_LABELS[key] ?? "路由状态尚未说明" : "路由状态尚未说明";
}

export function operationEventLabel(value: unknown): string {
  const key = normalized(value).replace(/[-\s]+/g, "_");
  return key ? EVENT_LABELS[key] ?? "事件尚未说明" : "事件尚未说明";
}

export function operationMainlineLabel(value: unknown): string {
  const key = normalized(value);
  return key ? MAINLINE_LABELS[key] ?? "主线尚未说明" : "主线尚未说明";
}

/** Render machine-like operational values without putting raw enums in the reading layer. */
export function operationReadableLabel(value: unknown, fallback = "记录已登记"): string {
  if (typeof value !== "string" || value.trim().length === 0) return fallback;
  const original = value.trim();
  const key = original.toLowerCase().replace(/[\s-]+/g, "_");
  return STATUS_LABELS[key]
    ?? STAGE_LABELS[key]
    ?? SOURCE_TYPE_LABELS[key]
    ?? SOURCE_GROUP_LABELS[key]
    ?? SOURCE_ROLE_LABELS[key]
    ?? REASON_LABELS[key]
    ?? ROUTER_LABELS[key]
    ?? (/[\u4e00-\u9fff]/.test(original) ? original : fallback);
}

/** Keep the identifier useful while moving its technical nature out of the headline. */
export function evidenceLabel(value: unknown, missing = "未提供") {
  if (typeof value !== "string" || value.trim().length === 0) return missing;
  return "已登记";
}

export function evidenceDetailLabel(value: unknown, missing = "未登记") {
  if (typeof value !== "string" || value.trim().length === 0) return missing;
  return "已登记，可展开查看";
}
