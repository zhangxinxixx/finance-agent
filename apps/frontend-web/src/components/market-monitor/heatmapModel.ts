export interface HeatmapCell {
  key: string;
  name: string;
  symbol: string;
  group: "rates" | "liquidity" | "dollar" | "metals" | "funding";
}

export const HEATMAP_GRID: HeatmapCell[][] = [
  [
    { key: "US10Y", name: "10Y 国债", symbol: "US10Y", group: "rates" },
    { key: "US02Y", name: "2Y 国债", symbol: "US02Y", group: "rates" },
    { key: "REAL_10Y", name: "实际利率", symbol: "TIPS", group: "rates" },
    { key: "T10YIE", name: "通胀预期", symbol: "T10YIE", group: "rates" },
    { key: "YIELD_SPREAD_2Y_3M", name: "短端利差", symbol: "2Y-3M", group: "rates" },
  ],
  [
    { key: "TGA", name: "财政账户", symbol: "TGA", group: "liquidity" },
    { key: "REPO", name: "逆回购", symbol: "REPO", group: "liquidity" },
    { key: "FED_BS", name: "联储BS", symbol: "FedBS", group: "liquidity" },
    { key: "DXY", name: "美元指数", symbol: "DXY", group: "dollar" },
  ],
  [
    { key: "XAUUSD", name: "现货黄金", symbol: "XAU", group: "metals" },
    { key: "XAGUSD", name: "现货白银", symbol: "XAG", group: "metals" },
    { key: "SPX", name: "标普500", symbol: "SPX", group: "funding" },
    { key: "VIX", name: "波动率", symbol: "VIX", group: "funding" },
  ],
  [
    { key: "VIX_FULL", name: "VIX 恐慌指数", symbol: "VIX", group: "funding" },
    { key: "BTC", name: "比特币", symbol: "BTC", group: "funding" },
  ],
];

export function getImpactBg(val: number | string | null | undefined): string {
  if (val === null || val === undefined || val === "") return "rgba(255,255,255,0.02)";
  const num = typeof val === "number" ? val : parseFloat(String(val).replace(/[+,]/g, ""));
  if (!Number.isFinite(num)) return "rgba(255,255,255,0.02)";
  if (num > 1) return "rgba(16,185,129,0.18)";
  if (num > 0) return "rgba(16,185,129,0.10)";
  if (num < -1) return "rgba(240,82,82,0.18)";
  if (num < 0) return "rgba(240,82,82,0.10)";
  return "rgba(255,255,255,0.04)";
}

export function getImpactBorder(val: number | string | null | undefined): string {
  if (val === null || val === undefined || val === "") return "1px solid var(--border)";
  const num = typeof val === "number" ? val : parseFloat(String(val).replace(/[+,]/g, ""));
  if (!Number.isFinite(num)) return "1px solid var(--border)";
  if (num > 0) return "1px solid rgba(16,185,129,0.22)";
  if (num < 0) return "1px solid rgba(240,82,82,0.22)";
  return "1px solid var(--border)";
}

export function getImpactColor(val: number | string | null | undefined): string {
  if (val === null || val === undefined || val === "") return "var(--fg-5)";
  const num = typeof val === "number" ? val : parseFloat(String(val).replace(/[+,]/g, ""));
  if (!Number.isFinite(num)) return "var(--fg-5)";
  if (num > 0) return "#10b981";
  if (num < 0) return "#f05252";
  return "var(--fg-4)";
}
