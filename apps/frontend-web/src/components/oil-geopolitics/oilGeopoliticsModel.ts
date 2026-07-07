import {
  normalizeGoldMainlineId,
} from "@/components/shared/goldMainlineFormat";
import type { FAStatusTone } from "@/components/shared/FAStatusPill";
import type { SourceRef } from "@/types/common";
import type {
  GoldMacroOverview,
  GoldMainline,
  GoldMainlineEventLink,
  GoldMainlineRanking,
  TransmissionChainSummary,
  VerificationItem,
} from "@/types/gold-mainlines";

export const OIL_MAINLINES: GoldMainline[] = ["oil_prices", "geopolitical_war_risk"];
export const OIL_PATHS = ["geopolitics_to_oil_to_rates", "haven_bid"];

export const OIL_CHAIN_STEPS = [
  { id: "geopolitical_event", label: "地缘事件", mainlineId: "geopolitical_war_risk" as GoldMainline },
  { id: "supply_risk", label: "原油供应风险", mainlineId: "geopolitical_war_risk" as GoldMainline },
  { id: "oil_price", label: "WTI / Brent", mainlineId: "oil_prices" as GoldMainline },
  { id: "inflation_expectation", label: "通胀预期", mainlineId: "oil_prices" as GoldMainline },
  { id: "fed_path", label: "Fed path", mainlineId: "oil_prices" as GoldMainline },
  { id: "rates_usd", label: "实际利率 / 美元", mainlineId: "oil_prices" as GoldMainline },
  { id: "gold_response", label: "黄金方向确认", mainlineId: "geopolitical_war_risk" as GoldMainline },
];

export interface TopicMainlineRow {
  id: GoldMainline;
  ranking: GoldMainlineRanking | null;
  verificationItems: VerificationItem[];
  status: "covered" | "pending" | "missing";
}

export function scoreLabel(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "--";
  return value <= 1 ? `${Math.round(value * 100)}` : `${Math.round(value)}`;
}

export function statusTone(value: string | null | undefined): FAStatusTone {
  if (value === "available" || value === "ok" || value === "confirmed" || value === "official_confirmed" || value === "multi_source") return "up";
  if (value === "partial" || value === "stale" || value === "pending" || value === "single_source" || value === "report_derived") return "warn";
  if (value === "unavailable" || value === "failed" || value === "error") return "down";
  if (value === "unknown") return "dim";
  return "neutral";
}

export function rankingMainlineId(item: GoldMainlineRanking | null | undefined): GoldMainline | null {
  return normalizeGoldMainlineId(item?.mainline_id ?? item?.mainline);
}

export function eventMainlineIds(event: GoldMainlineEventLink): GoldMainline[] {
  const ids = [...(event.mainline_ids ?? []), event.primary_mainline ?? null]
    .map((value) => normalizeGoldMainlineId(value))
    .filter((value): value is GoldMainline => Boolean(value));
  return [...new Set(ids)];
}

export function topicRankings(overview: GoldMacroOverview): GoldMainlineRanking[] {
  return [...(overview.theme_rankings ?? [])]
    .filter((item) => {
      const mainlineId = rankingMainlineId(item);
      return mainlineId ? OIL_MAINLINES.includes(mainlineId) : false;
    })
    .sort((left, right) => left.rank - right.rank);
}

export function topicRows(overview: GoldMacroOverview): TopicMainlineRow[] {
  const rankingById = new Map(
    topicRankings(overview)
      .map((item) => [rankingMainlineId(item), item] as const)
      .filter((entry): entry is readonly [GoldMainline, GoldMainlineRanking] => Boolean(entry[0])),
  );

  return OIL_MAINLINES.map((id) => {
    const ranking = rankingById.get(id) ?? null;
    const verificationItems = overview.verification_matrix.filter((item) => item.mainline_id === id);
    const hasPendingVerification = verificationItems.some((item) => item.status === "pending" || item.status === "unavailable");
    return {
      id,
      ranking,
      verificationItems,
      status: ranking ? (hasPendingVerification || ranking.verification_status === "single_source" ? "pending" : "covered") : "missing",
    };
  });
}

export function coverageStatusLabel(value: TopicMainlineRow["status"]): string {
  if (value === "covered") return "已覆盖";
  if (value === "pending") return "待验证";
  return "待接入";
}

export function coverageStatusTone(value: TopicMainlineRow["status"]): FAStatusTone {
  if (value === "covered") return "up";
  if (value === "pending") return "warn";
  return "dim";
}

export function topicEvents(events: GoldMainlineEventLink[]): GoldMainlineEventLink[] {
  return events
    .filter((event) => eventMainlineIds(event).some((id) => OIL_MAINLINES.includes(id)) || event.transmission_path_ids.some((id) => OIL_PATHS.includes(id)))
    .slice(0, 8);
}

export function topicVerification(overview: GoldMacroOverview): VerificationItem[] {
  return overview.verification_matrix
    .filter((item) => {
      const mainlineId = normalizeGoldMainlineId(item.mainline_id);
      return mainlineId ? OIL_MAINLINES.includes(mainlineId) : false;
    })
    .slice(0, 8);
}

export function sourceKey(ref: SourceRef, index: number): string {
  return `${ref.source_ref}:${ref.snapshot_id ?? ""}:${index}`;
}

export function collectSources(overview: GoldMacroOverview, rankings: GoldMainlineRanking[], chain: TransmissionChainSummary | null): SourceRef[] {
  const refs = [
    ...rankings.flatMap((item) => item.source_refs ?? []),
    ...(chain?.source_refs ?? []),
    ...(overview.source_refs ?? []),
  ];
  const seen = new Set<string>();
  const unique: SourceRef[] = [];
  refs.forEach((ref) => {
    const stable = `${ref.source_ref}:${ref.snapshot_id ?? ""}:${ref.status ?? ""}`;
    if (seen.has(stable)) return;
    seen.add(stable);
    unique.push(ref);
  });
  return unique.slice(0, 8);
}

export function chainStepStatus(row: TopicMainlineRow | undefined, hasChain: boolean, hasEvents: boolean): { label: string; tone: FAStatusTone } {
  if (hasChain) return { label: "已返回", tone: "up" };
  if (!row || row.status === "missing") return { label: "待接入", tone: "dim" };
  if (row.status === "pending") return { label: "待验证", tone: "warn" };
  if (hasEvents) return { label: "已归因", tone: "up" };
  return { label: "已覆盖", tone: "up" };
}
