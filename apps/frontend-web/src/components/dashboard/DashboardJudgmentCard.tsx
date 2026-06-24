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
      className="rounded-[var(--radius-md)]"
      style={{
        background: "var(--bg-card)",
        border: "1px solid var(--border)",
        borderLeft: "3px solid #f59e0b",
      }}
    >
      <div
        className="flex flex-wrap items-center gap-2.5"
        style={{
          background: "var(--bg-panel)",
          padding: "8px 14px",
        }}
      >
        <Star size={12} color="#f59e0b" fill="#f59e0b" />
        <span
          style={{
            fontSize: "12px",
            fontWeight: 600,
            fontFamily: "var(--font-sans)",
            color: "var(--fg-2)",
          }}
        >
          今日综合判断卡
        </span>
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
            <span style={{ fontSize: "8px", color: "var(--fg-5)", letterSpacing: "0.06em" }}>事实审查</span>
            <span style={{ fontSize: "10px", fontWeight: 600, color: reviewTone.color }}>
              {reviewStatusLabel(agentSynthesis.factReviewStatus)}
            </span>
          </div>
        ) : null}
        <div className="flex-1" />
        <div
          className="inline-flex items-center gap-1.5"
          style={{
            padding: "3px 10px",
            background: "rgba(245,158,11,0.08)",
            border: "1px solid rgba(245,158,11,0.20)",
            borderRadius: "3px",
          }}
        >
          <span style={{ fontSize: "8px", color: "var(--fg-5)", letterSpacing: "0.06em" }}>确信度</span>
          <span
            style={{
              fontSize: "16px",
              fontWeight: 700,
              fontFamily: "var(--font-mono)",
              color: "#f59e0b",
              lineHeight: 1,
            }}
          >
            {conviction}
          </span>
          <span style={{ fontSize: "9px", color: "var(--fg-5)" }}>/ 100</span>
        </div>
        <div
          style={{
            padding: "3px 8px",
            background: "rgba(245,158,11,0.10)",
            color: "#f59e0b",
            border: "1px solid rgba(245,158,11,0.25)",
            borderRadius: "3px",
            fontSize: "9px",
            fontWeight: 700,
            letterSpacing: "0.08em",
            textTransform: "uppercase",
          }}
        >
          总览
        </div>
      </div>

      <div
        className="dashboard-judgment-grid"
      >
        <div style={{ minWidth: 0, padding: "14px 14px 14px 16px", borderRight: "1px solid var(--border)" }}>
          <div className="space-y-2">
            <DetailRow label="市场阶段" value={macroPhase} valueColor="#f59e0b" />
            <DetailRow label="黄金状态" value={biasLabel} />
            <DetailRow
              label="交易方向"
              value={directionLabel(direction)}
              valueColor={direction === "bullish" ? "var(--up)" : direction === "bearish" ? "var(--down)" : "var(--fg-3)"}
            />
            <DetailRow label="置信度" value={`${conviction}/100`} valueColor="#f59e0b" />
          </div>

          <div className="mt-3 flex flex-wrap gap-1.5">
            <Chip label={macroPhase} />
            <Chip label={directionLabel(direction)} />
          </div>

          <div
            style={{
              marginTop: "10px",
              padding: "8px 10px",
              borderRadius: "6px",
              border: "1px solid var(--border-faint)",
              background: "var(--bg-card-inner)",
              fontSize: "10px",
              color: "var(--fg-3)",
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
                marginTop: "8px",
                fontSize: "9px",
                color: "var(--fg-5)",
                lineHeight: 1.5,
              }}
            >
              {realtimeHint}
            </div>
          ) : null}
          {agentSynthesis ? (
            <div className="mt-3 flex flex-wrap gap-1.5">
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

        <div style={{ minWidth: 0, padding: "14px 14px", borderRight: "1px solid var(--border)" }}>
          <div className="dashboard-judgment-factor-grid">
            <FactorGroup
              title="主导因子"
              color="#10b981"
              items={triggers}
              icon={<ChevronUp size={10} color="#10b981" style={{ marginTop: "1px", flexShrink: 0 }} />}
            />
            <FactorGroup
              title="压制因子"
              color="#f05252"
              items={invalids}
              icon={<ChevronDown size={10} color="#f05252" style={{ marginTop: "1px", flexShrink: 0 }} />}
            />
          </div>
        </div>

        <div style={{ minWidth: 0, padding: "14px 18px 14px 20px" }}>
          <div
            style={{
              fontSize: "9px",
              color: "#3b82f6",
              letterSpacing: "0.08em",
              textTransform: "uppercase",
              fontWeight: 600,
              marginBottom: "10px",
            }}
          >
            关键价位
          </div>
          <div className="space-y-2">
            {keyLevels.resistance.slice(0, 3).map((price, index) => (
              <LevelRow key={`r-${index}-${price}`} price={price} label="阻力" color="#f05252" />
            ))}
            {keyLevels.support.slice(0, 3).map((price, index) => (
              <LevelRow key={`s-${index}-${price}`} price={price} label="支撑" color="#10b981" />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
