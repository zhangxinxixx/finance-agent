import { FACard } from "@/components/shared/FACard";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import type { DataSourceStatusViewModel } from "@/types/data-ingestion";
import { operationSourceGroupLabel, operationStatusLabel } from "@/components/operations/operationsLabels";
import { dataSourceAccent, pageStatusTone } from "./DataSourceCard.helpers";
import {
  DataSourceCardHeader,
  DataSourceMetadataGrid,
  DataSourceMetricsGrid,
  DataSourceRefsFooter,
  DataSourceStageGrid,
  DataSourceTraceFooter,
  DataSourceWarnings,
} from "./DataSourceCardSections";

interface DataSourceCardProps {
  source: DataSourceStatusViewModel;
}

export function DataSourceCard({ source }: DataSourceCardProps) {
  return (
    <FACard
      title={source.label}
      eyebrow={operationSourceGroupLabel(source.group)}
      accent={dataSourceAccent(source)}
      action={
        <div className="flex items-center gap-2">
          <FAStatusPill tone={pageStatusTone(source.status)}>{operationStatusLabel(source.status)}</FAStatusPill>
        </div>
      }
      bodyClassName="space-y-4"
    >
      <DataSourceCardHeader source={source} />
      <DataSourceStageGrid source={source} />
      <DataSourceMetricsGrid source={source} />
      <DataSourceMetadataGrid source={source} />
      <DataSourceWarnings source={source} />
      <DataSourceRefsFooter source={source} />
      <DataSourceTraceFooter source={source} />
    </FACard>
  );
}
