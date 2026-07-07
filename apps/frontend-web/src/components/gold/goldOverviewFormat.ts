import {
  normalizeGoldMainlineId,
} from "@/components/shared/goldMainlineFormat";
import type { GoldMacroOverview, GoldMainlineRanking } from "@/types/gold-mainlines";

export function formatGoldScore(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "-";
  return value <= 1 ? `${Math.round(value * 100)}` : `${Math.round(value)}`;
}

export function scoreFormulaLabel(item: GoldMainlineRanking): string {
  const direction = item.direction_score ?? 0;
  const impact = item.impact_score ?? 1;
  const confidence = item.confidence_score ?? 1;
  const freshness = item.freshness_score ?? 1;
  return `${direction}/${impact}/${confidence}/${freshness}`;
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
