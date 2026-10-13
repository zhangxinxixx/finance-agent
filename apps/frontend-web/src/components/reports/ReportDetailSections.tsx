import { ExternalLink } from "lucide-react";
import { Link } from "react-router-dom";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { modelDisplayLabel } from "@/components/llm-audit/llmAuditFormat";
import { formatGoldMainlineLabel, formatGoldNetBiasLabel, goldNetBiasTone, normalizeGoldMainlineId } from "@/components/shared/goldMainlineFormat";
import { getReportDetailStatus, reportFamilyLabel, reportTitleLabel, reviewStatusLabel, statusTone } from "@/components/reports/reportDetailMeta";
import { getDataStatusLabel } from "@/lib/status";
import type { FATabOption } from "@/components/shared/FATabBar";
import type { GoldMainlineRanking } from "@/types/gold-mainlines";
import type { ReportDetailTabKey, ReportDetailView } from "@/types/reports";

function InlineMetaItem({ label, value }: { label: string; value: string }) {
  return (
    <span className="inline-flex min-w-0 items-center gap-1 text-[length:var(--type-caption)] text-[var(--fg-4)]">
      <span className="shrink-0 text-[var(--fg-5)]">{label}</span>
      <span className="max-w-[11rem] truncate font-semibold text-[var(--fg-2)]">{value}</span>
    </span>
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

function formatNullable(value: unknown, fallback = "未记录"): string {
  if (typeof value === "string" && value.trim()) return value.trim();
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return fallback;
}

function formatOptionalCount(value: unknown): string {
  return typeof value === "number" && Number.isFinite(value) ? String(value) : "未提供";
}

function payloadString(value: unknown): string {
  if (typeof value === "string") return value;
  if (value == null) return "";
  try {
    return JSON.stringify(value);
  } catch {
    return "";
  }
}

function formatAuditStatus(value: unknown): string {
  const status = typeof value === "string" ? value : "";
  if (status === "pass" || status === "accepted") return "通过";
  if (status === "needs_review") return "需复核";
  if (status === "missing_assets") return "缺资产";
  if (status === "untracked") return "未归档";
  return status ? "未解释状态（技术值见详情）" : "未知";
}

function auditTone(value: unknown): "info" | "neutral" | "warn" {
  const status = typeof value === "string" ? value : "";
  if (status === "pass" || status === "accepted" || status === "tracked") return "info";
  if (status === "needs_review" || status === "missing_assets" || status === "untracked") return "warn";
  return "neutral";
}

function ReportDetailCompactTabs({
  tabs,
  activeTab,
  onTabChange,
}: {
  tabs: FATabOption<ReportDetailTabKey>[];
  activeTab: ReportDetailTabKey;
  onTabChange: (value: ReportDetailTabKey) => void;
}) {
  if (tabs.length === 0) return null;
  return (
    <div className="flex flex-wrap items-center gap-1" role="group" aria-label="报告内容切换">
      {tabs.map((tab) => {
        const active = tab.value === activeTab;
        return (
          <button
            key={tab.value}
            type="button"
            aria-pressed={active}
            disabled={tab.disabled}
            onClick={() => onTabChange(tab.value)}
            className={`rounded-[var(--radius-md)] border px-2.5 py-1 text-[length:var(--type-caption)] font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
              active
                ? "border-[var(--brand-dim)] bg-[var(--bg-active)] text-[var(--brand-hover)]"
                : "border-[var(--border-faint)] bg-transparent text-[var(--fg-4)] hover:border-[var(--border)] hover:text-[var(--fg-2)]"
            }`}
          >
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}

export function ReportGoldMacroOverviewCard({ data }: { data: ReportDetailView }) {
  const reportType = typeof data.structured_payload?.report_type === "string" ? data.structured_payload.report_type : "";
  const isMarketObservation = data.meta.family === "jin10_market_observation_report" || reportType === "market_observation";
  if (isMarketObservation) return null;
  const overview = data.gold_macro_overview;
  if (!overview) return null;
  const topRankings = [...(overview.theme_rankings ?? [])]
    .sort((left, right) => left.rank - right.rank)
    .slice(0, 3);
  const rankingTotal = overview.theme_rankings?.length ?? 0;
  const pendingVerification = (overview.verification_matrix ?? []).filter((item) => {
    const status = String(item.status ?? "").toLowerCase();
    return status === "pending" || status === "missing" || status === "unverified" || status.includes("needed");
  }).length;

  return (
    <section className="rounded-[var(--radius-lg)] border border-[var(--warn-border)] bg-[var(--warn-soft)]/45 px-3 py-2">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="shrink-0 text-[length:var(--type-caption)] font-semibold uppercase tracking-[0.12em] text-[var(--warn)]">
          黄金主线
        </span>
        <FAStatusPill tone={goldNetBiasTone(overview.net_bias)} dot={false} className="text-[length:var(--type-caption)]">
          {formatGoldNetBiasLabel(overview.net_bias)}
        </FAStatusPill>
        <FAStatusPill tone="info" dot={false} className="text-[length:var(--type-caption)]">
          {formatGoldMainlineLabel(overview.dominant_mainline)}
        </FAStatusPill>
        <p className="min-w-[18rem] flex-1 truncate text-[length:var(--type-caption)] leading-5 text-[var(--fg-3)]">
          {overview.one_line_conclusion || "当前报告关联最新黄金主线总览，用于复核报告结论与宏观主线是否一致。"}
        </p>
        <span className="fa-num rounded-[var(--radius-pill)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2 py-0.5 text-[length:var(--type-caption)] text-[var(--fg-4)]">
          风险 {formatScore(overview.risk_score)}/100
        </span>
        <span className="rounded-[var(--radius-pill)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2 py-0.5 text-[length:var(--type-caption)] text-[var(--fg-4)]">
          待验证 {pendingVerification}
        </span>
        <span className="fa-num text-[length:var(--type-caption)] text-[var(--fg-5)]">{overview.as_of?.slice(0, 10) || "日期未知"}</span>
        <Link
          to="/gold-mainlines"
          className="rounded-[var(--radius-pill)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2 py-0.5 text-[length:var(--type-caption)] font-semibold text-[var(--fg-3)] hover:border-[var(--border)] hover:text-[var(--fg-1)]"
        >
          查看九主线
        </Link>
      </div>
      {topRankings.length > 0 ? (
        <div className="mt-1.5 flex flex-wrap items-center gap-1.5 border-t border-[var(--border-faint)] pt-1.5">
          <span className="shrink-0 text-[length:var(--type-caption)] text-[var(--fg-5)]">排序</span>
          {topRankings.map((item) => (
            <span
              key={`${rankingMainlineId(item) ?? item.label ?? "mainline"}-${item.rank}`}
              className="inline-flex max-w-[16rem] items-center gap-1 rounded-[var(--radius-pill)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2 py-0.5 text-[length:var(--type-caption)] text-[var(--fg-4)]"
              title={item.label || formatGoldMainlineLabel(rankingMainlineId(item))}
            >
              <span className="fa-num text-[var(--fg-5)]">#{item.rank}</span>
              <span className="truncate font-semibold text-[var(--fg-2)]">
                {item.label || formatGoldMainlineLabel(rankingMainlineId(item))}
              </span>
              <span className="text-[var(--fg-5)]">{formatGoldNetBiasLabel(item.direction)}</span>
              <span className="fa-num font-semibold text-[var(--fg-2)]">{formatScore(item.score)}</span>
            </span>
          ))}
        </div>
      ) : null}
      {rankingTotal > topRankings.length ? <p className="mt-1 text-[length:var(--type-caption)] text-[var(--fg-5)]">另有 {rankingTotal - topRankings.length} 条主线排序未在摘要展开。</p> : null}
    </section>
  );
}

export function ReportMarketObservationCard({ data }: { data: ReportDetailView }) {
  const reportType = typeof data.structured_payload?.report_type === "string" ? data.structured_payload.report_type : "";
  const isMarketObservation = data.meta.family === "jin10_market_observation_report" || reportType === "market_observation";
  if (!isMarketObservation) return null;

  const contentText = `${data.meta.title ?? ""} ${payloadString(data.structured_payload)}`;
  const hasOddsTable = /市场赔率|赔率表|odds/i.test(contentText);
  const hasVipObservation = /VIP每日市场观察|每日市场观察|market observation/i.test(contentText);
  const originalUrl = pickOriginalUrl(data);

  return (
    <section className="rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card)] px-3 py-2">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5">
        <span className="shrink-0 text-[length:var(--type-caption)] font-semibold uppercase tracking-[0.12em] text-[var(--fg-4)]">
          市场观察
        </span>
        <FAStatusPill tone="info" dot={false} className="text-[length:var(--type-caption)]">
          辅助证据
        </FAStatusPill>
        <FAStatusPill tone="neutral" dot={false} className="text-[length:var(--type-caption)]">
          单源观察
        </FAStatusPill>
        {hasVipObservation ? (
          <span className="rounded-[var(--radius-pill)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2 py-0.5 text-[length:var(--type-caption)] text-[var(--fg-4)]">
            VIP每日市场观察
          </span>
        ) : null}
        {hasOddsTable ? (
          <span className="rounded-[var(--radius-pill)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2 py-0.5 text-[length:var(--type-caption)] text-[var(--fg-4)]">
            市场赔率表
          </span>
        ) : null}

        <span className="fa-num rounded-[var(--radius-pill)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2 py-0.5 text-[length:var(--type-caption)] text-[var(--fg-4)]">
          {data.meta.trade_date ?? "日期未知"}
        </span>
        <span className="min-w-[14rem] flex-1 truncate text-[length:var(--type-caption)] text-[var(--fg-4)]">
          {reportTitleLabel(data.meta.title)}
        </span>
        {originalUrl ? (
          <a
            href={originalUrl}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 rounded-[var(--radius-pill)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2 py-0.5 text-[length:var(--type-caption)] font-semibold text-[var(--fg-3)] hover:border-[var(--border)] hover:text-[var(--fg-1)]"
          >
            原文
            <ExternalLink size={10} />
          </a>
        ) : null}
      </div>
    </section>
  );
}

export function ReportGenerationTraceCard({
  data,
  onTabChange,
}: {
  data: ReportDetailView;
  onTabChange: (value: ReportDetailTabKey) => void;
}) {
  const trace = data.generation_trace;
  if (!trace) return null;
  const assetAudit = trace.asset_audit;
  const qualityAudit = trace.quality_audit;
  const strategyHandoff = trace.strategy_handoff;
  const semanticStatus = qualityAudit?.semantic_review_status;
  const chartIssueCount = qualityAudit?.chart_text_issue_count ?? 0;
  const chartIssues = qualityAudit?.chart_text_issues ?? [];
  const assetCountIssues = assetAudit?.count_issues ?? [];
  const scenarioCount = strategyHandoff?.scenario_paths?.length;
  const implicationCount = strategyHandoff?.trading_implications?.length;

  return (
    <section className="rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card)] px-3 py-2">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5">
        <span className="shrink-0 text-[length:var(--type-caption)] font-semibold uppercase tracking-[0.12em] text-[var(--fg-4)]">
          生成链
        </span>
        <FAStatusPill tone={trace.llm?.model ? "info" : "warn"} dot={false} className="text-[length:var(--type-caption)]">
          文本模型：{modelDisplayLabel(trace.llm?.model)}
        </FAStatusPill>
        <FAStatusPill tone={auditTone(trace.vlm?.status)} dot={false} className="text-[length:var(--type-caption)]">
          视觉模型：{trace.vlm?.model ? modelDisplayLabel(trace.vlm.model) : formatAuditStatus(trace.vlm?.status)}
        </FAStatusPill>
        {trace.vlm?.vision_layout_status ? (
          <FAStatusPill tone={auditTone(trace.vlm.vision_layout_status === "present" ? "pass" : "needs_review")} dot={false} className="text-[length:var(--type-caption)]">
            图文布局：{formatAuditStatus(trace.vlm.vision_layout_status === "present" ? "pass" : "needs_review")}
          </FAStatusPill>
        ) : null}
        {data.source_refs.length > 0 ? (
          <span className="rounded-[var(--radius-pill)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2 py-0.5 text-[length:var(--type-caption)] text-[var(--fg-4)]">
            来源 {data.source_refs.length}
          </span>
        ) : null}
        <span className="rounded-[var(--radius-pill)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2 py-0.5 text-[length:var(--type-caption)] text-[var(--fg-4)]">
          原图 {trace.source_counts?.original_images ?? "-"}
        </span>
        <FAStatusPill tone={auditTone(assetAudit?.status)} dot={false} className="text-[length:var(--type-caption)]">
          切图 {formatOptionalCount(assetAudit?.figure_files)}/{formatOptionalCount(assetAudit?.chart_image_refs)}
          {typeof assetAudit?.parser_figures_total === "number" ? ` 解析图形 ${assetAudit.parser_figures_total}` : ""} {formatAuditStatus(assetAudit?.status)}
        </FAStatusPill>
        <FAStatusPill tone={auditTone(semanticStatus)} dot={false} className="text-[length:var(--type-caption)]">
          图文语义 {formatAuditStatus(semanticStatus)}{chartIssueCount ? ` ${chartIssueCount}` : ""}
        </FAStatusPill>
        <span className="min-w-[14rem] flex-1 truncate text-[length:var(--type-caption)] text-[var(--fg-4)]">
          后续策略：{formatOptionalCount(scenarioCount)} 条剧本、{formatOptionalCount(implicationCount)} 条操作含义，需进入策略卡/分析输入继续校准。
        </span>
        {data.available_tabs.includes("inputs") ? (
          <button
            type="button"
            onClick={() => onTabChange("inputs")}
            className="rounded-[var(--radius-pill)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2 py-0.5 text-[length:var(--type-caption)] font-semibold text-[var(--fg-3)] hover:border-[var(--border)] hover:text-[var(--fg-1)]"
          >
            分析输入
          </button>
        ) : null}
        {data.available_tabs.includes("evidence") ? (
          <button
            type="button"
            onClick={() => onTabChange("evidence")}
            className="rounded-[var(--radius-pill)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2 py-0.5 text-[length:var(--type-caption)] font-semibold text-[var(--fg-3)] hover:border-[var(--border)] hover:text-[var(--fg-1)]"
          >
            证据包
          </button>
        ) : null}
        <Link
          to="/strategy"
          className="rounded-[var(--radius-pill)] border border-[var(--brand-dim)] bg-[var(--bg-active)] px-2 py-0.5 text-[length:var(--type-caption)] font-semibold text-[var(--brand-hover)]"
        >
          进入策略中心
        </Link>
      </div>
      {trace.vlm?.reason || chartIssues.length > 0 || assetCountIssues.length > 0 ? (
        <div className="mt-1.5 flex flex-wrap items-center gap-1.5 border-t border-[var(--border-faint)] pt-1.5 text-[length:var(--type-caption)] text-[var(--fg-4)]">
          {trace.vlm?.reason ? (
            <span className="rounded-[var(--radius-md)] border border-[var(--warn-border)] bg-[var(--warn-soft)] px-2 py-0.5 font-semibold text-[var(--warn)]">
              {trace.vlm.reason}
            </span>
          ) : null}
          {assetCountIssues.slice(0, 4).map((issue, index) => (
            <span
              key={`${String(issue.code ?? "asset-count")}-${index}`}
              className="inline-flex max-w-[24rem] items-center gap-1 rounded-[var(--radius-md)] border border-[var(--warn-border)] bg-[var(--warn-soft)] px-2 py-0.5 text-[var(--warn)]"
              title={payloadString(issue)}
            >
              <span className="font-semibold">资产数量需复核</span>
            </span>
          ))}
          {chartIssues.slice(0, 4).map((issue) => (
            <span
              key={`${issue.figure_id ?? issue.image_path ?? "chart"}-${issue.text_len ?? 0}`}
              className="inline-flex max-w-[21rem] items-center gap-1 rounded-[var(--radius-md)] border border-[var(--warn-border)] bg-[var(--warn-soft)] px-2 py-0.5 text-[var(--warn)]"
              title={issue.sample ?? undefined}
            >
              <span className="font-semibold">图表文本需复核</span>
              <span className="truncate">{issue.title ?? "标题缺失"}</span>
              <span className="fa-num">{issue.text_len ?? 0}字</span>
            </span>
          ))}
          {chartIssues.length > 4 ? <span>+{chartIssues.length - 4} 项</span> : null}
          {assetCountIssues.length > 4 ? <span>另有 {assetCountIssues.length - 4} 项资产计数问题</span> : null}
        </div>
      ) : null}
    </section>
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
  returnTo = "/reports",
  isRefreshing = false,
  qualificationPending = false,
}: {
  data: ReportDetailView;
  metrics: Array<{ label: string; value: string }>;
  onRefresh: () => void;
  tabs: FATabOption<ReportDetailTabKey>[];
  activeTab: ReportDetailTabKey;
  onTabChange: (value: ReportDetailTabKey) => void;
  summaryChips?: string[];
  returnTo?: string;
  isRefreshing?: boolean;
  qualificationPending?: boolean;
}) {
  const familyLabel = reportFamilyLabel(data.meta.family);
  const titleLabel = reportTitleLabel(data.meta.title);
  const showFamilyLabel = Boolean(familyLabel && titleLabel && familyLabel !== titleLabel);
  const anchorTradeDate =
    typeof data.structured_payload?.anchor_trade_date === "string" ? data.structured_payload.anchor_trade_date : null;
  const isSupplementalReport =
    data.meta.family === "macro_event_followup_supplement" || String(data.meta.title ?? "").includes("宏观事件跟进补充");
  const originalUrl = pickOriginalUrl(data);
  const qualification = getReportDetailStatus(data);
  const observationOnly =
    data.meta.report_identity?.authority === "observation_only" ||
    data.meta.report_identity?.output_mode === "observe";

  return (
    <section className="rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card)] px-3 py-2">
      <div className="grid gap-2 xl:grid-cols-[minmax(0,1fr)_auto] xl:items-center">
        <div className="min-w-0">
          <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
            {showFamilyLabel ? (
              <span className="shrink-0 text-[length:var(--type-caption)] font-semibold text-[var(--fg-4)]">{familyLabel}</span>
            ) : null}
            <h1 className="min-w-[14rem] flex-1 truncate text-[length:var(--type-card-title)] font-semibold leading-tight text-[var(--fg-1)]">
              {titleLabel}
            </h1>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-1.5 xl:justify-end">
          <FAStatusPill tone={statusTone(data.data_status)} className="text-[length:var(--type-caption)]">
            {getDataStatusLabel(data.data_status)}
          </FAStatusPill>
          <FAStatusPill tone="neutral" className="text-[length:var(--type-caption)]">
            {qualificationPending ? "资格待重新核验" : qualification.label}
          </FAStatusPill>
          {!qualificationPending && data.meta.review_status ? (
            <FAStatusPill tone="info" className="text-[length:var(--type-caption)]">
              复核：{reviewStatusLabel(data.meta.review_status)}
            </FAStatusPill>
          ) : null}
          {observationOnly ? (
            <>
              <FAStatusPill tone="warn" className="text-[length:var(--type-caption)]">
                研究观察
              </FAStatusPill>
            </>
          ) : null}
          {originalUrl ? (
            <a
              href={originalUrl}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 rounded-[var(--radius-pill)] border border-[var(--border)] px-2 py-0.5 text-[length:var(--type-caption)] font-semibold text-[var(--fg-3)] transition-colors hover:border-[var(--border-strong)] hover:text-[var(--fg-1)]"
              title="打开原始链接"
            >
              原文
              <ExternalLink size={10} />
            </a>
          ) : null}
          <Link
            to={returnTo}
            className="rounded-[var(--radius-md)] border border-[var(--border)] px-2 py-0.5 text-[length:var(--type-caption)] font-semibold text-[var(--fg-3)]"
          >
            返回报告中心
          </Link>
          <button
            type="button"
            onClick={onRefresh}
            disabled={isRefreshing}
            className="rounded-[var(--radius-md)] border border-[var(--border)] bg-[var(--bg-card-inner)] px-2 py-0.5 text-[length:var(--type-caption)] font-semibold text-[var(--fg-2)]"
          >
            {isRefreshing ? "读取中" : "刷新"}
          </button>
        </div>
      </div>
      <p className="mt-2 text-[length:var(--type-caption)] leading-5 text-[var(--fg-4)]">
        {qualificationPending ? "正文保留上次读取版本；当前发布许可、发布状态和参考有效性待重新核验。" : qualification.description}
      </p>

      <div className="mt-2 flex flex-wrap items-center justify-between gap-x-3 gap-y-2 border-t border-[var(--border-faint)] pt-1.5">
        <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
          {metrics.map((metric) => (
            <InlineMetaItem key={metric.label} label={metric.label} value={metric.value} />
          ))}
          {anchorTradeDate ? (
            <span className="text-[length:var(--type-caption)] text-[var(--fg-4)]">
              锚定 <span className="font-semibold text-[var(--fg-2)]">{anchorTradeDate}</span>
            </span>
          ) : null}
          {isSupplementalReport ? (
            <span className="rounded-[var(--radius-pill)] border border-[var(--warn-border)] bg-[var(--warn-soft)] px-2 py-0.5 text-[length:var(--type-caption)] font-semibold text-[var(--warn)]">
              补充分析
            </span>
          ) : null}
        </div>
        <div className="flex flex-wrap items-center gap-1.5 xl:justify-end">
          <ReportDetailCompactTabs tabs={tabs} activeTab={activeTab} onTabChange={onTabChange} />
          {summaryChips.length > 0 ? (
            <div className="flex flex-wrap items-center gap-1">
              {summaryChips.map((chip) => (
                <span
                  key={chip}
                  className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2 py-0.5 text-[length:var(--type-caption)] text-[var(--fg-4)]"
                >
                  {chip}
                </span>
              ))}
            </div>
          ) : null}
        </div>
      </div>
    </section>
  );
}
