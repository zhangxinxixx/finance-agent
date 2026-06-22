import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ArrowRight, ChevronDown, ChevronRight, ExternalLink, RefreshCw } from "lucide-react";
import { fetchEventFlowOverviewView } from "@/adapters/eventFlow";
import { fetchFeishuJin10MessageMonitorDates } from "@/adapters/feishuMonitor";
import { findBestEventIdForBrief } from "@/components/event-flow/eventFlowMatching";
import { useFeishuMonitor } from "@/hooks/useFeishuMonitor";
import { useReports } from "@/hooks/useReports";
import { CATEGORY_MAP, getReportDetailId } from "@/components/reports/reportListMeta";
import { FACard } from "@/components/shared/FACard";
import { FAEmptyState } from "@/components/shared/FAEmptyState";
import { FAFilterBar } from "@/components/shared/FAFilterBar";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import type { FeishuMonitorArticleBrief, FeishuMonitorMessage } from "@/types/feishu-monitor";
import type { EventFlowTimelineItem, Jin10ArticleBrief, Jin10ArticleBriefBundle } from "@/types/event-flow";
import type { ReportIndexItem } from "@/types/reports";

type MonitorFilterKey = "all" | "high_value" | "flash" | "article" | "triggered" | "brief" | "task" | "blocked";

function isIsoDate(value: string | null): value is string {
  return typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value);
}

function compactTime(value?: string | null): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value.slice(0, 16);
  return parsed.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function normalizeStatus(value?: string | null): string {
  return String(value ?? "").trim().toLowerCase();
}

function statusTone(value?: string | null) {
  const normalized = normalizeStatus(value);
  if (normalized.includes("high") || normalized.includes("success") || normalized.includes("queued")) return "up" as const;
  if (normalized.includes("vip") || normalized.includes("block") || normalized.includes("partial")) return "warn" as const;
  if (normalized.includes("fail")) return "down" as const;
  return "neutral" as const;
}

function displayFilterStatus(value?: string | null): string {
  switch (normalizeStatus(value)) {
    case "high_value":
      return "高价值";
    case "candidate":
      return "候选";
    default:
      return value?.trim() || "未知";
  }
}

function displayContentKind(value?: string | null): string {
  switch (normalizeStatus(value)) {
    case "flash":
      return "快讯";
    case "article":
      return "文章";
    default:
      return value?.trim() || "未分类";
  }
}

function contentKindRank(value?: string | null): number {
  switch (normalizeStatus(value)) {
    case "article":
      return 0;
    case "flash":
      return 1;
    default:
      return 2;
  }
}

function publishedAtValue(value?: string | null): number {
  if (!value) return 0;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function articlePriorityScore(message: FeishuMonitorMessage): number {
  let score = 0;
  if (message.article_brief) score += 100;
  score += Math.min((message.report_tags ?? []).filter(Boolean).length, 2) * 20;
  if (message.trigger) score += 12;
  if (message.task) score += 8;
  if (normalizeStatus(message.filter_status) === "high_value") score += 4;
  return score;
}

function sortMessagesWithinGroup(kind: string, items: FeishuMonitorMessage[]): FeishuMonitorMessage[] {
  const copied = [...items];
  if (kind !== "article") {
    return copied;
  }

  return copied.sort((left, right) => {
    const scoreDelta = articlePriorityScore(right) - articlePriorityScore(left);
    if (scoreDelta !== 0) return scoreDelta;
    return publishedAtValue(right.published_at) - publishedAtValue(left.published_at);
  });
}

function displayAccessStatus(value?: string | null): string {
  switch (normalizeStatus(value)) {
    case "readable":
      return "可读";
    case "vip_locked":
      return "VIP受限";
    case "javascript_required":
      return "需浏览器补抓";
    default:
      return value?.trim() || "未知";
  }
}

function displayPipelineStatus(value?: string | null): string {
  switch (normalizeStatus(value)) {
    case "queued":
      return "已排队";
    case "pending":
      return "待处理";
    case "blocked":
      return "已阻塞";
    case "success":
      return "已完成";
    case "failed":
      return "失败";
    default:
      return value?.trim() || "未知";
  }
}

function labelForFilter(filterKey: MonitorFilterKey): string {
  switch (filterKey) {
    case "high_value":
      return "高价值";
    case "flash":
      return "快讯";
    case "article":
      return "文章";
    case "triggered":
      return "已触发";
    case "brief":
      return "有简报";
    case "task":
      return "有任务";
    case "blocked":
      return "已阻塞";
    case "all":
    default:
      return "全部";
  }
}

function getTaskRunId(message: FeishuMonitorMessage): string | null {
  const runId = message.task?.run_id?.trim();
  return runId && runId.length > 0 ? runId : null;
}

function messageTitle(message: FeishuMonitorMessage): string {
  return message.title?.trim() || message.summary?.trim() || message.primary_url || message.message_id;
}

function messageSummary(message: FeishuMonitorMessage): string | null {
  const briefSummary = message.article_brief?.analysis_summary?.trim();
  if (briefSummary) {
    return briefSummary;
  }
  const title = messageTitle(message);
  const summary = message.summary?.trim();
  if (!summary) return null;
  return summary === title ? null : summary;
}

function normalizeInlineText(value?: string | null): string | null {
  if (!value) return null;
  const normalized = value
    .replace(/\s+/g, " ")
    .replace(/&nbsp;/gi, " ")
    .trim();
  return normalized.length > 0 ? normalized : null;
}

function truncateText(value: string | null, limit: number): string | null {
  if (!value) return null;
  if (value.length <= limit) return value;
  return `${value.slice(0, Math.max(0, limit)).trim()}...`;
}

function messageExcerpt(message: FeishuMonitorMessage): string | null {
  const excerpt = normalizeInlineText(message.article_brief?.original_excerpt);
  if (!excerpt) return null;
  const title = normalizeInlineText(messageTitle(message));
  const summary = normalizeInlineText(messageSummary(message));
  if (excerpt === title || excerpt === summary) return null;
  return truncateText(excerpt, 180);
}

function messageKeyPoints(message: FeishuMonitorMessage): string[] {
  return (message.article_brief?.key_points ?? [])
    .map((item) => normalizeInlineText(item))
    .filter((item): item is string => Boolean(item))
    .slice(0, 2);
}

function briefForEventFlowMatch(brief: FeishuMonitorArticleBrief | null | undefined): Jin10ArticleBrief | null {
  const briefId = brief?.brief_id?.trim();
  const headline = brief?.headline?.trim();
  const sourceUrl = brief?.source_url?.trim() || brief?.final_url?.trim();
  const accessStatus = brief?.access_status?.trim();
  if (!briefId || !headline || !sourceUrl || !accessStatus) return null;

  return {
    brief_id: briefId,
    article_class: brief?.article_class?.trim() || "unknown",
    display_bucket: brief?.display_bucket?.trim() || "未分类",
    headline,
    source_url: sourceUrl,
    final_url: brief?.final_url?.trim() || null,
    access_status: accessStatus,
    original_excerpt: brief?.original_excerpt?.trim() || "",
    key_points: brief?.key_points ?? [],
    analysis_summary: brief?.analysis_summary?.trim() || "",
    asset_tags: brief?.asset_tags ?? [],
    topic_tags: brief?.topic_tags ?? [],
    suggested_actions: brief?.suggested_actions ?? [],
    source_refs: brief?.source_refs,
    detail_artifacts: brief?.detail_artifacts ?? undefined,
    data_quality: undefined,
    created_at: brief?.created_at ?? null,
  };
}

function eventFlowTarget(message: FeishuMonitorMessage, timeline: EventFlowTimelineItem[]): string | null {
  const briefId = message.article_brief?.brief_id?.trim();
  if (!briefId) return null;
  const brief = briefForEventFlowMatch(message.article_brief);
  const matchedEventId = brief ? findBestEventIdForBrief(brief, timeline) : null;
  const targetId = matchedEventId || `brief_${briefId}`;
  return `/event-flow/${encodeURIComponent(targetId)}?briefId=${encodeURIComponent(briefId)}`;
}

function briefChainTarget(message: FeishuMonitorMessage, timeline: EventFlowTimelineItem[]): string | null {
  const detailTarget = eventFlowTarget(message, timeline);
  if (detailTarget) return detailTarget;

  const kind = normalizeStatus(message.content_kind);
  const status = normalizeStatus(message.filter_status);
  const hasFollowUpChain = kind === "article" || status === "high_value" || Boolean(message.trigger?.run_id);
  return hasFollowUpChain ? "/event-flow?tab=inputs" : null;
}

function reportChainTarget(message: FeishuMonitorMessage, relatedReport: ReportIndexItem | null): { href: string; label: string } | null {
  const report = relatedReport;
  if (report) {
    const relatedReportId = getReportDetailId(report);
    if (relatedReportId) {
      return {
        href: `/reports/${encodeURIComponent(relatedReportId)}`,
        label: CATEGORY_MAP[report.type]?.label ?? report.type,
      };
    }
  }

  const runId = message.trigger?.run_id?.trim();
  if (!runId) return null;
  return {
    href: `/reports/${encodeURIComponent(runId)}`,
    label: "关联报告",
  };
}

function reportIntentHint(message: FeishuMonitorMessage): "daily" | "weekly" | "options" | null {
  const articleClass = normalizeStatus(message.article_brief?.article_class);
  const displayBucket = normalizeInlineText(message.article_brief?.display_bucket)?.toLowerCase() ?? "";
  const sourceUrl = (message.article_brief?.source_url ?? message.article_brief?.final_url ?? message.primary_url ?? "").toLowerCase();
  const text = [
    message.title ?? "",
    message.summary ?? "",
    message.article_brief?.headline ?? "",
    message.article_brief?.display_bucket ?? "",
    message.article_brief?.article_class ?? "",
    ...(message.article_brief?.asset_tags ?? []),
    ...(message.article_brief?.topic_tags ?? []),
  ]
    .join(" ")
    .toLowerCase();
  const hasStructuredBrief = Boolean(
    message.article_brief?.brief_id ||
      message.article_brief?.headline ||
      message.article_brief?.analysis_summary ||
      message.article_brief?.display_bucket ||
      message.article_brief?.article_class,
  );
  const hasOptionsTerm =
    text.includes("cme") ||
    text.includes("gamma") ||
    text.includes("期权") ||
    text.includes("call") ||
    text.includes("put") ||
    text.includes("周末规则");
  const hasMetalsOptionsContext =
    text.includes("黄金") ||
    text.includes("白银") ||
    text.includes("xau") ||
    text.includes("gold") ||
    text.includes("silver") ||
    text.includes("comex") ||
    text.includes("cme");
  const hasOptionsStructureSignal =
    text.includes("增仓") ||
    text.includes("增持") ||
    text.includes("持仓") ||
    text.includes("期权墙") ||
    text.includes("波动率") ||
    text.includes("隐波") ||
    text.includes("gex") ||
    text.includes("gamma");

  if (articleClass === "flash_news" || displayBucket.includes("快讯") || sourceUrl.includes("flash.jin10.com")) {
    return null;
  }
  if (text.includes("周报") || text.includes("周末") || text.includes("大师复盘")) return "weekly";
  if (hasOptionsTerm && ((hasMetalsOptionsContext && hasOptionsStructureSignal) || text.includes("cme") || text.includes("comex"))) {
    return "options";
  }
  if (
    hasStructuredBrief &&
    articleClass.includes("market_reference") ||
    (hasStructuredBrief && displayBucket.includes("重点分析")) ||
    (hasStructuredBrief && displayBucket.includes("黄金观察")) ||
    (hasStructuredBrief && displayBucket.includes("vip预览")) ||
    (hasStructuredBrief && sourceUrl.includes("xnews.jin10.com")) ||
    (hasStructuredBrief && sourceUrl.includes("vip_column"))
  ) {
    return "daily";
  }
  return null;
}

function findRelatedReport(
  message: FeishuMonitorMessage,
  reports: ReportIndexItem[],
  tradeDate: string,
): ReportIndexItem | null {
  const hint = reportIntentHint(message);
  if (!hint) return null;
  const assetTags = (message.article_brief?.asset_tags ?? []).map((item) => item.toLowerCase());
  const goldRelated =
    assetTags.some((item) => item.includes("xau") || item.includes("gold")) ||
    ["title", "summary"].some((key) => String(message[key as keyof FeishuMonitorMessage] ?? "").toLowerCase().includes("黄金"));

  const scored = reports
    .filter((report) => report.available && report.trade_date === tradeDate)
    .map((report) => {
      let score = 0;
      if (hint === "daily" && report.type === "jin10_daily_report") score += 8;
      if (hint === "weekly" && report.type === "jin10_weekly_report") score += 8;
      if (hint === "options" && report.type === "options_report") score += 8;
      if (hint !== "options" && report.type === "options_report") score -= 4;
      if (hint !== "weekly" && report.type === "jin10_weekly_report") score -= 3;
      if (goldRelated && report.type === "options_report") score += 2;

      return { report, score };
    })
    .filter((item) => item.score >= 6)
    .sort((a, b) => b.score - a.score);

  return scored[0]?.report ?? null;
}

function messageExternalUrl(message: FeishuMonitorMessage): string | null {
  return message.article_brief?.final_url?.trim() || message.primary_url?.trim() || null;
}

function taskStatusLabel(message: FeishuMonitorMessage): string | null {
  const task = message.task;
  if (!task) return null;
  return task.blocked_reason?.trim() || task.current_stage?.trim() || task.status?.trim() || "已建任务";
}

function matchesFilter(message: FeishuMonitorMessage, filterKey: MonitorFilterKey): boolean {
  if (filterKey === "all") return true;
  if (filterKey === "high_value") return normalizeStatus(message.filter_status) === "high_value";
  if (filterKey === "flash") return normalizeStatus(message.content_kind) === "flash";
  if (filterKey === "article") return normalizeStatus(message.content_kind) === "article";
  if (filterKey === "triggered") return Boolean(message.trigger?.status || message.trigger?.run_id);
  if (filterKey === "brief") return Boolean(message.article_brief?.headline || message.article_brief?.access_status);
  if (filterKey === "task") return Boolean(message.task?.run_id || message.task?.status || message.task?.current_stage);
  if (filterKey === "blocked") return Boolean(message.blocked || message.task?.blocked || message.task?.blocked_reason);
  return true;
}

function MessageCard({
  message,
  eventFlowTimeline,
  relatedReport,
}: {
  message: FeishuMonitorMessage;
  eventFlowTimeline: EventFlowTimelineItem[];
  relatedReport: ReportIndexItem | null;
}) {
  const title = messageTitle(message);
  const summary = messageSummary(message);
  const excerpt = messageExcerpt(message);
  const keyPoints = messageKeyPoints(message);
  const taskRunId = getTaskRunId(message);
  const externalUrl = messageExternalUrl(message);
  const taskLabel = taskStatusLabel(message);
  const briefTarget = briefChainTarget(message, eventFlowTimeline);
  const displayBucket = message.article_brief?.display_bucket?.trim();
  const accessStatus = message.article_brief?.access_status?.trim();
  const assetTags = (message.article_brief?.asset_tags ?? []).filter(Boolean).slice(0, 3);
  const reportTags = (message.report_tags ?? []).filter(Boolean).slice(0, 2);
  const contentKind = normalizeStatus(message.content_kind);
  const reportTarget = reportChainTarget(message, relatedReport);

  return (
    <article className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-3 py-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <FAStatusPill tone={statusTone(message.filter_status)}>{displayFilterStatus(message.filter_status)}</FAStatusPill>
            {contentKind && contentKind !== "unknown" ? (
              <FAStatusPill tone={contentKind === "flash" ? "neutral" : "info"}>{displayContentKind(message.content_kind)}</FAStatusPill>
            ) : null}
            {message.trigger?.status ? <FAStatusPill tone={statusTone(message.trigger.status)}>{displayPipelineStatus(message.trigger.status)}</FAStatusPill> : null}
            {reportTags.map((tag) => (
              <FAStatusPill key={`${message.message_id}-${tag}`} tone="info">
                {tag}
              </FAStatusPill>
            ))}
            {displayBucket ? <FAStatusPill tone="info">{displayBucket}</FAStatusPill> : null}
            {accessStatus ? <FAStatusPill tone={statusTone(accessStatus)}>{displayAccessStatus(accessStatus)}</FAStatusPill> : null}
            {message.task?.blocked ? <FAStatusPill tone="warn">阻塞</FAStatusPill> : null}
          </div>
          <div className="mt-2 text-[12px] font-semibold leading-5 text-[var(--fg-1)]">{title}</div>
          {summary ? <div className="mt-1 text-[11px] leading-5 text-[var(--fg-3)]">{summary}</div> : null}
          {excerpt ? (
            <div className="mt-2 rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-panel)] px-2.5 py-2 text-[10px] leading-5 text-[var(--fg-4)]">
              <span className="mr-1 font-semibold text-[var(--fg-5)]">原文摘录</span>
              {excerpt}
            </div>
          ) : null}
          {keyPoints.length > 0 ? (
            <ul className="mt-2 grid gap-1 text-[10px] leading-5 text-[var(--fg-3)]">
              {keyPoints.map((point) => (
                <li key={`${message.message_id}-${point}`} className="flex gap-2">
                  <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-[var(--fg-5)]" />
                  <span>{point}</span>
                </li>
              ))}
            </ul>
          ) : null}
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[10px] leading-5 text-[var(--fg-4)]">
            <span>发布时间：{compactTime(message.published_at)}</span>
            {message.source_marker ? <span>来源：{message.source_marker}</span> : null}
            {taskLabel ? <span>任务：{taskLabel}</span> : null}
            {assetTags.length > 0 ? <span>资产：{assetTags.join(" / ")}</span> : null}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {briefTarget ? (
            <Link
              to={briefTarget}
              className="inline-flex h-8 items-center gap-1.5 rounded-[var(--radius-sm)] border border-[var(--border)] px-2.5 text-[10px] font-semibold text-[var(--fg-3)] transition-colors hover:border-[var(--border-strong)] hover:text-[var(--fg-2)]"
              title="打开简报/报告输入链路"
            >
              <span>简报</span>
              <ArrowRight size={12} />
            </Link>
          ) : null}
          {reportTarget ? (
            <Link
              to={reportTarget.href}
              className="inline-flex h-8 items-center gap-1.5 rounded-[var(--radius-sm)] border border-[var(--border)] px-2.5 text-[10px] font-semibold text-[var(--fg-3)] transition-colors hover:border-[var(--border-strong)] hover:text-[var(--fg-2)]"
              title={reportTarget.label}
            >
              <span>报告</span>
              <ArrowRight size={12} />
            </Link>
          ) : null}
          {externalUrl ? (
            <a
              href={externalUrl}
              target="_blank"
              rel="noreferrer"
              className="inline-flex h-8 w-8 items-center justify-center rounded-[var(--radius-sm)] border border-[var(--border)] text-[var(--fg-4)] transition-colors hover:border-[var(--border-strong)] hover:text-[var(--fg-2)]"
              title="打开来源链接"
            >
              <ExternalLink size={14} />
            </a>
          ) : null}
          {taskRunId ? (
            <Link
              to={`/agent-tasks/${encodeURIComponent(taskRunId)}`}
              className="rounded-[var(--radius-sm)] border border-[var(--border)] px-2.5 py-1 text-[10px] font-semibold text-[var(--fg-3)] transition-colors hover:border-[var(--border-strong)] hover:text-[var(--fg-2)]"
            >
              任务
            </Link>
          ) : null}
        </div>
      </div>
    </article>
  );
}

export function FeishuMonitorPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedDate = searchParams.get("date");
  const hasExplicitDate = isIsoDate(requestedDate);
  const initialDate = hasExplicitDate ? requestedDate : null;
  const { date, payload, loading, error, refresh, setDate } = useFeishuMonitor(initialDate, { preferLatest: !hasExplicitDate });
  const { indexItems: reportIndexItems } = useReports();
  const [filterKey, setFilterKey] = useState<MonitorFilterKey>("all");
  const [eventFlowTimeline, setEventFlowTimeline] = useState<EventFlowTimelineItem[]>([]);
  const [eventFlowBundle, setEventFlowBundle] = useState<Jin10ArticleBriefBundle | null>(null);
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(() => new Set(["flash"]));
  const [availableDates, setAvailableDates] = useState<string[]>([]);
  const [datesLoading, setDatesLoading] = useState(true);

  function handleDateChange(nextDate: string) {
    if (!isIsoDate(nextDate)) return;
    setDate(nextDate);
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      next.set("date", nextDate);
      return next;
    });
  }

  function handleViewLatest() {
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      next.delete("date");
      return next;
    });
  }

  useEffect(() => {
    let cancelled = false;

    async function loadAvailableDates() {
      setDatesLoading(true);
      try {
        const dates = await fetchFeishuJin10MessageMonitorDates();
        if (!cancelled) {
          setAvailableDates(dates);
        }
      } catch {
        if (!cancelled) {
          setAvailableDates([]);
        }
      } finally {
        if (!cancelled) {
          setDatesLoading(false);
        }
      }
    }

    async function loadEventFlowTargets() {
      try {
        const view = await fetchEventFlowOverviewView();
        if (cancelled) return;
        setEventFlowTimeline(view.timeline ?? []);
        setEventFlowBundle(view.article_briefs ?? null);
      } catch {
        if (cancelled) return;
        setEventFlowTimeline([]);
        setEventFlowBundle(null);
      }
    }

    void loadAvailableDates();
    void loadEventFlowTargets();

    return () => {
      cancelled = true;
    };
  }, []);

  const matchingEventFlowTimeline = eventFlowBundle?.date === date ? eventFlowTimeline : [];

  const messages = payload?.messages ?? [];
  const visibleMessages = useMemo(() => messages.filter((message) => matchesFilter(message, filterKey)), [messages, filterKey]);
  const groupedVisibleMessages = useMemo(() => {
    const groups = new Map<string, FeishuMonitorMessage[]>();
    for (const message of visibleMessages) {
      const key = normalizeStatus(message.content_kind) || "unknown";
      const existing = groups.get(key);
      if (existing) {
        existing.push(message);
      } else {
        groups.set(key, [message]);
      }
    }

    return Array.from(groups.entries())
      .sort((a, b) => contentKindRank(a[0]) - contentKindRank(b[0]))
      .map(([key, items]) => ({
        key,
        label: displayContentKind(key),
        messages: sortMessagesWithinGroup(key, items),
      }));
  }, [visibleMessages]);

  useEffect(() => {
    if (filterKey !== "flash") {
      return;
    }
    setCollapsedGroups((current) => {
      if (!current.has("flash")) {
        return current;
      }
      const next = new Set(current);
      next.delete("flash");
      return next;
    });
  }, [filterKey]);

  useEffect(() => {
    setCollapsedGroups((current) => {
      let changed = false;
      const visibleKeys = new Set(groupedVisibleMessages.map((group) => group.key));
      const next = new Set<string>();
      for (const key of current) {
        if (visibleKeys.has(key)) {
          next.add(key);
        } else {
          changed = true;
        }
      }
      return changed ? next : current;
    });
  }, [groupedVisibleMessages]);
  const filterCounts = useMemo(() => {
    return messages.reduce(
      (acc, message) => {
        acc.all += 1;
        if (matchesFilter(message, "high_value")) acc.high_value += 1;
        if (matchesFilter(message, "flash")) acc.flash += 1;
        if (matchesFilter(message, "article")) acc.article += 1;
        if (matchesFilter(message, "triggered")) acc.triggered += 1;
        if (matchesFilter(message, "brief")) acc.brief += 1;
        if (matchesFilter(message, "task")) acc.task += 1;
        if (matchesFilter(message, "blocked")) acc.blocked += 1;
        return acc;
      },
      { all: 0, high_value: 0, flash: 0, article: 0, triggered: 0, brief: 0, task: 0, blocked: 0 },
    );
  }, [messages]);

  const filterOptions: Array<{ key: MonitorFilterKey; label: string; count: number }> = [
    { key: "all", label: "全部", count: filterCounts.all },
    { key: "high_value", label: "高价值", count: filterCounts.high_value },
    { key: "flash", label: "快讯", count: filterCounts.flash },
    { key: "article", label: "文章", count: filterCounts.article },
    { key: "triggered", label: "已触发", count: filterCounts.triggered },
    { key: "brief", label: "有简报", count: filterCounts.brief },
    { key: "task", label: "有任务", count: filterCounts.task },
    { key: "blocked", label: "已阻塞", count: filterCounts.blocked },
  ];
  const availableDateOptions = useMemo(() => {
    if (availableDates.includes(date)) {
      return availableDates;
    }
    return [date, ...availableDates];
  }, [availableDates, date]);

  return (
    <div className="finance-page-shell space-y-3">
      <div className="grid gap-3">
        <FACard
          title="消息清单"
          eyebrow="每日消息"
          accent="brand"
          action={
            <div className="flex flex-wrap items-end justify-end gap-2">
              <label className="flex flex-col gap-0.5">
                <span className="text-[8px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">日期筛选</span>
                <select
                  value={date}
                  onChange={(event) => handleDateChange(event.target.value)}
                  disabled={datesLoading || availableDateOptions.length === 0}
                  className="h-[28px] min-w-[132px] rounded-[var(--radius-sm)] border border-[var(--border)] bg-[var(--bg-card-inner)] px-2.5 text-[11px] text-[var(--fg-2)] outline-none transition-colors hover:border-[var(--border-strong)]"
                >
                  {availableDateOptions.map((optionDate) => (
                    <option key={optionDate} value={optionDate}>
                      {optionDate}
                    </option>
                  ))}
                </select>
              </label>
              {hasExplicitDate ? (
                <button
                  type="button"
                  onClick={handleViewLatest}
                  className="inline-flex h-8 items-center rounded-[var(--radius-sm)] border border-[var(--border)] bg-[var(--bg-card-inner)] px-3 text-[11px] font-semibold text-[var(--fg-3)] transition-colors hover:border-[var(--border-strong)] hover:text-[var(--fg-2)]"
                >
                  查看最新
                </button>
              ) : null}
              <button
                type="button"
                onClick={refresh}
                className="inline-flex h-8 items-center gap-1.5 rounded-[var(--radius-sm)] border border-[var(--border)] bg-[var(--bg-card-inner)] px-3 text-[11px] font-semibold text-[var(--fg-2)] transition-colors hover:border-[var(--border-strong)]"
              >
                <RefreshCw size={12} />
                刷新
              </button>
              <Link
                to="/data-sources/jin10_feishu"
                className="inline-flex h-8 items-center rounded-[var(--radius-sm)] border border-[var(--border)] px-3 text-[11px] font-semibold text-[var(--fg-3)]"
              >
                数据源详情
              </Link>
            </div>
          }
          bodyClassName="space-y-3"
        >
          <div className="border-b border-[var(--border-faint)] pb-3">
            <FAFilterBar
              left={filterOptions.map((option) => {
                const active = filterKey === option.key;
                return (
                  <button
                    key={option.key}
                    type="button"
                    onClick={() => setFilterKey(option.key)}
                    className={`inline-flex items-center gap-1.5 rounded-[var(--radius-pill)] border px-2.5 py-1 text-[10px] font-semibold transition-colors ${
                      active
                        ? "border-[var(--brand-border)] bg-[var(--brand-soft)] text-[var(--brand)]"
                        : "border-[var(--border)] bg-[var(--bg-card-inner)] text-[var(--fg-3)] hover:border-[var(--border-strong)] hover:text-[var(--fg-2)]"
                    }`}
                  >
                    <span>{labelForFilter(option.key)}</span>
                    <span className="font-mono text-[10px] opacity-80">{option.count}</span>
                  </button>
                );
              })}
              right={<div className="text-[11px] text-[var(--fg-4)]">按跟进状态筛选</div>}
            />
          </div>
          {loading && !payload ? (
            <div className="grid gap-3 md:grid-cols-2">
              {Array.from({ length: 4 }).map((_, index) => (
                <div key={index} className="finance-skeleton-card h-28" />
              ))}
            </div>
          ) : visibleMessages.length > 0 ? (
            <div className="space-y-3">
              {groupedVisibleMessages.map((group) => (
                <section key={group.key} className="space-y-2">
                  {(() => {
                    const collapsed = collapsedGroups.has(group.key);
                    const tone = group.key === "article" ? "info" : group.key === "flash" ? "neutral" : "dim";
                    const Icon = collapsed ? ChevronRight : ChevronDown;
                    return (
                      <>
                  <div className="flex items-center justify-between gap-2 border-b border-[var(--border-faint)] pb-1.5">
                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        onClick={() =>
                          setCollapsedGroups((current) => {
                            const next = new Set(current);
                            if (next.has(group.key)) next.delete(group.key);
                            else next.add(group.key);
                            return next;
                          })
                        }
                        className="inline-flex h-6 items-center gap-1.5 rounded-[var(--radius-pill)] border border-[var(--border)] bg-[var(--bg-card-inner)] px-2 text-[10px] font-semibold text-[var(--fg-3)] transition-colors hover:border-[var(--border-strong)] hover:text-[var(--fg-2)]"
                        aria-expanded={!collapsed}
                        aria-label={`${collapsed ? "展开" : "收起"}${group.label}分组`}
                      >
                        <Icon size={12} />
                        <span>{collapsed ? "展开" : "收起"}</span>
                      </button>
                      <FAStatusPill tone={tone}>{group.label}</FAStatusPill>
                      <span className="text-[10px] text-[var(--fg-4)]">
                        {group.key === "article" ? "可进入简报/报告链路" : group.key === "flash" ? "偏即时事件入口" : "未命中类型规则"}
                      </span>
                    </div>
                    <div className="text-[10px] font-mono text-[var(--fg-5)]">{group.messages.length}</div>
                  </div>
                  {!collapsed ? (
                    <div className="space-y-2.5">
                      {group.messages.map((message) => (
                        <MessageCard
                          key={message.message_id}
                          message={message}
                          eventFlowTimeline={matchingEventFlowTimeline}
                          relatedReport={findRelatedReport(message, reportIndexItems, date)}
                        />
                      ))}
                    </div>
                  ) : (
                    <div className="rounded-[var(--radius-sm)] border border-dashed border-[var(--border-faint)] bg-[var(--bg-panel)] px-3 py-2 text-[10px] text-[var(--fg-4)]">
                      当前默认折叠，保留 {group.messages.length} 条 {group.label}。
                    </div>
                  )}
                      </>
                    );
                  })()}
                </section>
              ))}
            </div>
          ) : (
            <FAEmptyState title="当天暂无监控消息" description="当前日期没有命中的飞书监控消息，或当前筛选没有结果。" className="py-8" />
          )}
        </FACard>
      </div>
    </div>
  );
}

export default FeishuMonitorPage;
