import type { CMEOptionsNetGEXAggregate, CMEOptionsWallScore } from "@/types/cme-options";
import { FACard } from "../shared/FACard";
import { FAStatusPill } from "../shared/FAStatusPill";

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
    positive: "正 Gamma",
    negative: "负 Gamma",
    neutral: "中性",
  }[direction];
  const directionStatus = {
    positive: "up",
    negative: "down",
    neutral: "neutral",
  }[direction] as "ok" | "error" | "neutral";

  return (
    <FACard
      title="真实 GEX 结构"
      eyebrow="GEX Core"
      accent={direction === "positive" ? "up" : direction === "negative" ? "down" : "info"}
      action={<FAStatusPill tone={directionStatus === "ok" ? "up" : directionStatus === "error" ? "down" : "neutral"}>{directionLabel}</FAStatusPill>}
      bodyClassName="space-y-3"
    >
      <div className="grid gap-3 sm:grid-cols-3">
        <div style={{ padding: "12px 14px", background: "var(--bg-card-inner)", border: "1px solid var(--border)", borderLeft: "3px solid var(--brand)", borderRadius: 3 }}>
          <div style={{ fontSize: 9, fontWeight: 600, color: "var(--fg-5)", letterSpacing: "0.08em", textTransform: "uppercase" }}>gz_price</div>
          <div className="fa-num" style={{ fontSize: 18, fontWeight: 700, color: "var(--fg-1)", fontFamily: "var(--font-mono)", letterSpacing: "-0.02em", marginTop: 6 }}>
            {formatNumber(gammaZero?.price)}
          </div>
          <div style={{ fontSize: 10, color: "var(--fg-5)", marginTop: 4 }}>关键翻转价位</div>
        </div>
        <div style={{ padding: "12px 14px", background: "var(--bg-card-inner)", border: "1px solid var(--border)", borderRadius: 3 }}>
          <div style={{ fontSize: 9, fontWeight: 600, color: "var(--fg-5)", letterSpacing: "0.08em", textTransform: "uppercase" }}>method</div>
          <div className="fa-num" style={{ fontSize: 14, fontWeight: 700, color: "var(--fg-2)", fontFamily: "var(--font-mono)", letterSpacing: "-0.02em", marginTop: 6 }}>
            {gammaZero?.method?.trim() || "—"}
          </div>
          <div style={{ fontSize: 10, color: "var(--fg-5)", marginTop: 4 }}>Gamma Zero 推导方法</div>
        </div>
        <div style={{ padding: "12px 14px", background: direction === "negative" ? "rgba(240,82,82,0.08)" : direction === "positive" ? "rgba(16,185,129,0.08)" : "var(--bg-card-inner)", border: `1px solid ${direction === "negative" ? "rgba(240,82,82,0.25)" : direction === "positive" ? "rgba(16,185,129,0.25)" : "var(--border)"}`, borderLeft: `3px solid ${direction === "negative" ? "var(--down)" : direction === "positive" ? "var(--up)" : "var(--fg-4)"}`, borderRadius: 3 }}>
          <div style={{ fontSize: 9, fontWeight: 600, color: "var(--fg-5)", letterSpacing: "0.08em", textTransform: "uppercase" }}>net_gex</div>
          <div className={`fa-num ${directionStyles}`} style={{ fontSize: 18, fontWeight: 700, fontFamily: "var(--font-mono)", letterSpacing: "-0.02em", marginTop: 6 }}>
            {formatInteger(netGexAggregate.net_gex)}
          </div>
          <div style={{ fontSize: 10, color: "var(--fg-5)", marginTop: 4 }}>净 Gamma Exposure · {directionLabel}</div>
        </div>
      </div>
      <div style={{ padding: "12px 14px", background: "var(--bg-card-inner)", border: "1px solid var(--border)", borderRadius: 3 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
            <span style={{ fontSize: 11, color: "var(--fg-4)" }}>Put GEX 主导</span>
            <span className={`fa-num ${direction === "negative" ? "text-[var(--down)]" : "text-[var(--fg-5)]"}`} style={{ fontSize: 11, fontWeight: 600, fontFamily: "var(--font-mono)" }}>
              {direction === "negative" ? "Active" : "Weak"}
            </span>
          </div>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
            <span style={{ fontSize: 11, color: "var(--fg-4)" }}>Gamma Zero</span>
            <span className="fa-num" style={{ fontSize: 12, fontWeight: 700, color: "var(--fg-2)", fontFamily: "var(--font-mono)" }}>{formatNumber(gammaZero?.price, 1)}</span>
          </div>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, paddingTop: 8, borderTop: "1px solid var(--border-faint)" }}>
            <span style={{ fontSize: 11, color: "var(--fg-4)" }}>当前净 GEX 方向</span>
            <span className={directionStyles} style={{ fontSize: 12, fontWeight: 600 }}>{directionLabel}</span>
          </div>
          {callWall && (
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
              <span style={{ fontSize: 11, color: "var(--fg-4)" }}>Call Resistance</span>
              <span className="fa-num" style={{ fontSize: 11, fontWeight: 600, color: "var(--down)", fontFamily: "var(--font-mono)" }}>{formatNumber(callWall.strike)} · {callWall.wall_score.toFixed(2)}</span>
            </div>
          )}
          {putWall && (
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
              <span style={{ fontSize: 11, color: "var(--fg-4)" }}>Put Support</span>
              <span className="fa-num" style={{ fontSize: 11, fontWeight: 600, color: "var(--up)", fontFamily: "var(--font-mono)" }}>{formatNumber(putWall.strike)} · {putWall.wall_score.toFixed(2)}</span>
            </div>
          )}
        </div>
      </div>
    </FACard>
  );
}
