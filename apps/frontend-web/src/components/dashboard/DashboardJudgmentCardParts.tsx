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
    <div className="grid grid-cols-[72px_1fr] items-baseline gap-2">
      <span className="text-[9px] text-[var(--fg-5)] tracking-[0.06em] uppercase font-semibold">
        {label}
      </span>
      <span className="text-[11px] font-semibold" style={{ color: valueColor }}>{value}</span>
    </div>
  );
}

export function Chip({ label }: { label: string }) {
  return (
    <span className="rounded-[var(--radius-pill)] border border-[var(--warn-border)] bg-[var(--warn-soft)] px-2 py-0.5 text-[9px] font-semibold text-[var(--warn)]">
      {label}
    </span>
  );
}

export function MetaPill({ label, tone = "neutral" }: { label: string; tone?: "neutral" | "warn" }) {
  return (
    <span
      className={`rounded-[var(--radius-pill)] border px-2 py-0.5 text-[9px] font-semibold ${
        tone === "warn"
          ? "border-[var(--warn-border)] bg-[var(--warn-soft)] text-[var(--warn)]"
          : "border-[var(--border)] bg-[rgba(255,255,255,0.025)] text-[var(--fg-4)]"
      }`}
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
    <div
      className="h-full rounded-[var(--radius-md)] border p-2.5"
      style={{
        borderColor: `color-mix(in srgb, ${color} 28%, var(--border))`,
        background: `linear-gradient(180deg, color-mix(in srgb, ${color} 9%, transparent), rgba(255,255,255,0.018))`,
      }}
    >
      <div
        className="mb-1.5 flex items-center gap-1.5 text-[9px] tracking-[0.08em] uppercase font-semibold"
        style={{ color }}
      >
        {icon}
        <span>{title}</span>
      </div>
      <div className="space-y-1.5">
        {visibleItems.length > 0 ? (
          visibleItems.map((item, index) => (
            <div key={`${title}-${index}-${item}`} className="flex items-start gap-2 rounded-[var(--radius-sm)] bg-[rgba(0,0,0,0.12)] px-2 py-1">
              {icon}
              <span className="line-clamp-2 text-[10px] leading-5 text-[var(--fg-2)]">{item}</span>
            </div>
          ))
        ) : (
          <div className="text-[10px] text-[var(--fg-5)]">—</div>
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
        className="text-[11px] font-bold font-[var(--font-mono)]"
        style={{ color }}
      >
        {price.toLocaleString("en-US", { maximumFractionDigits: 1 })}
      </span>
      <span className="text-[9px] text-[var(--fg-4)]">{label}</span>
    </div>
  );
}
