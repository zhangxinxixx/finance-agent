import { GitBranch } from "lucide-react";

import { FACard } from "@/components/shared/FACard";
import { FAStatusPill } from "@/components/shared/FAStatusPill";
import {
  formatGoldNetBiasLabel,
  formatTransmissionPathLabel,
  goldNetBiasTone,
} from "@/components/shared/goldMainlineFormat";
import type {
  GoldMainlineEventLink,
  TransmissionChainSummary,
} from "@/types/gold-mainlines";
import {
  OIL_CHAIN_STEPS,
  chainStepStatus,
  statusTone,
  type TopicMainlineRow,
} from "./oilGeopoliticsModel";

interface WarOilRateChainPanelProps {
  chain: TransmissionChainSummary | null;
  rows: TopicMainlineRow[];
  events: GoldMainlineEventLink[];
}

export function WarOilRateChainPanel({ chain, rows, events }: WarOilRateChainPanelProps) {
  const rowById = new Map(rows.map((row) => [row.id, row]));
  const hasEvents = events.length > 0;
  const fallbackSteps = OIL_CHAIN_STEPS.map((step) => {
    const status = chainStepStatus(rowById.get(step.mainlineId), false, hasEvents);
    return {
      id: step.id,
      label: step.label,
      status: status.label,
      tone: status.tone,
    };
  });

  return (
    <FACard
      title={chain ? formatTransmissionPathLabel(chain.path_id) : "战争-石油-利率链"}
      eyebrow="Chain Board"
      accent="warn"
      className="shrink-0"
      action={chain ? <FAStatusPill tone={goldNetBiasTone(chain.net_effect)} dot={false}>{formatGoldNetBiasLabel(chain.net_effect)}</FAStatusPill> : null}
    >
      {chain ? (
        <div className="grid gap-3">
          <p className="text-[length:var(--type-caption)] leading-5 text-[var(--fg-3)]">{chain.summary}</p>
          <div className="grid gap-1.5">
            {chain.steps.map((step, index) => (
              <div key={step.id} className="flex items-center gap-2 rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2.5 py-1.5 text-[length:var(--type-caption)]">
                <GitBranch size={11} className="text-[var(--warn)]" />
                <span className="fa-num text-[length:var(--type-caption)] text-[var(--fg-5)]">{String(index + 1).padStart(2, "0")}</span>
                <span className="min-w-0 flex-1 truncate font-semibold text-[var(--fg-2)]">{step.label}</span>
                <FAStatusPill tone={statusTone(step.status ?? chain.status)} dot={false}>{step.status ?? chain.status}</FAStatusPill>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <div className="grid gap-3">
          <div className="rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2.5 py-2 text-[length:var(--type-caption)] leading-5 text-[var(--fg-4)]">
            当前 artifact 未返回完整战争-石油-利率传导链，以下显示专题应覆盖的链条节点和数据接入状态。
          </div>
          <div className="grid gap-1.5">
            {fallbackSteps.map((step, index) => (
              <div key={step.id} className="flex items-center gap-2 rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2.5 py-1.5 text-[length:var(--type-caption)]">
                <GitBranch size={11} className="text-[var(--warn)]" />
                <span className="fa-num text-[length:var(--type-caption)] text-[var(--fg-5)]">{String(index + 1).padStart(2, "0")}</span>
                <span className="min-w-0 flex-1 truncate font-semibold text-[var(--fg-2)]">{step.label}</span>
                <FAStatusPill tone={step.tone} dot={false}>{step.status}</FAStatusPill>
              </div>
            ))}
          </div>
        </div>
      )}
    </FACard>
  );
}
