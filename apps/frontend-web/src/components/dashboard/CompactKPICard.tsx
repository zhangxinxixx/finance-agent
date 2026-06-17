import { FAStatusPill, type FAStatusTone } from "@/components/shared/FAStatusPill";
import { getStatusMeta } from "@/components/shared/statusMeta";
import { Sparkline, mockSparkline } from "./Sparkline";

interface CompactKPICardProps {
  label: string;
  value: string;
  delta?: string;
  trend?: "up" | "down" | "flat";
  unit?: string;
  sparkData?: number[];
  sparkColor?: string;
  accent?: string;
  subtitle?: string;
  impactLabel: "利多黄金" | "利空黄金" | "中性" | "混合" | "数据不足";
  dataStatus: string;
}

const accentDefaults: Record<string, string> = {
  XAUUSD: "#f59e0b",
  DXY: "#3b82f6",
  US10Y: "#06b6d4",
  "REAL 10Y": "#a78bfa",
  "净GEX": "#f59e0b",
  "钉住价位": "#3b82f6",
};

function impactTone(label: CompactKPICardProps["impactLabel"]): FAStatusTone {
  if (label === "利多黄金") return "up";
  if (label === "利空黄金") return "down";
  if (label === "混合") return "warn";
  if (label === "数据不足") return "dim";
  return "neutral";
}

export function CompactKPICard({
  label,
  value,
  delta,
  trend = "flat",
  unit,
  sparkData,
  sparkColor,
  accent,
  subtitle,
  impactLabel,
  dataStatus,
}: CompactKPICardProps) {
  const accentColor = accent ?? accentDefaults[label] ?? "var(--brand)";
  const autoSpark = sparkData ?? mockSparkline(parseFloat(value.replace(/[^0-9.\-]/g, "")) || 100);
  const autoColor = sparkColor ?? (trend === "up" ? "var(--up)" : trend === "down" ? "var(--down)" : accentColor);
  const displaySubtitle = subtitle ?? null;
  const dataStatusMeta = getStatusMeta(dataStatus, { domain: "source" });
  const changeColor =
    trend === "up" ? "var(--up)" : trend === "down" ? "var(--down)" : "var(--fg-5)";

  return (
    <article
      className="relative flex flex-col overflow-hidden"
      style={{
        background: "var(--bg-card)",
        border: "1px solid var(--border)",
        borderRadius: "var(--radius-md)",
        padding: "10px 12px",
        gap: "5px",
      }}
    >
      {/* Top accent bar with glow */}
      <div
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          right: 0,
          height: "2px",
          background: accentColor,
          boxShadow: `0 0 6px ${accentColor}80`,
        }}
      />

      {/* Label row */}
      <div className="flex min-w-0 items-center justify-between gap-2">
        <span
          className="min-w-0 flex-1 truncate"
          style={{
            fontSize: "9px",
            fontWeight: 600,
            lineHeight: 1,
            fontFamily: "var(--font-sans)",
            color: "var(--fg-5)",
            letterSpacing: "0.08em",
            textTransform: "uppercase",
          }}
        >
          {label}
        </span>
        <FAStatusPill tone={impactTone(impactLabel)} dot={false} className="shrink-0 whitespace-nowrap">
          {impactLabel}
        </FAStatusPill>
      </div>

      {/* Value */}
      <div className="flex items-baseline gap-1.5">
        <span
          className="fa-num"
          style={{
            fontSize: "20px",
            fontWeight: 700,
            fontFamily: "var(--font-mono)",
            color: "var(--fg-1)",
            letterSpacing: "-0.02em",
            lineHeight: 1,
          }}
        >
          {value}
        </span>
      </div>

      {/* Unit + change */}
      <div className="flex items-center gap-1.5">
        {unit ? (
          <span style={{ fontSize: "9px", color: "var(--fg-5)" }}>{unit}</span>
        ) : null}
        {delta ? (
          <span
            className="fa-num"
            style={{
              fontSize: "11px",
              fontWeight: 600,
              color: changeColor,
            }}
          >
            {delta}
          </span>
        ) : null}
      </div>

      {/* Sparkline */}
      <div className="mt-auto">
        <Sparkline
          data={autoSpark}
          width={120}
          height={18}
          color={autoColor}
          strokeWidth={1.5}
        />
      </div>

      {/* Subtitle pill */}
      <div className="mt-1 flex min-w-0 items-center justify-between gap-2">
        <div className="min-w-0 flex-1">
          {displaySubtitle ? (
            <div
              title={displaySubtitle}
              className="min-w-0"
              style={{
                display: "inline-flex",
                maxWidth: "100%",
                padding: "2px 7px",
                borderRadius: "3px",
                background: `${accentColor}28`,
                border: `1px solid ${accentColor}70`,
                fontSize: "9px",
                fontWeight: 700,
                color: accentColor,
              }}
            >
              <span className="block min-w-0 truncate">{displaySubtitle}</span>
            </div>
          ) : null}
        </div>
        <FAStatusPill
          status={dataStatus}
          domain="source"
          dot={false}
          title={dataStatusMeta.label}
          className="shrink-0 whitespace-nowrap"
        >
          {dataStatusMeta.label}
        </FAStatusPill>
      </div>
    </article>
  );
}
