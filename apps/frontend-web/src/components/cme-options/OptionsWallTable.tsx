import { useMemo, useState } from "react";

import { FACard } from "../shared/FACard";
import type { CMEOptionsWallScore } from "../../types/cme-options";
import {
  OptionsWallEmptyState,
  OptionsWallTableHeader,
  OptionsWallTableRows,
  sortWallRows,
  type OptionsWallSortDirection,
  type OptionsWallSortKey,
} from "./OptionsWallTableParts";
import { formatCMEExpiryLabel } from "./cmeOptionsFormat";

interface OptionsWallTableProps {
  wallScores: CMEOptionsWallScore[];
  selectedExpiry?: string;
}

export function OptionsWallTable({ wallScores, selectedExpiry }: OptionsWallTableProps) {
  const [sortKey, setSortKey] = useState<OptionsWallSortKey>("wall_score");
  const [sortDirection, setSortDirection] = useState<OptionsWallSortDirection>("desc");
  const [expanded, setExpanded] = useState(true);

  const sortedWallScores = useMemo(
    () => sortWallRows(wallScores, sortKey, sortDirection),
    [wallScores, sortKey, sortDirection],
  );

  const handleHeaderClick = (key: OptionsWallSortKey) => {
    if (sortKey === key) {
      setSortDirection((currentDirection) => (currentDirection === "asc" ? "desc" : "asc"));
      return;
    }

    setSortKey(key);
    setSortDirection(key === "wall_score" ? "desc" : "asc");
  };

  const getAriaSort = (key: OptionsWallSortKey) => {
    if (sortKey !== key) return "none";
    return sortDirection === "asc" ? "ascending" : "descending";
  };

  if (wallScores.length === 0) {
    return <OptionsWallEmptyState />;
  }

  return (
    <FACard
      title="墙位明细"
      eyebrow="墙位评分"
      accent="info"
      bodyClassName="p-0"
      action={
        <button
          type="button"
          onClick={() => setExpanded((prev) => !prev)}
          className="inline-flex items-center gap-1 rounded px-2 py-1 text-[length:var(--text-10)] font-medium text-[var(--fg-4)] transition-colors hover:bg-[var(--bg-hover)]"
        >
          {expanded ? "收起" : "展开"}
          <span className="text-[length:var(--text-10)]">{expanded ? "▲" : "▼"}</span>
        </button>
      }
    >
      <div className="border-b border-[var(--border-faint)] px-3 py-2 text-[length:var(--type-caption)] leading-5 text-[var(--fg-4)]">
        墙位评分和吸附值是当前快照的结构指标，不是概率。墙位接口未返回到期月坐标，因此到期月筛选不会赋予墙位期限归属；未提供的数值显示为“—”，真实零保留。缺失评分不参与强弱比较。
      </div>
      {expanded && (
        <div>
          {selectedExpiry ? <div className="border-b border-[var(--border-faint)] px-3 py-2 text-[length:var(--type-caption)] text-[var(--fg-4)]">当前筛选到期月：{formatCMEExpiryLabel(selectedExpiry)}；墙位仍按快照聚合。</div> : null}
          <div className="overflow-x-auto">
          <table className="w-full min-w-[600px] border-collapse">
            <OptionsWallTableHeader
              sortKey={sortKey}
              sortDirection={sortDirection}
              onHeaderClick={handleHeaderClick}
              getAriaSort={getAriaSort}
            />
            <OptionsWallTableRows rows={sortedWallScores} />
          </table>
          </div>
        </div>
      )}
    </FACard>
  );
}
