import {
  normalizeGoldMainlineId,
} from "@/components/shared/goldMainlineFormat";
import type { GoldMacroOverview, GoldMainlineRanking } from "@/types/gold-mainlines";

export function formatGoldScore(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "-";
  return value <= 1 ? `${Math.round(value * 100)}` : `${Math.round(value)}`;
}

export function scoreFormulaLabel(item: GoldMainlineRanking): string {
  const value = (input: number | null | undefined) => typeof input === "number" && Number.isFinite(input) ? String(input) : "未提供";
  return [item.direction_score, item.impact_score, item.confidence_score, item.freshness_score].map(value).join(" / ");
}

export function rankingMainlineId(item: GoldMainlineRanking): string | null {
  return normalizeGoldMainlineId(item.mainline_id ?? item.mainline);
}

export function collectVerificationItems(overview: GoldMacroOverview, limit = 5): string[] {
  const seen = new Set<string>();
  const result: string[] = [];
  const values = [
    ...(overview.driver_conflict?.verification_needed ?? []),
    ...overview.verification_matrix.map((item) => item.label || item.reason || item.required_source || null),
  ];

  for (const value of values) {
    const normalized = (value || "").trim();
    if (!normalized || seen.has(normalized)) continue;
    seen.add(normalized);
    result.push(normalized);
    if (result.length >= limit) break;
  }
  return result;
}
