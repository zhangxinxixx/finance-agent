import { Route } from "lucide-react";

import { FAStatusPill } from "@/components/shared/FAStatusPill";
import { formatTransmissionPathLabel } from "@/components/shared/goldMainlineFormat";
import type { EventFlowTimelineItem } from "@/types/event-flow";
import type { TransmissionChain, TransmissionPath } from "@/types/gold-mainlines";

interface TransmissionChainTagGroupProps {
  event: EventFlowTimelineItem;
  density?: "compact" | "normal";
}

function uniqueList<T extends string>(values: Array<T | null | undefined>): T[] {
  const result: T[] = [];
  const seen = new Set<string>();
  values.forEach((value) => {
    if (!value || seen.has(value)) return;
    seen.add(value);
    result.push(value);
  });
  return result;
}

function pathList(event: EventFlowTimelineItem): Array<TransmissionPath | TransmissionChain> {
  return uniqueList(event.transmission_chains ?? []);
}

export function TransmissionChainTagGroup({ event, density = "normal" }: TransmissionChainTagGroupProps) {
  const paths = pathList(event);
  const compact = density === "compact";

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="inline-flex items-center gap-1 text-[length:var(--type-caption)] font-semibold text-[var(--fg-5)]">
        <Route size={10} />
        传导链
      </span>
      {paths.length ? paths.map((path) => (
        <FAStatusPill key={`${event.id}-${path}`} tone="warn" dot={false} className={compact ? "px-1.5 py-0" : undefined}>
          {formatTransmissionPathLabel(path)}
        </FAStatusPill>
      )) : (
        <span className="text-[length:var(--type-caption)] text-[var(--fg-5)]">未返回</span>
      )}
    </div>
  );
}
