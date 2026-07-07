import {
  GOLD_MAINLINE_ORDER,
  normalizeGoldMainlineId,
} from "@/components/shared/goldMainlineFormat";
import type { FAStatusTone } from "@/components/shared/FAStatusPill";
import type {
  GoldMacroOverview,
  GoldMainline,
  GoldMainlineRanking,
  VerificationItem,
} from "@/types/gold-mainlines";

export type MainlineCoverageStatus = "covered" | "pending" | "missing";

export interface MainlineCoverageRow {
  id: GoldMainline;
  ranking: GoldMainlineRanking | null;
  verificationItems: VerificationItem[];
  eventIds: string[];
  sourceCount: number;
  status: MainlineCoverageStatus;
}

export function scoreLabel(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "--";
  return value <= 1 ? `${Math.round(value * 100)}` : `${Math.round(value)}`;
}

export function scoreFormulaLabel(item: GoldMainlineRanking | null): string {
  if (!item) return "--";
  const direction = item.direction_score ?? 0;
  const impact = item.impact_score ?? 1;
  const confidence = item.confidence_score ?? 1;
  const freshness = item.freshness_score ?? 1;
  return `${direction}/${impact}/${confidence}/${freshness}`;
}

export function rankingMainlineId(item: GoldMainlineRanking): GoldMainline | null {
  return normalizeGoldMainlineId(item.mainline_id ?? item.mainline);
}

export function mainlineCoverageRows(overview: GoldMacroOverview): MainlineCoverageRow[] {
  const rankings = new Map(
    (overview.theme_rankings ?? [])
      .map((item) => [rankingMainlineId(item), item] as const)
      .filter((entry): entry is readonly [GoldMainline, GoldMainlineRanking] => Boolean(entry[0])),
  );

  return GOLD_MAINLINE_ORDER.map((id) => {
    const ranking = rankings.get(id) ?? null;
    const verificationItems = overview.verification_matrix.filter((item) => item.mainline_id === id);
    const eventIds = ranking?.event_ids ?? [];
    const sourceKeys = new Set(
      [
        ...(ranking?.source_refs ?? []),
        ...verificationItems.flatMap((item) => item.source_refs ?? []),
      ].map((ref, index) => `${ref.source_ref ?? "source"}:${ref.snapshot_id ?? index}`),
    );
    const hasPendingVerification = verificationItems.some((item) => item.status === "pending" || item.status === "unavailable");
    const status: MainlineCoverageStatus = ranking ? (hasPendingVerification || ranking.verification_status === "single_source" ? "pending" : "covered") : "missing";

    return {
      id,
      ranking,
      verificationItems,
      eventIds,
      sourceCount: sourceKeys.size,
      status,
    };
  });
}

export function coverageStatusLabel(value: MainlineCoverageStatus): string {
  if (value === "covered") return "已覆盖";
  if (value === "pending") return "待验证";
  return "待接入";
}

export function coverageStatusTone(value: MainlineCoverageStatus): FAStatusTone {
  if (value === "covered") return "up";
  if (value === "pending") return "warn";
  return "dim";
}

export function statusTone(value: string | null | undefined): FAStatusTone {
  if (value === "available" || value === "ok" || value === "confirmed") return "up";
  if (value === "partial" || value === "stale" || value === "pending") return "warn";
  if (value === "unavailable" || value === "failed" || value === "error") return "down";
  return "neutral";
}

export function formatEventCount(value: number): string {
  return `${value} 条事件`;
}
