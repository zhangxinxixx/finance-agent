import { ShieldAlert } from "lucide-react";

import { FAStatusPill, type FAStatusTone } from "@/components/shared/FAStatusPill";
import {
  formatGoldDriverLabel,
  formatGoldVerificationStatusLabel,
  goldVerificationStatusTone,
} from "@/components/shared/goldMainlineFormat";
import type { EventFlowTimelineItem } from "@/types/event-flow";
import { MainlineTagGroup } from "./MainlineTagGroup";
import { MixedDriverSplitCard } from "./MixedDriverSplitCard";
import { ProcessingTraceLink } from "./ProcessingTraceLink";
import { TransmissionChainTagGroup } from "./TransmissionChainTagGroup";

interface EventGoldMainlineTraceProps {
  event: EventFlowTimelineItem;
  density?: "compact" | "normal";
}

function hasTrace(event: EventFlowTimelineItem): boolean {
  return Boolean(
    event.primary_mainline ||
    (event.mainlines ?? []).length > 0 ||
    (event.transmission_chains ?? []).length > 0 ||
    event.dominant_driver ||
    (event.bullish_drivers ?? []).length > 0 ||
    (event.bearish_drivers ?? []).length > 0 ||
    (event.verification_needed ?? []).length > 0 ||
    event.verification_chain ||
    event.net_effect ||
    event.changed_dominant_theme,
  );
}

function chainValue(event: EventFlowTimelineItem, key: string): unknown {
  return event.verification_chain && typeof event.verification_chain === "object"
    ? event.verification_chain[key]
    : null;
}

function chainNumber(event: EventFlowTimelineItem, key: string): number | null {
  const value = chainValue(event, key);
  const numeric = typeof value === "number" ? value : Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

function chainBoolean(event: EventFlowTimelineItem, key: string): boolean {
  return chainValue(event, key) === true;
}

function chainStringList(event: EventFlowTimelineItem, key: string): string[] {
  const value = chainValue(event, key);
  return Array.isArray(value) ? value.map((item) => String(item)).filter(Boolean) : [];
}

function verificationChainTone(event: EventFlowTimelineItem): FAStatusTone {
  if (chainBoolean(event, "has_official_source") || chainBoolean(event, "has_multi_source")) return "up";
  if (String(chainValue(event, "required_status") ?? "") === "needs_multi_source") return "warn";
  return event.verification_status ? goldVerificationStatusTone(event.verification_status) : "dim";
}

function verificationChainLabel(event: EventFlowTimelineItem): string {
  if (!event.verification_chain) return "验证链未返回";
  if (chainBoolean(event, "has_official_source")) return "官方源确认";
  if (chainBoolean(event, "has_multi_source")) return "多源确认";
  if (String(chainValue(event, "required_status") ?? "") === "needs_multi_source") return "待多源确认";
  return formatGoldVerificationStatusLabel(String(chainValue(event, "status") ?? event.verification_status ?? "unavailable"));
}

export function EventGoldMainlineTrace({ event, density = "normal" }: EventGoldMainlineTraceProps) {
  if (!hasTrace(event)) return null;

  const verificationChainMissing = chainStringList(event, "missing_confirmations");
  const chainSourceCount = chainNumber(event, "source_count");
  const chainOfficialCount = chainNumber(event, "official_source_count");
  const chainIndependentCount = chainNumber(event, "independent_source_count");
  const compact = density === "compact";

  return (
    <div className={`rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] ${compact ? "px-2 py-1.5" : "px-2.5 py-2"}`}>
      <div className="space-y-2">
        <MainlineTagGroup event={event} density={density} />
        <TransmissionChainTagGroup event={event} density={density} />
        <MixedDriverSplitCard event={event} density={density} />
        <ProcessingTraceLink event={event} density={density} />
      </div>

      {!compact && event.verification_chain ? (
        <div className="mt-2 rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-card)] px-2 py-1.5">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="inline-flex items-center gap-1 text-[9px] font-semibold text-[var(--fg-5)]">
              <ShieldAlert size={10} />
              官方/多源验证链
            </span>
            <FAStatusPill tone={verificationChainTone(event)} dot={false} className="px-[5px] py-[1px] text-[9px]">
              {verificationChainLabel(event)}
            </FAStatusPill>
            {chainSourceCount !== null ? (
              <FAStatusPill tone="neutral" dot={false} className="px-[5px] py-[1px] text-[9px]">
                来源 {chainSourceCount}
              </FAStatusPill>
            ) : null}
            {chainIndependentCount !== null ? (
              <FAStatusPill tone={chainIndependentCount >= 2 ? "up" : "warn"} dot={false} className="px-[5px] py-[1px] text-[9px]">
                独立源 {chainIndependentCount}
              </FAStatusPill>
            ) : null}
            {chainOfficialCount !== null ? (
              <FAStatusPill tone={chainOfficialCount > 0 ? "up" : "dim"} dot={false} className="px-[5px] py-[1px] text-[9px]">
                官方源 {chainOfficialCount}
              </FAStatusPill>
            ) : null}
          </div>
          {verificationChainMissing.length ? (
            <div className="mt-1.5 flex flex-wrap gap-1">
              {verificationChainMissing.slice(0, 5).map((item) => (
                <FAStatusPill key={`${event.id}-chain-${item}`} tone="warn" dot={false} className="px-[5px] py-[1px] text-[9px]">
                  {formatGoldDriverLabel(item)}
                </FAStatusPill>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
