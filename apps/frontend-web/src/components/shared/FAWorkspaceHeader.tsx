import type { ComponentType, ReactNode } from "react";
import { FATabBar, type FATabOption } from "./FATabBar";

export interface FAWorkspaceHeaderChip {
  label: ReactNode;
  value: ReactNode;
  title?: string;
}

interface FAWorkspaceHeaderProps<TValue extends string = string> {
  title: ReactNode;
  icon?: ComponentType<{ size?: number | string; className?: string }>;
  tabs?: FATabOption<TValue>[];
  value?: TValue;
  onChange?: (value: TValue) => void;
  ariaLabel?: string;
  actions?: ReactNode;
  primaryLabel?: ReactNode;
  primaryItems?: FAWorkspaceHeaderChip[];
  secondaryLabel?: ReactNode;
  secondaryItems?: FAWorkspaceHeaderChip[];
  className?: string;
}

function Chip({ item }: { item: FAWorkspaceHeaderChip }) {
  return (
    <span className="fa-workspace-context-chip" title={item.title}>
      <span className="fa-workspace-context-chip-label">{item.label}</span>
      <span className="fa-workspace-context-chip-value">{item.value}</span>
    </span>
  );
}

export function FAWorkspaceHeader<TValue extends string = string>({
  title,
  icon: Icon,
  tabs,
  value,
  onChange,
  ariaLabel,
  actions,
  primaryLabel,
  primaryItems,
  secondaryLabel,
  secondaryItems,
  className = "",
}: FAWorkspaceHeaderProps<TValue>) {
  const hasPrimary = Boolean(primaryItems?.length);
  const hasSecondary = Boolean(secondaryItems?.length);
  const hasContext = hasPrimary || hasSecondary;
  const showTabs = Boolean(tabs?.length && value !== undefined && onChange);

  return (
    <section className={`fa-workspace-top-band ${className}`}>
      <div className="fa-workspace-top-band-main">
        <div className="fa-workspace-top-band-title">
          {Icon ? <Icon size={14} className="text-[var(--brand-hover)]" /> : null}
          <span>{title}</span>
        </div>

        {showTabs ? (
          <div className="fa-workspace-tabs-strip">
            <FATabBar
              tabs={tabs ?? []}
              value={value as TValue}
              onChange={(next) => onChange?.(next)}
              ariaLabel={ariaLabel}
            />
          </div>
        ) : null}

        {actions ? <div className="fa-workspace-top-band-actions">{actions}</div> : null}
      </div>

      {hasContext ? (
        <div className="fa-workspace-context-strip">
          {hasPrimary ? (
            <div className="fa-workspace-context-group">
              {primaryLabel ? <span className="fa-workspace-toolbar-label">{primaryLabel}</span> : null}
              {primaryItems?.map((item, index) => <Chip key={`primary-${index}`} item={item} />)}
            </div>
          ) : null}

          {hasSecondary ? (
            <div className="fa-workspace-context-group fa-workspace-context-group--compact">
              {secondaryLabel ? <span className="fa-workspace-toolbar-label">{secondaryLabel}</span> : null}
              {secondaryItems?.map((item, index) => <Chip key={`secondary-${index}`} item={item} />)}
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
