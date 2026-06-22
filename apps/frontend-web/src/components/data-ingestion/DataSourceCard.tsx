import { Link } from "react-router-dom";
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

function normalizeMonitorDate(value?: string | null): string | null {
  if (!value) return null;
  const trimmed = value.trim();
  const ymd = trimmed.match(/^(\d{4}-\d{2}-\d{2})/);
  if (ymd) return ymd[1];
  const parsed = new Date(trimmed);
  if (Number.isNaN(parsed.getTime())) return null;
  const yyyy = String(parsed.getFullYear());
  const mm = String(parsed.getMonth() + 1).padStart(2, "0");
  const dd = String(parsed.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

function feishuMonitorHref(source: DataSourceStatusViewModel): string | null {
  if (source.id !== "jin10_feishu") return null;
  const date = normalizeMonitorDate(source.latest_parsed_time ?? source.latest_raw_time ?? source.latest_update_time ?? null);
  return date ? `/feishu-monitor?date=${encodeURIComponent(date)}` : "/feishu-monitor";
}

interface DataSourceCardProps {
  source: DataSourceStatusViewModel;
}

export function DataSourceCard({ source }: DataSourceCardProps) {
  const monitorHref = feishuMonitorHref(source);

  return (
    <FACard
      title={source.label}
      eyebrow={source.group}
      accent={dataSourceAccent(source)}
      action={
        <div className="flex items-center gap-2">
          {monitorHref ? (
            <Link
              to={monitorHref}
              className="rounded-[var(--radius-md)] border border-[var(--border)] px-2.5 py-1 text-[10px] font-semibold text-[var(--fg-3)] transition-colors hover:border-[var(--border-strong)] hover:text-[var(--fg-1)]"
            >
              飞书监控
            </Link>
          ) : null}
          <FAStatusPill tone={pageStatusTone(source.status)}>{`page ${source.status}`}</FAStatusPill>
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
