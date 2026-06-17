import { FAStatusPill, type FAStatusTone } from "@/components/shared/FAStatusPill";

interface SourceGaugeProps {
  total: number;
  available: number;
  partial: number;
  error: number;
}

function statusTone(count: number): FAStatusTone {
  if (count === 0) return "dim";
  return "up";
}

export function SourceGauge({ total, available, partial, error }: SourceGaugeProps) {
  const radius = 30;
  const stroke = 4;
  const circumference = 2 * Math.PI * radius;
  const pct = total > 0 ? available / total : 0;
  const offset = circumference * (1 - pct);

  const gaugeColor =
    pct >= 0.8 ? "var(--up)" : pct >= 0.5 ? "var(--warn)" : "var(--down)";

  return (
    <div className="flex flex-col items-center justify-center gap-1 rounded-[var(--radius-lg)] border border-[var(--border)] bg-[var(--bg-card)] px-2 py-1.5 w-full h-full">
      <div className="relative">
        <svg width="68" height="68" viewBox="0 0 68 68">
          <circle
            cx="34"
            cy="34"
            r={radius}
            fill="none"
            stroke="var(--border-faint)"
            strokeWidth={stroke}
          />
          <circle
            cx="34"
            cy="34"
            r={radius}
            fill="none"
            stroke={gaugeColor}
            strokeWidth={stroke}
            strokeLinecap="round"
            strokeDasharray={circumference}
            strokeDashoffset={offset}
            transform="rotate(-90 34 34)"
            style={{ transition: "stroke-dashoffset 600ms ease" }}
          />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="fa-num text-[20px] font-bold leading-none text-[var(--fg-1)]">{total}</span>
          <span className="text-[8px] font-semibold uppercase tracking-[0.1em] text-[var(--fg-5)]">sources</span>
        </div>
      </div>
      <div className="flex flex-wrap justify-center gap-x-3 gap-y-1 text-[9px] font-semibold">
        <FAStatusPill tone={statusTone(available)}>{available} LIVE</FAStatusPill>
        <FAStatusPill tone={statusTone(partial)}>{partial} WARN</FAStatusPill>
        <FAStatusPill tone={statusTone(error)}>{error} ERR</FAStatusPill>
      </div>
    </div>
  );
}
