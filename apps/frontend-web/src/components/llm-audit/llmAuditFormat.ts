import type { FAStatusTone } from "@/components/shared/FAStatusPill";

const CALLER_LABELS: Record<string, string> = {
  gold_analysis_agent: "黄金分析智能体",
  synthesis_agent: "综合分析智能体",
  options_analysis_agent: "期权分析智能体",
  jin10_analysis_agent: "市场观察分析智能体",
};

const STATUS_LABELS: Record<string, string> = {
  success: "成功",
  failed: "失败",
  error: "失败",
  pending: "处理中",
  running: "进行中",
  cancelled: "已取消",
};

export function auditStatusLabel(value: string | null | undefined): string {
  const normalized = String(value ?? "").trim().toLowerCase();
  return STATUS_LABELS[normalized] ?? (normalized ? "未知状态（技术值见详情）" : "未提供状态");
}

export function auditStatusTone(value: string | null | undefined): FAStatusTone {
  const normalized = String(value ?? "").trim().toLowerCase();
  if (normalized === "success") return "up";
  if (["failed", "error"].includes(normalized)) return "down";
  if (["pending", "running"].includes(normalized)) return "warn";
  return "dim";
}

export function callerLabel(value: string | null | undefined): string {
  const normalized = String(value ?? "").trim();
  return CALLER_LABELS[normalized] ?? (normalized ? "内部调用（技术标识见详情）" : "未命名调用");
}

export function reasoningEffortLabel(value: string | null | undefined): string {
  const normalized = String(value ?? "").trim().toLowerCase();
  if (normalized === "low") return "低";
  if (normalized === "medium") return "中";
  if (normalized === "high") return "高";
  return normalized ? "未解释（技术值见详情）" : "未记录";
}

/** Keep provider/model identifiers available to the audit record without making them ordinary reading text. */
export function modelDisplayLabel(value: string | null | undefined): string {
  const normalized = String(value ?? "").trim();
  if (!normalized) return "未记录模型";
  if (/fixture|mock|simulat/i.test(normalized)) return "本地模拟模型";
  if (/^gpt[-_]/i.test(normalized)) return "文本生成模型";
  if (/claude|gemini|qwen|deepseek/i.test(normalized)) return "外部文本模型";
  return "已记录模型（技术详情可查）";
}

export function providerDisplayLabel(value: string | null | undefined): string {
  const normalized = String(value ?? "").trim();
  if (!normalized) return "未记录服务商";
  if (/fixture|mock|local|simulat/i.test(normalized)) return "本地模拟服务";
  return "已记录服务商（技术详情可查）";
}

export function shortAuditId(value: string | null | undefined): string {
  if (!value) return "未提供";
  return value.length <= 16 ? value : `${value.slice(0, 8)}…${value.slice(-4)}`;
}

export function hasChineseText(value: string | null | undefined): boolean {
  return Boolean(value && /[\u3400-\u9fff]/.test(value));
}
