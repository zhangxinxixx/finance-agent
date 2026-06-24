import type { CSSProperties, ElementType, ReactNode } from "react";

interface ContextPanelShellProps {
  children: ReactNode;
  width?: CSSProperties["width"];
  padded?: boolean;
  gap?: CSSProperties["gap"];
  className?: string;
  style?: CSSProperties;
}

interface ContextPanelSectionHeaderProps {
  icon: ElementType;
  title: ReactNode;
  meta?: ReactNode;
  iconColor?: string;
  className?: string;
}

export function ContextPanelShell({
  children,
  width = "100%",
  padded = true,
  gap = 10,
  className = "",
  style,
}: ContextPanelShellProps) {
  return (
    <aside
      className={className}
      style={{
        width,
        flexShrink: 0,
        border: "1px solid var(--border-faint)",
        borderRadius: "var(--radius-lg)",
        background: "var(--bg-panel)",
        overflowY: "auto",
        ...(padded
          ? {
              padding: 10,
              display: "flex",
              flexDirection: "column",
              gap,
            }
          : {}),
        ...style,
      }}
    >
      {children}
    </aside>
  );
}

export function ContextPanelSectionHeader({
  icon: Icon,
  title,
  meta,
  iconColor = "var(--brand-hover)",
  className = "",
}: ContextPanelSectionHeaderProps) {
  return (
    <div className={`flex items-center gap-2 ${className}`}>
      <Icon size={12} style={{ color: iconColor }} />
      <span style={{ font: "600 10px/1 Inter", color: "var(--fg-2)" }}>{title}</span>
      {meta ? <span className="text-[9px] text-[var(--fg-5)]">{meta}</span> : null}
    </div>
  );
}
