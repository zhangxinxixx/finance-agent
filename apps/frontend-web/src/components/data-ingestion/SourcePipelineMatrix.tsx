import { useState } from "react";
import type { DataSourceStatusViewModel, PipelineStageKey } from "@/types/data-ingestion";
import { SourcePipelineRow } from "./SourcePipelineRow";
import { StageLegend } from "./StageLegend";
import { Database } from "lucide-react";

interface SourcePipelineMatrixProps {
  sources: DataSourceStatusViewModel[];
  selectedId?: string | null;
  onSelect?: (sourceId: string) => void;
  onStageClick?: (sourceId: string, stageKey: PipelineStageKey) => void;
}

interface GroupDef {
  key: string;
  label: string;
  dotColor: string;
  filter: (s: DataSourceStatusViewModel) => boolean;
}

const GROUPS: GroupDef[] = [
  { key: "live",      label: "可用数据源",     dotColor: "var(--up)",   filter: (s) => s.status === "available" },
  { key: "partial",   label: "部分可用",       dotColor: "var(--warn)", filter: (s) => s.status === "partial" },
  { key: "error",     label: "暂不可用",       dotColor: "var(--down)", filter: (s) => s.status === "error" || s.status === "unavailable" },
];

/** Derive a group label from the overall status. */
function deriveGroup(source: DataSourceStatusViewModel): string {
  if (source.status === "available") return "live";
  if (source.status === "partial") return "partial";
  return "error";
}

const STAGE_HEADERS = [
  "连接",
  "采集",
  "Raw落地",
  "解析",
  "校验",
  "快照",
  "下游",
];

export function SourcePipelineMatrix({ sources, selectedId, onSelect, onStageClick }: SourcePipelineMatrixProps) {
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());

  const toggle = (key: string) => {
    setCollapsedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const grouped = GROUPS.map((g) => ({
    ...g,
    items: sources.filter(g.filter),
  })).filter((g) => g.items.length > 0);

  return (
    <div className="flex flex-col gap-2 rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card)] overflow-hidden min-h-0">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-[var(--border)] bg-[var(--bg-panel)] px-3 py-2 shrink-0">
        <div className="flex items-center gap-2">
          <Database size={12} className="text-[var(--fg-6)]" />
          <span className="text-[10px] font-semibold uppercase tracking-[0.14em] text-[var(--fg-2)]">
            数据源采集加工健康矩阵
          </span>
        </div>
        <div className="flex items-center gap-2">
          <StageLegend />
          <span className="fa-num text-[9px] font-bold text-[var(--fg-5)]">
            {sources.length} sources
          </span>
        </div>
      </div>

      {/* Column headers (only visible when we have data) */}
      {sources.length > 0 && (
        <div className="flex items-center gap-2 px-2 py-1 text-[8px] font-semibold uppercase tracking-wider text-[var(--fg-6)] border-b border-[var(--border-faint)] shrink-0">
          <div className="w-[6px] shrink-0" /> {/* dot space */}
          <div className="min-w-[130px] max-w-[150px] shrink-0">数据源</div>
          <div className="flex-1 flex items-center gap-0">
            {STAGE_HEADERS.map((h, i) => (
              <div key={h} className="flex items-center">
                <div className="w-[48px] text-center">{h}</div>
                {i < STAGE_HEADERS.length - 1 && <div className="w-[12px]" />}
              </div>
            ))}
          </div>
          <div className="hidden xl:block w-[140px] shrink-0">影响模块</div>
        </div>
      )}

      {/* Groups */}
      <div className="flex-1 overflow-y-auto min-h-0">
        {sources.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-8">
            <Database size={20} className="text-[var(--fg-6)] mb-2" />
            <span className="text-[11px] text-[var(--fg-4)]">暂无数据源</span>
          </div>
        ) : (
          grouped.map((group) => {
            const isCollapsed = collapsedGroups.has(group.key);
            return (
              <div key={group.key} className="mb-1">
                {/* Group separator */}
                <button
                  className="flex items-center gap-2 w-full px-3 py-1.5 text-left hover:bg-[var(--bg-hover)] transition-colors"
                  onClick={() => toggle(group.key)}
                >
                  <div
                    className="rounded-full shrink-0"
                    style={{ width: 6, height: 6, background: group.dotColor, boxShadow: `0 0 6px ${group.dotColor}` }}
                  />
                  <span className="text-[9px] font-semibold text-[var(--fg-3)]">
                    {group.label}
                  </span>
                  <span className="fa-num text-[9px] font-bold" style={{ color: group.dotColor }}>
                    {group.items.length}
                  </span>
                  <span className="text-[8px] text-[var(--fg-6)] ml-1">
                    {group.key === "live" ? "全部 live · 直接消费" : group.key === "partial" ? "子源失败或覆盖受限" : "不可用或未实现"}
                  </span>
                  <svg
                    width="8" height="8" viewBox="0 0 8 8"
                    className="ml-auto shrink-0 transition-transform"
                    style={{ transform: isCollapsed ? "rotate(-90deg)" : "rotate(0)" }}
                  >
                    <path d="M1 2 L4 5 L7 2" fill="none" stroke="var(--fg-6)" strokeWidth="1.2" strokeLinecap="round" />
                  </svg>
                </button>

                {/* Rows */}
                {!isCollapsed && group.items.map((source) => (
                  <SourcePipelineRow
                    key={source.id}
                    source={source}
                    selected={selectedId === source.id}
                    onSelect={onSelect}
                    onStageClick={onStageClick}
                  />
                ))}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
