import { FACard } from "@/components/shared/FACard";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import type { DataSourceStatusViewModel } from "@/types/data-ingestion";
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
      eyebrow={source.group}
      accent={dataSourceAccent(source)}
      action={<FAStatusPill tone={pageStatusTone(source.status)}>{`page ${source.status}`}</FAStatusPill>}
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
