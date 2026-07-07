import { GitBranch } from "lucide-react";

import { FAStatusPill } from "@/components/shared/FAStatusPill";
import {
  formatGoldMainlineLabel,
  formatGoldNetBiasLabel,
  formatGoldVerificationStatusLabel,
  goldNetBiasTone,
  goldVerificationStatusTone,
} from "@/components/shared/goldMainlineFormat";
import type { EventFlowTimelineItem } from "@/types/event-flow";
import type { GoldMainline } from "@/types/gold-mainlines";

interface MainlineTagGroupProps {
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

function mainlineList(event: EventFlowTimelineItem): GoldMainline[] {
  return uniqueList([
    event.primary_mainline,
    ...(event.mainlines ?? []),
  ]);
}

export function MainlineTagGroup({ event, density = "normal" }: MainlineTagGroupProps) {
  const mainlines = mainlineList(event);
  const compact = density === "compact";

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="inline-flex items-center gap-1 text-[length:var(--type-caption)] font-semibold text-[var(--fg-5)]">
        <GitBranch size={10} />
        主线
      </span>
      {mainlines.length ? mainlines.map((mainline, index) => (
        <FAStatusPill
          key={`${event.id}-${mainline}`}
          tone={index === 0 ? "info" : "neutral"}
          dot={false}
          className={compact ? "px-1.5 py-0" : undefined}
        >
          {formatGoldMainlineLabel(mainline)}
        </FAStatusPill>
      )) : (
        <span className="text-[length:var(--type-caption)] text-[var(--fg-5)]">未返回</span>
      )}
      {event.changed_dominant_theme ? (
        <FAStatusPill tone="warn" dot={false} className={compact ? "px-1.5 py-0" : undefined}>
          改变主导因素
        </FAStatusPill>
      ) : null}
      {event.net_effect ? (
        <FAStatusPill tone={goldNetBiasTone(event.net_effect)} dot={false} className={compact ? "px-1.5 py-0" : undefined}>
          {formatGoldNetBiasLabel(event.net_effect)}
        </FAStatusPill>
      ) : null}
      {event.verification_status ? (
        <FAStatusPill tone={goldVerificationStatusTone(event.verification_status)} dot={false} className={compact ? "px-1.5 py-0" : undefined}>
          {formatGoldVerificationStatusLabel(event.verification_status)}
        </FAStatusPill>
      ) : null}
    </div>
  );
}
