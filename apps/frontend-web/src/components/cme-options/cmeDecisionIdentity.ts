import type { CMEOptionsWallScore } from "@/types/cme-options";

export type CMEDecisionIdentityStatus = "aligned" | "mismatch" | "unverified";

export interface CMEDecisionIdentity {
  status: CMEDecisionIdentityStatus;
  commonSnapshotId: string | null;
  snapshotIds: string[];
  decisionSnapshotIds: string[];
}

export type CMETradeDateIdentityStatus = "aligned" | "mismatch" | "unverified";

export function resolveCMETradeDateIdentity(
  selectedDate: string | null | undefined,
  snapshotTradeDate: string | null | undefined,
  decisionTradeDate: string | null | undefined,
): { status: CMETradeDateIdentityStatus; selectedDateMismatch: boolean; snapshotDecisionMismatch: boolean } {
  const selectedDateMismatch = Boolean(
    selectedDate
      && ((snapshotTradeDate && snapshotTradeDate !== selectedDate)
        || (decisionTradeDate && decisionTradeDate !== selectedDate)),
  );
  const snapshotDecisionMismatch = Boolean(
    snapshotTradeDate && decisionTradeDate && snapshotTradeDate !== decisionTradeDate,
  );
  const mismatch = selectedDateMismatch || snapshotDecisionMismatch;
  return {
    status: mismatch ? "mismatch" : !snapshotTradeDate || !decisionTradeDate ? "unverified" : "aligned",
    selectedDateMismatch,
    snapshotDecisionMismatch,
  };
}

function cleanIds(values: readonly (string | null | undefined)[]): string[] {
  return values
    .filter((value): value is string => typeof value === "string" && value.trim().length > 0)
    .map((value) => value.trim())
    .filter((value, index, items) => items.indexOf(value) === index);
}

export function collectCMESnapshotIds(
  snapshotId: string | null | undefined,
  inputSnapshotIds: readonly (string | null | undefined)[] = [],
  sourceSnapshotIds: readonly (string | null | undefined)[] = [],
): string[] {
  const primaryId = cleanIds([snapshotId]);
  if (primaryId.length > 0) return primaryId;
  const sourceIds = cleanIds([...inputSnapshotIds, ...sourceSnapshotIds]);
  return sourceIds.length === 1 ? sourceIds : [];
}

export function resolveCMEDecisionIdentity(
  snapshotIds: readonly string[],
  decisionSnapshotIds: readonly string[],
): CMEDecisionIdentity {
  const normalizedSnapshotIds = cleanIds(snapshotIds);
  const normalizedDecisionIds = cleanIds(decisionSnapshotIds);
  const commonSnapshotId = normalizedDecisionIds.find((id) => normalizedSnapshotIds.includes(id)) ?? null;
  const everyDecisionRevisionIsPresent = normalizedDecisionIds.every((id) => normalizedSnapshotIds.includes(id));

  return {
    status: commonSnapshotId && everyDecisionRevisionIsPresent
      ? "aligned"
      : normalizedSnapshotIds.length === 0 || normalizedDecisionIds.length === 0
        ? "unverified"
        : "mismatch",
    commonSnapshotId,
    snapshotIds: normalizedSnapshotIds,
    decisionSnapshotIds: normalizedDecisionIds,
  };
}

export function resolveCMEExpiryScope(
  expiries: readonly string[],
  requestedExpiry: string | null | undefined,
): { expiry: string | null; missing: boolean } {
  const normalized = expiries.filter((expiry) => Boolean(expiry));
  if (!requestedExpiry) return { expiry: normalized[0] ?? null, missing: false };
  if (normalized.includes(requestedExpiry)) return { expiry: requestedExpiry, missing: false };
  return { expiry: null, missing: true };
}

export function selectCMEPinWall(rows: readonly CMEOptionsWallScore[]): CMEOptionsWallScore | null {
  const validRows = rows.filter((row) => typeof row.strike === "number" && Number.isFinite(row.strike) && typeof row.pnt === "number" && Number.isFinite(row.pnt));
  const explicitPin = validRows.find((row) => row.wall_type === "Pin Wall");
  if (explicitPin) return explicitPin;
  return [...validRows].sort((left, right) => (right.pnt ?? Number.NEGATIVE_INFINITY) - (left.pnt ?? Number.NEGATIVE_INFINITY))[0] ?? null;
}

export function cmeLivePriceStatusLabel(
  status: "fresh" | "stale" | "future" | "unavailable",
  freshnessSeconds: number | null | undefined,
): string {
  if (status === "fresh") return freshnessSeconds == null ? "观测价新鲜度：新鲜" : `观测价新鲜度：新鲜 · ${freshnessSeconds} 秒`;
  if (status === "stale") return freshnessSeconds == null ? "观测价已陈旧" : `观测价已陈旧 · ${freshnessSeconds} 秒`;
  if (status === "future") return "观测价时间异常";
  return "观测价不可用";
}
