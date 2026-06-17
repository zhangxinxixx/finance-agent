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
    <div className={`inline-flex flex-wrap rounded-[var(--radius-xl)] border border-[var(--border)] bg-[var(--bg-panel)] p-1 ${className}`} role="group" aria-label={ariaLabel}>
      {tabs.map((tab) => {
        const active = tab.value === value;
        return (
          <button
            key={tab.value}
            type="button"
            aria-pressed={active}
            disabled={tab.disabled}
            onClick={() => onChange?.(tab.value)}
            className={`inline-flex items-center gap-1.5 rounded-[var(--radius-pill)] px-3 py-1.5 text-[10px] font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
              active
                ? "border border-[var(--brand-dim)] bg-[var(--bg-active)] text-[var(--brand-hover)]"
                : "border border-transparent text-[var(--fg-4)] hover:bg-[var(--bg-hover)] hover:text-[var(--fg-2)]"
            }`}
          >
            <span>{tab.label}</span>
            {typeof tab.count === "number" ? <span className="fa-num text-[9px] text-current/75">{tab.count}</span> : null}
          </button>
        );
      })}
    </div>
  );
}
