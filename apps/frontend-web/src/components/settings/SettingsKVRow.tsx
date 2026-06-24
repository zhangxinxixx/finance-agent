interface SettingsKVRowProps {
  label: string;
  value: string;
  mono?: boolean;
}

export function SettingsKVRow({ label, value, mono = false }: SettingsKVRowProps) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-[11px] text-[var(--fg-3)]">{label}</span>
      <span className={`text-[11px] font-medium text-[var(--fg-2)] ${mono ? "fa-num" : ""}`}>{value}</span>
    </div>
  );
}
