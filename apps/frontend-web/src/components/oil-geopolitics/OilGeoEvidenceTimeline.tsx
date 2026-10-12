import { ResearchDetails } from "@/components/shared/ResearchDetails";
import { EvidenceRecordActions } from "@/components/shared/EvidenceRecordActions";
import { readerSource } from "@/lib/readerLabels";
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

const OIL_EVENT_LABELS: Record<string, string> = {
  hormuz_risk: "霍尔木兹风险",
  oil_supply_shock: "原油供应冲击",
  geopolitical_conflict: "地缘冲突",
  macro_release: "宏观数据发布",
};

function readableOilEventLabel(eventId: string | null | undefined): string {
  const kind = eventId?.split(":")[1] ?? "";
  return OIL_EVENT_LABELS[kind] ? `${OIL_EVENT_LABELS[kind]}（事件记录）` : "事件记录待确认";
}

export function OilGeoEvidenceTimeline({ events, sourceRefs }: OilGeoEvidenceTimelineProps) {
  return (
    <ResearchDetails label="查看事件与来源记录"><div className="grid content-start gap-3">
      <FACard title="相关事件" eyebrow="事件依据" accent="none" className="shrink-0">
        {events.length ? (
          <div className="grid gap-2">
            {events.map((event) => (
              <div key={event.event_id} className="rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2.5 py-2">
                <div className="flex items-center justify-between gap-2">
                  <div className="min-w-0 truncate text-[length:var(--type-caption)] font-semibold text-[var(--fg-2)]">{readableOilEventLabel(event.event_id)}</div>
                  {event.changed_dominant_theme ? <FAStatusPill tone="warn" dot={false}>改变主线</FAStatusPill> : null}
                </div>
                <div className="mt-1 flex flex-wrap gap-1.5">
                  {eventMainlineIds(event).map((id) => <FAStatusPill key={id} tone="neutral" dot={false}>{formatGoldMainlineLabel(id)}</FAStatusPill>)}
                  {event.transmission_path_ids.map((id) => <FAStatusPill key={id} tone="dim" dot={false}>{formatTransmissionPathLabel(id)}</FAStatusPill>)}
                </div>
                <EvidenceRecordActions record={{ event_id: event.event_id }} label="事件关联记录" />
              </div>
            ))}
          </div>
        ) : (
          <div className="text-[length:var(--type-caption)] text-[var(--fg-4)]">当前主线产物未返回石油与地缘相关事件链接。</div>
        )}
      </FACard>

      {sourceRefs.length ? (
        <FACard title="证据来源" eyebrow="来源记录" accent="none" className="shrink-0">
          <div className="flex flex-wrap gap-1.5">
            {sourceRefs.map((ref, index) => (
              <FASourceTraceBadge key={sourceKey(ref, index)} source={readerSource(ref.label || ref.source_ref)} status={ref.status ?? "trace"} snapshotId={ref.snapshot_id} />
            ))}
          </div>
        </FACard>
      ) : null}
    </div></ResearchDetails>
  );
}
