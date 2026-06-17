import type { ReactNode } from "react";
import type { DataStatus } from "@/types/common";
import type { DataIngestionStatus, DataSourceStatusViewModel } from "@/types/data-ingestion";
import { Database, FileText, Globe, Webhook } from "lucide-react";
import { getStatusTone } from "@/components/shared/statusMeta";
import type { FAStatusTone } from "@/components/shared/FAStatusPill";

export function typeIcon(sourceType: DataSourceStatusViewModel["type"]): ReactNode {
  switch (sourceType) {
    case "pdf":
      return <FileText size={12} />;
    case "scrape":
    case "scraper":
      return <Globe size={12} />;
    case "webhook":
      return <Webhook size={12} />;
    default:
      return <Database size={12} />;
  }
}

export function rawStatusTone(status: DataIngestionStatus): FAStatusTone {
  return getStatusTone(status, "source");
}

export function pageStatusTone(status: DataStatus): FAStatusTone {
  return getStatusTone(status, "data");
}

export function roleLabel(role: string) {
  switch (role) {
    case "official_primary":
      return "官方主源";
    case "fallback":
      return "回退补源";
    case "supplemental":
      return "事件补充";
    case "derived":
      return "衍生数据";
    default:
      return role;
  }
}

export function roleTone(role: string): FAStatusTone {
  switch (role) {
    case "official_primary":
      return "up";
    case "fallback":
      return "warn";
    case "supplemental":
      return "info";
    case "derived":
    default:
      return "dim";
  }
}

export function boolTone(value: boolean): FAStatusTone {
  return value ? "up" : "dim";
}

export function formatRelativeTime(value: string | null) {
  if (!value) {
    return "不可用";
  }

  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }

  const diffMs = parsed.getTime() - Date.now();
  const diffMinutes = Math.round(diffMs / 60000);
  const diffHours = Math.round(diffMs / 3600000);
  const diffDays = Math.round(diffMs / 86400000);
  const rtf = new Intl.RelativeTimeFormat("zh-CN", { numeric: "auto" });

  if (Math.abs(diffMinutes) < 60) {
    return rtf.format(diffMinutes, "minute");
  }

  if (Math.abs(diffHours) < 24) {
    return rtf.format(diffHours, "hour");
  }

  return rtf.format(diffDays, "day");
}

export function formatAbsoluteTime(value: string | null) {
  if (!value) {
    return "不可用";
  }

  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "medium",
    hour12: false,
  }).format(parsed);
}

export function relationLabel(keys: string[]) {
  return keys.length > 0 ? keys.join(" / ") : "—";
}

export function dataSourceAccent(source: DataSourceStatusViewModel) {
  if (source.raw_status === "error") {
    return "down";
  }

  if (source.raw_status === "warn") {
    return "warn";
  }

  if (source.raw_status === "ok") {
    return "up";
  }

  return "none";
}
