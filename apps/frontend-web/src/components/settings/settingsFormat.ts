import { readerSource } from "@/lib/readerLabels";

export function formatSettingsTime(value: string | null | undefined): string {
  if (!value) return "未记录时间";
  return value.replace("T", " ").replace("Z", "");
}

const ACTION_LABELS: Record<string, string> = {
  set: "写入",
  reset: "清除",
  rollback: "回滚",
};

const SCOPE_LABELS: Record<string, string> = {
  global: "全局设置",
  source: "数据源",
  secret: "密钥",
};

const SOURCE_STATUS_LABELS: Record<string, string> = {
  CONNECTED: "已连接",
  DISCONNECTED: "未连接",
  UNKNOWN: "未知",
};

const PROMPT_STATUS_LABELS: Record<string, string> = {
  active: "已激活",
  draft: "草稿",
  candidate: "候选",
  deprecated: "已弃用",
  rolled_back: "已回滚",
};

const PROMPT_KIND_LABELS: Record<string, string> = {
  llm: "模型提示词",
  rule: "规则模板",
  hybrid: "混合模板",
  planned: "规划中",
};

const FEEDBACK_CATEGORY_LABELS: Record<string, string> = {
  prompt_quality: "提示词质量",
  analysis_error: "分析错误",
  missing_context: "上下文缺失",
};

const SETTING_KEY_LABELS: Record<string, string> = {
  language: "界面语言",
  timezone: "时区",
  report_template: "报告模板",
};

const PREFERENCE_VALUE_LABELS: Record<string, Record<string, string>> = {
  language: {
    "zh-CN": "简体中文",
    "en-US": "英文界面",
    English: "英文界面",
    Chinese: "中文界面",
    "简体中文": "简体中文",
  },
  timezone: {
    "Asia/Shanghai": "中国标准时间（东八区）",
    UTC: "协调世界时（UTC）",
  },
  report_template: {
    standard: "标准报告",
    institutional_focus: "机构重点报告",
    default: "默认报告模板",
  },
};

const AGENT_STATUS_LABELS: Record<string, string> = {
  active_prompt: "提示词已激活",
  planned: "规划中",
  disabled: "已停用",
  active: "已启用",
};

const AGENT_PRIORITY_LABELS: Record<string, string> = {
  P0: "最高优先",
  P1: "高优先",
  P2: "普通优先",
  P3: "低优先",
};

const AGENT_NAME_LABELS: Record<string, string> = {
  SourceHealthAgent: "数据源健康智能体",
  EventAttributionAgent: "事件归因智能体",
  TransmissionChainAgent: "传导链智能体",
  DriverDecompositionAgent: "驱动拆解智能体",
  MainlineRankingAgent: "主线排序智能体",
  GoldMacroOverviewAgent: "黄金宏观总览智能体",
  ReviewGateAgent: "审查门智能体",
  ReportRenderAgent: "报告渲染智能体",
  SystemEvolutionAgent: "系统演进智能体",
  ArchitectureAgent: "架构智能体",
  SchemaAgent: "数据结构智能体",
  DagLineageAgent: "DAG 血缘智能体",
  TestValidationAgent: "测试验证智能体",
  PromptEvolutionAgent: "提示词演进智能体",
};

export function settingsActionLabel(value: string | null | undefined): string {
  const normalized = String(value ?? "").trim().toLowerCase();
  return ACTION_LABELS[normalized] ?? (normalized ? "未知动作（技术值见详情）" : "未提供动作");
}

export function settingsScopeLabel(value: string | null | undefined): string {
  const normalized = String(value ?? "").trim().toLowerCase();
  return SCOPE_LABELS[normalized] ?? (normalized ? "未知范围（技术值见详情）" : "未提供范围");
}

export function settingsSourceStatusLabel(value: string | null | undefined): string {
  const normalized = String(value ?? "").trim().toUpperCase();
  return SOURCE_STATUS_LABELS[normalized] ?? (normalized ? "未知状态（技术值见详情）" : "未提供状态");
}

export function promptStatusLabel(value: string | null | undefined): string {
  const normalized = String(value ?? "").trim().toLowerCase();
  return PROMPT_STATUS_LABELS[normalized] ?? (normalized ? "未知状态（技术值见详情）" : "未提供状态");
}

export function promptKindLabel(value: string | null | undefined): string {
  const normalized = String(value ?? "").trim().toLowerCase();
  return PROMPT_KIND_LABELS[normalized] ?? (normalized ? "未解释模板（技术值见详情）" : "未提供模板类型");
}

export function feedbackCategoryLabel(value: string | null | undefined): string {
  const normalized = String(value ?? "").trim().toLowerCase();
  return FEEDBACK_CATEGORY_LABELS[normalized] ?? (normalized ? "未解释类别（技术值见详情）" : "未提供类别");
}

export function feedbackStatusLabel(value: string | null | undefined): string {
  const normalized = String(value ?? "").trim().toLowerCase();
  if (normalized === "open") return "待处理";
  if (normalized === "resolved" || normalized === "closed") return "已处理";
  return normalized ? "未知状态（技术值见详情）" : "未提供状态";
}

export function settingsKeyLabel(value: string | null | undefined): string {
  const normalized = String(value ?? "").trim();
  if (!normalized) return "未提供设置项";
  return SETTING_KEY_LABELS[normalized] ?? (/[\u3400-\u9fff]/.test(normalized) ? normalized : "未解释设置项（技术值见详情）");
}

export function settingsPreferenceValueLabel(key: string | null | undefined, value: string | null | undefined): string {
  const normalizedKey = String(key ?? "").trim();
  const normalizedValue = String(value ?? "").trim();
  if (!normalizedValue) return "未提供选项";
  return PREFERENCE_VALUE_LABELS[normalizedKey]?.[normalizedValue] ?? "已记录选项（技术值见详情）";
}

export function settingsActorLabel(value: string | null | undefined): string {
  const normalized = String(value ?? "").trim();
  if (!normalized || normalized.toLowerCase() === "system") return "系统";
  return /[\u3400-\u9fff]/.test(normalized) ? normalized : "已记录操作者（技术标识见详情）";
}

export function settingsSourceLabel(value: string | null | undefined): string {
  return readerSource(value, "已关联数据源（技术值见详情）");
}

export function agentStatusLabel(value: string | null | undefined, fallback?: string | null): string {
  const normalized = String(value ?? "").trim().toLowerCase();
  if (AGENT_STATUS_LABELS[normalized]) return AGENT_STATUS_LABELS[normalized];
  const label = String(fallback ?? "").trim();
  if (label && /[\u3400-\u9fff]/.test(label)) return label.replace(/\s*Agent\b/gi, "智能体");
  return normalized ? "未解释状态（技术值见详情）" : "未提供状态";
}

export function agentPriorityLabel(value: string | null | undefined): string {
  const normalized = String(value ?? "").trim().toUpperCase();
  return AGENT_PRIORITY_LABELS[normalized] ?? (normalized ? "未解释优先级（技术值见详情）" : "未提供优先级");
}

export function agentNameLabel(value: string | null | undefined): string {
  const normalized = String(value ?? "").trim();
  if (!normalized) return "未提供智能体名称";
  if (AGENT_NAME_LABELS[normalized]) return AGENT_NAME_LABELS[normalized];
  const agentSuffix = normalized.replace(/\s*Agent$/i, "").trim();
  if (agentSuffix && /[\u3400-\u9fff]/.test(agentSuffix)) return `${agentSuffix}智能体`;
  return /[\u3400-\u9fff]/.test(normalized) ? normalized : "未解释智能体（技术标识见详情）";
}
