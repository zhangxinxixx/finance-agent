import type { FAStatusTone } from "@/components/shared/FAStatusPill";
import { getDataStatusTone } from "@/lib/status";
import type { ReportAnalysisAgentOutputView, ReportDetailView } from "@/types/reports";

export function shortId(value: string | undefined): string {
  if (!value) return "-";
  return value.length <= 16 ? value : `${value.slice(0, 8)}...${value.slice(-4)}`;
}

export function reportFamilyLabel(value: string | undefined): string {
  if (!value) return "-";
  if (value === "jin10_weekly_visual") return "Jin10 周报";
  if (value === "jin10_daily_visual") return "Jin10 日报";
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

export function isSynthesisOutput(item: ReportAnalysisAgentOutputView): boolean {
  return item.registry_id === "synthesis_agent" || item.role === "synthesis_agent" || item.agent_name === "synthesis_agent";
}
