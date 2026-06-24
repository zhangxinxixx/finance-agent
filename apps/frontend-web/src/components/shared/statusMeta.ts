import type { DataStatus } from "@/types/common";
import {
  isExplicitStatusKey,
  normalizeStatusKey,
  resolveStatusDataStatus,
  resolveStatusLabel,
  resolveStatusTone,
} from "./statusMeta.helpers";

export type FAStatusTone = "up" | "down" | "warn" | "info" | "dim" | "neutral";

export type StatusDomain =
  | "data"
  | "task"
  | "step"
  | "review"
  | "report"
  | "source"
  | "agent"
  | "event"
  | "generic";

export type StatusLike = DataStatus | string | null | undefined;

export interface StatusMeta {
  raw: string;
  key: string;
  label: string;
  tone: FAStatusTone;
  dataStatus: DataStatus;
  explicit: boolean;
}

interface StatusMetaOptions {
  domain?: StatusDomain;
  label?: string;
}

export function getStatusMeta(status: StatusLike, options: StatusMetaOptions = {}): StatusMeta {
  const key = normalizeStatusKey(status);
  const domain = options.domain ?? "generic";
  return {
    raw: String(status ?? ""),
    key,
    label: options.label ?? resolveStatusLabel(key, domain),
    tone: resolveStatusTone(key),
    dataStatus: resolveStatusDataStatus(key),
    explicit: isExplicitStatusKey(key),
  };
}

export function getStatusTone(status: StatusLike, domain?: StatusDomain): FAStatusTone {
  return getStatusMeta(status, { domain }).tone;
}

export function getStatusLabel(status: StatusLike, domain?: StatusDomain): string {
  return getStatusMeta(status, { domain }).label;
}
