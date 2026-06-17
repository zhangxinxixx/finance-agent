import { useMemo, useState } from "react";
import { ExternalLink, FileStack, Link2, Loader2, MessageSquareWarning, ShieldOff } from "lucide-react";
import { Link } from "react-router-dom";
import { ApiError } from "@/adapters/apiClient";
import { ignoreEventFlowBrief, linkEventFlowBrief, reviewEventFlowEvent } from "@/adapters/eventFlow";
import { FACard } from "@/components/shared/FACard";
import { FAEmptyState } from "@/components/shared/FAEmptyState";
import { FASourceTraceBadge } from "@/components/shared/FASourceTraceBadge";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { formatDateTime } from "@/lib/date";
import { compactSourceLabel, dedupeSourceRefs, normalizeSourceRefs, sourceRefPairs } from "@/lib/sourceRefs";
import type { SourceRef } from "@/types/common";
import type { EventFlowActionResponse, EventFlowTimelineItem, Jin10ArticleBrief, Jin10ArticleBriefBundle } from "@/types/event-flow";
import { articleBriefTone } from "./EventFlowSectionHelpers";
import { findBestEventIdForBrief } from "./eventFlowMatching";

interface EventFlowLiveBriefsPanelProps {
  bundle?: Jin10ArticleBriefBundle | null;
  timeline?: EventFlowTimelineItem[];
  sourceRefs?: SourceRef[];
}

function sourceRefKey(ref: SourceRef): string {
  return [
    ref.source_ref,
    ref.endpoint ?? "",
    ref.artifact_path ?? "",
    ref.snapshot_id ?? "",
    ref.trade_date ?? "",
    ref.run_id ?? "",
  ].join("|");
}

function formatArtifactValue(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (value && typeof value === "object") return JSON.stringify(value);
  return "";
}

function uniqueStrings(values: Array<string | null | undefined>): string[] {
  const seen = new Set<string>();
  const result: string[] = [];

  for (const value of values) {
    if (!value) continue;
    const trimmed = value.trim();
    if (!trimmed || seen.has(trimmed)) continue;
    seen.add(trimmed);
    result.push(trimmed);
  }

  return result;
}

function collectTopLevelArtifactPaths(
  bundle: Jin10ArticleBriefBundle | null | undefined,
  pageRefs: SourceRef[],
  timelineRefs: SourceRef[],
): string[] {
  return uniqueStrings([
    bundle?.artifact_path,
    ...pageRefs.map((ref) => ref.artifact_path),
    ...timelineRefs.map((ref) => ref.artifact_path),
  ]);
}

type BriefActionKind = "link" | "review" | "ignore";

interface ActionButtonProps {
  icon: React.ReactNode;
  label: string;
  pending?: boolean;
  disabled?: boolean;
  title?: string;
  onClick?: () => void;
}

function ActionButton({ icon, label, pending = false, disabled = false, title, onClick }: ActionButtonProps) {
  return (
    <button
      type="button"
      disabled={disabled || pending}
      title={title}
      onClick={onClick}
      className="inline-flex h-7 items-center gap-1.5 rounded-[var(--radius-pill)] border border-[var(--border)] bg-[var(--bg-card-inner)] px-2.5 text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-4)] transition-colors hover:border-[var(--border-strong)] hover:text-[var(--fg-2)] disabled:cursor-not-allowed disabled:opacity-60"
    >
      <span className="text-[var(--fg-5)]">{pending ? <Loader2 size={11} className="animate-spin" /> : icon}</span>
      <span>{label}</span>
      <span className="text-[var(--fg-5)]">{pending ? "提交中" : "动作"}</span>
    </button>
  );
}

function actionSummaryLabel(action: string): string {
  if (action === "link") return "已登记关联请求";
  if (action === "review") return "已登记复核请求";
  if (action === "ignore") return "已登记忽略请求";
  return "已登记动作请求";
}

function actionErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.responseBody ?? error.message;
  }
  if (error instanceof Error) return error.message;
  return "提交动作失败";
}

function BriefActionReceipt({
  receipt,
  matchedEvent,
}: {
  receipt: EventFlowActionResponse;
  matchedEvent: EventFlowTimelineItem | null;
}) {
  return (
    <div className="space-y-2 rounded-[var(--radius-sm)] border border-[var(--warn-border)] bg-[var(--warn-soft)] px-3 py-2 text-[11px] leading-5 text-[var(--fg-2)]">
      <div className="flex flex-wrap items-center gap-1.5">
        <FAStatusPill tone="warn">{actionSummaryLabel(receipt.action)}</FAStatusPill>
        <FAStatusPill tone="info">{receipt.status}</FAStatusPill>
        <FAStatusPill tone="neutral">{receipt.data_status}</FAStatusPill>
        {receipt.review_id ? <FAStatusPill tone="warn">review pending</FAStatusPill> : null}
      </div>
      <div className="grid gap-1.5 text-[10px] sm:grid-cols-2">
        <div className="rounded-[var(--radius-sm)] bg-[var(--bg-card-inner)] px-2 py-1.5">
          <div className="text-[var(--fg-5)]">run_id</div>
          <div className="break-all font-mono text-[var(--fg-2)]">{receipt.run_id ?? "—"}</div>
        </div>
        <div className="rounded-[var(--radius-sm)] bg-[var(--bg-card-inner)] px-2 py-1.5">
          <div className="text-[var(--fg-5)]">review_id</div>
          <div className="break-all font-mono text-[var(--fg-2)]">{receipt.review_id ?? "—"}</div>
        </div>
        {matchedEvent ? (
          <div className="rounded-[var(--radius-sm)] bg-[var(--bg-card-inner)] px-2 py-1.5 sm:col-span-2">
            <div className="text-[var(--fg-5)]">matched_event</div>
            <div className="text-[var(--fg-2)]">{matchedEvent.title}</div>
          </div>
        ) : null}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Link to="/review-center" className="text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--warn)] hover:text-[var(--fg-1)]">
          进入 Review Center
        </Link>
        {receipt.source_refs.slice(0, 2).map((ref) => (
          <FASourceTraceBadge
            key={sourceRefKey(ref)}
            source={compactSourceLabel(ref)}
            status={ref.status ?? "available"}
            tone={ref.status ? undefined : "neutral"}
          />
        ))}
      </div>
    </div>
  );
}

function TopLevelTraceSection({
  pageRefs,
  timelineRefs,
  artifactPaths,
}: {
  pageRefs: SourceRef[];
  timelineRefs: SourceRef[];
  artifactPaths: string[];
}) {
  return (
    <section className="space-y-2 rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">当前事件流追踪</div>
          <div className="mt-1 text-[11px] font-semibold text-[var(--fg-2)]">页面级 source refs 与顶层工件路径</div>
        </div>
        <div className="flex flex-wrap gap-1.5">
          <FAStatusPill tone="info">{pageRefs.length} 页面引用</FAStatusPill>
          <FAStatusPill tone="neutral">{timelineRefs.length} 事件引用</FAStatusPill>
          <FAStatusPill tone="dim">{artifactPaths.length} 工件</FAStatusPill>
        </div>
      </div>

      <div className="grid gap-2 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
        <div className="space-y-2">
          {pageRefs.length > 0 || timelineRefs.length > 0 ? (
            <>
              {pageRefs.length > 0 ? (
                <div className="space-y-1.5">
                  <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">页面引用</div>
                  <div className="flex flex-wrap gap-1.5">
                    {pageRefs.slice(0, 6).map((ref) => (
                      <FASourceTraceBadge
                        key={`page-${sourceRefKey(ref)}`}
                        source={compactSourceLabel(ref)}
                        status={ref.status ?? "available"}
                        tone={ref.status ? undefined : "info"}
                      />
                    ))}
                  </div>
                </div>
              ) : null}
              {timelineRefs.length > 0 ? (
                <div className="space-y-1.5">
                  <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">事件引用</div>
                  <div className="flex flex-wrap gap-1.5">
                    {timelineRefs.slice(0, 6).map((ref) => (
                      <FASourceTraceBadge
                        key={`timeline-${sourceRefKey(ref)}`}
                        source={compactSourceLabel(ref)}
                        status={ref.status ?? "available"}
                        tone={ref.status ? undefined : "neutral"}
                      />
                    ))}
                  </div>
                </div>
              ) : null}
            </>
          ) : (
            <div className="rounded-[var(--radius-sm)] border border-dashed border-[var(--border)] bg-[var(--bg-panel)] px-3 py-2 text-[11px] leading-5 text-[var(--fg-4)]">
              当前事件流没有返回页面级或时间线级 `source_refs`。
            </div>
          )}
        </div>

        <div className="space-y-1.5">
          <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">顶层工件路径</div>
          {artifactPaths.length > 0 ? (
            <div className="space-y-1.5">
              {artifactPaths.slice(0, 6).map((path) => (
                <div
                  key={path}
                  className="rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-panel)] px-2.5 py-2 font-mono text-[10px] text-[var(--fg-3)]"
                >
                  {path}
                </div>
              ))}
            </div>
          ) : (
            <div className="rounded-[var(--radius-sm)] border border-dashed border-[var(--border)] bg-[var(--bg-panel)] px-3 py-2 text-[11px] leading-5 text-[var(--fg-4)]">
              当前页面尚未暴露顶层工件路径。
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

function BriefSourceRefsSection({ brief }: { brief: Jin10ArticleBrief }) {
  const refs = dedupeSourceRefs(normalizeSourceRefs(brief.source_refs));

  if (refs.length === 0) {
    return (
      <div className="rounded-[var(--radius-sm)] border border-dashed border-[var(--border)] bg-[var(--bg-panel)] px-3 py-2 text-[11px] leading-5 text-[var(--fg-4)]">
        当前 brief 未返回 `source_refs`。
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-1.5">
        {refs.slice(0, 4).map((ref) => (
          <FASourceTraceBadge
            key={sourceRefKey(ref)}
            source={compactSourceLabel(ref)}
            status={ref.status ?? "available"}
            tone={ref.status ? undefined : "info"}
          />
        ))}
      </div>
      <div className="grid gap-1.5 text-[10px] text-[var(--fg-4)] sm:grid-cols-2">
        {refs.slice(0, 2).flatMap((ref) =>
          sourceRefPairs(ref)
            .slice(0, 3)
            .map((pair) => (
              <div key={`${sourceRefKey(ref)}-${pair.label}`} className="min-w-0 rounded-[var(--radius-sm)] bg-[var(--bg-panel)] px-2 py-1.5">
                <div className="text-[var(--fg-5)]">{pair.label}</div>
                <div className="truncate font-mono text-[var(--fg-3)]">{pair.value}</div>
              </div>
            )),
        )}
      </div>
    </div>
  );
}

function BriefArtifactsSection({ brief }: { brief: Jin10ArticleBrief }) {
  const entries = Object.entries(brief.detail_artifacts ?? {}).filter(([, value]) => formatArtifactValue(value));

  if (entries.length === 0) {
    return (
      <div className="rounded-[var(--radius-sm)] border border-dashed border-[var(--border)] bg-[var(--bg-panel)] px-3 py-2 text-[11px] leading-5 text-[var(--fg-4)]">
        当前 brief 未返回 `detail_artifacts`。
      </div>
    );
  }

  return (
    <div className="grid gap-1.5 text-[10px] text-[var(--fg-4)] sm:grid-cols-2">
      {entries.slice(0, 6).map(([key, value]) => (
        <div key={`${brief.brief_id}-${key}`} className="rounded-[var(--radius-sm)] bg-[var(--bg-panel)] px-2 py-1.5">
          <div className="text-[var(--fg-5)]">{key}</div>
          <div className="break-all font-mono text-[var(--fg-3)]">{formatArtifactValue(value)}</div>
        </div>
      ))}
    </div>
  );
}

function BriefCard({
  brief,
  matchedEvent,
  activeAction,
  receipt,
  error,
  onLink,
  onReview,
  onIgnore,
}: {
  brief: Jin10ArticleBrief;
  matchedEvent: EventFlowTimelineItem | null;
  activeAction: BriefActionKind | null;
  receipt: EventFlowActionResponse | null;
  error: string | null;
  onLink: () => void;
  onReview: () => void;
  onIgnore: () => void;
}) {
  const tags = uniqueStrings([...brief.asset_tags, ...brief.topic_tags]);

  return (
    <article className="space-y-3 rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <FAStatusPill tone={articleBriefTone(brief)}>{brief.display_bucket || "未分类"}</FAStatusPill>
            <FAStatusPill tone="neutral">{brief.article_class || "unknown"}</FAStatusPill>
            <FAStatusPill tone={brief.access_status === "readable" ? "up" : "warn"}>{brief.access_status || "unknown"}</FAStatusPill>
          </div>
          <div className="mt-2 text-[12px] font-semibold leading-5 text-[var(--fg-1)]">{brief.headline}</div>
          <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[10px] text-[var(--fg-4)]">
            <span>created_at: {brief.created_at ? formatDateTime(brief.created_at) : "—"}</span>
            <span>assets: {brief.asset_tags.length}</span>
            <span>topics: {brief.topic_tags.length}</span>
          </div>
        </div>

        {brief.source_url ? (
          <a
            href={brief.final_url ?? brief.source_url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-[var(--radius-sm)] border border-[var(--border)] text-[var(--fg-4)] transition-colors hover:border-[var(--border-strong)] hover:text-[var(--fg-2)]"
            title="打开来源链接"
          >
            <ExternalLink size={13} />
          </a>
        ) : null}
      </div>

      {brief.analysis_summary ? (
        <div className="rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-panel)] px-3 py-2 text-[11px] leading-5 text-[var(--fg-2)]">
          {brief.analysis_summary}
        </div>
      ) : brief.original_excerpt ? (
        <div className="rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-panel)] px-3 py-2 text-[11px] leading-5 text-[var(--fg-3)]">
          {brief.original_excerpt}
        </div>
      ) : null}

      {tags.length > 0 ? (
        <div className="flex flex-wrap gap-1.5">
          {tags.slice(0, 10).map((tag) => (
            <span
              key={`${brief.brief_id}-${tag}`}
              className="rounded-[var(--radius-pill)] border border-[var(--border-faint)] px-2 py-0.5 text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-4)]"
            >
              {tag}
            </span>
          ))}
        </div>
      ) : null}

      <div className="grid gap-2 lg:grid-cols-2">
        <section className="space-y-2 rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-card)] p-2.5">
          <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">
            <Link2 size={12} />
            <span>来源引用</span>
          </div>
          <BriefSourceRefsSection brief={brief} />
        </section>

        <section className="space-y-2 rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-card)] p-2.5">
          <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">
            <FileStack size={12} />
            <span>详情工件</span>
          </div>
          <BriefArtifactsSection brief={brief} />
        </section>
      </div>

      <div className="flex flex-wrap gap-1.5 border-t border-[var(--border-faint)] pt-3">
        <ActionButton
          icon={<Link2 size={11} />}
          label="关联"
          pending={activeAction === "link"}
          disabled={!matchedEvent}
          title={matchedEvent ? `关联到 ${matchedEvent.title}` : "当前未找到可匹配事件，暂不可关联"}
          onClick={onLink}
        />
        <ActionButton
          icon={<MessageSquareWarning size={11} />}
          label="复核"
          pending={activeAction === "review"}
          disabled={!matchedEvent}
          title={matchedEvent ? `登记事件复核：${matchedEvent.title}` : "当前未找到可匹配事件，暂不可提交复核"}
          onClick={onReview}
        />
        <ActionButton
          icon={<ShieldOff size={11} />}
          label="忽略"
          pending={activeAction === "ignore"}
          title="登记忽略请求"
          onClick={onIgnore}
        />
        {matchedEvent ? <FAStatusPill tone="info">建议匹配 {matchedEvent.title}</FAStatusPill> : <FAStatusPill tone="dim">待匹配事件</FAStatusPill>}
      </div>
      {receipt ? <BriefActionReceipt receipt={receipt} matchedEvent={matchedEvent} /> : null}
      {error ? (
        <div className="rounded-[var(--radius-sm)] border border-[var(--down-border)] bg-[var(--down-soft)] px-3 py-2 text-[11px] leading-5 text-[var(--down)]">
          {error}
        </div>
      ) : null}
    </article>
  );
}

export function EventFlowLiveBriefsPanel({ bundle, timeline = [], sourceRefs = [] }: EventFlowLiveBriefsPanelProps) {
  const briefs = bundle?.briefs ?? [];
  const pageRefs = dedupeSourceRefs(sourceRefs);
  const timelineRefs = dedupeSourceRefs(timeline.flatMap((item) => item.source_refs ?? []));
  const artifactPaths = collectTopLevelArtifactPaths(bundle, pageRefs, timelineRefs);
  const [activeActionKey, setActiveActionKey] = useState<string | null>(null);
  const [receipts, setReceipts] = useState<Record<string, EventFlowActionResponse>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const matchedEventByBriefId = useMemo(() => {
    const map: Record<string, EventFlowTimelineItem | null> = {};
    for (const brief of briefs) {
      const matchedEventId = findBestEventIdForBrief(brief, timeline);
      map[brief.brief_id] = matchedEventId ? timeline.find((event) => event.id === matchedEventId) ?? null : null;
    }
    return map;
  }, [briefs, timeline]);

  async function runBriefAction(
    brief: Jin10ArticleBrief,
    action: BriefActionKind,
  ) {
    const matchedEvent = matchedEventByBriefId[brief.brief_id] ?? null;
    const actionKey = `${brief.brief_id}:${action}`;
    setActiveActionKey(actionKey);
    setErrors((current) => ({ ...current, [brief.brief_id]: "" }));
    try {
      let receipt: EventFlowActionResponse;
      if (action === "link") {
        if (!matchedEvent) {
          throw new Error("当前未找到可匹配事件，无法登记关联请求");
        }
        receipt = await linkEventFlowBrief(brief.brief_id, {
          target_event_id: matchedEvent.id,
        });
      } else if (action === "review") {
        if (!matchedEvent) {
          throw new Error("当前未找到可匹配事件，无法登记复核请求");
        }
        receipt = await reviewEventFlowEvent(matchedEvent.id, {
          review: `review matched event ${matchedEvent.id} from brief ${brief.brief_id}`,
        });
      } else {
        receipt = await ignoreEventFlowBrief(brief.brief_id, {
          reason: `ignore brief ${brief.brief_id} from Event Flow Live Briefs`,
        });
      }
      setReceipts((current) => ({ ...current, [brief.brief_id]: receipt }));
    } catch (error) {
      setErrors((current) => ({ ...current, [brief.brief_id]: actionErrorMessage(error) }));
    } finally {
      setActiveActionKey(null);
    }
  }

  return (
    <FACard
      title="当日快讯 / 金十文章"
      eyebrow="实时快讯"
      accent="warn"
      action={bundle ? <FAStatusPill tone="warn">{bundle.brief_count} 条摘要</FAStatusPill> : <FAStatusPill tone="dim">无摘要包</FAStatusPill>}
      bodyClassName="space-y-3"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap gap-1.5">
          {bundle?.as_of ? <FASourceTraceBadge source={formatDateTime(bundle.as_of)} status="updated_at" tone="info" /> : null}
          {bundle?.date ? <FASourceTraceBadge source={bundle.date} status="trade_date" tone="neutral" /> : null}
          {bundle?.run_id ? <FASourceTraceBadge source={bundle.run_id} status="run_id" tone="dim" /> : null}
          {bundle?.status ? <FASourceTraceBadge source={bundle.status} status="bundle_status" tone={bundle.status === "available" ? "up" : "warn"} /> : null}
        </div>
        <div className="flex flex-wrap gap-1.5">
          <FAStatusPill tone="info">{timeline.length} 条事件</FAStatusPill>
          <FAStatusPill tone="neutral">{pageRefs.length + timelineRefs.length} 条引用</FAStatusPill>
        </div>
      </div>

      <TopLevelTraceSection pageRefs={pageRefs} timelineRefs={timelineRefs} artifactPaths={artifactPaths} />

      {briefs.length === 0 ? (
        <FAEmptyState
          title="当日没有可展示的 article briefs"
          description="当前 Tab 不回退 mock。请等待 Jin10 article brief bundle 产出，或检查上游是否返回 empty 状态。"
        />
      ) : (
        <div className="space-y-2">
          {briefs.map((brief) => (
            <BriefCard
              key={brief.brief_id}
              brief={brief}
              matchedEvent={matchedEventByBriefId[brief.brief_id] ?? null}
              activeAction={
                activeActionKey === `${brief.brief_id}:link`
                  ? "link"
                  : activeActionKey === `${brief.brief_id}:review`
                    ? "review"
                    : activeActionKey === `${brief.brief_id}:ignore`
                      ? "ignore"
                      : null
              }
              receipt={receipts[brief.brief_id] ?? null}
              error={errors[brief.brief_id] || null}
              onLink={() => void runBriefAction(brief, "link")}
              onReview={() => void runBriefAction(brief, "review")}
              onIgnore={() => void runBriefAction(brief, "ignore")}
            />
          ))}
        </div>
      )}
    </FACard>
  );
}
