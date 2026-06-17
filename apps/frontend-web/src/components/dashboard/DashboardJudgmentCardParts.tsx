import type { ReactNode } from "react";

export function DetailRow({
  label,
  value,
  valueColor = "var(--fg-2)",
}: {
  label: string;
  value: string;
  valueColor?: string;
}) {
  return (
    <div className="grid" style={{ gridTemplateColumns: "72px 1fr", gap: "8px" }}>
      <span
        style={{
          fontSize: "9px",
          color: "var(--fg-5)",
          letterSpacing: "0.06em",
          textTransform: "uppercase",
          fontWeight: 600,
        }}
      >
        {label}
      </span>
      <span style={{ fontSize: "11px", fontWeight: 600, color: valueColor }}>{value}</span>
    </div>
  );
}

export function Chip({ label }: { label: string }) {
  return (
    <span
      style={{
        padding: "2px 7px",
        borderRadius: "3px",
        background: "rgba(245,158,11,0.10)",
        border: "1px solid rgba(245,158,11,0.28)",
        color: "#f59e0b",
        fontSize: "9px",
        fontWeight: 600,
      }}
    >
      {label}
    </span>
  );
}

export function MetaPill({ label, tone = "neutral" }: { label: string; tone?: "neutral" | "warn" }) {
  return (
    <span
      style={{
        padding: "2px 7px",
        borderRadius: "3px",
        background: tone === "warn" ? "rgba(245,158,11,0.08)" : "var(--bg-card-inner)",
        border: tone === "warn" ? "1px solid rgba(245,158,11,0.22)" : "1px solid var(--border)",
        color: tone === "warn" ? "#f59e0b" : "var(--fg-4)",
        fontSize: "9px",
        fontWeight: 600,
      }}
    >
      {label}
    </span>
  );
}

export function FactorGroup({
  title,
  color,
  items,
  icon,
}: {
  title: string;
  color: string;
  items: string[];
  icon: ReactNode;
}) {
  const visibleItems = items.slice(0, 3);

  return (
    <div className="space-y-2">
      <div
        className="flex items-center gap-1.5"
        style={{
          fontSize: "9px",
          color,
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          fontWeight: 600,
        }}
      >
        {icon}
        <span>{title}</span>
      </div>
      <div className="space-y-1.5">
        {visibleItems.length > 0 ? (
          visibleItems.map((item, index) => (
            <div key={`${title}-${index}-${item}`} className="flex items-start gap-1.5">
              {icon}
              <span className="line-clamp-2 text-[10px] leading-5 text-[var(--fg-2)]">{item}</span>
            </div>
          ))
        ) : (
          <div style={{ fontSize: "10px", color: "var(--fg-5)" }}>—</div>
        )}
      </div>
    </div>
  );
}

export function LevelRow({ price, label, color }: { price: number; label: string; color: string }) {
  return (
    <div className="flex items-center gap-2">
      <div
        style={{
          width: "3px",
          height: "16px",
          borderRadius: "1px",
          background: color,
        }}
      />
      <span
        style={{
          fontSize: "11px",
          fontWeight: 700,
          fontFamily: "var(--font-mono)",
          color,
        }}
      >
        {price.toLocaleString("en-US", { maximumFractionDigits: 1 })}
      </span>
      <span style={{ fontSize: "9px", color: "var(--fg-4)" }}>{label}</span>
    </div>
  );
}
