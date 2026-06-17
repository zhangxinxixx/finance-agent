import type { DataSourceStatusViewModel } from "@/types/data-ingestion";
import type { FAStatusTone } from "@/components/shared/FAStatusPill";

export const SOURCE_TABLE_GRID_CLASS = "grid grid-cols-[1fr_64px_72px_132px_80px_60px_minmax(120px,0.8fr)] gap-2";

export type GroupKey = "live" | "partial" | "offline";

export interface SourceGroup {
  key: GroupKey;
  label: string;
  note: string;
  status: "ok" | "partial" | "unavailable";
  sources: DataSourceStatusViewModel[];
}

export function groupSources(sources: DataSourceStatusViewModel[]): SourceGroup[] {
  const live: DataSourceStatusViewModel[] = [];
  const partial: DataSourceStatusViewModel[] = [];
  const offline: DataSourceStatusViewModel[] = [];

  for (const s of sources) {
    if (s.status === "available") live.push(s);
    else if (s.status === "partial" || s.status === "error") partial.push(s);
    else offline.push(s);
  }

  const all: SourceGroup[] = [
    { key: "live", label: "可用数据源", note: "全部 live · 直接消费", status: "ok", sources: live },
    { key: "partial", label: "部分可用", note: "子源失败或覆盖受限", status: "partial", sources: partial },
    { key: "offline", label: "暂不可用", note: "未配置或上游不可用", status: "unavailable", sources: offline },
  ];

  return all.filter((g) => g.sources.length > 0);
}

export function dotColor(status: string): string {
  switch (status) {
    case "ok":
      return "var(--up)";
    case "partial":
      return "var(--warn)";
    case "error":
      return "var(--down)";
    case "unavailable":
      return "var(--fg-6)";
    default:
      return "var(--fg-6)";
  }
}

export function pillBg(status: string): string {
  switch (status) {
    case "ok":
      return "var(--up-soft)";
    case "partial":
      return "var(--warn-soft)";
    case "error":
      return "var(--down-soft)";
    default:
      return "rgba(255,255,255,0.03)";
  }
}

export function pillFg(status: string): string {
  switch (status) {
    case "ok":
      return "var(--up)";
    case "partial":
      return "var(--warn)";
    case "error":
      return "var(--down)";
    default:
      return "var(--fg-5)";
  }
}

export function statusTone(status: string): FAStatusTone {
  switch (status) {
    case "ok":
      return "up";
    case "warn":
    case "partial":
      return "warn";
    case "error":
      return "down";
    default:
      return "dim";
  }
}

export function freshnessRatio(source: DataSourceStatusViewModel): number {
  const value = source.latest_update_time ?? source.latest_parsed_time ?? source.latest_raw_time;
  if (!value) return 0;
  const t = new Date(value).getTime();
  if (Number.isNaN(t)) return 0;
  const ageHours = (Date.now() - t) / 3600000;
  if (ageHours < 1) return 1;
  if (ageHours < 4) return 0.8;
  if (ageHours < 12) return 0.5;
  if (ageHours < 24) return 0.3;
  return 0.1;
}

export function freshnessColor(ratio: number): string {
  if (ratio >= 0.8) return "var(--up)";
  if (ratio >= 0.5) return "var(--warn)";
  return "var(--down)";
}

export function freshnessLabel(source: DataSourceStatusViewModel): string {
  const value = source.latest_update_time ?? source.latest_parsed_time ?? source.latest_raw_time;
  if (!value) return "无数据";
  const t = new Date(value).getTime();
  if (Number.isNaN(t)) return "—";
  const diffMin = Math.round((Date.now() - t) / 60000);
  if (diffMin < 60) return `${diffMin}m`;
  const diffH = Math.round(diffMin / 60);
  if (diffH < 24) return `${diffH}h`;
  return `${Math.round(diffH / 24)}d`;
}

export function roleLabel(role: string): string {
  switch (role) {
    case "official_primary":
      return "主源";
    case "fallback":
      return "回退";
    case "supplemental":
      return "补充";
    default:
      return "衍生";
  }
}
