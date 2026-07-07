import { ShieldAlert } from "lucide-react";

import { FACard } from "@/components/shared/FACard";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import {
  formatGoldDriverLabel,
  formatGoldMainlineLabel,
} from "@/components/shared/goldMainlineFormat";
import type { GoldMacroOverview, VerificationItem } from "@/types/gold-mainlines";
import { statusTone } from "./oilGeopoliticsModel";

interface OilGeoVerificationCardProps {
  overview: GoldMacroOverview;
  items: VerificationItem[];
}

export function OilGeoVerificationCard({ overview, items }: OilGeoVerificationCardProps) {
  const conflictChecks = overview.driver_conflict?.verification_needed ?? [];

  return (
    <FACard title="验证清单" eyebrow="Verification Rail" accent="info" className="shrink-0">
      {items.length || conflictChecks.length ? (
        <div className="grid gap-2">
          {conflictChecks.map((item) => (
            <div key={`conflict-${item}`} className="flex items-start gap-2 rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2.5 py-2">
              <ShieldAlert size={12} className="mt-0.5 shrink-0 text-[var(--warn)]" />
              <div className="min-w-0 flex-1 text-[length:var(--type-caption)] leading-5 text-[var(--fg-3)]">{formatGoldDriverLabel(item)}</div>
            </div>
          ))}
          {items.map((item) => (
            <div key={item.id} className="rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2.5 py-2">
              <div className="flex items-center justify-between gap-2">
                <div className="min-w-0 truncate text-[length:var(--type-caption)] font-semibold text-[var(--fg-2)]">{item.label || item.reason || item.required_source || item.id}</div>
                <FAStatusPill tone={statusTone(item.status)} dot={false}>{item.status}</FAStatusPill>
              </div>
              <div className="mt-1 text-[length:var(--type-caption)] text-[var(--fg-5)]">{item.required_source || formatGoldMainlineLabel(item.mainline_id)}</div>
            </div>
          ))}
        </div>
      ) : (
        <div className="text-[length:var(--type-caption)] text-[var(--fg-4)]">当前主线总览未返回地缘/石油待验证项。</div>
      )}
    </FACard>
  );
}
