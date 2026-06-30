import { ExternalLink } from "lucide-react";
import { Link } from "react-router-dom";
import { FACard } from "@/components/shared/FACard";
import { FATabBar, type FATabOption } from "@/components/shared/FATabBar";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { formatGoldMainlineLabel, formatGoldNetBiasLabel, goldNetBiasTone, normalizeGoldMainlineId } from "@/components/shared/goldMainlineFormat";
import { reportFamilyLabel, reportLifecycleLabel, reportTitleLabel, reviewStatusLabel, statusTone } from "@/components/reports/reportDetailMeta";
import { getDataStatusLabel } from "@/lib/status";
import type { GoldMainlineRanking } from "@/types/gold-mainlines";
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

function rankingMainlineId(item: GoldMainlineRanking): string | null {
  return normalizeGoldMainlineId(item.mainline_id ?? item.mainline);
}

function formatScore(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "-";
  return value <= 1 ? String(Math.round(value * 100)) : String(Math.round(value));
}

export function ReportGoldMacroOverviewCard({ data }: { data: ReportDetailView }) {
  const overview = data.gold_macro_overview;
  if (!overview) return null;
  const topRankings = [...(overview.theme_rankings ?? [])]
    .sort((left, right) => left.rank - right.rank)
    .slice(0, 3);
  const pendingVerification = (overview.verification_matrix ?? []).filter((item) => {
    const status = String(item.status ?? "").toLowerCase();
    return status === "pending" || status === "missing" || status === "unverified" || status.includes("needed");
  }).length;

  return (
    <FACard title="黄金主线上下文" eyebrow="Gold Macro Overview" accent="warn" bodyClassName="space-y-3">
      <div className="grid gap-3 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
        <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
          <div className="flex flex-wrap items-center gap-2">
            <FAStatusPill tone={goldNetBiasTone(overview.net_bias)} dot={false}>
              {formatGoldNetBiasLabel(overview.net_bias)}
            </FAStatusPill>
            <FAStatusPill tone="info" dot={false}>
              {formatGoldMainlineLabel(overview.dominant_mainline)}
            </FAStatusPill>
            <span className="fa-num text-[10px] text-[var(--fg-5)]">{overview.as_of?.slice(0, 10) || "日期未知"}</span>
          </div>
          <p className="mt-2 line-clamp-2 text-[11px] leading-5 text-[var(--fg-3)]">
            {overview.one_line_conclusion || "当前报告关联最新黄金主线总览，用于复核报告结论与宏观主线是否一致。"}
          </p>
          <div className="mt-2 flex flex-wrap gap-1.5 text-[10px] text-[var(--fg-4)]">
            <span className="rounded-[var(--radius-pill)] border border-[var(--border-faint)] px-2 py-0.5">风险 {formatScore(overview.risk_score)}/100</span>
            <span className="rounded-[var(--radius-pill)] border border-[var(--border-faint)] px-2 py-0.5">待验证 {pendingVerification}</span>
          </div>
        </div>
        <div className="space-y-1.5">
          {topRankings.map((item) => (
            <div
              key={`${rankingMainlineId(item) ?? item.label ?? "mainline"}-${item.rank}`}
              className="grid grid-cols-[22px_minmax(0,1fr)_auto] items-center gap-2 rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2.5 py-1.5"
            >
              <span className="fa-num text-[10px] text-[var(--fg-5)]">#{item.rank}</span>
              <div className="min-w-0">
                <div className="truncate text-[11px] font-semibold text-[var(--fg-2)]">
                  {item.label || formatGoldMainlineLabel(rankingMainlineId(item))}
                </div>
                <div className="truncate text-[10px] text-[var(--fg-5)]">{formatGoldNetBiasLabel(item.direction)}</div>
              </div>
              <span className="fa-num text-[11px] font-semibold text-[var(--fg-2)]">{formatScore(item.score)}</span>
            </div>
          ))}
        </div>
      </div>
      <div className="flex justify-end">
        <Link
          to="/gold-mainlines"
          className="inline-flex items-center rounded-[var(--radius-pill)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2.5 py-1 text-[10px] font-semibold text-[var(--fg-3)] hover:border-[var(--border)] hover:text-[var(--fg-1)]"
        >
          查看九主线
        </Link>
      </div>
    </FACard>
  );
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
  const anchorTradeDate =
    typeof data.structured_payload?.anchor_trade_date === "string" ? data.structured_payload.anchor_trade_date : null;
  const isSupplementalReport =
    data.meta.family === "macro_event_followup_supplement" || String(data.meta.title ?? "").includes("宏观事件跟进补充");
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

        {anchorTradeDate ? (
          <div className="flex flex-wrap items-center gap-2 text-[9px] text-[var(--fg-4)]">
            <span className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2 py-0.5">
              锚定日期 {anchorTradeDate}
            </span>
            {isSupplementalReport ? (
              <span className="rounded-[var(--radius-md)] border border-[var(--warn-border)] bg-[var(--warn-bg)] px-2 py-0.5 text-[var(--warn)]">
                补充分析
              </span>
            ) : null}
          </div>
        ) : null}

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
