import { ShieldAlert } from "lucide-react";

import { FAStatusPill } from "@/components/shared/FAStatusPill";
import {
  formatGoldDriverLabel,
  formatGoldNetBiasLabel,
  goldConflictTone,
  goldNetBiasTone,
} from "@/components/shared/goldMainlineFormat";
import type { DriverConflict } from "@/types/gold-mainlines";

interface DriverConflictCardProps {
  conflict?: DriverConflict | null;
}

function DriverList({ label, values, tone }: { label: string; values: string[]; tone: "up" | "down" | "warn" }) {
  return (
    <div className="min-w-0">
      <div className="fa-label text-[var(--fg-5)]">{label}</div>
      <div className="mt-1 flex flex-wrap gap-1">
        {values.length ? values.slice(0, 4).map((item) => (
          <FAStatusPill key={`${label}-${item}`} tone={tone} dot={false}>
            {formatGoldDriverLabel(item)}
          </FAStatusPill>
        )) : <span className="text-[length:var(--type-caption)] text-[var(--fg-5)]">未返回</span>}
      </div>
    </div>
  );
}

export function DriverConflictCard({ conflict }: DriverConflictCardProps) {
  if (!conflict) return null;

  const mixedIncomplete = conflict.status === "mixed" && (
    conflict.bullish_drivers.length === 0 ||
    conflict.bearish_drivers.length === 0 ||
    !conflict.dominant_driver ||
    conflict.verification_needed.length === 0
  );

  return (
    <div className={`rounded-[var(--radius-md)] border px-2.5 py-2 ${mixedIncomplete ? "border-[var(--warn-border)] bg-[var(--warn-soft)]" : "border-[var(--border-faint)] bg-[var(--bg-card-inner)]"}`}>
      <div className="mb-1.5 flex flex-wrap items-center gap-1.5 text-[length:var(--type-caption)] font-semibold text-[var(--fg-5)]">
        <ShieldAlert size={11} />
        <span>驱动冲突</span>
        <FAStatusPill tone={goldConflictTone(conflict.status)} dot={false}>{conflict.status}</FAStatusPill>
        <FAStatusPill tone={goldNetBiasTone(conflict.net_effect)} dot={false}>{formatGoldNetBiasLabel(conflict.net_effect)}</FAStatusPill>
        {mixedIncomplete ? <FAStatusPill tone="warn" dot={false}>拆解不完整</FAStatusPill> : null}
      </div>
      <div className="grid gap-2 sm:grid-cols-3">
        <DriverList label="利多因素" values={conflict.bullish_drivers} tone="up" />
        <DriverList label="利空因素" values={conflict.bearish_drivers} tone="down" />
        <DriverList label="待验证" values={conflict.verification_needed} tone="warn" />
      </div>
    </div>
  );
}
