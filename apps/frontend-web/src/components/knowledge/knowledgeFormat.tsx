import type { ReactNode } from "react";
import type { KnowledgeItemStatus } from "@/types/knowledge";

const STATUS_LABELS: Record<string, string> = {
  "长期有效": "长期有效",
  "待复核": "待复核",
  "阶段有效": "阶段有效",
};

const DEPENDENCY_LABELS: Record<string, string> = {
  ready: "可用",
  active: "已启用",
  pending: "待补充",
  blocked: "已阻塞",
  degraded: "部分可用",
};

const TAG_LABELS: Record<string, string> = {
  Prompt: "提示词",
  Playbook: "剧本模板",
  "Market Odds": "市场赔率",
  Agent: "智能体",
  "Agent规则": "智能体规则",
  "Agent 可用": "智能体可用",
  CME: "芝商所",
};

export function knowledgeStatusLabel(value: KnowledgeItemStatus | string | null | undefined): string {
  const normalized = String(value ?? "").trim();
  return STATUS_LABELS[normalized] ?? (normalized ? "未知状态（技术值见详情）" : "未提供状态");
}

export function knowledgeDependencyLabel(value: string | null | undefined): string {
  const normalized = String(value ?? "").trim().toLowerCase();
  return DEPENDENCY_LABELS[normalized] ?? (normalized ? "未解释状态（技术值见详情）" : "未提供状态");
}

export function knowledgeTagLabel(value: string | null | undefined): string {
  const normalized = String(value ?? "").trim();
  return TAG_LABELS[normalized] ?? (normalized || "未命名标签");
}

export function knowledgeConfidenceLabel(value: number | null | undefined): string {
  return typeof value === "number" && Number.isFinite(value) ? `${value}/100（非胜率）` : "未提供";
}

export function hasChineseKnowledgeText(value: string | null | undefined): boolean {
  return Boolean(value && /[\u3400-\u9fff]/.test(value));
}

export function KnowledgeReadableText({ value, className }: { value: string | null | undefined; className?: string }): ReactNode {
  const text = value?.trim();
  if (!text) return <span className={className}>未提供</span>;
  if (hasChineseKnowledgeText(text)) return <span className={className}>{text}</span>;
  return (
    <span className={className}>
      <span>中文整理缺口：原文尚未形成中文说明，当前内容需人工核对。</span>
      <details className="mt-1 text-[10px] text-[var(--fg-5)]">
        <summary className="cursor-pointer">查看原文</summary>
        <span className="mt-1 block break-words">{text}</span>
      </details>
    </span>
  );
}
