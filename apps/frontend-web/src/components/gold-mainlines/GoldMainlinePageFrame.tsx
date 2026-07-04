import type { ReactNode } from "react";
import { RefreshCw } from "lucide-react";

import { FACard } from "@/components/shared/FACard";
import { FAStatusPill, type FAStatusTone } from "@/components/shared/FAStatusPill";
import { getStatusLabel } from "@/components/shared/statusMeta";
import {
  formatGoldNetBiasLabel,
  formatGoldPhaseLabel,
  goldNetBiasTone,
} from "@/components/shared/goldMainlineFormat";
import type { GoldMainlineStatus, GoldNetBias, GoldPhase } from "@/types/gold-mainlines";

export interface GoldTopicMetric {
  label: ReactNode;
  value: ReactNode;
  meta?: ReactNode;
  tone?: FAStatusTone;
}

interface GoldTopicStatusBarProps {
  status: GoldMainlineStatus | string | null | undefined;
  date: string | null | undefined;
  runId?: string | null;
  netBias?: GoldNetBias | string | null;
  phase?: GoldPhase | string | null;
  riskScore?: number | null;
  onRefresh: () => void;
}

interface GoldTopicOverviewCardProps {
  title: ReactNode;
  eyebrow: ReactNode;
  description: ReactNode;
  accent?: "brand" | "up" | "down" | "warn" | "info" | "emphasis" | "none";
  metrics: GoldTopicMetric[];
}

function statusTone(value: string | null | undefined): FAStatusTone {
  if (value === "available" || value === "ok" || value === "confirmed" || value === "official_confirmed" || value === "multi_source") return "up";
  if (value === "partial" || value === "stale" || value === "pending" || value === "single_source" || value === "report_derived") return "warn";
  if (value === "unavailable" || value === "failed" || value === "error") return "down";
  if (value === "unknown") return "dim";
  return "neutral";
}

function compactRunId(value: string): string {
  return value.length > 26 ? `${value.slice(0, 14)}...${value.slice(-8)}` : value;
}

function scoreLabel(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "--";
  return value <= 1 ? `${Math.round(value * 100)}` : `${Math.round(value)}`;
}

function metricToneClass(tone: FAStatusTone | undefined): string {
  if (tone === "up") return "text-[var(--up)]";
  if (tone === "down") return "text-[var(--down)]";
  if (tone === "warn") return "text-[var(--warn)]";
  if (tone === "info") return "text-[var(--info)]";
  if (tone === "dim") return "text-[var(--fg-4)]";
  return "text-[var(--fg-2)]";
}

export function GoldTopicStatusBar({
  status,
  date,
  runId,
  netBias,
  phase,
  riskScore,
  onRefresh,
}: GoldTopicStatusBarProps) {
  const statusValue = String(status || "unknown");

  return (
    <div className="flex min-w-0 flex-wrap items-center justify-between gap-2 rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-card)] px-2.5 py-1.5">
      <div className="flex min-w-0 flex-wrap items-center gap-1.5">
        <FAStatusPill tone={statusTone(statusValue)} dot={false} className="px-1.5 py-[1px] text-[10px]">
          {getStatusLabel(statusValue)}
        </FAStatusPill>
        <FAStatusPill tone="neutral" dot={false} className="px-1.5 py-[1px] text-[10px]">
          {date || "日期未知"}
        </FAStatusPill>
        {netBias ? (
          <FAStatusPill tone={goldNetBiasTone(netBias)} dot={false} className="px-1.5 py-[1px] text-[10px]">
            {formatGoldNetBiasLabel(netBias)}
          </FAStatusPill>
        ) : null}
        {phase ? (
          <FAStatusPill tone="dim" dot={false} className="px-1.5 py-[1px] text-[10px]">
            {formatGoldPhaseLabel(phase)}
          </FAStatusPill>
        ) : null}
        {typeof riskScore === "number" && Number.isFinite(riskScore) ? (
          <FAStatusPill tone="dim" dot={false} className="px-1.5 py-[1px] text-[10px]">
            风险 {scoreLabel(riskScore)}/100
          </FAStatusPill>
        ) : null}
        {runId ? (
          <span
            title={runId}
            className="hidden max-w-[180px] items-center rounded-[var(--radius-pill)] border border-[var(--border-faint)] bg-[var(--bg-panel)] px-1.5 py-[1px] text-[10px] font-semibold leading-[1.35] tracking-[0] text-[var(--fg-4)] sm:inline-flex"
          >
            {compactRunId(runId)}
          </span>
        ) : null}
      </div>
      <button
        type="button"
        onClick={onRefresh}
        className="inline-flex h-7 shrink-0 items-center gap-1.5 rounded-[var(--radius-pill)] border border-[var(--border)] px-2.5 text-[10px] font-semibold text-[var(--fg-2)] transition-colors hover:bg-[var(--bg-panel)]"
      >
        <RefreshCw size={12} />
        <span>刷新</span>
      </button>
    </div>
  );
}

export function GoldTopicOverviewCard({
  title,
  eyebrow,
  description,
  accent = "brand",
  metrics,
}: GoldTopicOverviewCardProps) {
  return (
    <FACard
      title={title}
      eyebrow={eyebrow}
      description={<span className="line-clamp-2">{description}</span>}
      accent={accent}
      density="compact"
      className="shrink-0"
      bodyClassName="!p-2.5"
    >
      <div className="grid gap-1.5 sm:grid-cols-2 xl:grid-cols-4">
        {metrics.map((metric, index) => (
          <div
            key={index}
            className="min-w-0 rounded-[var(--radius-sm)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2.5 py-1.5"
          >
            <div className="truncate text-[10px] font-semibold text-[var(--fg-5)]">{metric.label}</div>
            <div className={`mt-0.5 truncate text-[13px] font-semibold ${metricToneClass(metric.tone)}`}>
              {metric.value}
            </div>
            {metric.meta ? <div className="mt-0.5 truncate text-[10px] text-[var(--fg-5)]">{metric.meta}</div> : null}
          </div>
        ))}
      </div>
    </FACard>
  );
}
