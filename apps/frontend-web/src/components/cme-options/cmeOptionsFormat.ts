import type { CMEOptionsResponse } from "@/types/cme-options";

export const CME_META_TEXT = "#8c9cc8";

export const CME_TONE = {
  up: { text: "var(--up)", bg: "var(--up-soft)", border: "var(--up-border)" },
  down: { text: "var(--down)", bg: "var(--down-soft)", border: "var(--down-border)" },
  warn: { text: "var(--warn)", bg: "var(--warn-soft)", border: "var(--warn-border)" },
  info: { text: "var(--brand-hover)", bg: "rgba(59,130,246,0.12)", border: "rgba(59,130,246,0.24)" },
  violet: { text: "#b388ff", bg: "rgba(167,139,250,0.14)", border: "rgba(167,139,250,0.28)" },
  slate: { text: "var(--fg-3)", bg: "rgba(148,163,184,0.10)", border: "rgba(148,163,184,0.18)" },
} as const;

export function toneStyle(kind: string) {
  return CME_TONE[kind as keyof typeof CME_TONE] || CME_TONE.slate;
}

export function formatNumber(value: number | null | undefined, digits = 0) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function topWall(wallScores: CMEOptionsResponse["wall_scores"], side: "CALL" | "PUT") {
  return [...wallScores].filter((wall) => wall.side === side).sort((a, b) => b.wall_score - a.wall_score)[0] ?? null;
}

export function shortId(value: string | null | undefined): string {
  if (!value) return "—";
  return value.length <= 18 ? value : `${value.slice(0, 8)}…${value.slice(-4)}`;
}

export function translateIntent(text: string | null | undefined): string {
  if (!text) return "—";
  const map: Record<string, string> = {
    "neutral-bullish": "中性偏多",
    "neutral-bearish": "中性偏空",
    bullish: "偏多",
    bearish: "偏空",
    neutral: "中性",
    "Pin Compression": "Pin 压缩",
    "Gamma Squeeze": "Gamma 挤压",
  };
  return map[text] ?? text;
}
