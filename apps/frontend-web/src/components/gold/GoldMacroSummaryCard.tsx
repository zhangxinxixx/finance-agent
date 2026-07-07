import { Link } from "react-router-dom";
import { ArrowRight } from "lucide-react";

import { FAStatusPill } from "@/components/shared/FAStatusPill";
import {
  formatGoldDriverLabel,
  formatGoldMainlineLabel,
  formatGoldNetBiasLabel,
  formatGoldPhaseLabel,
  goldConflictTone,
  goldNetBiasTone,
} from "@/components/shared/goldMainlineFormat";
import type { GoldMacroOverview } from "@/types/gold-mainlines";
import { formatGoldScore } from "./goldOverviewFormat";

interface GoldMacroSummaryCardProps {
  overview?: GoldMacroOverview | null;
}

const FALLBACK_LINKS = [
  { to: "/gold-mainlines", label: "黄金主线排序" },
  { to: "/rates-dollar", label: "利率与美元" },
  { to: "/oil-geopolitics", label: "石油与地缘" },
];

export function GoldMacroSummaryCard({ overview }: GoldMacroSummaryCardProps) {
  if (!overview) {
    return (
      <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2.5 py-2">
        <div className="mb-1.5 text-[length:var(--type-caption)] font-semibold text-[var(--fg-5)]">主线入口</div>
        <p className="text-[length:var(--type-caption)] leading-5 text-[var(--fg-3)]">
          当前黄金主线总览产物暂不可用；先保留右栏入口，用于快速进入三条专题链路。
        </p>
        <div className="mt-3 grid gap-1.5">
          {FALLBACK_LINKS.map((item) => (
            <Link
              key={item.to}
              to={item.to}
              className="inline-flex items-center justify-between gap-2 rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2.5 py-1.5 text-[length:var(--type-caption)] font-semibold text-[var(--fg-3)] no-underline transition-colors hover:border-[var(--border)] hover:bg-[var(--bg-panel)] hover:text-[var(--fg-2)]"
            >
              <span>{item.label}</span>
              <ArrowRight size={11} />
            </Link>
          ))}
        </div>
      </div>
    );
  }

  const conflict = overview.driver_conflict;

  return (
    <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2.5 py-2">
      <div className="flex items-center justify-between gap-2">
        <span className="dashboard-cme-micro-label">主导主线</span>
        <span className="fa-num text-[length:var(--type-caption)] text-[var(--fa-text-label)]">风险 {formatGoldScore(overview.risk_score)}/100</span>
      </div>
      <div className="mt-1 flex min-w-0 flex-wrap items-center gap-1.5">
        <FAStatusPill tone="info" dot={false}>
          {formatGoldMainlineLabel(overview.dominant_mainline)}
        </FAStatusPill>
        <FAStatusPill tone={goldNetBiasTone(overview.net_bias)} dot={false}>
          {formatGoldNetBiasLabel(overview.net_bias)}
        </FAStatusPill>
        <FAStatusPill tone="neutral" dot={false}>
          {formatGoldPhaseLabel(overview.phase)}
        </FAStatusPill>
        {conflict?.dominant_driver ? (
          <FAStatusPill tone={goldConflictTone(conflict.status)} dot={false}>
            {formatGoldDriverLabel(conflict.dominant_driver)}
          </FAStatusPill>
        ) : null}
      </div>
      <p className="mt-2 line-clamp-2 text-[length:var(--type-caption)] leading-5 text-[var(--fg-3)]">
        {overview.one_line_conclusion || conflict?.explanation || "后端暂未返回主线结论。"}
      </p>
      {overview.priority_reason ? (
        <p className="mt-1 line-clamp-2 text-[length:var(--type-caption)] leading-4 text-[var(--fg-5)]">
          {overview.priority_reason}
        </p>
      ) : null}
    </div>
  );
}
