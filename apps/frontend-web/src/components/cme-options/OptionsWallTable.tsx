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

interface OptionsWallTableProps {
  wallScores: CMEOptionsWallScore[];
}

export function OptionsWallTable({ wallScores }: OptionsWallTableProps) {
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
          className="inline-flex items-center gap-1 rounded px-2 py-1 text-[10px] font-medium text-[var(--fg-4)] transition-colors hover:bg-[var(--bg-hover)]"
        >
          {expanded ? "收起" : "展开"}
          <span className="text-[10px]">{expanded ? "▲" : "▼"}</span>
        </button>
      }
    >
      {expanded && (
        <div className="overflow-x-auto">
          <table className="min-w-full border-collapse">
            <OptionsWallTableHeader
              sortKey={sortKey}
              sortDirection={sortDirection}
              onHeaderClick={handleHeaderClick}
              getAriaSort={getAriaSort}
            />
            <OptionsWallTableRows rows={sortedWallScores} />
          </table>
        </div>
      )}
    </FACard>
  );
}
