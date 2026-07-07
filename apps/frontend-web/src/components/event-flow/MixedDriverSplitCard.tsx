import { ShieldAlert } from "lucide-react";

import { FAStatusPill, type FAStatusTone } from "@/components/shared/FAStatusPill";
import { formatGoldDriverLabel, formatGoldNetBiasLabel, goldNetBiasTone } from "@/components/shared/goldMainlineFormat";
import type { EventFlowTimelineItem } from "@/types/event-flow";

interface MixedDriverSplitCardProps {
  event: EventFlowTimelineItem;
  density?: "compact" | "normal";
}

function isMixedEffect(value: string | null | undefined): boolean {
  return value === "mixed" || value === "mixed_bullish" || value === "mixed_bearish";
}

function DriverGroup({ title, values, tone }: { title: string; values: string[]; tone: FAStatusTone }) {
  return (
    <div className="min-w-0">
      <div className="fa-label text-[var(--fg-5)]">{title}</div>
      <div className="mt-1 flex flex-wrap gap-1">
        {values.length ? values.slice(0, 5).map((item) => (
          <FAStatusPill key={`${title}-${item}`} tone={tone} dot={false}>
            {formatGoldDriverLabel(item)}
          </FAStatusPill>
        )) : (
          <span className="text-[length:var(--type-caption)] text-[var(--fg-5)]">未返回</span>
        )}
      </div>
    </div>
  );
}

export function MixedDriverSplitCard({ event, density = "normal" }: MixedDriverSplitCardProps) {
  const bullishDrivers = event.bullish_drivers ?? [];
  const bearishDrivers = event.bearish_drivers ?? [];
  const verificationNeeded = event.verification_needed ?? [];
  const shouldRender = isMixedEffect(event.net_effect) || bullishDrivers.length > 0 || bearishDrivers.length > 0 || verificationNeeded.length > 0 || Boolean(event.dominant_driver);

  if (!shouldRender) return null;

  const compact = density === "compact";
  const missingMixedParts = isMixedEffect(event.net_effect) && (
    bullishDrivers.length === 0 ||
    bearishDrivers.length === 0 ||
    !event.dominant_driver ||
    verificationNeeded.length === 0
  );

  return (
    <div className={`rounded-[var(--radius-sm)] border ${missingMixedParts ? "border-[var(--warn-border)] bg-[var(--warn-soft)]" : "border-[var(--border-faint)] bg-[var(--bg-card)]"} ${compact ? "px-2 py-1.5" : "p-2.5"}`}>
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="inline-flex items-center gap-1 text-[length:var(--type-caption)] font-semibold text-[var(--fg-5)]">
          <ShieldAlert size={10} />
          Mixed 拆解
        </span>
        {event.net_effect ? (
          <FAStatusPill tone={goldNetBiasTone(event.net_effect)} dot={false}>
            {formatGoldNetBiasLabel(event.net_effect)}
          </FAStatusPill>
        ) : null}
        {event.dominant_driver ? (
          <FAStatusPill tone="info" dot={false}>
            主导：{formatGoldDriverLabel(event.dominant_driver)}
          </FAStatusPill>
        ) : null}
        {missingMixedParts ? (
          <FAStatusPill tone="warn" dot={false}>拆解不完整</FAStatusPill>
        ) : null}
      </div>

      {!compact ? (
        <div className="mt-2 grid gap-2 sm:grid-cols-3">
          <DriverGroup title="利多因素" values={bullishDrivers} tone="up" />
          <DriverGroup title="利空因素" values={bearishDrivers} tone="down" />
          <DriverGroup title="待验证" values={verificationNeeded} tone="warn" />
        </div>
      ) : null}
    </div>
  );
}
