import { Link } from "react-router-dom";
import { ExternalLink, SearchCode } from "lucide-react";

import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { compactSourceLabel } from "@/lib/sourceRefs";
import type { EventFlowTimelineItem } from "@/types/event-flow";
import type { ProcessingTraceMode } from "@/types/processing-monitor";

interface ProcessingTraceLinkProps {
  event: EventFlowTimelineItem;
  density?: "compact" | "normal";
}

function firstSourceRef(event: EventFlowTimelineItem): string | null {
  const first = event.source_refs?.[0];
  if (!first) return null;
  return first.source_ref || first.artifact_path || first.snapshot_id || compactSourceLabel(first);
}

function traceTarget(event: EventFlowTimelineItem): { mode: ProcessingTraceMode; value: string; label: string } | null {
  if (event.processing_trace_id) {
    return { mode: "processing_trace_id", value: event.processing_trace_id, label: "查看加工记录" };
  }
  if (event.id) {
    return { mode: "event_id", value: event.id, label: "查看事件加工记录" };
  }
  const sourceRef = firstSourceRef(event);
  if (sourceRef) {
    return { mode: "source_ref", value: sourceRef, label: "查看来源加工记录" };
  }
  return null;
}

export function ProcessingTraceLink({ event, density = "normal" }: ProcessingTraceLinkProps) {
  const target = traceTarget(event);
  const compact = density === "compact";

  if (!target) {
    return (
      <div className="flex flex-wrap items-center gap-1.5 text-[length:var(--type-caption)] text-[var(--fg-5)]">
        <SearchCode size={10} />
        加工记录未提供
      </div>
    );
  }

  const href = `/processing-monitor?mode=${encodeURIComponent(target.mode)}&q=${encodeURIComponent(target.value)}`;

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <Link
        to={href}
        className="inline-flex items-center gap-1 text-[length:var(--type-caption)] font-semibold text-[var(--info)] no-underline hover:text-[var(--fg-1)]"
      >
        <SearchCode size={10} />
        <span>{target.label}</span>
        <ExternalLink size={10} />
      </Link>
      {event.source_refs?.length ? (
        <FAStatusPill tone="neutral" dot={false}>
          来源 {event.source_refs.length}
        </FAStatusPill>
      ) : null}
    </div>
  );
}
