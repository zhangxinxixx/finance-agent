import type { ReportFilters } from "./reportsRailOptions";
import {
  ASSET_OPTIONS,
  CATEGORY_CONFIGS,
  DATA_SOURCE_OPTIONS,
  DATE_RANGE_OPTIONS,
  STATUS_OPTIONS,
} from "./reportsRailOptions";
import {
  ReportsRailColorOptionButton,
  ReportsRailDateRangeButton,
  ReportsRailDateRangeGrid,
  ReportsRailDotOptionButton,
  ReportsRailFilterSection,
  ReportsRailTextOptionButton,
} from "./ReportsRailFilterPrimitives";

export function ReportsRailReportTypeSection({
  filters,
  onToggle,
  countByType,
}: {
  filters: ReportFilters;
  onToggle: (type: string) => void;
  countByType: (matchType: string) => number;
}) {
  return (
    <ReportsRailFilterSection label="报告类型">
      {CATEGORY_CONFIGS.map((cat) => {
        const count = countByType(cat.matchType);
        const isActive = filters.reportTypes.includes(cat.matchType);
        return (
          <ReportsRailColorOptionButton
            key={cat.key}
            onClick={() => onToggle(cat.matchType)}
            isActive={isActive}
            color={cat.color}
            label={cat.label}
            count={count}
          />
        );
      })}
    </ReportsRailFilterSection>
  );
}

export function ReportsRailAssetSection({
  filters,
  onFilterChange,
}: {
  filters: ReportFilters;
  onFilterChange: (filters: ReportFilters) => void;
}) {
  return (
    <ReportsRailFilterSection label="资产">
      {ASSET_OPTIONS.map((asset) => {
        const isActive = filters.asset === asset.key || (asset.key === "all" && filters.asset === null);
        return (
          <ReportsRailDotOptionButton
            key={asset.key}
            onClick={() => onFilterChange({ ...filters, asset: asset.key === "all" ? null : asset.key })}
            isActive={isActive}
            color={asset.color}
            label={asset.label}
          />
        );
      })}
    </ReportsRailFilterSection>
  );
}

export function ReportsRailStatusSection({
  filters,
  onFilterChange,
}: {
  filters: ReportFilters;
  onFilterChange: (filters: ReportFilters) => void;
}) {
  return (
    <ReportsRailFilterSection label="报告状态">
      {STATUS_OPTIONS.map((opt) => {
        const isActive = filters.status === opt.key;
        return (
          <ReportsRailTextOptionButton
            key={opt.key}
            isActive={isActive}
            onClick={() => onFilterChange({ ...filters, status: isActive ? null : opt.key })}
          >
            {opt.label}
          </ReportsRailTextOptionButton>
        );
      })}
    </ReportsRailFilterSection>
  );
}

export function ReportsRailDataSourceSection({
  filters,
  onFilterChange,
}: {
  filters: ReportFilters;
  onFilterChange: (filters: ReportFilters) => void;
}) {
  return (
    <ReportsRailFilterSection label="数据来源">
      {DATA_SOURCE_OPTIONS.map((opt) => {
        const isActive = filters.dataSource === opt.key;
        return (
          <ReportsRailTextOptionButton
            key={opt.key}
            isActive={isActive}
            onClick={() => onFilterChange({ ...filters, dataSource: isActive ? null : opt.key })}
          >
            {opt.label}
          </ReportsRailTextOptionButton>
        );
      })}
    </ReportsRailFilterSection>
  );
}

export function ReportsRailDateRangeSection({
  filters,
  onFilterChange,
}: {
  filters: ReportFilters;
  onFilterChange: (filters: ReportFilters) => void;
}) {
  return (
    <ReportsRailFilterSection label="日期范围">
      <ReportsRailDateRangeGrid>
        {DATE_RANGE_OPTIONS.map(([id, label]) => {
          const isActive = filters.dateRange === id;
          return (
            <ReportsRailDateRangeButton
              key={id}
              onClick={() => onFilterChange({ ...filters, dateRange: isActive ? null : id })}
              isActive={isActive}
              label={label}
            />
          );
        })}
      </ReportsRailDateRangeGrid>
    </ReportsRailFilterSection>
  );
}
