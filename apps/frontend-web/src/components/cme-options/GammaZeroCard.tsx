import type { CMEOptionsNetGEXAggregate, CMEOptionsWallScore } from "@/types/cme-options";
import { FACard } from "../shared/FACard";
import { FAStatusPill } from "../shared/FAStatusPill";
import { translateEvidence } from "./cmeOptionsFormat";

interface GammaZeroCardProps {
  netGexAggregate: CMEOptionsNetGEXAggregate;
  wallScores?: CMEOptionsWallScore[];
}

function formatNumber(value: number | null | undefined, fractionDigits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "—";
  }

  return value.toLocaleString("en-US", {
    minimumFractionDigits: fractionDigits,
    maximumFractionDigits: fractionDigits,
  });
}

function formatInteger(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "—";
  }

  return value.toLocaleString("en-US");
}

export function GammaZeroCard({ netGexAggregate, wallScores = [] }: GammaZeroCardProps) {
  const direction = netGexAggregate.net_gex_direction ?? "neutral";
  const gammaZero = netGexAggregate.gamma_zero;

  const callWall = [...wallScores].filter((w) => w.side === "CALL").sort((a, b) => b.wall_score - a.wall_score)[0];
  const putWall = [...wallScores].filter((w) => w.side === "PUT").sort((a, b) => b.wall_score - a.wall_score)[0];
  const directionStyles = {
    positive: "text-[var(--up)]",
    negative: "text-[var(--down)]",
    neutral: "text-[var(--fg-4)]",
  }[direction];
  const directionLabel = {
    positive: "正伽马",
    negative: "负伽马",
    neutral: "中性",
  }[direction];
  const directionStatus = {
    positive: "up",
    negative: "down",
    neutral: "neutral",
  }[direction] as "ok" | "error" | "neutral";

  return (
    <FACard
      title="真实伽马结构"
      eyebrow="伽马核心"
      accent={direction === "positive" ? "up" : direction === "negative" ? "down" : "info"}
      action={<FAStatusPill tone={directionStatus === "ok" ? "up" : directionStatus === "error" ? "down" : "neutral"}>{directionLabel}</FAStatusPill>}
      bodyClassName="space-y-3"
    >
      <div className="grid gap-3 sm:grid-cols-3">
        <div style={{ padding: "12px 14px", background: "var(--bg-card-inner)", border: "1px solid var(--border)", borderLeft: "3px solid var(--brand)", borderRadius: 3 }}>
          <div style={{ fontSize: "var(--text-9)", fontWeight: 600, color: "var(--fg-5)" }}>伽马零点</div>
          <div className="fa-num" style={{ fontSize: "var(--text-18)", fontWeight: 700, color: "var(--fg-1)", marginTop: 6 }}>
            {formatNumber(gammaZero?.price)}
          </div>
          <div style={{ fontSize: "var(--text-10)", color: "var(--fg-5)", marginTop: 4 }}>关键翻转价位</div>
        </div>
        <div style={{ padding: "12px 14px", background: "var(--bg-card-inner)", border: "1px solid var(--border)", borderRadius: 3 }}>
          <div style={{ fontSize: "var(--text-9)", fontWeight: 600, color: "var(--fg-5)" }}>推导方法</div>
          <div className="fa-num" style={{ fontSize: "var(--text-13)", fontWeight: 700, color: "var(--fg-2)", marginTop: 6 }}>
            {translateEvidence(gammaZero?.method?.trim())}
          </div>
          <div style={{ fontSize: "var(--text-10)", color: "var(--fg-5)", marginTop: 4 }}>伽马零点推导方法</div>
        </div>
        <div style={{ padding: "12px 14px", background: direction === "negative" ? "rgba(240,82,82,0.08)" : direction === "positive" ? "rgba(16,185,129,0.08)" : "var(--bg-card-inner)", border: `1px solid ${direction === "negative" ? "rgba(240,82,82,0.25)" : direction === "positive" ? "rgba(16,185,129,0.25)" : "var(--border)"}`, borderLeft: `3px solid ${direction === "negative" ? "var(--down)" : direction === "positive" ? "var(--up)" : "var(--fg-4)"}`, borderRadius: 3 }}>
          <div style={{ fontSize: "var(--text-9)", fontWeight: 600, color: "var(--fg-5)" }}>净伽马敞口</div>
          <div className={`fa-num ${directionStyles}`} style={{ fontSize: "var(--text-18)", fontWeight: 700, marginTop: 6 }}>
            {formatInteger(netGexAggregate.net_gex)}
          </div>
          <div style={{ fontSize: "var(--text-10)", color: "var(--fg-5)", marginTop: 4 }}>净伽马敞口 · {directionLabel}</div>
        </div>
      </div>
      <div style={{ padding: "12px 14px", background: "var(--bg-card-inner)", border: "1px solid var(--border)", borderRadius: 3 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
            <span style={{ fontSize: "var(--text-10)", color: "var(--fg-4)" }}>看跌伽马主导</span>
            <span className={`fa-num ${direction === "negative" ? "text-[var(--down)]" : "text-[var(--fg-5)]"}`} style={{ fontSize: "var(--text-10)", fontWeight: 600 }}>
              {direction === "negative" ? "活跃" : "偏弱"}
            </span>
          </div>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
            <span style={{ fontSize: "var(--text-10)", color: "var(--fg-4)" }}>伽马零点</span>
            <span className="fa-num" style={{ fontSize: "var(--text-11)", fontWeight: 700, color: "var(--fg-2)" }}>{formatNumber(gammaZero?.price, 1)}</span>
          </div>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, paddingTop: 8, borderTop: "1px solid var(--border-faint)" }}>
            <span style={{ fontSize: "var(--text-10)", color: "var(--fg-4)" }}>当前净伽马方向</span>
            <span className={directionStyles} style={{ fontSize: "var(--text-11)", fontWeight: 600 }}>{directionLabel}</span>
          </div>
          {callWall && (
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
              <span style={{ fontSize: 11, color: "var(--fg-4)" }}>看涨压制</span>
              <span className="fa-num" style={{ fontSize: "var(--text-10)", fontWeight: 600, color: "var(--down)" }}>{formatNumber(callWall.strike)} · {callWall.wall_score.toFixed(2)}</span>
            </div>
          )}
          {putWall && (
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
              <span style={{ fontSize: 11, color: "var(--fg-4)" }}>看跌支撑</span>
              <span className="fa-num" style={{ fontSize: "var(--text-10)", fontWeight: 600, color: "var(--up)" }}>{formatNumber(putWall.strike)} · {putWall.wall_score.toFixed(2)}</span>
            </div>
          )}
        </div>
      </div>
    </FACard>
  );
}
