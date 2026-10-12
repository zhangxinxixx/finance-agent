import { formatNumber } from "./cmeOptionsFormat";

export function formatGEXM(value: number) {
  if (!Number.isFinite(value)) return "—";
  const abs = Math.abs(value);
  if (abs >= 1e6) return `${(value / 1e6).toFixed(1)}百万`;
  if (abs >= 1e3) return `${(value / 1e3).toFixed(1)}千`;
  return value.toFixed(0);
}

export function formatBillions(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return "—";
  const abs = Math.abs(value);
  if (abs >= 1e9) return `${(value / 1e9).toFixed(2)}十亿`;
  if (abs >= 1e6) return `${(value / 1e6).toFixed(1)}百万`;
  return formatNumber(value);
}
