import type { DataAvailability, DataStatus, Severity } from "@/types/common";
import { getStatusMeta } from "@/components/shared/statusMeta";

export type LegacyStatus = "ok" | "warn" | "error" | "unavailable" | "info" | "neutral";
export type StatusLike = DataStatus | LegacyStatus | "LIVE" | "PARTIAL" | "MOCK" | "UNAVAILABLE" | string | null | undefined;

export function normalizeDataStatus(status: StatusLike): DataStatus {
  return getStatusMeta(status).dataStatus;
}

export function normalizeDataAvailability(status: StatusLike): DataAvailability {
  const value = String(status ?? "unavailable").toLowerCase();

  if (value === "mock") {
    return "MOCK";
  }
  if (
    value === "available" ||
    value === "ok" ||
    value === "live" ||
    value === "done" ||
    value === "ready" ||
    value === "final" ||
    value === "success" ||
    value === "generated"
  ) {
    return "LIVE";
  }
  if (value === "partial" || value === "warn" || value === "warning" || value === "stale" || value === "fallback" || value === "manual_required" || value === "prelim" || value === "degraded" || value === "needs_review") {
    return "PARTIAL";
  }
  return "UNAVAILABLE";
}

export function getDataStatusLabel(status: StatusLike): string {
  const raw = String(status ?? "").toUpperCase();
  if (raw === "LIVE") return "实时";
  if (raw === "PARTIAL") return "部分可用";
  if (raw === "MOCK") return "模拟数据";
  if (raw === "UNAVAILABLE") return "不可用";
  if (raw === "PRELIM") return "初步数据";

  switch (normalizeDataStatus(status)) {
    case "available":
      return "可用";
    case "partial":
      return "部分可用";
    case "error":
      return "错误";
    case "unavailable":
    default:
      return "不可用";
  }
}

export function getDataAvailabilityLabel(status: StatusLike): DataAvailability {
  return normalizeDataAvailability(status);
}

export function getDataStatusSeverity(status: StatusLike): Severity {
  switch (normalizeDataStatus(status)) {
    case "available":
      return "success";
    case "partial":
      return "warning";
    case "error":
      return "danger";
    case "unavailable":
    default:
      return "muted";
  }
}

export function getDataStatusTone(status: StatusLike): "success" | "warning" | "danger" | "info" | "muted" {
  const value = String(status ?? "").toLowerCase();
  if (value === "info") return "info";
  if (value === "neutral") return "muted";
  const severity = getDataStatusSeverity(status);
  return severity === "success"
    ? "success"
    : severity === "warning"
      ? "warning"
      : severity === "danger"
        ? "danger"
        : "muted";
}

export function isUnavailableStatus(status: StatusLike): boolean {
  return normalizeDataStatus(status) === "unavailable";
}

export function mergeDataStatus(statuses: StatusLike[]): DataStatus {
  if (statuses.length === 0) return "unavailable";
  const normalized = statuses.map(normalizeDataStatus);
  if (normalized.includes("error")) return "error";
  if (normalized.every((status) => status === "unavailable")) return "unavailable";
  if (normalized.some((status) => status === "partial" || status === "unavailable")) return "partial";
  return "available";
}

export function statusDotClass(status: StatusLike): string {
  switch (getDataStatusTone(status)) {
    case "success":
      return "bg-finance-bullish";
    case "warning":
      return "bg-finance-warning";
    case "danger":
      return "bg-finance-bearish";
    case "info":
      return "bg-finance-accent";
    case "muted":
    default:
      return "bg-finance-text-muted";
  }
}
