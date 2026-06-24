import { ExternalLink } from "lucide-react";
import { Link } from "react-router-dom";
import { FACard } from "@/components/shared/FACard";
import { FATabBar, type FATabOption } from "@/components/shared/FATabBar";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { reportFamilyLabel, reportLifecycleLabel, reportTitleLabel, reviewStatusLabel, statusTone } from "@/components/reports/reportDetailMeta";
import { getDataStatusLabel } from "@/lib/status";
import type { ReportDetailTabKey, ReportDetailView } from "@/types/reports";

function InlineMetaItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex min-w-0 flex-col justify-center gap-0.5 rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2 py-1.5">
      <span className="text-[8px] font-medium text-[var(--fg-5)]">{label}</span>
      <span className="truncate text-[10px] font-semibold text-[var(--fg-2)]">{value}</span>
    </div>
  );
}

function isHttpUrl(value: unknown): value is string {
  return typeof value === "string" && /^https?:\/\//.test(value);
}

function pickOriginalUrl(data: ReportDetailView): string | null {
  const payloadSourceRefs = Array.isArray(data.structured_payload?.source_refs)
    ? data.structured_payload.source_refs
    : [];
  const prioritizedPayloadUrls = payloadSourceRefs.flatMap((item) => {
    if (!item || typeof item !== "object") return [];
    const record = item as Record<string, unknown>;
    const assetType = typeof record.asset_type === "string" ? record.asset_type.toLowerCase() : "";
    if (assetType !== "meta_json" && assetType !== "report_md") {
      return [];
    }
    return isHttpUrl(record.source_url) ? [record.source_url] : [];
  });
  const candidates = [
    data.structured_payload?.source_url,
    ...prioritizedPayloadUrls,
    ...data.source_refs.map((item) => item.source_url),
    ...(data.analysis_inputs?.source_refs ?? []).map((item) => item.source_url),
  ];
  return candidates.find(isHttpUrl) ?? null;
}

export function ReportDetailHero({
  data,
  metrics,
  onRefresh,
  tabs,
  activeTab,
  onTabChange,
  summaryChips = [],
}: {
  data: ReportDetailView;
  metrics: Array<{ label: string; value: string }>;
  onRefresh: () => void;
  tabs: FATabOption<ReportDetailTabKey>[];
  activeTab: ReportDetailTabKey;
  onTabChange: (value: ReportDetailTabKey) => void;
  summaryChips?: string[];
}) {
  const familyLabel = reportFamilyLabel(data.meta.family);
  const titleLabel = reportTitleLabel(data.meta.title);
  const showFamilyLabel = Boolean(familyLabel && titleLabel && familyLabel !== titleLabel);
  const originalUrl = pickOriginalUrl(data);

  return (
    <FACard
      title="报告"
      accent="brand"
      headerClassName="py-1"
      action={
        <div className="flex flex-wrap items-center gap-2">
          <Link
            to="/reports"
            className="rounded-[var(--radius-md)] border border-[var(--border)] px-2 py-0.5 text-[10px] font-semibold text-[var(--fg-3)]"
          >
            返回列表
          </Link>
          <button
            type="button"
            onClick={onRefresh}
            className="rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-card-inner)] px-2 py-0.5 text-[10px] font-semibold text-[var(--fg-2)]"
          >
            刷新
          </button>
        </div>
      }
      bodyClassName="space-y-2"
    >
      <div className="space-y-2.5">
        <div className="grid gap-2 xl:grid-cols-[minmax(0,1.45fr)_minmax(280px,0.95fr)] xl:items-start">
          <div className="min-w-0 space-y-1">
            {showFamilyLabel ? <div className="text-[9px] text-[var(--fg-4)]">{familyLabel}</div> : null}
            <div className="truncate text-[13px] font-semibold leading-tight text-[var(--fg-1)]">{titleLabel}</div>
          </div>
          <div className="flex flex-wrap items-center gap-1 xl:justify-end">
            <FAStatusPill tone={statusTone(data.data_status)} className="text-[8px]">
              {getDataStatusLabel(data.data_status)}
            </FAStatusPill>
            <FAStatusPill tone="neutral" className="text-[8px]">
              {reportLifecycleLabel(data.meta.lifecycle_status)}
            </FAStatusPill>
            {data.meta.review_status ? (
              <FAStatusPill tone="info" className="text-[8px]">
                {reviewStatusLabel(data.meta.review_status)}
              </FAStatusPill>
            ) : null}
            {originalUrl ? (
              <a
                href={originalUrl}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 rounded-[var(--radius-pill)] border border-[var(--border)] px-2 py-0.5 text-[8px] font-semibold text-[var(--fg-3)] transition-colors hover:border-[var(--border-strong)] hover:text-[var(--fg-1)]"
                title="打开原始链接"
              >
                原文
                <ExternalLink size={10} />
              </a>
            ) : null}
          </div>
        </div>

        <div className="grid gap-1.5 sm:grid-cols-2 xl:grid-cols-4">
          {metrics.map((metric) => (
            <InlineMetaItem key={metric.label} label={metric.label} value={metric.value} />
          ))}
        </div>

        <div className="grid gap-1.5 xl:grid-cols-[minmax(0,1fr)_auto] xl:items-center">
          <div className="min-w-0">
            {tabs.length > 0 ? (
              <FATabBar
                tabs={tabs}
                value={activeTab}
                onChange={onTabChange}
                ariaLabel="报告内容切换"
                className="min-w-0"
              />
            ) : null}
          </div>
          {summaryChips.length > 0 ? (
            <div className="flex flex-wrap items-center gap-1 xl:justify-end">
              {summaryChips.map((chip) => (
                <span
                  key={chip}
                  className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2 py-0.5 text-[9px] text-[var(--fg-4)]"
                >
                  {chip}
                </span>
              ))}
            </div>
          ) : null}
        </div>
      </div>
    </FACard>
  );
}
