import { FACard } from "@/components/shared/FACard";
import type { SettingsPreferenceItem } from "@/adapters/settings";

function PreferenceSelect({
  item,
  value,
  disabled,
  onChange,
}: {
  item: SettingsPreferenceItem;
  value: string;
  disabled?: boolean;
  onChange: (next: string) => void;
}) {
  return (
    <label className="block">
      <div className="mb-1 text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--fg-5)]">{item.label}</div>
      <div className="rounded-[var(--radius-sm)] border border-[var(--border)] bg-[var(--bg-card-inner)] px-2.5">
        <select
          value={value}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value)}
          className="h-9 w-full bg-transparent text-[11px] font-medium text-[var(--fg-2)] outline-none disabled:cursor-not-allowed"
        >
          {item.options.map((option) => (
            <option key={option} value={option} className="bg-[var(--bg-card)] text-[var(--fg-2)]">
              {option}
            </option>
          ))}
        </select>
      </div>
    </label>
  );
}

interface GeneralPreferencesPanelProps {
  items: SettingsPreferenceItem[];
  values: Record<string, string>;
  disabled?: boolean;
  hasChanges: boolean;
  onChange: (key: string, next: string) => void;
  onReset: () => void;
  onSave: () => void;
}

export function GeneralPreferencesPanel({
  items,
  values,
  disabled,
  hasChanges,
  onChange,
  onReset,
  onSave,
}: GeneralPreferencesPanelProps) {
  return (
    <FACard
      title="全局偏好"
      eyebrow="Writable Preferences"
      accent="brand"
      action={
        <div className="flex items-center gap-2">
          <button
            type="button"
            disabled={disabled}
            onClick={onReset}
            className="inline-flex h-8 items-center rounded-full border border-[var(--border)] bg-[var(--bg-card)] px-3.5 text-[11px] font-semibold text-[var(--fg-2)] hover:border-[var(--border-strong)] hover:bg-[var(--bg-hover)] disabled:cursor-not-allowed disabled:opacity-50"
          >
            恢复默认
          </button>
          <button
            type="button"
            disabled={!hasChanges || disabled}
            onClick={onSave}
            className="inline-flex h-8 items-center rounded-full border border-[var(--border)] bg-[var(--bg-card)] px-3.5 text-[11px] font-semibold text-[var(--fg-2)] hover:border-[var(--border-strong)] hover:bg-[var(--bg-hover)] disabled:cursor-not-allowed disabled:opacity-50"
          >
            {disabled ? "保存中..." : "保存"}
          </button>
        </div>
      }
      bodyClassName="space-y-3"
    >
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {items.map((item) => (
          <PreferenceSelect
            key={item.key}
            item={item}
            value={values[item.key] ?? item.value}
            disabled={disabled}
            onChange={(next) => onChange(item.key, next)}
          />
        ))}
      </div>
    </FACard>
  );
}
