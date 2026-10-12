import type { FAStatusTone } from "@/components/shared/FAStatusPill";
import { readerSource } from "@/lib/readerLabels";

/** Presentation of supplied values only; these helpers do not calculate strategy. */
export function changeTone(value: number | null | undefined, verified = true): FAStatusTone {
  if (!verified || value == null || !Number.isFinite(value)) return "dim";
  return value > 0 ? "up" : value < 0 ? "down" : "neutral";
}

export function biasPresentation(bias: string | null): { label: string; tone: FAStatusTone } {
  return ({ bullish: { label: "偏多", tone: "up" }, bearish: { label: "偏空", tone: "down" },
    neutral: { label: "中性", tone: "neutral" }, mixed: { label: "多空分歧", tone: "warn" },
  } as Record<string, { label: string; tone: FAStatusTone }>)[bias?.toLowerCase() ?? ""] ?? { label: "方向待核验", tone: "warn" };
}

export function scenarioTone(name: string): FAStatusTone {
  if (/^(?:上行|向上|上涨|up\b)/i.test(name.trim())) return "up";
  if (/^(?:下行|向下|下跌|down\b)/i.test(name.trim())) return "down";
  return "warn";
}

export function goldSourceLabel(source: string | null | undefined): string {
  if (source?.startsWith("twelvedata_")) {
    const frame = source.match(/_(5m|15m|1h|4h|1d)$/)?.[1];
    const label = ({ "5m": "5分钟", "15m": "15分钟", "1h": "1小时", "4h": "4小时", "1d": "日线" } as Record<string, string>)[frame ?? ""];
    return label ? `Twelve Data · ${label}现货K线` : "Twelve Data 行情";
  }
  if (source === "jin10_mcp_realtime") return "金十现货报价";
  if (source === "treasury_rates") return "美国财政部";
  return readerSource(source);
}
