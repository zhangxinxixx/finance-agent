import { BookOpenText, ExternalLink, Link2 } from "lucide-react";
import { Link } from "react-router-dom";
import { FACard } from "@/components/shared/FACard";
import { FASourceTraceBadge } from "@/components/shared/FASourceTraceBadge";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { formatDateTime } from "@/lib/date";
import type { Jin10ArticleBrief, Jin10ArticleBriefBundle } from "@/types/event-flow";
import { formatEventFlowArtifactLabel, translateEventFlowValue } from "./eventFlowFormat";
import { articleBriefTone } from "./EventFlowSectionHelpers";

export function Jin10ArticleBriefsPanel({
  bundle,
  onOpenDetail,
}: {
  bundle: Jin10ArticleBriefBundle;
  onOpenDetail?: (brief: Jin10ArticleBrief) => void;
}) {
  const briefs = bundle.briefs.slice(0, 4);
  const monitorHref = bundle.date ? `/feishu-monitor?date=${encodeURIComponent(bundle.date)}` : null;
  if (briefs.length === 0) {
    return null;
  }

  return (
    <FACard
      title="金十重点文章"
      eyebrow="文章摘要"
      accent="warn"
      action={
        <div className="flex flex-wrap items-center gap-1.5">
          <FAStatusPill tone="info">{bundle.brief_count} 条</FAStatusPill>
          {monitorHref ? (
            <Link
              to={monitorHref}
              className="inline-flex h-7 items-center gap-1 rounded-[var(--radius-pill)] border border-[var(--border)] bg-[var(--bg-card-inner)] px-2.5 text-[10px] font-semibold text-[var(--fg-4)] transition-colors hover:border-[var(--brand-gold)] hover:text-[var(--brand)]"
            >
              <Link2 size={11} />
              查看飞书监控
            </Link>
          ) : null}
        </div>
      }
      bodyClassName="space-y-2"
    >
      <div className="flex flex-wrap gap-2">
        <FASourceTraceBadge source={formatDateTime(bundle.as_of ?? "")} status="updated_at" tone="info" />
        <FASourceTraceBadge source={formatEventFlowArtifactLabel(bundle.artifact_path)} status="artifact" tone="dim" />
      </div>

      <div className="space-y-2">
        {briefs.map((brief) => (
          <article
            key={brief.brief_id}
            className="rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-2.5"
          >
            <div className="flex min-w-0 items-start justify-between gap-2">
              <button
                type="button"
                onClick={() => onOpenDetail?.(brief)}
                className="min-w-0 flex-1 space-y-1 text-left"
              >
                <div className="flex flex-wrap items-center gap-1.5">
                  <FAStatusPill tone={articleBriefTone(brief)}>{brief.display_bucket}</FAStatusPill>
                  <FAStatusPill tone={brief.access_status === "readable" ? "up" : "warn"}>{translateEventFlowValue(brief.access_status)}</FAStatusPill>
                </div>
                <div className="text-[12px] font-semibold leading-5 text-[var(--fg-1)]">{brief.headline}</div>
                {onOpenDetail ? (
                  <div className="text-[10px] font-semibold text-[var(--brand-hover)]">打开事件详情</div>
                ) : null}
              </button>
              <div className="flex shrink-0 items-center gap-1">
                {monitorHref ? (
                  <Link
                    to={monitorHref}
                    className="inline-flex h-7 items-center gap-1 rounded-[var(--radius-pill)] border border-[var(--border)] px-2 text-[9px] font-semibold text-[var(--fg-4)] transition-colors hover:border-[var(--brand-gold)] hover:text-[var(--brand)]"
                    title="查看飞书监控"
                  >
                    <Link2 size={11} />
                    监控
                  </Link>
                ) : null}
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
            </div>

            {brief.original_excerpt ? (
              <div className="mt-2 rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-panel)] px-2.5 py-2 text-[11px] leading-5 text-[var(--fg-3)]">
                {brief.original_excerpt}
              </div>
            ) : null}

            {brief.analysis_summary ? (
              <div className="mt-2 flex gap-2 text-[11px] leading-5 text-[var(--fg-2)]">
                <BookOpenText size={13} className="mt-0.5 shrink-0 text-[var(--warn)]" />
                <span>{brief.analysis_summary}</span>
              </div>
            ) : null}

            {brief.key_points.length > 0 ? (
              <ul className="mt-2 grid gap-1.5 text-[11px] leading-5 text-[var(--fg-3)]">
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
