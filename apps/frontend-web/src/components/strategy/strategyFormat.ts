import { BarChart3, BookOpen, GitBranch, Minus, Shield, TrendingDown, TrendingUp, Zap } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { FAStatusTone } from "@/components/shared/FAStatusPill";
import { getStatusLabel, getStatusTone } from "@/components/shared/statusMeta";
import type {
  StrategyHeroViewModel,
  StrategyModuleKey,
  StrategyModuleSignal,
  StrategyViewModel,
} from "@/types/strategy";

export function statusTone(status: StrategyViewModel["status"]): FAStatusTone {
  return getStatusTone(status, "data");
}

export function directionIcon(direction: StrategyHeroViewModel["direction"]): LucideIcon {
  switch (direction) {
    case "bullish":
      return TrendingUp;
    case "bearish":
      return TrendingDown;
    default:
      return Minus;
  }
}

export function directionTone(direction: StrategyHeroViewModel["direction"]): FAStatusTone {
  switch (direction) {
    case "bullish":
      return "up";
    case "bearish":
      return "down";
    case "neutral":
      return "dim";
    default:
      return "warn";
  }
}

export function moduleIcon(key: StrategyModuleKey): LucideIcon {
  switch (key) {
    case "market":
      return BarChart3;
    case "cme":
      return Shield;
    case "event":
      return Zap;
    case "knowledge":
      return BookOpen;
    default:
      return GitBranch;
  }
}

export function moduleStatusTone(status: StrategyModuleSignal["status"]): FAStatusTone {
  return getStatusTone(status, "data");
}

export function traceStatusTone(status?: string | null): FAStatusTone {
  return getStatusTone(status, "source");
}

export function sourceTone(source: StrategyViewModel["source"]): FAStatusTone {
  return getStatusTone(source, "source");
}

export function sourceLabel(source: StrategyViewModel["source"]): string {
  return getStatusLabel(source, "source");
}

const STRATEGY_VALUE_LABELS: Record<string, string> = {
  api: "真实接口",
  unavailable: "不可用",
  available: "可用",
  partial: "部分可用",
  error: "错误",
  bullish: "看多",
  bearish: "看空",
  neutral: "中性",
  unknown: "未知",
  mixed: "混合",
  rate_pressure: "利率压制",
  transition_release: "过渡释放",
  trend_tailwind: "趋势顺风",
  consolidation: "高位整固",
  liquidity_crunch: "流动性踩踏",
  monetary_credit_repricing: "货币信用重估",
  direction_choice: "方向选择",
  breakout_accumulation: "突破蓄势",
  l1_defensive: "一级防御",
  l2_balanced: "二级均衡",
  l3_aggressive: "三级进攻",
};

export function strategyValueLabel(value?: string | null): string {
  const key = String(value ?? "").trim();
  if (!key) return "--";
  return STRATEGY_VALUE_LABELS[key.toLowerCase()] ?? key;
}

export function strategySentence(value?: string | null): string {
  const text = String(value ?? "").trim();
  if (!text) return "";
  const labeled = strategyValueLabel(text);
  if (labeled !== text) return labeled;
  if (/^[a-z][a-z0-9_/-]*$/i.test(text)) return text.replace(/_/g, " ");
  const asciiChars = text.match(/[A-Za-z]/g)?.length ?? 0;
  const cjkChars = text.match(/[\u4e00-\u9fff]/g)?.length ?? 0;
  const isLikelyEnglishSentence = asciiChars > 32 && asciiChars > cjkChars * 2;
  if (isLikelyEnglishSentence) {
    return "后端返回英文策略摘要，已在主视图折叠；请在溯源或原始报告中查看原文。";
  }
  return text;
}

export function formatConfidence(value: number | null): string {
  if (value === null || value === undefined) return "--";
  return `${Math.round(value * 100)}%`;
}

export function formatDate(dateStr: string | null): string {
  if (!dateStr) return "--";
  const text = String(dateStr).trim();
  if (!text) return "--";

  const parsed = new Date(text);
  if (!Number.isNaN(parsed.getTime())) {
    return new Intl.DateTimeFormat("zh-CN", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: text.includes("T") ? "2-digit" : undefined,
      minute: text.includes("T") ? "2-digit" : undefined,
      second: text.includes("T") ? "2-digit" : undefined,
      hour12: false,
    }).format(parsed);
  }

  return text;
}

export function biasTone(bias: string): FAStatusTone {
  const lower = bias.toLowerCase();
  if (lower.includes("bull") || lower.includes("多")) return "up";
  if (lower.includes("bear") || lower.includes("空")) return "down";
  if (lower.includes("neutral") || lower.includes("中")) return "dim";
  return "info";
}
