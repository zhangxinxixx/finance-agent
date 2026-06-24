import type { DataStatus } from "@/types/common";

import type { FAStatusTone, StatusDomain, StatusLike } from "./statusMeta";
import {
  DIM_STATUSES,
  DOMAIN_LABELS,
  DOWN_STATUSES,
  EXPLICIT_STATUS_LABELS,
  GENERIC_LABELS,
  INFO_STATUSES,
  UP_STATUSES,
  WARN_STATUSES,
} from "./statusMeta.constants";

export function normalizeStatusKey(status: StatusLike): string {
  return String(status ?? "unavailable").trim().toLowerCase() || "unavailable";
}

export function resolveStatusTone(key: string): FAStatusTone {
  if (UP_STATUSES.has(key)) return "up";
  if (WARN_STATUSES.has(key)) return "warn";
  if (DOWN_STATUSES.has(key)) return "down";
  if (INFO_STATUSES.has(key)) return "info";
  if (DIM_STATUSES.has(key)) return "dim";
  return "neutral";
}

export function resolveStatusDataStatus(key: string): DataStatus {
  if (UP_STATUSES.has(key)) return "available";
  if (WARN_STATUSES.has(key) || INFO_STATUSES.has(key) || key === "pending") return "partial";
  if (DOWN_STATUSES.has(key)) return "error";
  return "unavailable";
}

export function resolveExplicitStatusLabel(key: string): string | undefined {
  return EXPLICIT_STATUS_LABELS[key];
}

export function resolveStatusLabel(key: string, domain: StatusDomain): string {
  return DOMAIN_LABELS[domain]?.[key] ?? resolveExplicitStatusLabel(key) ?? GENERIC_LABELS[key] ?? key.toUpperCase();
}

export function isExplicitStatusKey(key: string): boolean {
  return Object.prototype.hasOwnProperty.call(EXPLICIT_STATUS_LABELS, key);
}
