import { FACard } from "@/components/shared/FACard";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { FASourceTraceBadge } from "@/components/shared/FASourceTraceBadge";
import {
  GOLD_MAINLINE_META,
  formatGoldEventRefLabel,
  formatGoldSourceRefLabel,
} from "@/components/shared/goldMainlineFormat";
import type { GoldMacroOverview } from "@/types/gold-mainlines";
import {
  coverageStatusTone,
  formatEventCount,
  type MainlineCoverageRow,
} from "./goldMainlineCoverage";

interface MainlineEvidenceListProps {
  overview: GoldMacroOverview;
  rows: MainlineCoverageRow[];
}

export function MainlineEvidenceList({ overview, rows }: MainlineEvidenceListProps) {
  const eventRows = rows.filter((row) => row.eventIds.length > 0);
  const sourceRefs = overview.source_refs.slice(0, 8);

  return (
    <div className="grid content-start gap-3">
      <FACard title="事件归因索引" eyebrow="Event Links" accent="none" className="shrink-0">
        {eventRows.length ? (
          <div className="grid gap-2">
            {eventRows.map((row) => (
              <div key={row.id} className="rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2.5 py-2">
                <div className="flex items-center justify-between gap-2">
                  <div className="text-[length:var(--type-caption)] font-semibold text-[var(--fg-2)]">{GOLD_MAINLINE_META[row.id].label}</div>
                  <FAStatusPill tone={coverageStatusTone(row.status)} dot={false}>{formatEventCount(row.eventIds.length)}</FAStatusPill>
                </div>
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  {row.eventIds.slice(0, 4).map((eventId) => (
                    <span
                      key={eventId}
                      title={eventId.replace(/^event:/, "")}
                      className="fa-num max-w-full truncate rounded-[var(--radius-pill)] border border-[var(--border-faint)] px-2 py-0.5 text-[length:var(--type-caption)] text-[var(--fg-4)]"
                    >
                      {formatGoldEventRefLabel(eventId)}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-[length:var(--type-caption)] text-[var(--fg-4)]">当前主线总览未返回事件归因索引。</div>
        )}
      </FACard>

      {sourceRefs.length ? (
        <FACard title="证据来源" eyebrow="Source Trace" accent="none" className="shrink-0">
          <div className="flex flex-wrap gap-1.5">
            {sourceRefs.map((ref, index) => (
              <FASourceTraceBadge
                key={`${ref.source_ref}-${ref.snapshot_id ?? index}`}
                source={formatGoldSourceRefLabel(ref, `来源 ${index + 1}`)}
                status={ref.status ?? "trace"}
                snapshotId={ref.snapshot_id}
              />
            ))}
          </div>
        </FACard>
      ) : null}
    </div>
  );
}
