import type { FAStatusTone } from "@/components/shared/FAStatusPill";
import { getStatusLabel } from "@/components/shared/statusMeta";
import { getDataStatusTone } from "@/lib/status";
import type { ReportAnalysisAgentOutputView, ReportDetailView } from "@/types/reports";

export function shortId(value: string | undefined): string {
  if (!value) return "-";
  return value.length <= 16 ? value : `${value.slice(0, 8)}...${value.slice(-4)}`;
}

export function reportFamilyLabel(value: string | undefined): string {
  if (!value) return "-";
  if (value === "macro_event_followup_supplement") return "宏观事件补充分析";
  if (value === "jin10_weekly_visual") return "Jin10 周报";
  if (value === "jin10_daily_visual") return "Jin10 日报";
  return value;
}

export function reportTitleLabel(value: string | undefined): string {
  if (!value) return "-";
  const normalized = value.trim().toLowerCase();
  if (normalized.includes("宏观事件跟进补充")) return "宏观事件补充分析";
  if (normalized === "jin10 daily report") return "Jin10 日报";
  if (normalized === "jin10 weekly report") return "Jin10 周报";
  if (normalized === "daily report") return "日报";
  if (normalized === "weekly report") return "周报";
  return value;
}

export function statusTone(status: ReportDetailView["data_status"]): FAStatusTone {
  const tone = getDataStatusTone(status);
  if (tone === "success") return "up";
  if (tone === "warning") return "warn";
  if (tone === "danger") return "down";
  if (tone === "info") return "info";
  return "dim";
}

export function factReviewTone(status: string | null | undefined): FAStatusTone {
  const value = (status || "").toLowerCase();
  if (value === "success" || value === "supported") return "up";
  if (value === "needs_review" || value === "conflicted" || value === "partial" || value === "partially_supported") return "warn";
  if (value === "unavailable" || value === "unsupported" || value === "contradicted") return "down";
  if (value === "not_reviewed") return "dim";
  return "info";
}

export function factReviewLabel(status: string | null | undefined): string {
  const value = (status || "").toLowerCase();
  if (value === "success" || value === "supported") return "事实已核验";
  if (value === "needs_review" || value === "conflicted") return "待人工复核";
  if (value === "partial" || value === "partially_supported") return "部分待补证";
  if (value === "unavailable" || value === "unsupported" || value === "contradicted") return "审查有风险";
  if (value === "not_reviewed") return "未审查";
  return "审查状态未知";
}

export function reportLifecycleLabel(status: string | null | undefined): string {
  return getStatusLabel(status, "report");
}

export function reviewStatusLabel(status: string | null | undefined): string {
  const value = (status || "").toLowerCase();
  if (value === "not_required") return "无需审查";
  return getStatusLabel(status, "review");
}

export function biasLabel(value: string | null | undefined): string {
  const normalized = (value || "").toLowerCase();
  if (normalized === "bullish") return "偏多";
  if (normalized === "bearish") return "偏空";
  if (normalized === "mixed") return "混合";
  if (normalized === "neutral") return "中性";
  return value || "-";
}

export function generationModeLabel(value: string | null | undefined): string {
  const normalized = (value || "").toLowerCase();
  if (normalized === "rule" || normalized === "rule-based") return "规则生成";
  if (normalized === "llm") return "模型生成";
  return value || "-";
}

export function isSynthesisOutput(item: ReportAnalysisAgentOutputView): boolean {
  return item.registry_id === "synthesis_agent" || item.role === "synthesis_agent" || item.agent_name === "synthesis_agent";
}
