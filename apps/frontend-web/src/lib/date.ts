const EMPTY = "—";

export function formatDateTime(value: string | number | Date | null | undefined): string {
  if (!value) return EMPTY;
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString("zh-CN", {
    hour12: false,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatTradeDate(value: string | null | undefined): string {
  if (!value) return EMPTY;
  return value;
}

export function sortTradeDatesDesc(dates: string[]): string[] {
  return [...dates].sort((a, b) => b.localeCompare(a));
}

/**
 * Get the most recent trade date (Mon-Fri) for a given date.
 * If the date is Saturday or Sunday, returns the preceding Friday.
 */
export function getLatestTradeDate(date: Date = new Date()): string {
  const d = new Date(date);
  const day = d.getDay(); // 0=Sun, 6=Sat
  if (day === 0) d.setDate(d.getDate() - 2); // Sun → Fri
  if (day === 6) d.setDate(d.getDate() - 1); // Sat → Fri
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${dd}`;
}

/**
 * Check if today is a weekend (Saturday or Sunday).
 */
export function isWeekend(date: Date = new Date()): boolean {
  const day = date.getDay();
  return day === 0 || day === 6;
}
