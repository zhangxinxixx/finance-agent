import type { EventFlowEvidenceIdentity } from "@/types/event-flow";

export interface EventEvidenceWindowRow {
  window: string;
  asset: string;
  direction: string;
  value: number;
  unit: "bp" | "%" | "";
}

function asRecord(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  return value as Record<string, unknown>;
}

function finiteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function numericChange(item: Record<string, unknown>): { value: number; unit: EventEvidenceWindowRow["unit"] } | null {
  if (finiteNumber(item.change_bp)) return { value: item.change_bp, unit: "bp" };
  if (finiteNumber(item.pct_change)) return { value: item.pct_change, unit: "%" };
  if (finiteNumber(item.abs_change)) return { value: item.abs_change, unit: "" };
  return null;
}

/** Only a finite numeric movement is an observed market window. Empty asset
 * objects and text placeholders must stay out of the observed count. */
export function extractObservedEventWindowRows(value: unknown, maxRows = Number.POSITIVE_INFINITY): EventEvidenceWindowRow[] {
  const windows = asRecord(asRecord(value).windows);
  const rows = Object.entries(windows)
    .flatMap(([window, assets]) => Object.entries(asRecord(assets)).flatMap(([asset, movement]) => {
      const item = asRecord(movement);
      const change = numericChange(item);
      if (!change) return [];
      return [{
        window,
        asset,
        direction: typeof item.direction === "string" && item.direction.trim() ? item.direction : "unknown",
        value: change.value,
        unit: change.unit,
      }];
    }))
  return Number.isFinite(maxRows) ? rows.slice(0, maxRows) : rows;
}

export function formatObservedEventWindowValue(row: EventEvidenceWindowRow): string {
  return `${row.value}${row.unit}`;
}

export function resolveEventPricingStatus({
  status,
  rawPricingStatus,
  hasObservedWindows,
  identity,
}: {
  status: string | null | undefined;
  rawPricingStatus: string | null | undefined;
  hasObservedWindows: boolean;
  identity?: EventFlowEvidenceIdentity;
}): string {
  if (!hasObservedWindows || status === "unavailable" || status === "error") return "未核验";
  const normalized = rawPricingStatus?.trim().toLowerCase();
  const pricing = normalized === "已定价" || normalized === "priced" || normalized === "fully_priced" || normalized === "fully-priced"
    ? "已定价"
    : normalized === "部分定价" || normalized === "partially_priced" || normalized === "partially-priced"
      ? "部分定价"
      : normalized === "未定价" || normalized === "unpriced" || normalized === "not_priced" || normalized === "not-priced"
        ? "未定价"
        : null;
  if (identity && identity !== "verified") return "未核验";
  const normalizedStatus = status?.trim().toLowerCase();
  if (normalizedStatus === "partial") {
    if (pricing === "已定价" || pricing === "部分定价") return "部分定价";
    if (pricing === "未定价") return "未定价";
    return "未核验";
  }
  if (normalizedStatus !== "available" && normalizedStatus !== "validated") return "未核验";
  if (pricing) return pricing;
  return "未核验";
}

export function resolveEventEvidenceIdentity(
  routeEventId: string | null | undefined,
  modelEventId: string | null | undefined,
): EventFlowEvidenceIdentity {
  if (typeof modelEventId !== "string" || !modelEventId.trim()) return "unverified";
  return routeEventId === modelEventId ? "verified" : "mismatch";
}

export function eventEvidenceIdentityLabel(identity: EventFlowEvidenceIdentity): string {
  if (identity === "verified") return "事件 ID 已核验";
  if (identity === "mismatch") return "事件 ID 不一致";
  return "事件 ID 未核验";
}
