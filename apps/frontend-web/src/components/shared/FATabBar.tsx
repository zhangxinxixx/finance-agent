import type { ReactNode } from "react";

export interface FATabOption<TValue extends string = string> {
  value: TValue;
  label: ReactNode;
  count?: number;
  disabled?: boolean;
}

interface FATabBarProps<TValue extends string = string> {
  tabs: FATabOption<TValue>[];
  value: TValue;
  onChange?: (value: TValue) => void;
  className?: string;
  ariaLabel?: string;
}

export function FATabBar<TValue extends string = string>({ tabs, value, onChange, className = "", ariaLabel = "筛选项" }: FATabBarProps<TValue>) {
  return (
    <div className={`inline-flex flex-wrap rounded-[var(--radius-xl)] border border-[var(--border-faint)] bg-[var(--bg-card-inner)] p-1.5 shadow-[var(--shadow-card)] ${className}`} role="group" aria-label={ariaLabel}>
      {tabs.map((tab) => {
        const active = tab.value === value;
        return (
          <button
            key={tab.value}
            type="button"
            aria-pressed={active}
            disabled={tab.disabled}
            onClick={() => onChange?.(tab.value)}
            className={`inline-flex items-center gap-1.5 rounded-[var(--radius-lg)] px-3.5 py-2 text-[length:var(--text-11)] font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
              active
                ? "border border-[var(--brand-dim)] bg-[var(--bg-active)] text-[var(--brand-hover)] shadow-[var(--shadow-card)]"
                : "border border-transparent bg-transparent text-[var(--fg-4)] hover:bg-[var(--bg-hover)] hover:text-[var(--fg-2)]"
            }`}
          >
            <span>{tab.label}</span>
            {typeof tab.count === "number" ? <span className="fa-num text-[length:var(--text-10)] text-current/75">{tab.count}</span> : null}
          </button>
        );
      })}
    </div>
  );
}
