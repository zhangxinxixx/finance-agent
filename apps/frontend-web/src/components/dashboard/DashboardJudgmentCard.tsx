import { ChevronDown, ChevronUp, Star } from "lucide-react";
import type { DashboardAgentCompactSummary, SignalDirection, StrategyCardData } from "@/types/dashboard";
import { directionLabel, reviewStatusLabel, reviewStatusTone } from "@/components/dashboard/judgmentFormat";
import {
  Chip,
  DetailRow,
  FactorGroup,
  LevelRow,
  MetaPill,
} from "@/components/dashboard/DashboardJudgmentCardParts";

export function DashboardJudgmentCard({
  direction,
  confidence,
  macroPhase,
  biasLabel,
  compactSummary,
  realtimeHint,
  triggers,
  invalids,
  keyLevels,
  agentSynthesis,
}: {
  direction: SignalDirection;
  confidence: number | null;
  macroPhase: string;
  biasLabel: string;
  compactSummary: string;
  realtimeHint: string | null;
  triggers: string[];
  invalids: string[];
  keyLevels: StrategyCardData["key_levels"];
  agentSynthesis: DashboardAgentCompactSummary | null | undefined;
}) {
  const reviewTone = reviewStatusTone(agentSynthesis?.factReviewStatus);
  const conviction = confidence != null ? Math.round(confidence * 100) : 0;

  return (
    <div
      className="relative overflow-hidden rounded-[var(--radius-lg)] shadow-[0_18px_36px_rgba(0,0,0,0.22),inset_0_1px_0_rgba(255,255,255,0.045)]"
      style={{
        background:
          "linear-gradient(135deg, rgba(245,158,11,0.12), transparent 28%), linear-gradient(180deg, rgba(255,255,255,0.045), rgba(255,255,255,0.01)), var(--bg-card)",
        border: "1px solid color-mix(in srgb, var(--warn) 34%, var(--border))",
      }}
    >
      <div className="pointer-events-none absolute inset-x-0 top-0 h-[2px] bg-[linear-gradient(90deg,var(--warn),rgba(245,158,11,0.15),transparent)]" />
      <div
        className="flex flex-wrap items-center gap-2.5"
        style={{
          background: "linear-gradient(180deg, rgba(245,158,11,0.08), rgba(12,23,40,0.72))",
          padding: "7px 12px",
          borderBottom: "1px solid var(--border)",
        }}
      >
        <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-[var(--radius-md)] border border-[var(--warn-border)] bg-[var(--warn-soft)] shadow-[0_0_18px_rgba(245,158,11,0.14)]">
          <Star size={13} color="var(--warn)" fill="var(--warn)" />
        </span>
        <div className="min-w-0">
          <div className="text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--warn)]">Decision Card</div>
          <div className="text-[13px] font-bold leading-tight text-[var(--fg-1)]">今日综合判断卡</div>
        </div>
        {agentSynthesis?.factReviewStatus ? (
          <div
            className="inline-flex items-center gap-1.5"
            style={{
              padding: "3px 8px",
              borderRadius: "3px",
              background: reviewTone.background,
              border: reviewTone.border,
            }}
          >
            <span className="text-[8px] text-[var(--fg-5)] tracking-[0.06em]">事实审查</span>
            <span className="text-[10px] font-semibold" style={{ color: reviewTone.color }}>
              {reviewStatusLabel(agentSynthesis.factReviewStatus)}
            </span>
          </div>
        ) : null}
        <div className="flex-1" />
        <div
          className="inline-flex items-center gap-2 shadow-[inset_0_1px_0_rgba(255,255,255,0.05)]"
          style={{
            padding: "3px 9px",
            background: "var(--warn-soft)",
            border: "1px solid var(--warn-border)",
            borderRadius: "var(--radius-md)",
          }}
        >
          <span className="text-[8px] text-[var(--fg-5)] tracking-[0.06em]">确信度</span>
          <span className="text-[17px] font-bold font-[var(--font-mono)] text-[var(--warn)] leading-none">
            {conviction}
          </span>
          <span className="text-[9px] text-[var(--fg-5)]">/ 100</span>
        </div>
        <div
          className="text-[9px] font-bold tracking-[0.08em] uppercase text-[var(--warn)]"
          style={{
            padding: "3px 8px",
            background: "var(--warn-soft)",
            border: "1px solid var(--warn-border)",
            borderRadius: "3px",
          }}
        >
          总览
        </div>
      </div>

      <div
        className="dashboard-judgment-grid"
      >
        <div className="min-w-0 p-2.5" style={{ borderRight: "1px solid var(--border)" }}>
          <div className="rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[rgba(255,255,255,0.025)] p-2.5">
          <div className="space-y-1.5">
            <DetailRow label="市场阶段" value={macroPhase} valueColor="var(--warn)" />
            <DetailRow label="黄金状态" value={biasLabel} />
            <DetailRow
              label="交易方向"
              value={directionLabel(direction)}
              valueColor={direction === "bullish" ? "var(--up)" : direction === "bearish" ? "var(--down)" : "var(--fg-3)"}
            />
            <DetailRow label="置信度" value={`${conviction}/100`} valueColor="var(--warn)" />
          </div>

          <div className="mt-2 flex flex-wrap gap-1.5">
            <Chip label={macroPhase} />
            <Chip label={directionLabel(direction)} />
          </div>

          <div
            style={{
              marginTop: "8px",
              padding: "6px 9px",
              borderRadius: "var(--radius-md)",
              border: "1px solid var(--warn-border)",
              background: "linear-gradient(180deg, var(--warn-soft), rgba(255,255,255,0.018))",
              fontSize: "10px",
              color: "var(--fg-2)",
              lineHeight: 1.4,
            }}
          >
            <div className="truncate" title={compactSummary}>
              {compactSummary}
            </div>
          </div>
          {realtimeHint ? (
            <div
              style={{
                marginTop: "6px",
                fontSize: "9px",
                color: "var(--fg-5)",
                lineHeight: 1.5,
              }}
            >
              {realtimeHint}
            </div>
          ) : null}
          {agentSynthesis ? (
            <div className="mt-2 flex flex-wrap gap-1.5">
              <MetaPill label={`已汇总 ${agentSynthesis.claimCount} 条判断`} />
              {agentSynthesis.invalidConditions.length > 0 ? (
                <MetaPill
                  label={`待跟踪 ${agentSynthesis.invalidConditions.length}`}
                  tone="warn"
                />
              ) : null}
            </div>
          ) : null}
          </div>
        </div>

        <div className="min-w-0 p-2.5" style={{ borderRight: "1px solid var(--border)" }}>
          <div className="dashboard-judgment-factor-grid">
            <FactorGroup
              title="主导因子"
              color="var(--up)"
              items={triggers}
              icon={<ChevronUp size={10} color="var(--up)" style={{ marginTop: "1px", flexShrink: 0 }} />}
            />
            <FactorGroup
              title="压制因子"
              color="var(--down)"
              items={invalids}
              icon={<ChevronDown size={10} color="var(--down)" style={{ marginTop: "1px", flexShrink: 0 }} />}
            />
          </div>
        </div>

        <div className="min-w-0 p-2.5">
          <div className="h-full rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[rgba(255,255,255,0.02)] p-2.5">
          <div
            className="text-[9px] text-[var(--info)] tracking-[0.08em] uppercase font-semibold"
            style={{ marginBottom: "8px" }}
          >
            关键价位
          </div>
          <div className="space-y-2">
            {keyLevels.resistance.slice(0, 3).map((price, index) => (
              <LevelRow key={`r-${index}-${price}`} price={price} label="阻力" color="var(--down)" />
            ))}
            {keyLevels.support.slice(0, 3).map((price, index) => (
              <LevelRow key={`s-${index}-${price}`} price={price} label="支撑" color="var(--up)" />
            ))}
          </div>
          </div>
        </div>
      </div>
    </div>
  );
}
