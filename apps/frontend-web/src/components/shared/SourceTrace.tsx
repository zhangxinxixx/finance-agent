import type { SourceRef } from "@/types/common";
import { compactSourceLabel, resolveSourceRefs, sourceRefPairs } from "@/lib/sourceRefs";
import { getDataStatusLabel, normalizeDataStatus } from "@/lib/status";
import { Database, FileText, Bot, ExternalLink } from "lucide-react";
import { FAEmptyState } from "./FAEmptyState";
import { FAStatusPill, type FAStatusTone } from "./FAStatusPill";

export interface LegacySourceTraceRecord {
  source_ref?: string | null;
  ref?: string | null;
  endpoint?: string | null;
  artifact_path?: string | null;
  file?: string | null;
  path?: string | null;
  snapshot_id?: string | null;
  input_snapshot_ids?: string[] | null;
  trade_date?: string | null;
  data_date?: string | null;
  dataDate?: string | null;
  as_of?: string | null;
  asOf?: string | null;
  run_id?: string | null;
  generated_at?: string | null;
  updated_at?: string | null;
  latest_raw_time?: string | null;
  latest_parsed_time?: string | null;
  provider?: string | null;
  source?: string | null;
  source_url?: string | null;
  model_version?: string | null;
  label?: string | null;
  name?: string | null;
  status?: string | null;
}

export interface SourceTraceProps {
  sources?: LegacySourceTraceRecord[];
  sourceRefs?: SourceRef[];
  compact?: boolean;
  emptyText?: string;
}

function sourceIcon(source: SourceRef) {
  const label = compactSourceLabel(source).toLowerCase();
  if (label.includes("agent") || label.includes("model") || label.includes("llm")) {
    return <Bot size={12} />;
  }

  if (label.includes("pdf") || label.includes("md") || label.includes("report") || source.artifact_path) {
    return <FileText size={12} />;
  }

  return <Database size={12} />;
}

function statusClass(status: SourceRef["status"]): string {
  const normalized = normalizeDataStatus(status);
  if (normalized === "available") return "text-[var(--up)]";
  if (normalized === "partial") return "text-[var(--warn)]";
  if (normalized === "error") return "text-[var(--down)]";
  return "text-[var(--fg-5)]";
}

function statusTone(status: SourceRef["status"]): FAStatusTone {
  const normalized = normalizeDataStatus(status);
  if (normalized === "available") return "up";
  if (normalized === "partial") return "warn";
  if (normalized === "error") return "down";
  return "dim";
}

function displaySourceLabel(label: string): string {
  const exact: Record<string, string> = {
    macro_latest: "宏观最新快照",
    source_api: "来源接口",
  };
  return exact[label.toLowerCase()] ?? label;
}

const SOURCE_PAIR_LABELS: Record<string, string> = {
  source_ref: "来源编号",
  endpoint: "接口",
  artifact: "产物",
  snapshot_id: "快照编号",
  trade_date: "交易日",
  dataDate: "数据日期",
  asOf: "截至时间",
  run_id: "运行编号",
  generated_at: "生成时间",
  source_url: "来源链接",
  provider: "来源方",
};

export function SourceTrace({ sources, sourceRefs, compact = false, emptyText = "暂无来源信息" }: SourceTraceProps) {
  const refs = resolveSourceRefs(sourceRefs, sources);

  if (refs.length === 0) {
    return <FAEmptyState title={emptyText} description="当前视图没有可展示的来源或溯源记录。" className={compact ? "py-4" : ""} />;
  }

  return (
    <div className={compact ? "space-y-1.5" : "space-y-2"}>
      {refs.map((source, index) => {
        const pairs = sourceRefPairs(source);
        const label = displaySourceLabel(compactSourceLabel(source));
        return (
          <article
            key={`${source.source_ref}-${source.snapshot_id ?? ""}-${source.run_id ?? ""}-${index}`}
            className={`rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card)] ${compact ? "p-2" : "p-3"}`}
          >
            <div className="flex items-start justify-between gap-3">
              <div className="flex min-w-0 items-center gap-2">
                <span className="text-[var(--brand)]">{sourceIcon(source)}</span>
                <div className="min-w-0">
                  <div className="truncate text-[11px] font-semibold text-[var(--fg-2)]">{label}</div>
                  <div className="text-[10px] text-[var(--fg-5)]">{source.trade_date ?? source.generated_at ?? "时间不可用"}</div>
                </div>
              </div>
              <FAStatusPill tone={statusTone(source.status)} dot={false}>
                {getDataStatusLabel(source.status)}
              </FAStatusPill>
            </div>

            {!compact ? (
              <div className="mt-3 grid gap-1.5 text-[10px] text-[var(--fg-5)]">
                {pairs.map((item) => (
                  <div key={`${item.label}-${item.value}`} className="flex items-center justify-between gap-3">
                    <span>{SOURCE_PAIR_LABELS[item.label] ?? item.label}</span>
                    <span className="truncate font-mono text-[var(--fg-4)]">{item.value}</span>
                  </div>
                ))}
                {source.provider ? (
                  <div className="flex items-center justify-between gap-3">
                    <span>{SOURCE_PAIR_LABELS.provider}</span>
                    <span className="truncate font-mono text-[var(--brand)]">{source.provider}</span>
                  </div>
                ) : null}
              </div>
            ) : null}

            <div className={`mt-3 flex items-center gap-1 text-[10px] ${statusClass(source.status)}`}>
              <ExternalLink size={11} />
              <span>可追溯</span>
            </div>
          </article>
        );
      })}
    </div>
  );
}
