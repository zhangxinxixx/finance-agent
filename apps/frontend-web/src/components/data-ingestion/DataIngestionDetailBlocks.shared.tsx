export function DetailMetric({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="min-w-0 rounded-[var(--radius-md)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] px-2 py-1.5">
      <div className="fa-compact-label">{label}</div>
      <div className={`mt-0.5 truncate text-[10px] font-semibold text-[var(--fg-3)] ${mono ? "font-mono" : ""}`}>{value}</div>
    </div>
  );
}

export function EvidencePathRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-2">
      <span className="fa-compact-label shrink-0">{label}</span>
      <span className="fa-num truncate text-right text-[10px] text-[var(--fa-text-muted)]" title={value}>
        {value}
      </span>
    </div>
  );
}
