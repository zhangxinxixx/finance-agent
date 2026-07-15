import type { CMEOptionsDecisionGammaSummary, CMEOptionsNetGEXAggregate, CMEOptionsWallScore } from "@/types/cme-options";
import { FACard } from "../shared/FACard";
import { FAStatusPill } from "../shared/FAStatusPill";
import { formatCompactNumber, translateDecisionText } from "./cmeOptionsFormat";

interface GammaZeroCardProps {
  netGexAggregate?: CMEOptionsNetGEXAggregate | null;
  decisionGamma?: CMEOptionsDecisionGammaSummary | null;
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

export function GammaZeroCard({ netGexAggregate, decisionGamma, wallScores = [] }: GammaZeroCardProps) {
  const snapshotDirection = netGexAggregate?.net_gex_direction === "negative" || netGexAggregate?.net_gex_direction === "positive" || netGexAggregate?.net_gex_direction === "neutral"
    ? netGexAggregate.net_gex_direction
    : null;
  const decisionDirection = decisionGamma?.regime === "negative_gamma"
    ? "negative"
    : decisionGamma?.regime === "positive_gamma"
      ? "positive"
      : decisionGamma?.regime === "flip_zone"
        ? "neutral"
        : null;
  const direction = snapshotDirection ?? decisionDirection;
  const gammaZero = netGexAggregate?.gamma_zero ?? (decisionGamma?.gamma_zero != null
    ? { price: decisionGamma.gamma_zero, method: decisionGamma.method }
    : null);
  const netGex = netGexAggregate?.net_gex ?? decisionGamma?.net_gex;

  const callWall = [...wallScores].filter((w) => w.side === "CALL").sort((a, b) => b.wall_score - a.wall_score)[0];
  const putWall = [...wallScores].filter((w) => w.side === "PUT").sort((a, b) => b.wall_score - a.wall_score)[0];
  const directionStyles = direction === null ? "text-[var(--fg-5)]" : {
    positive: "text-[var(--up)]",
    negative: "text-[var(--down)]",
    neutral: "text-[var(--fg-4)]",
  }[direction];
  const directionLabel = direction === null ? "未提供" : {
    positive: "正伽马",
    negative: "负伽马",
    neutral: "中性",
  }[direction];
  const directionStatus = direction === null ? "neutral" : {
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
          <div style={{ fontSize: "var(--type-label)", fontWeight: 600, color: "var(--fg-5)" }}>伽马零点</div>
          <div className="fa-num" style={{ fontSize: "var(--text-18)", fontWeight: 700, color: "var(--fg-1)", marginTop: 6 }}>
            {formatNumber(gammaZero?.price)} 点
          </div>
          <div style={{ fontSize: "var(--type-body-sm)", color: "var(--fg-5)", marginTop: 4 }}>关键翻转价位</div>
        </div>
        <div style={{ padding: "12px 14px", background: "var(--bg-card-inner)", border: "1px solid var(--border)", borderRadius: 3 }}>
          <div style={{ fontSize: "var(--type-label)", fontWeight: 600, color: "var(--fg-5)" }}>推导方法</div>
          <div className="fa-num" style={{ fontSize: "var(--type-card-title)", fontWeight: 700, color: "var(--fg-2)", marginTop: 6 }}>
            {translateDecisionText(gammaZero?.method?.trim())}
          </div>
          <div style={{ fontSize: "var(--type-body-sm)", color: "var(--fg-5)", marginTop: 4 }}>伽马零点推导方法</div>
        </div>
        <div style={{ padding: "12px 14px", background: direction === "negative" ? "rgba(240,82,82,0.08)" : direction === "positive" ? "rgba(16,185,129,0.08)" : "var(--bg-card-inner)", border: `1px solid ${direction === "negative" ? "rgba(240,82,82,0.25)" : direction === "positive" ? "rgba(16,185,129,0.25)" : "var(--border)"}`, borderLeft: `3px solid ${direction === "negative" ? "var(--down)" : direction === "positive" ? "var(--up)" : "var(--fg-4)"}`, borderRadius: 3 }}>
          <div style={{ fontSize: "var(--type-label)", fontWeight: 600, color: "var(--fg-5)" }}>净伽马敞口</div>
          <div className={`fa-num ${directionStyles}`} style={{ fontSize: "var(--text-18)", fontWeight: 700, marginTop: 6 }}>
            {formatCompactNumber(netGex)}
          </div>
          <div style={{ fontSize: "var(--type-body-sm)", color: "var(--fg-5)", marginTop: 4 }}>净伽马敞口 · {directionLabel}</div>
        </div>
      </div>
      <div style={{ padding: "12px 14px", background: "var(--bg-card-inner)", border: "1px solid var(--border)", borderRadius: 3 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
            <span style={{ fontSize: "var(--type-body-sm)", color: "var(--fg-4)" }}>看跌伽马状态</span>
            <span className={`fa-num ${direction === "negative" ? "text-[var(--down)]" : "text-[var(--fg-5)]"}`} style={{ fontSize: "var(--type-body-sm)", fontWeight: 600 }}>
              {direction === null ? "未提供" : direction === "negative" ? "活跃" : "偏弱"}
            </span>
          </div>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
            <span style={{ fontSize: "var(--type-body-sm)", color: "var(--fg-4)" }}>伽马零点</span>
            <span className="fa-num" style={{ fontSize: "var(--type-subtitle)", fontWeight: 700, color: "var(--fg-2)" }}>{formatNumber(gammaZero?.price, 1)} 点</span>
          </div>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, paddingTop: 8, borderTop: "1px solid var(--border-faint)" }}>
            <span style={{ fontSize: "var(--type-body-sm)", color: "var(--fg-4)" }}>当前净伽马方向</span>
            <span className={directionStyles} style={{ fontSize: "var(--type-subtitle)", fontWeight: 600 }}>{directionLabel}</span>
          </div>
          {callWall && (
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
              <span style={{ fontSize: "var(--type-body-sm)", color: "var(--fg-4)" }}>看涨压制</span>
              <span className="fa-num" style={{ fontSize: "var(--type-body-sm)", fontWeight: 600, color: "var(--down)" }}>{formatNumber(callWall.strike)} 点 · 评分 {callWall.wall_score.toFixed(2)}</span>
            </div>
          )}
          {putWall && (
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
              <span style={{ fontSize: "var(--type-body-sm)", color: "var(--fg-4)" }}>看跌支撑</span>
              <span className="fa-num" style={{ fontSize: "var(--type-body-sm)", fontWeight: 600, color: "var(--up)" }}>{formatNumber(putWall.strike)} 点 · 评分 {putWall.wall_score.toFixed(2)}</span>
            </div>
          )}
        </div>
      </div>
    </FACard>
  );
}
