import { readableWarning } from "@/lib/researchReading";
import type { CMEOptionsResponse } from "@/types/cme-options";
import { CME_META_TEXT, formatNumber, isFiniteNumber, toneStyle } from "./cmeOptionsFormat";

export type PriceLadderLevel = {
  strike: number;
  label: string;
  tone: "down" | "up" | "info";
  note: string;
  current?: boolean;
};

function distanceNote(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(value)) return "距离未提供";
  return `距接口参考价 ${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}

export function buildPriceLadderLevels(
  supportResistance: CMEOptionsResponse["support_resistance"],
  currentPrice: number | null,
  currentLabel = "黄金期货（GC）报告锚点",
  currentNote = "黄金期货（GC）报告基准（非实时现货）",
): PriceLadderLevel[] {
  const validLevels = (levels: CMEOptionsResponse["support_resistance"]["support"]) => levels
    .filter((item): item is typeof item & { strike: number } => isFiniteNumber(item.strike));
  const resistances = validLevels(supportResistance?.resistance ?? []);
  const supports = validLevels(supportResistance?.support ?? []);
  const anchor = currentPrice !== null && Number.isFinite(currentPrice)
    ? [{ strike: currentPrice, label: currentLabel, tone: "info" as const, note: currentNote, current: true }]
    : [];
  return [
    ...resistances.map((item) => ({
      strike: item.strike,
      label: "阻力",
      tone: "down" as const,
      note: `墙位评分 ${formatNumber(item.wall_score, 2)} · ${distanceNote(item.distance_pct)}`,
    })),
    ...anchor,
    ...supports.map((item) => ({
      strike: item.strike,
      label: "支撑",
      tone: "up" as const,
      note: `墙位评分 ${formatNumber(item.wall_score, 2)} · ${distanceNote(item.distance_pct)}`,
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
        <div className="fa-num" style={{ fontSize: "var(--text-10)", color: "var(--fg-1)", fontWeight: 700 }}>
          {formatNumber(level.strike)}
        </div>
        <div style={{ fontSize: "var(--text-9)", color: CME_META_TEXT, marginTop: 2 }}>{readableWarning(level.note)}</div>
      </div>
      <span
        style={{
          padding: "2px 6px",
          borderRadius: 3,
          background: tone.bg,
          border: `1px solid ${tone.border}`,
          color: tone.text,
          fontSize: "var(--text-9)",
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
