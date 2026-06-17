import type { FAStatusTone } from "@/components/shared/FAStatusPill";

export function toneForAuditAction(action: string): FAStatusTone {
  if (action === "reset") return "warn";
  if (action === "rollback") return "up";
  return "info";
}

export function prettyJson(value: Record<string, unknown> | null): string {
  if (value === null) return "null";
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}
