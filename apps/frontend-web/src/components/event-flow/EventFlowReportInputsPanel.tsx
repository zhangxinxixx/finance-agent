import { useMemo, useState, type ReactNode } from "react";
import { BookOpenText, CheckCircle2, FileText, FolderTree, Loader2, SearchCheck, ShieldAlert, XCircle } from "lucide-react";
import { ApiError } from "@/adapters/apiClient";
import { excludeEventFlowReportInput, includeEventFlowReportInput } from "@/adapters/eventFlow";
import { FACard } from "@/components/shared/FACard";
import { FAEmptyState } from "@/components/shared/FAEmptyState";
import { FASourceTraceBadge } from "@/components/shared/FASourceTraceBadge";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { formatDateTime } from "@/lib/date";
import { compactSourceLabel, dedupeSourceRefs, normalizeSourceRefs } from "@/lib/sourceRefs";
import type { SourceRef } from "@/types/common";
import type { EventFlowActionResponse, EventFlowBriefSummary, EventFlowReportInputItem, Jin10ArticleBriefBundle } from "@/types/event-flow";
import { EventFlowSourceRefsCard } from "./EventFlowSourceRefsCard";

function inputListSection({
  title,
  icon,
  items,
  emptyText,
}: {
  title: string;
  icon: typeof FileText;
  items: string[];
  emptyText: string;
}) {
  const Icon = icon;
  return (
    <section className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
      <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">
        <Icon size={11} />
        <span>{title}</span>
      </div>
      {items.length === 0 ? (
        <div className="mt-2 text-[11px] leading-5 text-[var(--fg-4)]">{emptyText}</div>
      ) : (
        <ul className="mt-2 space-y-1.5">
          {items.map((item) => (
            <li key={`${title}-${item}`} className="flex gap-2 text-[11px] leading-5 text-[var(--fg-2)]">
              <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-[var(--fg-5)]" />
              <span>{item}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function briefArtifactRows(bundle: Jin10ArticleBriefBundle | null | undefined): Array<{ label: string; value: string }> {
  if (!bundle) return [];
  return [
    { label: "artifact_path", value: bundle.artifact_path },
    { label: "date", value: bundle.date },
    { label: "run_id", value: bundle.run_id },
    { label: "as_of", value: bundle.as_of ? formatDateTime(bundle.as_of) : "—" },
    { label: "rule_version", value: bundle.rule_version ?? "—" },
    { label: "brief_count", value: String(bundle.brief_count) },
  ];
}

function collectBriefRefs(bundle: Jin10ArticleBriefBundle | null | undefined): SourceRef[] {
  return dedupeSourceRefs(bundle?.briefs.flatMap((brief) => normalizeSourceRefs(brief.source_refs)) ?? []);
}

function ArticleBriefSummary({ bundle }: { bundle: Jin10ArticleBriefBundle | null | undefined }) {
  if (!bundle || bundle.briefs.length === 0) {
    return (
      <FACard title="文章摘要输入" eyebrow="Article Briefs" accent="warn">
        <FAEmptyState title="暂无 article briefs" description="当前没有可展示的文章摘要输入。" className="py-6" />
      </FACard>
    );
  }

  return (
    <FACard
      title="文章摘要输入"
      eyebrow="Article Briefs"
      accent="warn"
      action={<FAStatusPill tone="info">{bundle.brief_count} 条</FAStatusPill>}
      bodyClassName="space-y-3"
    >
      <div className="flex flex-wrap gap-2">
        <FASourceTraceBadge source={bundle.artifact_path} status="artifact" tone="dim" />
        {bundle.as_of ? <FASourceTraceBadge source={formatDateTime(bundle.as_of)} status="updated_at" tone="info" /> : null}
        <FASourceTraceBadge source={bundle.run_id} status="run_id" tone="neutral" />
      </div>

      <div className="grid gap-2 text-[10px] text-[var(--fg-4)] sm:grid-cols-2 xl:grid-cols-3">
        {briefArtifactRows(bundle).map((row) => (
          <div key={row.label} className="rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-panel)] px-2.5 py-2">
            <div className="uppercase tracking-[0.08em] text-[var(--fg-5)]">{row.label}</div>
            <div className="mt-1 break-all font-mono text-[11px] text-[var(--fg-2)]">{row.value}</div>
          </div>
        ))}
      </div>

      <div className="space-y-2">
        {bundle.briefs.slice(0, 5).map((brief) => (
          <article key={brief.brief_id} className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
            <div className="flex flex-wrap items-center gap-1.5">
              <FAStatusPill tone="warn">{brief.display_bucket}</FAStatusPill>
              <FAStatusPill tone={brief.access_status === "readable" ? "up" : "warn"}>{brief.access_status}</FAStatusPill>
            </div>
            <div className="mt-2 text-[12px] font-semibold leading-5 text-[var(--fg-1)]">{brief.headline}</div>
            {brief.analysis_summary ? (
              <div className="mt-2 flex gap-2 text-[11px] leading-5 text-[var(--fg-2)]">
                <BookOpenText size={13} className="mt-0.5 shrink-0 text-[var(--warn)]" />
                <span>{brief.analysis_summary}</span>
              </div>
            ) : null}
            {brief.key_points.length > 0 ? (
              <ul className="mt-2 space-y-1 text-[11px] leading-5 text-[var(--fg-3)]">
                {brief.key_points.slice(0, 3).map((point) => (
                  <li key={`${brief.brief_id}-${point}`} className="flex gap-2">
                    <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-[var(--fg-5)]" />
                    <span>{point}</span>
                  </li>
                ))}
              </ul>
            ) : null}
            <div className="mt-2 flex flex-wrap gap-1.5">
              {[...brief.asset_tags, ...brief.topic_tags].slice(0, 8).map((tag) => (
                <span
                  key={`${brief.brief_id}-${tag}`}
                  className="rounded-[var(--radius-pill)] border border-[var(--border-faint)] px-2 py-0.5 text-[9px] font-semibold uppercase text-[var(--fg-5)]"
                >
                  {tag}
                </span>
              ))}
            </div>
          </article>
        ))}
      </div>
    </FACard>
  );
}

export function EventFlowReportInputsPanel({
  briefSummary,
  articleBriefs,
  reportInputItems = [],
  sourceRefs,
}: {
  briefSummary?: EventFlowBriefSummary | null;
  articleBriefs?: Jin10ArticleBriefBundle | null;
  reportInputItems?: EventFlowReportInputItem[];
  sourceRefs?: SourceRef[];
}) {
  const pageRefs = dedupeSourceRefs(sourceRefs ?? []);
  const briefRefs = collectBriefRefs(articleBriefs);
  const groupedInputs = useMemo(() => {
    const groups = new Map<string, EventFlowReportInputItem[]>();
    for (const item of reportInputItems) {
      const bucket = groups.get(item.group) ?? [];
      bucket.push(item);
      groups.set(item.group, bucket);
    }
    return Array.from(groups.entries());
  }, [reportInputItems]);

  return (
    <div className="space-y-4">
      <FACard
        title="报告输入"
        eyebrow="Report Inputs"
        accent="warn"
        bodyClassName="space-y-3"
      >
        {!briefSummary ? (
          <FAEmptyState
            title="暂无 report_inputs"
            description="当前 brief_summary 未返回 newsHighlights / watchlist / riskPoints。"
            className="py-6"
          />
        ) : (
          <>
            <div className="grid gap-3 xl:grid-cols-3">
              {inputListSection({
                title: "News Highlights",
                icon: FileText,
                items: briefSummary.newsHighlights,
                emptyText: "未返回新闻重点。",
              })}
              {inputListSection({
                title: "Watchlist",
                icon: SearchCheck,
                items: briefSummary.watchlist,
                emptyText: "未返回观察清单。",
              })}
              {inputListSection({
                title: "Risk Points",
                icon: ShieldAlert,
                items: briefSummary.riskPoints,
                emptyText: "未返回风险提示。",
              })}
            </div>

            <div className="grid gap-2 text-[10px] text-[var(--fg-4)] sm:grid-cols-2 xl:grid-cols-4">
              {[
                { label: "headline", value: briefSummary.headline || "—" },
                { label: "status", value: briefSummary.status ?? "—" },
                { label: "pricing", value: briefSummary.pricingStatus ?? "—" },
                { label: "verification", value: briefSummary.verificationStatus ?? "—" },
                { label: "risk", value: briefSummary.riskLevel ?? "—" },
                { label: "artifact_path", value: briefSummary.artifactPath ?? "—" },
                { label: "source_refs", value: String(briefSummary.counts.sourceRefCount) },
                { label: "confirmed_events", value: String(briefSummary.counts.confirmedEventCount) },
              ].map((row) => (
                <div key={row.label} className="rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-panel)] px-2.5 py-2">
                  <div className="uppercase tracking-[0.08em] text-[var(--fg-5)]">{row.label}</div>
                  <div className="mt-1 break-all text-[11px] text-[var(--fg-2)]">{row.value}</div>
                </div>
              ))}
            </div>
          </>
        )}
      </FACard>

      <FACard
        title="可登记输入"
        eyebrow="Actionable Inputs"
        accent="brand"
        bodyClassName="space-y-3"
      >
        {groupedInputs.length === 0 ? (
          <FAEmptyState
            title="暂无可登记输入"
            description="当前后端还没有返回稳定 input_id 的可操作输入项。"
            className="py-6"
          />
        ) : (
          groupedInputs.map(([group, items]) => (
            <div key={group} className="space-y-2">
              <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">{group}</div>
              <div className="space-y-2">
                {items.map((item) => (
                  <ReportInputActionCard key={item.input_id} item={item} />
                ))}
              </div>
            </div>
          ))
        )}
      </FACard>

      <ArticleBriefSummary bundle={articleBriefs} />

      <FACard
        title={
          <div className="flex items-center gap-2">
            <FolderTree size={12} className="text-[var(--brand-hover)]" />
            <span>来源与工件摘要</span>
          </div>
        }
        eyebrow="Artifacts"
        accent="info"
        bodyClassName="space-y-3"
      >
        {pageRefs.length === 0 && briefRefs.length === 0 && !briefSummary?.artifactPath && !articleBriefs?.artifact_path ? (
          <FAEmptyState
            title="暂无来源与工件"
            description="当前页面 source refs 和 article brief refs 都为空，artifact path 也未返回。"
            className="py-6"
          />
        ) : (
          <>
            <div className="flex flex-wrap gap-2">
              {briefSummary?.artifactPath ? <FASourceTraceBadge source={briefSummary.artifactPath} status="artifact" tone="dim" /> : null}
              {articleBriefs?.artifact_path ? <FASourceTraceBadge source={articleBriefs.artifact_path} status="artifact" tone="dim" /> : null}
              {pageRefs.slice(0, 2).map((ref) => (
                <FASourceTraceBadge
                  key={[ref.source_ref, ref.endpoint ?? "", ref.artifact_path ?? ""].join("|")}
                  source={compactSourceLabel(ref)}
                  status={ref.status ?? "ok"}
                />
              ))}
            </div>
            <EventFlowSourceRefsCard eventRefs={[]} briefRefs={briefRefs} pageRefs={pageRefs} />
          </>
        )}
      </FACard>
    </div>
  );
}

function actionErrorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.responseBody ?? error.message;
  if (error instanceof Error) return error.message;
  return "动作提交失败";
}

function actionLabel(action: string): string {
  if (action === "include") return "已登记纳入请求";
  if (action === "exclude") return "已登记排除请求";
  return "已登记请求";
}

function InputActionButton({
  label,
  icon,
  pending,
  onClick,
}: {
  label: string;
  icon: ReactNode;
  pending?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      disabled={pending}
      onClick={onClick}
      className="inline-flex h-7 items-center gap-1.5 rounded-[var(--radius-pill)] border border-[var(--border)] bg-[var(--bg-card-inner)] px-2.5 text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-4)] transition-colors hover:border-[var(--border-strong)] hover:text-[var(--fg-2)] disabled:cursor-not-allowed disabled:opacity-60"
    >
      <span className="text-[var(--fg-5)]">{pending ? <Loader2 size={11} className="animate-spin" /> : icon}</span>
      <span>{label}</span>
    </button>
  );
}

function ReportInputActionCard({ item }: { item: EventFlowReportInputItem }) {
  const [pendingAction, setPendingAction] = useState<"include" | "exclude" | null>(null);
  const [receipt, setReceipt] = useState<EventFlowActionResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function submit(action: "include" | "exclude") {
    setPendingAction(action);
    setError(null);
    try {
      const response = action === "include"
        ? await includeEventFlowReportInput(item.input_id, { reason: `report input ${item.input_id} requested include` })
        : await excludeEventFlowReportInput(item.input_id, { reason: `report input ${item.input_id} requested exclude` });
      setReceipt(response);
    } catch (cause) {
      setError(actionErrorMessage(cause));
    } finally {
      setPendingAction(null);
    }
  }

  return (
    <article className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <FAStatusPill tone="info">{item.input_kind}</FAStatusPill>
            {item.verification_status ? <FAStatusPill tone="warn">{item.verification_status}</FAStatusPill> : null}
            {item.access_status ? <FAStatusPill tone={item.access_status === "readable" ? "up" : "warn"}>{item.access_status}</FAStatusPill> : null}
            {item.task_status ? <FAStatusPill tone="neutral">{item.task_status}</FAStatusPill> : null}
          </div>
          <div className="mt-2 text-[12px] font-semibold leading-5 text-[var(--fg-1)]">{item.title}</div>
          <div className="mt-1 text-[11px] leading-5 text-[var(--fg-3)]">{item.summary}</div>
        </div>
        <div className="flex flex-wrap gap-1.5">
          <InputActionButton
            label="纳入"
            icon={<CheckCircle2 size={11} />}
            pending={pendingAction === "include"}
            onClick={() => void submit("include")}
          />
          <InputActionButton
            label="排除"
            icon={<XCircle size={11} />}
            pending={pendingAction === "exclude"}
            onClick={() => void submit("exclude")}
          />
        </div>
      </div>

      <div className="mt-3 flex flex-wrap gap-1.5">
        <FASourceTraceBadge source={item.input_id} status="input_id" tone="dim" />
        {item.artifact_path ? <FASourceTraceBadge source={item.artifact_path} status="artifact" tone="dim" /> : null}
        {item.source_url ? <FASourceTraceBadge source={item.source_url} status="source_url" tone="info" /> : null}
      </div>

      {item.source_refs && item.source_refs.length > 0 ? (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {item.source_refs.slice(0, 4).map((ref) => (
            <FASourceTraceBadge
              key={[ref.source_ref, ref.endpoint ?? "", ref.artifact_path ?? ""].join("|")}
              source={compactSourceLabel(ref)}
              status={ref.status ?? "available"}
            />
          ))}
        </div>
      ) : null}

      {receipt ? (
        <div className="mt-3 rounded-[var(--radius-sm)] border border-[var(--warn-border)] bg-[var(--warn-soft)] px-3 py-2 text-[11px] leading-5 text-[var(--fg-2)]">
          <div className="flex flex-wrap items-center gap-1.5">
            <FAStatusPill tone="warn">{actionLabel(receipt.action)}</FAStatusPill>
            <FAStatusPill tone="info">{receipt.status}</FAStatusPill>
            {receipt.review_id ? <FAStatusPill tone="warn">review pending</FAStatusPill> : null}
          </div>
          <div className="mt-2 grid gap-1.5 text-[10px] sm:grid-cols-2">
            <div className="rounded-[var(--radius-sm)] bg-[var(--bg-card-inner)] px-2 py-1.5">
              <div className="text-[var(--fg-5)]">run_id</div>
              <div className="break-all font-mono text-[var(--fg-2)]">{receipt.run_id ?? "—"}</div>
            </div>
            <div className="rounded-[var(--radius-sm)] bg-[var(--bg-card-inner)] px-2 py-1.5">
              <div className="text-[var(--fg-5)]">review_id</div>
              <div className="break-all font-mono text-[var(--fg-2)]">{receipt.review_id ?? "—"}</div>
            </div>
          </div>
        </div>
      ) : null}

      {error ? (
        <div className="mt-3 rounded-[var(--radius-sm)] border border-[var(--down-border)] bg-[var(--down-soft)] px-3 py-2 text-[11px] leading-5 text-[var(--down)]">
          {error}
        </div>
      ) : null}
    </article>
  );
}
