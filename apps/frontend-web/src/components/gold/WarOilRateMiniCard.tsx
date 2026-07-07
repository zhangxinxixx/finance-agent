import { Link } from "react-router-dom";
import { ArrowRight, GitBranch } from "lucide-react";

import { FAStatusPill } from "@/components/shared/FAStatusPill";
import {
  formatGoldNetBiasLabel,
  formatTransmissionPathLabel,
  goldNetBiasTone,
} from "@/components/shared/goldMainlineFormat";
import type { TransmissionChainSummary } from "@/types/gold-mainlines";

interface WarOilRateMiniCardProps {
  chain?: TransmissionChainSummary | null;
}

export function WarOilRateMiniCard({ chain }: WarOilRateMiniCardProps) {
  if (!chain) return null;

  return (
    <div className="rounded-[var(--radius-md)] border border-[var(--warn-border)] bg-[var(--warn-soft)] px-2.5 py-2">
      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-1.5 text-[length:var(--type-caption)] font-semibold text-[var(--warn)]">
          <GitBranch size={11} />
          <span className="truncate">{formatTransmissionPathLabel(chain.path_id)}</span>
        </div>
        {chain.conclusion_code ? (
          <FAStatusPill tone={goldNetBiasTone(chain.net_effect)} dot={false} className="shrink-0">
            {chain.conclusion_code}. {chain.conclusion_label || formatGoldNetBiasLabel(chain.net_effect)}
          </FAStatusPill>
        ) : null}
      </div>
      <p className="mt-1 line-clamp-2 text-[length:var(--type-caption)] leading-5 text-[var(--fg-2)]">
        {chain.summary}
      </p>
      <div className="mt-2 flex justify-end">
        <Link to="/oil-geopolitics" className="inline-flex items-center gap-1 text-[length:var(--type-caption)] font-semibold text-[var(--warn)] no-underline hover:text-[var(--fg-1)]">
          石油地缘链
          <ArrowRight size={11} />
        </Link>
      </div>
    </div>
  );
}
