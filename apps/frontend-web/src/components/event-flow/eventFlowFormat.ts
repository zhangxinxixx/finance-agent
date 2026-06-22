import type { EventImpact } from "@/types/event-flow";

export function getImpactLabel(impact: EventImpact): string {
  if (impact === "利多黄金") return "利多";
  if (impact === "利空黄金") return "利空";
  return impact;
}

const EVENT_FLOW_VALUE_MAP: Record<string, string> = {
  readable: "可读",
  unavailable: "不可用",
  available: "可用",
  empty: "空",
  unknown: "未知",
  partial: "部分返回",
  accepted: "已接受",
  rejected: "已拒绝",
  pending: "待处理",
  linked: "已关联",
  ignored: "已忽略",
  include: "纳入",
  exclude: "排除",
  review: "复核",
  review_pending: "待复核",
  needs_review: "待复核",
  verified: "已验证",
  needs_verification: "待验证",
  verification_pending: "待验证",
  javascript_required: "需浏览器渲染",
  vip_locked: "VIP受限",
  single_source: "单一来源",
  multi_source: "多来源",
  unpriced: "未定价",
  high: "高",
  medium: "中",
  low: "低",
  live: "实时",
  mock: "占位",
  derived: "推导",
  fallback: "回退",
  ok: "正常",
  reuters_public_news: "路透快讯",
  article_brief: "文章摘要",
  brief_summary: "摘要主线",
  summary: "摘要",
  followup: "跟进",
  news_highlight: "新闻要点",
  watchlist: "观察清单",
  risk_point: "风险点",
  event_candidate: "事件候选",
  candidate_event: "候选事件",
  confirmed_event: "已确认事件",
  unconfirmed_risk: "待验证风险",
  calendar: "日历事件",
  flash_news: "快讯",
  markdown: "文稿",
  json: "结构化数据",
  html: "网页",
  pdf: "PDF",
  options_report: "期权分析",
  jin10_daily_report: "金十日报",
  jin10_weekly_report: "金十周报",
  vip_market_reference: "VIP预览",
  gold_macro_market_reference: "重点分析",
  market_reference: "市场参考",
  hormuz_risk: "霍尔木兹风险",
  fomc_statement: "联邦公开市场委员会声明",
  fed_chair_signal: "联储表态",
  macro_data: "宏观数据",
  headline: "标题",
  status: "状态",
  pricing: "定价",
  verification: "验证",
  risk: "风险",
  artifact_path: "产物",
  source_refs: "来源引用",
  confirmed_events: "已确认事件",
  source_count: "来源数",
  run_id: "运行 ID",
  review_id: "复核 ID",
  input_id: "输入 ID",
  source_url: "来源链接",
  rule_version: "规则版本",
  brief_count: "摘要数量",
  created_at: "创建时间",
  assets: "关联资产",
  topics: "关联主题",
  as_of: "截止时间",
  date: "日期",
  data_status: "数据状态",
  matched_event: "匹配事件",
  article_class: "文章分类",
  source: "来源",
  task_status: "任务状态",
  display_bucket: "分组",
  success: "成功",
  failed: "失败",
  error: "异常",
  done: "已完成",
  submitted: "已提交",
  processed: "已处理",
  queued_not_implemented: "待实现",
  mixed: "混合",
  oil_up: "原油上行",
  dollar_strength: "美元走强",
  yield_up: "收益率上行",
  inflation_to_rates: "通胀 -> 利率",
  growth_to_yields: "增长 -> 美债收益率",
  geo_risk_to_oil_to_inflation: "地缘风险 -> 油价 -> 通胀",
  up: "上行",
  down: "下行",
  observed: "已观测",
  missing: "缺失",
};

function humanizeKey(value: string): string {
  return value
    .split(/[_-]+/)
    .filter(Boolean)
    .join(" ");
}

function normalizeEventFlowText(value: string): string {
  return value.trim().replace(/\s+/g, " ");
}

function canonicalizeEventFlowText(value: string): string {
  return normalizeEventFlowText(value)
    .replace(/\u00a0/g, " ")
    .replace(/\s*([|/\\])\s*/g, " $1 ")
    .replace(/\s*([:：])\s*/g, "$1 ")
    .replace(/\s*([—–])\s*/g, " $1 ")
    .replace(/\s+,/g, ",")
    .trim();
}

function isMostlyLatinText(value: string): boolean {
  const normalized = normalizeEventFlowText(value);
  if (!normalized) return false;
  const latinCount = (normalized.match(/[A-Za-z]/g) ?? []).length;
  const cjkCount = (normalized.match(/[\u4e00-\u9fff]/g) ?? []).length;
  return latinCount >= 4 && latinCount >= cjkCount * 2;
}

function isLikelyHeadlineBoilerplate(part: string): boolean {
  const normalized = canonicalizeEventFlowText(part).toLowerCase();
  return (
    /^(update|breaking|exclusive|analysis|alert|wrapup|factbox|preview|editorial)\b/.test(normalized) ||
    /^rtx\d*\b/.test(normalized) ||
    /^(reuters|bloomberg|ap|cnbc|wsj|ft)\b/.test(normalized)
  );
}

function truncateByWords(value: string, maxLength: number): string {
  if (value.length <= maxLength) return value;
  const words = value.split(/\s+/).filter(Boolean);
  if (words.length <= 1) return `${value.slice(0, Math.max(1, maxLength - 1))}…`;

  let result = words[0];
  for (let index = 1; index < words.length; index += 1) {
    const candidate = `${result} ${words[index]}`;
    if (candidate.length > maxLength - 1) break;
    result = candidate;
  }

  if (result.length === value.length) return value;
  return `${result}…`;
}

function truncateEventFlowText(value: string, maxLength: number): string {
  const normalized = normalizeEventFlowText(value);
  if (normalized.length <= maxLength) return normalized;

  const separatorSplit = normalized.split(/\s*[|/\\:：—–]\s*/).filter(Boolean);
  if (separatorSplit.length > 1) {
    const lead = separatorSplit[0];
    if (lead.length <= maxLength) {
      return `${lead}…`;
    }
  }

  if (isMostlyLatinText(normalized)) {
    return truncateByWords(normalized, maxLength);
  }

  return `${normalized.slice(0, Math.max(1, maxLength - 1))}…`;
}

function stripBoilerplate(value: string): string {
  return canonicalizeEventFlowText(value)
    .replace(/^\[[^\]]+\]\s*/, "")
    .replace(/^(?:Reuters|Bloomberg|AP|CNBC|WSJ|FT|MarketScreener|Investing\.com|FXStreet)\s*[:\-–—]\s*/i, "")
    .replace(/^(?:UPDATE|BREAKING|EXCLUSIVE|ANALYSIS|WRAPUP|FACTBOX|PREVIEW|ALERT|LIVE)\s*(?:\d+)?\s*[:\-–—]\s*/i, "")
    .replace(/^(?:\d+\s*)?(?:UPDATE|BREAKING|EXCLUSIVE|ANALYSIS|WRAPUP|FACTBOX|PREVIEW|ALERT|LIVE)\s*[:\-–—]\s*/i, "")
    .trim();
}

function displayText(value: string | null | undefined, maxLength: number): { text: string; raw: string; foreign: boolean } {
  if (!value) {
    return { text: "—", raw: "", foreign: false };
  }

  const raw = normalizeEventFlowText(value);
  const stripped = stripBoilerplate(raw);
  const foreign = isMostlyLatinText(stripped) && !/[\u4e00-\u9fff]/.test(stripped);
  const text = truncateEventFlowText(stripped, maxLength);
  return { text, raw, foreign };
}

function splitTitleSegments(value: string): { lead: string; subline: string | null } {
  const normalized = stripBoilerplate(value);
  const delimiters = [/ \| /, / — /, / – /, /: /];

  for (const delimiter of delimiters) {
    const parts = normalized.split(delimiter).map((part) => part.trim()).filter(Boolean);
    if (parts.length < 2) continue;
    const [lead, ...rest] = parts;
    const tail = rest.join(" ").trim();
    if (!lead || !tail) continue;
    if (lead.length > 64 || tail.length < 12) continue;
    if (isLikelyHeadlineBoilerplate(lead)) continue;
    return { lead, subline: tail };
  }

  if (isMostlyLatinText(normalized)) {
    const commaParts = normalized.split(/,\s+/).map((part) => part.trim()).filter(Boolean);
    if (commaParts.length >= 2) {
      const lead = commaParts[0];
      const tail = commaParts.slice(1).join(", ").trim();
      if (lead.length <= 64 && tail.length >= 12) {
        return { lead, subline: tail };
      }
    }
  }

  return { lead: normalized, subline: null };
}

const TAG_LABEL_MAP: Record<string, string> = {
  xauusd: "黄金",
  xagusd: "白银",
  dxy: "美元指数",
  us02y: "2年期美债",
  us10y: "10年期美债",
  us30y: "30年期美债",
  wti: "纽约原油",
  brent: "布伦特原油",
  gold: "黄金",
  silver: "白银",
  inflation: "通胀",
  rates: "利率",
  energy: "能源",
  macro: "宏观",
  geopolitics: "地缘",
  safe_haven: "避险",
  fx: "外汇",
  technical_level: "技术位",
  single_source: "单一来源",
  multi_source: "多来源",
  oil_supply: "原油供给",
  inflation_to_rates: "通胀 -> 利率",
  growth_to_yields: "增长 -> 美债收益率",
  geo_risk_to_oil_to_inflation: "地缘风险 -> 油价 -> 通胀",
};

const SOURCE_LABEL_MAP: Record<string, string> = {
  reuters: "路透",
  reuters_public_news: "路透快讯",
  bloomberg: "彭博",
  ap: "美联社",
  cnbc: "CNBC",
  wsj: "华尔街日报",
  ft: "金融时报",
  jin10: "金十",
  jin10_mcp_flash: "金十快讯",
  jin10_news: "金十新闻",
  source_api: "来源接口",
  macro_latest: "宏观最新快照",
  daily_market_brief: "日报主线",
  fed_rss: "联储公告",
};

function labelFromCode(value: string): string | null {
  const normalized = value.trim().toLowerCase().replace(/\s+/g, "_");
  return TAG_LABEL_MAP[normalized] ?? SOURCE_LABEL_MAP[normalized] ?? null;
}

export function translateEventFlowValue(value: string | null | undefined): string {
  if (!value) return "—";
  const normalized = value.trim();
  if (!normalized) return "—";
  if (/[\u4e00-\u9fff]/.test(normalized)) return normalized;

  const lower = normalized.toLowerCase().replace(/\s+/g, "_");
  if (EVENT_FLOW_VALUE_MAP[lower]) return EVENT_FLOW_VALUE_MAP[lower];
  if (lower.includes("needs_verification")) return "待验证";
  if (lower.includes("verification")) return "验证中";
  if (lower.includes("review") && lower.includes("pending")) return "待复核";
  if (lower.includes("pending")) return "待处理";
  if (lower.includes("queued_not_implemented")) return "待实现";
  if (lower.includes("success")) return "成功";
  if (lower.includes("failed")) return "失败";
  if (lower.includes("accepted")) return "已接受";
  if (lower.includes("submitted")) return "已提交";
  if (lower.includes("processed")) return "已处理";
  if (lower.includes("readable")) return "可读";
  if (lower.includes("unavailable")) return "不可用";
  if (lower.includes("available")) return "可用";
  if (lower.includes("partial")) return "部分返回";
  if (lower.includes("unknown")) return "未知";
  if (lower.includes("source")) return "来源";
  if (lower.includes("flash")) return "快讯";
  if (lower.includes("analysis")) return "分析";
  if (lower.includes("reference")) return "参考";
  return normalized;
}

export function translateEventFlowFieldLabel(label: string): string {
  const normalized = label.trim().toLowerCase();
  return EVENT_FLOW_VALUE_MAP[normalized] ?? humanizeKey(label);
}

export function translateEventFlowGroupLabel(group: string): string {
  const normalized = group.trim().toLowerCase();
  if (EVENT_FLOW_VALUE_MAP[normalized]) return EVENT_FLOW_VALUE_MAP[normalized];
  return group.includes("_") ? humanizeKey(group) : group;
}

export function formatEventFlowTagLabel(tag: string | null | undefined): string {
  if (!tag) return "—";
  const normalized = normalizeEventFlowText(tag);
  if (!normalized) return "—";
  if (/[\u4e00-\u9fff]/.test(normalized)) return normalized;

  const mapped = labelFromCode(normalized);
  if (mapped) return mapped;

  const snake = normalized.toLowerCase().replace(/\s+/g, "_");
  if (EVENT_FLOW_VALUE_MAP[snake]) return EVENT_FLOW_VALUE_MAP[snake];
  return humanizeKey(normalized);
}

export function formatEventFlowSourceLabel(source: string | null | undefined, maxLength = 24): { text: string; raw: string; foreign: boolean } {
  if (!source) return { text: "来源未知", raw: "", foreign: false };
  const normalized = normalizeEventFlowText(source);
  if (!normalized) return { text: "来源未知", raw: "", foreign: false };
  if (/[\u4e00-\u9fff]/.test(normalized)) {
    return { text: truncateEventFlowText(normalized, maxLength), raw: normalized, foreign: false };
  }

  const lower = normalized.toLowerCase();
  if (lower.startsWith("event_materials")) {
    return { text: "事件主线快照", raw: normalized, foreign: false };
  }
  if (lower.startsWith("daily_market_brief")) {
    return { text: "日报输入快照", raw: normalized, foreign: false };
  }
  if (lower.startsWith("market_reactions")) {
    return { text: "市场反应快照", raw: normalized, foreign: false };
  }
  if (lower.startsWith("jin10")) {
    return { text: "金十", raw: normalized, foreign: false };
  }

  const mapped = labelFromCode(normalized) ?? translateEventFlowValue(normalized);
  const foreign = isMostlyLatinText(normalized) && !/[\u4e00-\u9fff]/.test(mapped);
  return {
    text: truncateEventFlowText(mapped, maxLength),
    raw: normalized,
    foreign,
  };
}

export function formatEventFlowArtifactLabel(path: string | null | undefined): string {
  if (!path) return "工件";
  const normalized = normalizeEventFlowText(path).toLowerCase();
  if (!normalized) return "工件";
  if (normalized.includes("daily_market_brief")) return "日报输入快照";
  if (normalized.includes("daily_brief_input_snapshot")) return "日报输入快照";
  if (normalized.includes("daily_brief.md")) return "日报 Markdown";
  if (normalized.includes("daily_brief.json")) return "日报结构化工件";
  if (normalized.includes("jin10_article_briefs")) return "金十文章摘要工件";
  if (normalized.includes("daily_analysis_triggers")) return "重点事件进展工件";
  if (normalized.includes("event_candidates")) return "事件候选工件";
  if (normalized.includes("report_events")) return "报告事件工件";
  if (normalized.includes("market_reactions")) return "市场反应工件";
  if (normalized.includes("impact_assessments")) return "影响评估工件";
  if (normalized.includes("raw/")) return "原始采集快照";
  if (normalized.includes("parsed/")) return "解析快照";
  if (normalized.endsWith(".md")) return "Markdown 工件";
  if (normalized.endsWith(".json")) return "结构化工件";
  return "工件";
}

export function formatEventFlowHeadline(value: string | null | undefined, maxLength = 56): { text: string; raw: string; foreign: boolean } {
  return displayText(value, maxLength);
}

export function formatEventFlowHeadlineSummary(value: string | null | undefined, maxLength = 56): {
  lead: string;
  subline: string | null;
  raw: string;
  foreign: boolean;
} {
  const headline = displayText(value, maxLength);
  if (headline.foreign) {
    return {
      lead: "原文事件",
      subline: null,
      raw: headline.raw,
      foreign: true,
    };
  }
  const { lead, subline } = splitTitleSegments(headline.raw || headline.text);
  const summaryLead = truncateEventFlowText(lead, maxLength);
  const summarySubline = subline ? truncateEventFlowText(subline, Math.max(24, Math.floor(maxLength * 0.72))) : null;
  return {
    lead: summaryLead,
    subline: summarySubline,
    raw: headline.raw,
    foreign: headline.foreign,
  };
}
