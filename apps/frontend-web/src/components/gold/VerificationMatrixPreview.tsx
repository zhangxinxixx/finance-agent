import { ShieldAlert } from "lucide-react";

import { formatGoldDriverLabel } from "@/components/shared/goldMainlineFormat";
import type { GoldMacroOverview } from "@/types/gold-mainlines";
import { collectVerificationItems } from "./goldOverviewFormat";

interface VerificationMatrixPreviewProps {
  overview: GoldMacroOverview;
  limit?: number;
}

export function VerificationMatrixPreview({ overview, limit = 5 }: VerificationMatrixPreviewProps) {
  const verificationItems = collectVerificationItems(overview, limit);

  if (!verificationItems.length) return null;

  return (
    <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2.5 py-2">
      <div className="mb-1.5 flex items-center gap-1.5 text-[length:var(--type-caption)] font-semibold text-[var(--fg-5)]">
        <ShieldAlert size={11} />
        <span>待验证</span>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {verificationItems.map((item) => (
          <span key={item} className="rounded-[var(--radius-pill)] border border-[var(--border-faint)] px-2 py-0.5 text-[length:var(--type-caption)] font-semibold text-[var(--fg-3)]">
            {formatGoldDriverLabel(item)}
          </span>
        ))}
      </div>
    </div>
  );
}
