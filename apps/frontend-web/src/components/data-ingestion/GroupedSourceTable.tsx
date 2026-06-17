import { useState, useMemo } from "react";
import type { DataSourceStatusViewModel } from "@/types/data-ingestion";
import { GroupedSourceTableHeader, SourceGroupHeader, SourceRow, SourceTableHeader } from "./GroupedSourceTableParts";
import { groupSources, type GroupKey } from "./GroupedSourceTable.helpers";

interface GroupedSourceTableProps {
  sources: DataSourceStatusViewModel[];
}

export function GroupedSourceTable({ sources }: GroupedSourceTableProps) {
  const groups = useMemo(() => groupSources(sources), [sources]);
  const [expanded, setExpanded] = useState<Record<GroupKey, boolean>>({
    live: true,
    partial: true,
    offline: true,
  });

  const toggle = (key: GroupKey) =>
    setExpanded((prev) => ({ ...prev, [key]: !prev[key] }));

  return (
    <div
      className="flex max-h-[min(78vh,760px)] min-h-0 flex-col overflow-hidden rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card)]"
    >
      <GroupedSourceTableHeader sourceCount={sources.length} />
      <SourceTableHeader />

      <div className="min-h-0 flex-1 overflow-y-auto">
        {groups.map((group) => (
          <div key={group.key}>
            <SourceGroupHeader
              group={group}
              expanded={expanded[group.key]}
              onToggle={() => toggle(group.key)}
            />
            {expanded[group.key] &&
              group.sources.map((source) => <SourceRow key={source.id} source={source} />)}
          </div>
        ))}
      </div>
    </div>
  );
}
