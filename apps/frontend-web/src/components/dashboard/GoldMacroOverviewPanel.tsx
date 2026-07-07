import { ArrowRight } from "lucide-react";
import { Link } from "react-router-dom";

import { FAStatusPill } from "@/components/shared/FAStatusPill";
import {
  formatGoldNetBiasLabel,
  formatGoldPhaseLabel,
  goldNetBiasTone,
} from "@/components/shared/goldMainlineFormat";
import { DriverConflictCard } from "@/components/gold/DriverConflictCard";
import { GoldMacroSummaryCard } from "@/components/gold/GoldMacroSummaryCard";
import { TopMainlinesStrip } from "@/components/gold/TopMainlinesStrip";
import { VerificationMatrixPreview } from "@/components/gold/VerificationMatrixPreview";
import { WarOilRateMiniCard } from "@/components/gold/WarOilRateMiniCard";
import type { GoldMacroOverview } from "@/types/gold-mainlines";

interface GoldMacroOverviewPanelProps {
  overview?: GoldMacroOverview | null;
}

export function GoldMacroOverviewPanel({ overview }: GoldMacroOverviewPanelProps) {
  if (!overview) {
    return (
      <section className="fa-card min-h-[178px]">
        <header className="fa-card-header !px-3 !py-2">
          <span className="h-3.5 w-[3px] rounded-[var(--radius-xs)] fa-important-bg" />
          <div className="min-w-0 flex-1">
            <div className="dashboard-cme-micro-label">黄金主线总览</div>
            <div className="mt-0.5 flex flex-wrap items-center gap-2">
              <FAStatusPill tone="warn" dot={false} className="whitespace-nowrap">
                未生成
              </FAStatusPill>
              <span className="truncate text-[length:var(--type-label)] font-semibold text-[var(--fg-2)]">等待后端产物</span>
            </div>
          </div>
        </header>
        <div className="fa-card-body space-y-3" style={{ padding: "9px 12px" }}>
          <GoldMacroSummaryCard overview={overview} />
        </div>
      </section>
    );
  }

  return (
    <section className="fa-card min-h-[232px]">
      <header className="fa-card-header !px-3 !py-2">
        <span className="h-3.5 w-[3px] rounded-[var(--radius-xs)] fa-important-bg" />
        <div className="min-w-0 flex-1">
          <div className="dashboard-cme-micro-label">黄金主线总览</div>
          <div className="mt-0.5 flex flex-wrap items-center gap-2">
            <FAStatusPill tone={goldNetBiasTone(overview.net_bias)} dot={false} className="whitespace-nowrap">
              {formatGoldNetBiasLabel(overview.net_bias)}
            </FAStatusPill>
            <span className="truncate text-[length:var(--type-label)] font-semibold text-[var(--fg-2)]">
              {formatGoldPhaseLabel(overview.phase)}
            </span>
            <span className="fa-num text-[length:var(--type-caption)] text-[var(--fa-text-label)]">{overview.as_of?.slice(0, 10) || "日期未知"}</span>
          </div>
        </div>
      </header>

      <div className="fa-card-body space-y-3" style={{ padding: "9px 12px" }}>
        <GoldMacroSummaryCard overview={overview} />
        <TopMainlinesStrip rankings={overview.theme_rankings ?? []} />
        <DriverConflictCard conflict={overview.driver_conflict} />
        <WarOilRateMiniCard chain={overview.war_oil_rate_chain} />
        <VerificationMatrixPreview overview={overview} />

        <div className="flex justify-end">
          <Link
            to="/gold-mainlines"
            className="inline-flex items-center gap-1.5 rounded-[var(--radius-pill)] border px-2.5 py-1 text-[length:var(--type-caption)] font-semibold tracking-[0] text-[var(--fg-3)] transition-colors hover:border-[var(--border)] hover:bg-[var(--bg-panel)] hover:text-[var(--fg-2)]"
            style={{ borderColor: "var(--border-faint)", background: "var(--bg-card-inner)" }}
          >
            查看主线排序
            <ArrowRight size={11} />
          </Link>
        </div>
      </div>
    </section>
  );
}
