import { FACard } from "@/components/shared/FACard";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { FASourceTraceBadge } from "@/components/shared/FASourceTraceBadge";
import {
  formatGoldMainlineLabel,
  formatTransmissionPathLabel,
} from "@/components/shared/goldMainlineFormat";
import type { SourceRef } from "@/types/common";
import type { GoldMainlineEventLink } from "@/types/gold-mainlines";
import {
  eventMainlineIds,
  sourceKey,
} from "./oilGeopoliticsModel";

interface OilGeoEvidenceTimelineProps {
  events: GoldMainlineEventLink[];
  sourceRefs: SourceRef[];
}

export function OilGeoEvidenceTimeline({ events, sourceRefs }: OilGeoEvidenceTimelineProps) {
  return (
    <div className="grid content-start gap-3">
      <FACard title="相关事件" eyebrow="Event Evidence" accent="none" className="shrink-0">
        {events.length ? (
          <div className="grid gap-2">
            {events.map((event) => (
              <div key={event.event_id} className="rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2.5 py-2">
                <div className="flex items-center justify-between gap-2">
                  <div className="fa-num min-w-0 truncate text-[length:var(--type-caption)] font-semibold text-[var(--fg-2)]">{event.event_id}</div>
                  {event.changed_dominant_theme ? <FAStatusPill tone="warn" dot={false}>改变主线</FAStatusPill> : null}
                </div>
                <div className="mt-1 flex flex-wrap gap-1.5">
                  {eventMainlineIds(event).map((id) => <FAStatusPill key={id} tone="neutral" dot={false}>{formatGoldMainlineLabel(id)}</FAStatusPill>)}
                  {event.transmission_path_ids.map((id) => <FAStatusPill key={id} tone="dim" dot={false}>{formatTransmissionPathLabel(id)}</FAStatusPill>)}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-[length:var(--type-caption)] text-[var(--fg-4)]">当前主线产物未返回石油与地缘相关事件链接。</div>
        )}
      </FACard>

      {sourceRefs.length ? (
        <FACard title="证据来源" eyebrow="Source Trace" accent="none" className="shrink-0">
          <div className="flex flex-wrap gap-1.5">
            {sourceRefs.map((ref, index) => (
              <FASourceTraceBadge key={sourceKey(ref, index)} source={ref.label || ref.source_ref} status={ref.status ?? "trace"} snapshotId={ref.snapshot_id} />
            ))}
          </div>
        </FACard>
      ) : null}
    </div>
  );
}
