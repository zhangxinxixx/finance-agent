export function translateIntent(text: string | null | undefined): string {
  if (!text) return "—";

  const map: Record<string, string> = {
    "neutral-bullish": "中性偏多",
    "neutral-bearish": "中性偏空",
    bullish: "偏多",
    bearish: "偏空",
    neutral: "中性",
    unavailable: "不可用",
    I1_defensive: "防守结构",
    I2_balanced: "均衡结构",
    I2_structured_rebalance: "结构再平衡",
    i2_structured_rebalance: "结构再平衡",
    l2_structured_rebalance: "结构再平衡",
    structured_rebalance: "结构再平衡",
    I3_breakout: "突破结构",
    I4_squeeze: "挤压结构",
  };

  return map[text] ?? text;
}

export function getConfidenceColor(confidenceLevel: string): string {
  return confidenceLevel === "high" ? "var(--up)" : confidenceLevel === "medium" ? "var(--warn)" : "var(--down)";
}

export function getWallBias(wallScore: number | null): { label: string; color: string } {
  if (wallScore == null) return { label: "未知", color: "var(--fg-5)" };
  if (wallScore > 0.6) return { label: "阻力主导", color: "var(--down)" };
  if (wallScore < 0.4) return { label: "支撑主导", color: "var(--up)" };
  return { label: "均衡", color: "var(--fg-5)" };
}

export function formatOptionalNumber(
  value: number | null,
  maximumFractionDigits: number,
): string {
  return value != null
    ? value.toLocaleString("en-US", { maximumFractionDigits })
    : "—";
}

export function getConfidenceNote(confidenceLevel: string): string {
  if (confidenceLevel === "high") return "数据较新，可作为主要参考";
  if (confidenceLevel === "medium") return "数据存在一定滞后，结合盘面使用";
  return "数据滞后且为初步数据，仅作辅助参考";
}
