import { useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { Activity, ArrowRight, ExternalLink, FileText, Loader2, RefreshCw, ShieldAlert } from "lucide-react";
import { ApiError } from "@/adapters/apiClient";
import { reviewEventFlowEvent } from "@/adapters/eventFlow";
import { FACard } from "@/components/shared/FACard";
import { FAEmptyState } from "@/components/shared/FAEmptyState";
import { FASourceTraceBadge } from "@/components/shared/FASourceTraceBadge";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { EventChainAnalysis } from "@/components/event-flow/EventChainAnalysis";
import { EventFlowReportInputsPanel } from "@/components/event-flow/EventFlowReportInputsPanel";
import { EventFlowSourceRefsCard } from "@/components/event-flow/EventFlowSourceRefsCard";
import { EventTable } from "@/components/event-flow/EventTable";
import { ImpactAssets } from "@/components/event-flow/ImpactAssets";
import { RiskRadar } from "@/components/event-flow/RiskRadar";
import { formatEventFlowHeadlineSummary, formatEventFlowSourceLabel, translateEventFlowValue } from "@/components/event-flow/eventFlowFormat";
import { useEventFlow } from "@/hooks/useEventFlow";
import { useReports } from "@/hooks/useReports";
import { formatDateTime } from "@/lib/date";
import { compactSourceLabel, dedupeSourceRefs, normalizeSourceRefs } from "@/lib/sourceRefs";
import { CATEGORY_MAP, getReportDetailId, shortRunId } from "@/components/reports/reportListMeta";
import { findRelatedBriefs } from "@/components/event-flow/eventFlowMatching";
import { normalizeEventDateCandidates } from "@/components/event-flow/eventFlowDate";
import type { Jin10ArticleBrief, Jin10ArticleBriefBundle, EventFlowTimelineItem } from "@/types/event-flow";
import type { ReportIndexItem } from "@/types/reports";
import type { SourceRef } from "@/types/common";
import type { EventFlowTableRow } from "@/types/event-flow";

const EVENT_FLOW_ASSET_LABELS: Record<string, string> = {
  xauusd: "黄金",
  gold: "黄金",
  xagusd: "白银",
  silver: "白银",
  dxy: "美元指数",
  usd: "美元",
  usdjpy: "美元兑日元",
  us10y: "10年期美债",
  us02y: "2年期美债",
  us2y: "2年期美债",
  wti: "纽约原油",
  brent: "布伦特原油",
  oil: "原油",
  rates: "利率",
  macro: "宏观",
};

function formatReportFormatLabel(value: string | null | undefined): string {
  const normalized = value?.trim().toLowerCase();
  if (!normalized) return "未标注";
  if (normalized === "markdown" || normalized === "md") return "文稿";
  if (normalized === "json") return "结构化数据";
  if (normalized === "html") return "网页";
  if (normalized === "pdf") return "PDF";
  return value ?? "未标注";
}

function toTone(pricing: string | null | undefined): "up" | "warn" | "down" | "dim" {
  if (pricing === "已定价") return "up";
  if (pricing === "部分定价") return "warn";
  if (pricing === "未定价") return "down";
  return "dim";
}

function importanceLabel(value: string | null | undefined): string {
  return value || "低";
}

function riskTone(riskLevel: string | null | undefined): "up" | "warn" | "down" | "dim" {
  if (riskLevel === "high") return "down";
  if (riskLevel === "medium") return "warn";
  if (riskLevel === "low") return "up";
  return "dim";
}

function findRelatedReports(
  event: EventFlowTimelineItem | null,
  reports: ReportIndexItem[],
  fallbackDates: readonly string[] = [],
): ReportIndexItem[] {
  if (!event) return [];
  const dateCandidates = new Set(normalizeEventDateCandidates(event, fallbackDates));
  const assetText = `${event.assets ?? ""} ${event.title} ${event.desc}`.toLowerCase();
  const prefersGold = assetText.includes("xau") || assetText.includes("gold") || assetText.includes("黄金");

  const scored = reports
    .filter((report) => report.available && !report.type.includes("jin10"))
    .map((report) => {
      let score = 0;
      if (dateCandidates.has(report.trade_date)) score += 4;
      if (report.type === "options_report" && prefersGold) score += 2;
      return { report, score };
    })
    .filter((item) => item.score > 0)
    .sort((a, b) => {
      if (b.score !== a.score) return b.score - a.score;
      return b.report.trade_date.localeCompare(a.report.trade_date);
    });

  return scored.slice(0, 4).map((item) => item.report);
}

function buildEvidenceRefs(
  pageSourceRefs: SourceRef[] | undefined,
  eventSourceRefs: SourceRef[] | undefined,
  briefs: Jin10ArticleBrief[],
): SourceRef[] {
  const briefRefs = briefs.flatMap((brief) => normalizeSourceRefs(brief.source_refs));
  return dedupeSourceRefs([
    ...(pageSourceRefs ?? []),
    ...(eventSourceRefs ?? []),
    ...briefRefs,
  ]);
}

function buildFallbackRow(event: EventFlowTimelineItem): EventFlowTableRow {
  return {
    id: event.id,
    time: [event.date, event.time].filter(Boolean).join(" ").trim() || event.time,
    title: event.title,
    type: event.type,
    source: event.source ?? "事件流",
    assets: event.assets ?? event.affected_assets?.map(formatAssetToken).join(", ") ?? "—",
    impact: event.impact,
    pricing: event.pricing ?? "未定价",
    period: event.period ?? "主线",
    stars: event.importance === "高" ? 5 : event.importance === "中" ? 3 : 1,
    verification_status: event.verification_status,
    risk_level: event.risk_level,
    event_kind: event.event_kind,
    source_refs: event.source_refs,
  };
}

function formatAssetToken(value: string | null | undefined): string {
  const normalized = String(value ?? "").trim();
  if (!normalized) return "—";
  const key = normalized.toLowerCase();
  return EVENT_FLOW_ASSET_LABELS[key] ?? normalized;
}

function formatAssetList(values: string[]): string[] {
  return values.map((item) => formatAssetToken(item));
}

function normalizeFeishuMonitorDate(value: string | null | undefined): string | null {
  if (!value) return null;
  const trimmed = value.trim();
  const ymd = trimmed.match(/^(\d{4}-\d{2}-\d{2})/);
  if (ymd) return ymd[1];
  const compact = trimmed.match(/^(\d{4})(\d{2})(\d{2})$/);
  if (compact) return `${compact[1]}-${compact[2]}-${compact[3]}`;
  return null;
}

function resolveFeishuMonitorDate(bundle: Jin10ArticleBriefBundle | null | undefined): string | null {
  return normalizeFeishuMonitorDate(bundle?.date);
}

function EventRelatedBriefsCard({
  briefs,
  feishuMonitorDate,
}: {
  briefs: Jin10ArticleBrief[];
  feishuMonitorDate: string | null;
}) {
  if (briefs.length === 0) {
    return (
      <FACard
        title="关联快讯"
        eyebrow="快讯关联"
        accent="warn"
        action={
          feishuMonitorDate ? (
            <Link
              to={`/feishu-monitor?date=${encodeURIComponent(feishuMonitorDate)}`}
              className="inline-flex items-center gap-1.5 rounded-[var(--radius-md)] border border-[var(--border)] px-3 py-1.5 text-[11px] font-semibold text-[var(--fg-3)] transition-colors hover:border-[var(--border-strong)] hover:text-[var(--fg-2)]"
            >
              <span>回到当天飞书监控</span>
              <ExternalLink size={12} />
            </Link>
          ) : null
        }
      >
        <FAEmptyState
          title="当前事件暂无可匹配的快讯摘要"
          description="说明事件读模型还缺显式关联键，当前只保留来源和报告下钻。"
        />
      </FACard>
    );
  }

  return (
    <FACard
      title="关联快讯"
      eyebrow="快讯关联"
      accent="warn"
      action={
        feishuMonitorDate ? (
          <Link
            to={`/feishu-monitor?date=${encodeURIComponent(feishuMonitorDate)}`}
            className="inline-flex items-center gap-1.5 rounded-[var(--radius-md)] border border-[var(--border)] px-3 py-1.5 text-[11px] font-semibold text-[var(--fg-3)] transition-colors hover:border-[var(--border-strong)] hover:text-[var(--fg-2)]"
          >
            <span>回到当天飞书监控</span>
            <ExternalLink size={12} />
          </Link>
        ) : null
      }
      bodyClassName="space-y-2"
    >
      <div className="divide-y divide-[var(--border-faint)]">
        {briefs.map((brief) => {
          const headline = formatEventFlowHeadlineSummary(brief.headline, 44);
          return (
            <article key={brief.brief_id} className="py-3 first:pt-0 last:pb-0">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0 space-y-1">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <FAStatusPill tone="warn">{brief.display_bucket}</FAStatusPill>
                    <FAStatusPill tone={brief.access_status === "readable" ? "up" : "warn"}>{translateEventFlowValue(brief.access_status)}</FAStatusPill>
                  </div>
                  <div className="space-y-0.5">
                    <div className="text-[12px] font-semibold leading-5 text-[var(--fg-1)]">{headline.lead}</div>
                    {headline.subline ? (
                      <div className="text-[10px] leading-4 text-[var(--fg-4)]">{headline.subline}</div>
                    ) : null}
                  </div>
                </div>
                {brief.source_url ? (
                  <a
                    href={brief.final_url ?? brief.source_url}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-[var(--radius-sm)] border border-[var(--border)] text-[var(--fg-4)] transition-colors hover:border-[var(--border-strong)] hover:text-[var(--fg-2)]"
                    title="打开来源链接"
                  >
                    <ExternalLink size={13} />
                  </a>
                ) : null}
              </div>
              {brief.analysis_summary ? (
                <div className="mt-2 text-[11px] leading-5 text-[var(--fg-2)]">{brief.analysis_summary}</div>
              ) : null}
              {brief.key_points.length > 0 ? (
                <ul className="mt-2 grid gap-1 text-[11px] leading-5 text-[var(--fg-3)]">
                  {brief.key_points.slice(0, 2).map((point) => (
                    <li key={`${brief.brief_id}-${point}`} className="flex gap-2">
                      <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-[var(--fg-5)]" />
                      <span>{point}</span>
                    </li>
                  ))}
                </ul>
              ) : null}
              {brief.detail_artifacts && Object.keys(brief.detail_artifacts).length > 0 ? (
                <div className="mt-2 grid gap-1 text-[10px] text-[var(--fg-4)]">
                  <div className="text-[10px] font-semibold text-[var(--fg-5)]">关联工件</div>
                  {Object.entries(brief.detail_artifacts)
                    .slice(0, 6)
                    .map(([key, value]) => {
                      const display = formatArtifactValue(value);
                      if (!display) return null;
                      return (
                        <div key={`${brief.brief_id}-${key}`} className="grid gap-1 sm:grid-cols-[120px_minmax(0,1fr)]">
                          <span className="text-[var(--fg-5)]">{key}</span>
                          <span className="break-all font-mono text-[var(--fg-3)]">{display}</span>
                        </div>
                      );
                    })}
                </div>
              ) : null}
            </article>
          );
        })}
      </div>
    </FACard>
  );
}

function prioritizeSelectedBrief(briefs: Jin10ArticleBrief[], briefId: string | null): Jin10ArticleBrief[] {
  if (!briefId) return briefs;
  const selected = briefs.find((brief) => brief.brief_id === briefId);
  if (!selected) return briefs;
  return [selected, ...briefs.filter((brief) => brief.brief_id !== briefId)];
}

function includeSelectedBrief(briefs: Jin10ArticleBrief[], allBriefs: Jin10ArticleBrief[] | undefined, briefId: string | null): Jin10ArticleBrief[] {
  if (!briefId) return briefs;
  const selected = allBriefs?.find((brief) => brief.brief_id === briefId);
  if (!selected) return briefs;
  return prioritizeSelectedBrief([selected, ...briefs.filter((brief) => brief.brief_id !== briefId)], briefId);
}

function eventFromBrief(brief: Jin10ArticleBrief): EventFlowTimelineItem {
  return {
    id: `brief_${brief.brief_id}`,
    time: brief.created_at ?? "",
    date: brief.created_at?.slice(0, 10) ?? "",
    title: brief.headline,
    desc: brief.analysis_summary || brief.original_excerpt,
    type: "市场事件",
    importance: brief.display_bucket.includes("快讯") ? "中" : "低",
    status: "发展中",
    impact: "混合",
    source: "金十快讯摘要",
    assets: brief.asset_tags.join(", "),
    period: "短期",
    pricing: "未定价",
    verification_status: brief.access_status === "readable" ? "single_source" : "needs_verification",
    risk_level: "unknown",
    event_kind: brief.display_bucket,
    raw_event_type: brief.article_class,
    source_refs: normalizeSourceRefs(brief.source_refs),
  };
}

function formatArtifactValue(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (value && typeof value === "object") return JSON.stringify(value);
  return "";
}

function asDetailRecord(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  return value as Record<string, unknown>;
}

function numberOrZero(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function sourceRefRenderKey(ref: SourceRef): string {
  return [
    ref.source_ref,
    ref.endpoint ?? "",
    ref.artifact_path ?? "",
    ref.snapshot_id ?? "",
    ref.trade_date ?? "",
    ref.run_id ?? "",
  ].join("|");
}

function marketWindowRows(validation: Record<string, unknown>): Array<{ window: string; asset: string; direction: string; value: string }> {
  const windows = asDetailRecord(validation.windows);
  return Object.entries(windows)
    .flatMap(([window, assets]) =>
      Object.entries(asDetailRecord(assets)).map(([asset, movement]) => {
        const item = asDetailRecord(movement);
        const change = item.change_bp ?? item.pct_change ?? item.abs_change;
        const suffix = item.change_bp !== undefined ? "bp" : item.pct_change !== undefined ? "%" : "";
        return {
          window,
          asset: formatAssetToken(asset),
          direction: String(item.direction ?? "unknown"),
          value: change === undefined ? "—" : `${change}${suffix}`,
        };
      }),
    )
    .slice(0, 6);
}

function EventRelatedReportsCard({
  reports,
  isLoading,
  error,
  onOpen,
}: {
  reports: ReportIndexItem[];
  isLoading: boolean;
  error: Error | null;
  onOpen: (report: ReportIndexItem) => void;
}) {
  return (
    <FACard
      title={
        <div className="flex items-center gap-2">
          <FileText size={12} className="text-[var(--brand-hover)]" />
          <span>关联报告</span>
        </div>
      }
      eyebrow="报告联动"
      accent="brand"
    >
      {isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 3 }).map((_, index) => (
            <div key={index} className="h-16 animate-pulse rounded-[var(--radius-md)] bg-[var(--bg-card-inner)]" />
          ))}
        </div>
      ) : error ? (
        <FAEmptyState title="报告索引加载失败" description={error.message} />
      ) : reports.length === 0 ? (
        <FAEmptyState
          title="暂无关联报告"
          description="当前按事件日期与黄金主题做保守匹配，没有命中可跳转的报告。"
        />
      ) : (
        <div className="divide-y divide-[var(--border-faint)]">
          {reports.map((report) => {
            const meta = CATEGORY_MAP[report.type] ?? { label: translateEventFlowValue(report.type), color: "#64748b" };
            const detailId = getReportDetailId(report);
            return (
              <button
                key={[report.type, report.trade_date, report.run_id].join("|")}
                type="button"
                onClick={() => detailId && onOpen(report)}
                disabled={!detailId}
                className="w-full py-3 text-left transition-colors disabled:cursor-default disabled:opacity-60"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <FAStatusPill tone="info">{meta.label}</FAStatusPill>
                      <FAStatusPill tone="dim">{report.trade_date}</FAStatusPill>
                    </div>
                    <div className="mt-1 text-[12px] font-semibold text-[var(--fg-2)]">{meta.label} · {report.trade_date}</div>
                    <div className="mt-1 text-[10px] text-[var(--fg-4)]">批次 {shortRunId(report.run_id)} · {formatReportFormatLabel(report.format)}</div>
                  </div>
                  {detailId ? <ArrowRight size={14} className="mt-1 shrink-0 text-[var(--fg-5)]" /> : null}
                </div>
              </button>
            );
          })}
        </div>
      )}
    </FACard>
  );
}

function MarketValidationPlaceholder({
  activeEvent,
  sourceRefs,
}: {
  activeEvent: EventFlowTimelineItem;
  sourceRefs: SourceRef[];
}) {
  const validation = asDetailRecord(activeEvent.market_validation);
  const snapshot = asDetailRecord(activeEvent.market_snapshot ?? validation.market_snapshot);
  const confirmation = asDetailRecord(validation.confirmation_summary);
  const windowRows = marketWindowRows(validation);
  const observedAssets = Array.isArray(snapshot.observed_assets) ? formatAssetList(snapshot.observed_assets.map(String)) : [];
  const missingAssets = Array.isArray(snapshot.missing_assets) ? formatAssetList(snapshot.missing_assets.map(String)) : [];
  const hasValidation = Object.keys(validation).length > 0 || Object.keys(snapshot).length > 0;

  return (
    <FACard
      title={
        <div className="flex items-center gap-2">
          <ShieldAlert size={12} className="text-[var(--warn)]" />
          <span>市场验证</span>
        </div>
      }
      eyebrow="市场验证"
      accent="warn"
      bodyClassName="space-y-3"
    >
      {hasValidation ? (
        <>
          <div className="grid gap-2 sm:grid-cols-3">
            {[
              { label: "确认", value: numberOrZero(confirmation.confirmed_count) },
              { label: "背离", value: numberOrZero(confirmation.contradicted_count) },
              { label: "观测", value: numberOrZero(confirmation.observed_count) },
            ].map((item) => (
              <div key={item.label} className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-2">
                <div className="text-[10px] font-semibold text-[var(--fg-4)]">{item.label}</div>
                <div className="mt-1 font-mono text-[13px] font-semibold text-[var(--fg-1)]">{item.value}</div>
              </div>
            ))}
          </div>
          <div className="grid gap-2 text-[11px] text-[var(--fg-3)]">
            <div>当前定价标签：{translateEventFlowValue(activeEvent.pricing ?? String(validation.pricing_status ?? "未标注"))}</div>
            <div>影响路径：{translateEventFlowValue(activeEvent.impact_path ?? "未返回")}</div>
            <div>主窗口：{String(snapshot.primary_window ?? "未返回")}</div>
            <div>已观测资产：{observedAssets.length > 0 ? observedAssets.join(" / ") : "暂无"}</div>
            <div>缺失资产：{missingAssets.length > 0 ? missingAssets.join(" / ") : "暂无"}</div>
          </div>
          {windowRows.length > 0 ? (
            <div className="space-y-1.5">
              {windowRows.map((row) => (
                <div
                  key={`${row.window}-${row.asset}`}
                  className="grid grid-cols-[52px_72px_minmax(0,1fr)] gap-2 rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2 py-1.5 text-[10px] text-[var(--fg-3)]"
                >
                  <span className="font-mono text-[var(--fg-5)]">{row.window}</span>
                  <span className="font-semibold text-[var(--fg-2)]">{row.asset}</span>
                  <span className="truncate">{translateEventFlowValue(row.direction)} · {row.value}</span>
                </div>
              ))}
            </div>
          ) : (
            <FAEmptyState title="暂无窗口行情反应" description="当前事件已返回验证结构，但窗口反应字段为空或缺少行情样本。" className="py-4" />
          )}
        </>
      ) : (
        <>
          <div className="rounded-[var(--radius-md)] border border-[rgba(245,158,11,0.18)] bg-[rgba(245,158,11,0.06)] p-3 text-[11px] leading-5 text-[var(--fg-2)]">
            当前详情页已拿到事件状态、来源和关联快讯，但后端尚未给此事件返回真实价格验证。这里明确展示边界，不把占位说明伪装成结论。
          </div>
          <div className="grid gap-2 text-[11px] text-[var(--fg-3)]">
            <div>当前定价标签：{translateEventFlowValue(activeEvent.pricing ?? "未标注")}</div>
            <div>当前验证状态：{translateEventFlowValue(activeEvent.verification_status ?? "needs_verification")}</div>
            <div>后续接入项：黄金 / 美元指数 / 10年期美债 / 纽约原油 / 美元兑日元 事件窗口反应</div>
          </div>
        </>
      )}
      <div className="flex flex-wrap gap-2">
        {sourceRefs.slice(0, 3).map((ref) => (
          <FASourceTraceBadge
            key={sourceRefRenderKey(ref)}
            source={formatEventFlowSourceLabel(compactSourceLabel(ref), 18).text}
            status={ref.status ?? "ok"}
          />
        ))}
      </div>
    </FACard>
  );
}

export function EventFlowDetailPage() {
  const { eventId } = useParams<{ eventId: string }>();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { data, isLoading, error, refetch } = useEventFlow();
  const [reviewPending, setReviewPending] = useState(false);
  const [reviewReceipt, setReviewReceipt] = useState<{ runId: string | null; reviewId: string | null; status: string } | null>(null);
  const [reviewError, setReviewError] = useState<string | null>(null);
  const { indexItems, railLoading, railError } = useReports();
  const routeEventId = eventId ? decodeURIComponent(eventId) : "";
  const selectedBriefId = searchParams.get("briefId") ?? (routeEventId.startsWith("brief_") ? routeEventId.slice("brief_".length) : null);
  const allBriefs = data?.article_briefs?.briefs;
  const selectedBrief = selectedBriefId ? allBriefs?.find((brief) => brief.brief_id === selectedBriefId) ?? null : null;
  const activeEvent =
    data?.timeline.find((item) => item.id === routeEventId) ??
    (routeEventId.startsWith("brief_") && selectedBrief ? eventFromBrief(selectedBrief) : null);

  const relatedBriefs = useMemo(() => {
    const matched = findRelatedBriefs(activeEvent ?? null, data?.article_briefs?.briefs);
    return includeSelectedBrief(matched, data?.article_briefs?.briefs, selectedBriefId);
  }, [activeEvent, data?.article_briefs?.briefs, selectedBriefId]);
  const feishuMonitorDate = useMemo(() => resolveFeishuMonitorDate(data?.article_briefs), [data?.article_briefs]);

  const relatedRows = useMemo(() => {
    if (!data || !activeEvent) return [];
    const exactRows = data.table.filter((row) => row.id === activeEvent.id);
    if (exactRows.length > 0) return exactRows;

    const titlePrefix = activeEvent.title.slice(0, 6);
    if (!titlePrefix) return [buildFallbackRow(activeEvent)];

    const fuzzyRows = data.table.filter((row) => row.title.includes(titlePrefix));
    return fuzzyRows.length > 0 ? fuzzyRows : [buildFallbackRow(activeEvent)];
  }, [data, activeEvent]);

  const eventRefs = activeEvent?.source_refs ?? [];
  const briefRefs = useMemo(
    () => dedupeSourceRefs(relatedBriefs.flatMap((brief) => normalizeSourceRefs(brief.source_refs))),
    [relatedBriefs],
  );
  const pageRefs = data?.source_refs ?? [];
  const evidenceRefs = useMemo(
    () => buildEvidenceRefs(pageRefs, eventRefs, relatedBriefs),
    [pageRefs, eventRefs, relatedBriefs],
  );

  const relatedReports = useMemo(
    () => {
      if (!activeEvent) return [];
      const fallbackDates = [
        data?.article_briefs?.date,
        ...(data?.source_refs ?? []).flatMap((ref) => [ref.trade_date, ref.dataDate, ref.asOf, ref.generated_at]),
      ].filter((value): value is string => Boolean(value));
      return findRelatedReports(activeEvent, indexItems, fallbackDates);
    },
    [activeEvent, data?.article_briefs?.date, data?.source_refs, indexItems],
  );

  if (isLoading && !data) {
    return (
      <div className="finance-page-shell">
        <div className="fa-card h-28 animate-pulse" />
        <div className="grid gap-3 lg:grid-cols-2 2xl:grid-cols-4">
          {Array.from({ length: 4 }).map((_, index) => (
            <div key={index} className="fa-card h-20 animate-pulse" />
          ))}
        </div>
        <div className="fa-card h-[420px] animate-pulse" />
      </div>
    );
  }

  if (error || !data || !activeEvent) {
    return (
      <div className="finance-page-shell">
        <FACard title="事件详情不可用" eyebrow="事件详情" accent="down">
          <FAEmptyState
            title="未找到对应事件"
            description={error?.message ?? "当前链接没有命中可展示事件，请返回事件流重新选择。"}
            action={
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={refetch}
                  className="rounded-[var(--radius-md)] border border-[var(--border)] px-3 py-1.5 text-[11px] font-semibold text-[var(--fg-2)]"
                >
                  重试
                </button>
                <Link
                  to="/event-flow"
                  className="rounded-[var(--radius-md)] border border-[var(--border)] px-3 py-1.5 text-[11px] font-semibold text-[var(--fg-3)]"
                >
                  返回事件流
                </Link>
              </div>
            }
          />
        </FACard>
      </div>
    );
  }

  const headerMetrics = [
    { label: "类型", value: translateEventFlowValue(activeEvent.raw_event_type ?? activeEvent.type) },
    { label: "重要性", value: translateEventFlowValue(importanceLabel(activeEvent.importance)) },
    { label: "状态", value: translateEventFlowValue(activeEvent.status) },
    { label: "定价", value: translateEventFlowValue(activeEvent.pricing ?? "未标注") },
    { label: "验证", value: translateEventFlowValue(activeEvent.verification_status ?? "needs_verification") },
    { label: "资产", value: activeEvent.assets ?? "—" },
  ];
  const pageSource = formatEventFlowSourceLabel(data.source, 18).text;
  const eventSource = formatEventFlowSourceLabel(activeEvent.source ?? "—", 18).text;
  const headerTitle = formatEventFlowHeadlineSummary(activeEvent.title, 72);

  async function requestReview() {
    if (!activeEvent) return;
    setReviewPending(true);
    setReviewError(null);
    try {
      const response = await reviewEventFlowEvent(activeEvent.id, {
        reason: `event ${activeEvent.id} requested manual review`,
      });
      setReviewReceipt({
        runId: response.run_id,
        reviewId: response.review_id,
        status: response.status,
      });
    } catch (cause) {
      if (cause instanceof ApiError) {
        setReviewError(cause.responseBody ?? cause.message);
      } else if (cause instanceof Error) {
        setReviewError(cause.message);
      } else {
        setReviewError("登记复核请求失败");
      }
    } finally {
      setReviewPending(false);
    }
  }

  return (
    <div className="finance-page-shell">
      <div className="flex min-h-full flex-col gap-4">
        <FACard
          title="主线详情"
          eyebrow="事件流"
          accent="brand"
          action={
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={refetch}
                className="inline-flex items-center gap-1.5 rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-card-inner)] px-3 py-1.5 text-[11px] font-semibold text-[var(--fg-2)]"
              >
                <RefreshCw size={12} />
                刷新
              </button>
              <button
                type="button"
                onClick={() => void requestReview()}
                disabled={reviewPending}
                className="inline-flex items-center gap-1.5 rounded-[var(--radius-md)] border border-[var(--warn-border)] bg-[var(--warn-soft)] px-3 py-1.5 text-[11px] font-semibold text-[var(--warn)] disabled:cursor-not-allowed disabled:opacity-60"
              >
                {reviewPending ? <Loader2 size={12} className="animate-spin" /> : <ShieldAlert size={12} />}
                登记复核
              </button>
            </div>
          }
          bodyClassName="space-y-3"
        >
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0 flex-1 space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <Link to="/event-flow" className="text-[11px] font-semibold text-[var(--brand-hover)] hover:text-[var(--brand)]">
                  返回事件流
                </Link>
                <FAStatusPill tone={toTone(translateEventFlowValue(activeEvent.pricing ?? "未标注"))}>{translateEventFlowValue(activeEvent.pricing ?? "未标注")}</FAStatusPill>
                <FAStatusPill tone={riskTone(activeEvent.risk_level)}>{translateEventFlowValue(activeEvent.risk_level ?? "unknown")}</FAStatusPill>
              </div>
              <div className="space-y-1">
                <div className="text-[16px] font-semibold leading-7 text-[var(--fg-1)]">{headerTitle.lead}</div>
                {headerTitle.subline ? (
                  <div className="text-[11px] leading-5 text-[var(--fg-4)]">{headerTitle.subline}</div>
                ) : null}
              </div>
              <div className="line-clamp-2 text-[12px] leading-6 text-[var(--fg-3)]">
                {activeEvent.desc || "当前事件暂无更多正文说明。"}
              </div>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2 text-[10px] leading-5 text-[var(--fg-4)]">
            <FASourceTraceBadge source={formatDateTime(data.updated_at)} status="updated_at" tone="info" />
            <FASourceTraceBadge source={pageSource} status="data_source" tone="dim" />
            <FASourceTraceBadge source={eventSource} status="来源" tone="info" />
            {activeEvent.assets ? <FASourceTraceBadge source={activeEvent.assets} status="asset" tone="neutral" /> : null}
          </div>

          <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-6">
            {headerMetrics.map((item) => (
              <div
                key={item.label}
                className="rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2.5 py-2"
              >
                <div className="text-[9px] font-semibold text-[var(--fg-5)]">{item.label}</div>
                <div className="mt-1 text-[11px] font-semibold leading-5 text-[var(--fg-2)]">{item.value}</div>
              </div>
            ))}
          </div>

          {reviewReceipt ? (
            <div className="rounded-[var(--radius-sm)] border border-[var(--warn-border)] bg-[var(--warn-soft)] px-3 py-2 text-[11px] leading-5 text-[var(--fg-2)]">
              已登记复核：{translateEventFlowValue(reviewReceipt.status)} · 运行 {reviewReceipt.runId ?? "—"} · 复核 {reviewReceipt.reviewId ?? "—"}
            </div>
          ) : null}
          {reviewError ? (
            <div className="rounded-[var(--radius-sm)] border border-[var(--down-border)] bg-[var(--down-soft)] px-3 py-2 text-[11px] leading-5 text-[var(--down)]">
              {reviewError}
            </div>
          ) : null}
        </FACard>

        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
          <div className="space-y-4">
            <EventChainAnalysis chain={data.chain} activeEvent={activeEvent} />

            <FACard
              title={
                <div className="flex items-center gap-2">
                  <Activity size={12} className="text-[var(--brand-hover)]" />
                  <span>事件事实</span>
                </div>
              }
              eyebrow="事件事实"
              accent="brand"
            >
              <div className="grid gap-4 lg:grid-cols-[minmax(0,1.15fr)_minmax(0,0.85fr)]">
                <div className="space-y-2">
                  <div className="text-[11px] font-semibold text-[var(--fg-3)]">事实摘要</div>
                  <div className="text-[12px] leading-6 text-[var(--fg-2)]">{activeEvent.desc || "当前事件暂无更多事实摘要。"}</div>
                  <dl className="grid gap-x-3 gap-y-2 text-[11px] text-[var(--fg-4)] sm:grid-cols-2">
                    <div className="min-w-0">
                      <dt className="text-[var(--fg-5)]">来源</dt>
                      <dd className="mt-0.5 text-[var(--fg-2)]">{formatEventFlowSourceLabel(activeEvent.source ?? "—", 24).text}</dd>
                    </div>
                    <div className="min-w-0">
                      <dt className="text-[var(--fg-5)]">影响方向</dt>
                      <dd className="mt-0.5 text-[var(--fg-2)]">{translateEventFlowValue(activeEvent.impact)}</dd>
                    </div>
                    <div className="min-w-0">
                      <dt className="text-[var(--fg-5)]">资产</dt>
                      <dd className="mt-0.5 text-[var(--fg-2)]">{activeEvent.assets ?? "—"}</dd>
                    </div>
                    <div className="min-w-0">
                      <dt className="text-[var(--fg-5)]">事件分类</dt>
                      <dd className="mt-0.5 text-[var(--fg-2)]">{translateEventFlowValue(activeEvent.event_kind ?? activeEvent.raw_event_type ?? "—")}</dd>
                    </div>
                  </dl>
                </div>
                <div className="space-y-2 border-t border-[var(--border-faint)] pt-4 lg:border-l lg:border-t-0 lg:pl-4 lg:pt-0">
                  <div className="text-[11px] font-semibold text-[var(--fg-3)]">链路备注</div>
                  <div className="text-[12px] leading-6 text-[var(--fg-2)]">
                    当前详情页仅保留已落库的事件事实、快讯摘要、来源引用与关联报告，避免把未验证的行情推断写成结论。
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {activeEvent.verification_status ? <FAStatusPill tone="info">{translateEventFlowValue(activeEvent.verification_status)}</FAStatusPill> : null}
                    {activeEvent.event_kind ? <FAStatusPill tone="dim">{translateEventFlowValue(activeEvent.event_kind)}</FAStatusPill> : null}
                    {activeEvent.raw_event_type ? <FAStatusPill tone="dim">{translateEventFlowValue(activeEvent.raw_event_type)}</FAStatusPill> : null}
                  </div>
                </div>
              </div>
            </FACard>

            <EventFlowReportInputsPanel
              briefSummary={data.brief_summary}
              articleBriefs={data.article_briefs}
              reportInputItems={data.report_input_items ?? []}
              sourceRefs={data.source_refs ?? []}
              showBriefSummaryCard={false}
            />

            {relatedBriefs.length > 0 ? <EventRelatedBriefsCard briefs={relatedBriefs} feishuMonitorDate={feishuMonitorDate} /> : null}
            <EventFlowSourceRefsCard eventRefs={eventRefs} briefRefs={briefRefs} pageRefs={pageRefs} />
            <EventRelatedReportsCard
              reports={relatedReports}
              isLoading={railLoading}
              error={railError}
              onOpen={(report) => {
                const detailId = getReportDetailId(report);
                if (detailId) navigate(`/reports/${encodeURIComponent(detailId)}`);
              }}
            />

            <EventTable table={relatedRows} />
          </div>

          <aside className="space-y-4">
            <MarketValidationPlaceholder activeEvent={activeEvent} sourceRefs={evidenceRefs} />
            <RiskRadar radar={data.radar} />
            <ImpactAssets table={relatedRows} />
          </aside>
        </div>
      </div>
    </div>
  );
}

export default EventFlowDetailPage;
