/** Presentation-only guards for reader pages. They never alter API payloads. */
export function readingErrorMessage(error: unknown, fallback: string): string {
  const message = error instanceof Error ? error.message : typeof error === "string" ? error : "";
  const normalized = message.trim();
  if (!normalized) return fallback;
  // Fetch errors can echo internal routes, query strings, hosts or credentials.
  // Keep the user-facing state actionable without exposing transport details.
  if (/\/api\/|https?:\/\/|(?:bearer|token|api[_ -]?key|secret)\s*[:=]/i.test(normalized)) return fallback;
  return normalized.length > 240 ? `${normalized.slice(0, 237)}…` : normalized;
}

export function readerAssetLabel(value: string | null | undefined): string {
  const normalized = value?.trim();
  if (normalized === "XAUUSD") return "现货黄金（XAUUSD）";
  if (normalized === "OG") return "黄金期权（OG）";
  if (normalized === "BTCUSD") return "比特币美元（BTCUSD）";
  if (normalized === "EURUSD") return "欧元美元（EURUSD）";
  if (normalized === "DXY") return "美元指数（DXY）";
  if (normalized === "US10Y") return "美国10年期国债收益率（US10Y）";
  return normalized || "未提供资产";
}

export function readerContractMonth(value: string | null | undefined): string {
  const normalized = value?.trim();
  if (!normalized) return "期限未提供";
  const scopeLabels: Record<string, string> = {
    aggregate: "汇总范围",
    full_chain: "全链条",
    nearby_6pct: "主战区（约 ±6%）",
    aggregate_across_expiries: "跨到期月汇总",
  };
  if (scopeLabels[normalized.toLowerCase()]) return scopeLabels[normalized.toLowerCase()];
  const match = normalized.match(/^(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)(\d{2})$/i);
  if (!match) return "未解释期限（技术值见详情）";
  const months: Record<string, string> = { JAN: "1月", FEB: "2月", MAR: "3月", APR: "4月", MAY: "5月", JUN: "6月", JUL: "7月", AUG: "8月", SEP: "9月", OCT: "10月", NOV: "11月", DEC: "12月" };
  const month = match[1].toUpperCase();
  const year = Number(match[2]);
  const fullYear = year >= 70 ? 1900 + year : 2000 + year;
  return `${fullYear}年${months[month]}`;
}
