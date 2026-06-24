import type { DataSourceStatusViewModel } from "@/types/data-ingestion";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { ChevronDown, ChevronRight, Database, FileText, Globe, Link2, Webhook } from "lucide-react";
import { formatDateTime } from "@/lib/date";
import {
  dotColor,
  freshnessColor,
  freshnessLabel,
  freshnessRatio,
  pillBg,
  pillFg,
  roleLabel,
  SOURCE_TABLE_GRID_CLASS,
  statusTone,
  type SourceGroup,
} from "./GroupedSourceTable.helpers";

const TABLE_HEADERS = ["数据源", "类型", "状态", "更新时间", "新鲜度", "行数", "库表 / 溯源"];

export function GroupedSourceTableHeader({ sourceCount }: { sourceCount: number }) {
  return (
    <div className="flex items-center justify-between border-b border-[var(--border)] bg-[var(--bg-panel)] px-3 py-2">
      <span className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--fg-2)]">
        数据源分组明细
      </span>
      <span className="rounded-full border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2 py-0.5 text-[9px] font-semibold text-[var(--fg-4)]">
        {sourceCount} 个
      </span>
    </div>
  );
}

export function SourceTableHeader() {
  return (
    <div className={`${SOURCE_TABLE_GRID_CLASS} border-b border-[var(--border)] bg-[var(--bg-panel)] px-3 py-1.5`}>
      {TABLE_HEADERS.map((h) => (
        <span key={h} className="text-[8px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">
          {h}
        </span>
      ))}
    </div>
  );
}

export function SourceGroupHeader({
  group,
  expanded,
  onToggle,
}: {
  group: SourceGroup;
  expanded: boolean;
  onToggle: () => void;
}) {
  const dot = dotColor(group.status);
  return (
    <button
      onClick={onToggle}
      className="flex w-full items-center gap-2 border-b border-[var(--border)] bg-[var(--bg-panel)] px-3 py-2 text-left transition-[background] hover:bg-[var(--bg-hover)]"
    >
      <div
        className="h-[7px] w-[7px] shrink-0 rounded-full"
        style={{
          background: dot,
          boxShadow: group.status === "ok" ? `0 0 6px ${dot}80` : "none",
        }}
      />
      <span className="text-[11px] font-semibold text-[var(--fg-2)]">{group.label}</span>
      <span
        className="rounded-full px-1.5 py-px text-[9px] font-bold leading-[1.4]"
        style={{ background: pillBg(group.status), color: pillFg(group.status) }}
      >
        {group.sources.length}
      </span>
      <span className="text-[9px] text-[var(--fg-5)] opacity-70">{group.note}</span>
      <span className="ml-auto text-[var(--fg-5)]">
        {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
      </span>
    </button>
  );
}

export function SourceRow({ source }: { source: DataSourceStatusViewModel }) {
  const ratio = freshnessRatio(source);
  const fc = freshnessColor(ratio);
  const rs = source.raw_status;
  const latestUpdate = source.latest_update_time ?? source.latest_parsed_time ?? source.latest_raw_time ?? null;
  const primaryTable = source.database_tables[0] ?? "—";
  const rawHref = source.latest_raw_ref?.url ?? source.latest_raw_ref?.raw_path ?? source.source_refs[0]?.artifact_path ?? null;

  return (
    <div
      className={`${SOURCE_TABLE_GRID_CLASS} items-center border-b border-[var(--border-faint)] px-3 py-2 transition-[background] hover:bg-[var(--bg-hover)]`}
    >
      <div className="min-w-0">
        <div className="flex items-center gap-1.5">
          <span className="truncate text-[11px] font-semibold text-[var(--fg-2)]">{source.label}</span>
          <span className="shrink-0 text-[var(--fg-5)]">
            <TypeIcon type={source.type} />
          </span>
        </div>
        <div className="mt-0.5 flex items-center gap-1.5 text-[8px] text-[var(--fg-5)]">
          <span>{source.group}</span>
          <span>·</span>
          <span>{roleLabel(source.role)}</span>
        </div>
      </div>

      <span className="rounded border border-[var(--border)] bg-[var(--bg-card-inner)] px-1.5 py-0.5 text-center font-mono text-[8px] text-[var(--fg-5)]">
        {source.type}
      </span>

      <FAStatusPill tone={statusTone(rs)}>{rs}</FAStatusPill>

      <div className="min-w-0 font-mono tabular-nums">
        <div className="truncate text-[9px] text-[var(--fg-4)]" title={latestUpdate ?? undefined}>
          {latestUpdate ? formatDateTime(latestUpdate) : "—"}
        </div>
        <div className="truncate text-[7px] text-[var(--fg-6)]" title={`raw=${source.latest_raw_time ?? "—"} parsed=${source.latest_parsed_time ?? "—"}`}>
          raw {source.latest_raw_time ? formatDateTime(source.latest_raw_time).slice(11) : "—"} · parsed {source.latest_parsed_time ? formatDateTime(source.latest_parsed_time).slice(11) : "—"}
        </div>
      </div>

      <div className="flex items-center gap-1.5">
        <div className="h-[3px] w-[36px] shrink-0 overflow-hidden rounded-[1.5px] bg-[var(--bg-terminal)]">
          <div
            className="h-full rounded-[1.5px]"
            style={{ width: `${Math.min(100, ratio * 100)}%`, background: fc }}
          />
        </div>
        <span className="font-mono text-[9px]" style={{ color: fc }}>
          {freshnessLabel(source)}
        </span>
      </div>

      <span className="text-right font-mono text-[10px] text-[var(--fg-4)] tabular-nums">
        {source.row_count.toLocaleString("en-US")}
      </span>

      <div className="min-w-0 truncate text-[8px] text-[var(--fg-5)]" title={rawHref ?? undefined}>
        <Link2 size={9} className="mr-1 inline text-[var(--brand-hover)]" />
        {primaryTable}
      </div>
    </div>
  );
}

function TypeIcon({ type }: { type: string }) {
  switch (type) {
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
