import type { CMEOptionsResponse } from "@/types/cme-options";
import { CME_META_TEXT, formatNumber, toneStyle } from "./cmeOptionsFormat";

export type PriceLadderLevel = {
  strike: number;
  label: string;
  tone: "down" | "up" | "info";
  note: string;
  current?: boolean;
};

export function buildPriceLadderLevels(
  supportResistance: CMEOptionsResponse["support_resistance"],
  currentPrice: number,
): PriceLadderLevel[] {
  const resistances = [...(supportResistance?.resistance ?? [])].sort((a, b) => b.strike - a.strike);
  const supports = [...(supportResistance?.support ?? [])].sort((a, b) => b.strike - a.strike);
  return [
    ...resistances.map((item) => ({
      strike: item.strike,
      label: "阻力",
      tone: "down" as const,
      note: `WallScore ${item.wall_score.toFixed(2)}`,
    })),
    { strike: currentPrice, label: "当前F", tone: "info" as const, note: "现价参照", current: true },
    ...supports.map((item) => ({
      strike: item.strike,
      label: "支撑",
      tone: "up" as const,
      note: `WallScore ${item.wall_score.toFixed(2)}`,
    })),
  ].sort((a, b) => b.strike - a.strike);
}

export function PriceLadderLevelRow({
  level,
  isLast,
}: {
  level: PriceLadderLevel;
  isLast: boolean;
}) {
  const tone = toneStyle(level.tone);

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 9,
        padding: "8px 12px",
        borderBottom: !isLast ? "1px solid var(--border-faint)" : "none",
        background: level.current ? "rgba(59,130,246,0.07)" : "transparent",
        position: "relative",
      }}
    >
      <div style={{ width: 3, height: 26, borderRadius: 2, background: tone.text, flexShrink: 0 }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className="fa-num" style={{ fontSize: 11, color: "var(--fg-1)", fontWeight: 700, fontFamily: "var(--font-mono)" }}>
          {formatNumber(level.strike)}
        </div>
        <div style={{ fontSize: 9, color: CME_META_TEXT, marginTop: 2 }}>{level.note}</div>
      </div>
      <span
        style={{
          padding: "2px 6px",
          borderRadius: 3,
          background: tone.bg,
          border: `1px solid ${tone.border}`,
          color: tone.text,
          fontSize: 9,
          fontWeight: 600,
          whiteSpace: "nowrap",
        }}
      >
        {level.label}
      </span>
      {level.current ? (
        <div style={{ position: "absolute", left: 0, top: "50%", transform: "translateY(-50%)", width: 2, height: "100%", background: "var(--brand-hover)", opacity: 0.7 }} />
      ) : null}
    </div>
  );
}
