export function DetailMetric({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="min-w-0 rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2 py-1.5">
      <div className="text-[8px] font-semibold uppercase tracking-wider text-[var(--fg-6)]">{label}</div>
      <div className={`mt-0.5 truncate text-[10px] font-semibold text-[var(--fg-3)] ${mono ? "font-mono" : ""}`}>{value}</div>
    </div>
  );
}

export function EvidencePathRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-2">
      <span className="shrink-0 text-[8px] font-semibold uppercase tracking-wider text-[var(--fg-6)]">{label}</span>
      <span className="truncate text-right font-mono text-[8px] text-[var(--fg-4)]" title={value}>
        {value}
      </span>
    </div>
  );
}
