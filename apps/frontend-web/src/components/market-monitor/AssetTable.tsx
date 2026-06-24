import type { MarketMonitorMetric } from "@/types/market-monitor";
import {
  AssetGroupSection,
  AssetTableColumns,
  AssetTableHeader,
  GROUP_ORDER,
} from "@/components/market-monitor/AssetTableSections";

interface AssetTableProps {
  metrics: MarketMonitorMetric[];
}

export function AssetTable({ metrics }: AssetTableProps) {
  return (
    <div
      style={{
        background: "var(--bg-panel)",
        border: "1px solid var(--border-faint)",
        borderRadius: "var(--radius-lg)",
      }}
    >
      <AssetTableHeader metricCount={metrics.length} />
      <AssetTableColumns />
      {GROUP_ORDER.map((group) => (
        <AssetGroupSection key={group} group={group} metrics={metrics} />
      ))}
    </div>
  );
}

export default AssetTable;
